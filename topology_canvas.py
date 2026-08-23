"""
Interactive Topology Canvas (native Qt)
-----------------------------------------
A QGraphicsView-based replacement for the previous embedded-matplotlib
diagram: faster rendering, no extra dependencies (matplotlib/networkx),
and true interactivity —

  - Nodes are real scene items: drag to rearrange, wheel to zoom,
    drag empty space (or middle-mouse) to pan.
  - Double-click a node (or pick "Open Console" from its right-click menu)
    to launch a console session.
  - Right-click menu also offers Wireshark capture and node deletion.
  - Connect Mode: click a SOURCE node, then a DESTINATION node to create
    an EVE-NG link (the host window shows the interface picker dialogs).
  - Node positions persist: when a drag finishes, nodeMoved() carries the
    new coordinates so the caller can store them back to the server.

The widget itself never talks to the network — everything goes through the
signals above so the GUI layer owns all API calls.
"""

from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsObject, QMenu, QToolButton, QGraphicsProxyWidget
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import (
    QColor, QPen, QBrush, QPainter, QFont, QFontMetricsF, QPolygonF,
)

NODE_RADIUS = 26
EDGE_COLOR = QColor("#38bdf8")
GRID_BG = QColor("#0f172a")
GRID_DOT = QColor(148, 163, 184, 38)
HIGHLIGHT_COLOR = QColor("#f97316")

MINI_BTN_QSS = (
    "QToolButton{background:rgba(15,23,42,210);color:#ffffff;"
    "border:1px solid #475569;border-radius:9px;font-size:11px;padding:0;}"
    "QToolButton:hover{border-color:#38bdf8;background:rgba(2,132,199,180);}"
)

# EVE-NG/console shorthand -> proper Cisco-style interface names
_IF_PREFIXES = {
    "e": "Ethernet", "et": "Ethernet", "ethernet": "Ethernet",
    "fa": "FastEthernet", "fastethernet": "FastEthernet",
    "gi": "GigabitEthernet", "gigabitethernet": "GigabitEthernet",
    "te": "TenGigabitEthernet", "tengigabitethernet": "TenGigabitEthernet",
    "twe": "TwentyFiveGigE",
    "fo": "FortyGigE",
    "se": "Serial",
    "po": "Port-channel",
    "vl": "Vlan",
    "lo": "Loopback",
}


def pretty_ifname(label: str) -> str:
    """'e0/0' -> 'Ethernet0/0', 'Fa0/1' -> 'FastEthernet0/1',
    'ethernet0/0' -> 'Ethernet0/0'. Leaves unknown names untouched
    (e.g. Linux-style 'eth0')."""
    s = (label or "").strip()
    m = re.match(r"^([A-Za-z]+)[-_ ]?(\d+(?:/\d+)*)$", s)
    if not m:
        return s
    full = _IF_PREFIXES.get(m.group(1).lower())
    return f"{full}{m.group(2)}" if full else s


import re  # noqa: E402  (used by pretty_ifname above)


class EdgeItem:
    """Bookkeeping wrapper for one link between two NodeItems."""

    def __init__(self, scene, src_item, dst_item, label=""):
        self.src = src_item
        self.dst = dst_item
        self.label_text = label

        self.line = scene.addLine(0, 0, 0, 0, QPen(EDGE_COLOR, 2))
        self.line.setZValue(0)
        self.line.setAcceptHoverEvents(False)

        self.label = None
        if label:
            self.label = scene.addSimpleText(label, QFont("Segoe UI", 8))
            self.label.setBrush(QBrush(QColor("#cbd5e1")))
            self.label.setZValue(1)

        self.update_position()

    def update_position(self):
        p1 = self.src.scene_pos()
        p2 = self.dst.scene_pos()
        self.line.setLine(p1.x(), p1.y(), p2.x(), p2.y())
        if self.label is not None:
            self.label.setPos(
                (p1.x() + p2.x()) / 2 - self.label.boundingRect().width() / 2,
                (p1.y() + p2.y()) / 2 - 14,
            )

    def matches_node(self, item) -> bool:
        return item is self.src or item is self.dst


class NodeItem(QGraphicsObject):
    """One draggable device node: colored circle + type icon + label,
    with a running-status dot and per-node start/stop mini buttons."""

    dragged_to = pyqtSignal(object)       # self, emitted while moving (edge refresh)
    drag_finished = pyqtSignal(object)    # self, emitted once on mouse release

    def __init__(self, node_id: int, name: str, color: str,
                 icon: str = "", running: bool = False,
                 ip_text: str = "", parent=None):
        super().__init__(parent)
        self.node_id = node_id
        self.name = name
        self.base_color = QColor(color)
        self.icon_text = icon
        self.running = running
        self.ip_text = (ip_text or "").strip()
        self.is_connect_source = False

        self.setFlags(
            QGraphicsObject.GraphicsItemFlag.ItemIsMovable
            | QGraphicsObject.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsObject.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(5)
        self._hovered = False
        self._drag_active = False

    def set_running(self, running: bool):
        self.running = running
        self.update()

    def set_ip_text(self, ip_text: str):
        self.ip_text = (ip_text or "").strip()
        self.prepareGeometryChange()
        self.update()

    # ----- geometry -----
    def boundingRect(self):
        w = max(NODE_RADIUS * 2, self._label_width(), self._ip_width())
        extra = 14 if self.ip_text else 0
        return QRectF(-w / 2 - 6, -NODE_RADIUS - 6,
                      w + 12, NODE_RADIUS * 2 + 26 + extra)

    def _label_width(self):
        fm = QFontMetricsF(QFont("Segoe UI", 8, QFont.Weight.Bold))
        return fm.horizontalAdvance(self.name)

    def _ip_width(self):
        if not self.ip_text:
            return 0.0
        fm = QFontMetricsF(QFont("Consolas", 7))
        return fm.horizontalAdvance(self.ip_text)

    def scene_pos(self) -> QPointF:
        return self.mapToScene(QPointF(0, 0))

    # ----- painting -----
    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        r = NODE_RADIUS
        outline = QColor("#0b1220")
        pen_w = 2.0
        if self.is_connect_source or self.isSelected():
            outline = HIGHLIGHT_COLOR
            pen_w = 3.0
        elif self._hovered:
            outline = QColor("#e2e8f0")

        painter.setPen(QPen(outline, pen_w))
        painter.setBrush(QBrush(self.base_color))
        painter.drawEllipse(QPointF(0, 0), r, r)

        # Device-type icon centered in the circle
        if self.icon_text:
            font = QFont("Segoe UI Emoji", int(r * 0.62))
            painter.setFont(font)
            painter.setPen(QPen(QColor("#ffffff")))
            fm = QFontMetricsF(font)
            text_w = fm.horizontalAdvance(self.icon_text)
            painter.drawText(
                QPointF(-text_w / 2, fm.ascent() / 2 - fm.descent() / 2 + 1),
                self.icon_text)

        # Running status dot (top-right of the circle)
        dot_r = 5.5
        cx, cy = r * 0.82, -r * 0.82
        painter.setPen(QPen(QColor("#0b1220"), 1.5))
        painter.setBrush(QBrush(QColor("#22c55e") if self.running else QColor("#ef4444")))
        painter.drawEllipse(QPointF(cx, cy), dot_r, dot_r)

        # Label below the circle
        font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        painter.setFont(font)
        fm = QFontMetricsF(font)
        text_w = fm.horizontalAdvance(self.name)
        painter.setPen(QPen(QColor("#e2e8f0")))
        painter.drawText(QPointF(-text_w / 2, r + fm.ascent() + 3), self.name)

        # IP address line under the label
        if self.ip_text:
            ip_font = QFont("Consolas", 7)
            painter.setFont(ip_font)
            ifm = QFontMetricsF(ip_font)
            ip_w = ifm.horizontalAdvance(self.ip_text)
            painter.setPen(QPen(QColor("#94a3b8")))
            painter.drawText(QPointF(-ip_w / 2, r + fm.ascent() + 3 + ifm.ascent() + 3),
                             self.ip_text)

    # ----- events -----
    def hoverEnterEvent(self, event):
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsObject.GraphicsItemChange.ItemPositionHasChanged:
            self.dragged_to.emit(self)
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = True
            self.setSelected(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_active:
            self._drag_active = False
            self.drag_finished.emit(self)
        super().mouseReleaseEvent(event)


class TopologyCanvas(QGraphicsView):
    """Interactive lab map. See module docstring for interaction summary."""

    node_invoked = pyqtSignal(int, str)                 # open console (double-click / menu)
    node_capture_requested = pyqtSignal(int, str)       # Wireshark on this node
    node_delete_requested = pyqtSignal(int, str)        # delete this node
    node_ping_requested = pyqtSignal(int)               # ping FROM this device
    node_ip_edit_requested = pyqtSignal(int, str)       # set/edit the shown IP (id, current)
    node_start_requested = pyqtSignal(int)              # power-on toggle
    node_stop_requested = pyqtSignal(int)               # power-off toggle
    nodes_connect_requested = pyqtSignal(str, int, str, int)  # src name/id, dst name/id
    node_moved = pyqtSignal(int, float, float)          # node_id, left, top (server coords)
    status_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._scene.setSceneRect(-4000, -4000, 8000, 8000)

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(GRID_BG))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setMouseTracking(False)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setOptimizationFlags(QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing)

        self._panning = False
        self._pan_start = QPointF()
        self._connect_mode = False
        self._connect_source = None      # NodeItem or None
        self._space_pressed = False      # hold Space to pan with left-drag

        # Owner (MainWindow) may install: fn(selected_ids, menu) -> [(action, handler)]
        # Used to append group commands (save/add/remove) to the node menu.
        self.group_actions_provider = None

        self._nodes = {}                 # key -> NodeItem
        self._edges = []                 # [EdgeItem]
        self._power_buttons = []         # [(QGraphicsProxyWidget, node_id, is_start)]

    # ================= graph building =================
    def clear_graph(self):
        self._scene.clear()
        self._nodes.clear()
        self._edges.clear()
        self._power_buttons.clear()
        self._connect_source = None


    def set_graph(self, nodes: dict, links: list):
        """
        nodes: {key: {"id": int, "name": str, "color": "#rrggbb",
                      "icon": emoji, "running": bool,
                      "left": x, "top": y}}   (coords already in scene space)
        links: [(src_key, dst_key, edge_label), ...]
        """
        self.clear_graph()

        for key, info in nodes.items():
            item = NodeItem(int(info["id"]), info["name"],
                            info.get("color", "#64748b"),
                            icon=info.get("icon", ""),
                            running=bool(info.get("running", False)))
            item.setPos(float(info.get("left", 0)), float(info.get("top", 0)))
            item.dragged_to.connect(self._on_node_dragged)
            item.drag_finished.connect(self._on_drag_finished)
            self._scene.addItem(item)
            self._nodes[key] = item
            self._add_power_buttons(item)

        for src_key, dst_key, label in links:
            src = self._nodes.get(src_key)
            dst = self._nodes.get(dst_key)
            if src is None or dst is None:
                continue
            self._edges.append(EdgeItem(self._scene, src, dst, label))

        running_n = sum(1 for n in self._nodes.values() if n.running)
        self.status_message.emit(
            f"{len(self._nodes)} devices · {len(self._edges)} links · "
            f"{running_n} running · ▶/■ under each device powers it")

    def _add_power_buttons(self, item: NodeItem):
        """Two mini buttons under the node: start (▶) and stop (■)."""
        for offset_x, text, tooltip, is_start in (
                (-27, "▶", f"Start {item.name.splitlines()[0]}", True),
                (5, "■", f"Stop {item.name.splitlines()[0]}", False)):
            btn = QToolButton()
            btn.setText(text)
            btn.setToolTip(tooltip)
            btn.setFixedSize(22, 18)
            btn.setStyleSheet(MINI_BTN_QSS)
            proxy = self._scene.addWidget(btn)
            proxy.setParentItem(item)
            proxy.setPos(offset_x, NODE_RADIUS + 30)
            proxy.setZValue(6)
            node_id = item.node_id
            btn.clicked.connect(
                lambda checked, nid=node_id, s=is_start:
                self.node_start_requested.emit(nid) if s
                else self.node_stop_requested.emit(nid))
            self._power_buttons.append((proxy, node_id, is_start))

    def set_node_running(self, node_id: int, running: bool):
        """Updates a node's status dot without redrawing everything."""
        for item in self._nodes.values():
            if item.node_id == node_id:
                item.set_running(running)
                return

    def set_connect_mode(self, enabled: bool):
        self._connect_mode = enabled
        self._cancel_connect_source()
        for item in self._nodes.values():
            item.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIsMovable, not enabled)
        # Power buttons would swallow connect-mode clicks - park them aside.
        for proxy, _nid, _s in self._power_buttons:
            proxy.setVisible(not enabled)

    def _cancel_connect_source(self):
        if self._connect_source is not None:
            self._connect_source.is_connect_source = False
            self._connect_source.update()
        self._connect_source = None

    def selected_node_info(self):
        """Returns (node_id, name) of the currently selected node, or None."""
        sel = [i for i in self._scene.selectedItems() if isinstance(i, NodeItem)]
        if not sel:
            return None
        item = sel[-1]
        return item.node_id, item.name

    # ================= zoom / view helpers =================
    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        scale = self.transform().m11() * factor
        if 0.15 <= scale <= 6.0:
            self.scale(factor, factor)

    def zoom_in(self):
        self.scale(1.2, 1.2)

    def zoom_out(self):
        self.scale(1 / 1.2, 1 / 1.2)

    def zoom_reset(self):
        self.resetTransform()

    def zoom_fit(self):
        if not self._nodes:
            return
        rect = self._scene.itemsBoundingRect()
        rect.adjust(-80, -80, 80, 80)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    # ================= panning / selection =================
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._space_pressed = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._space_pressed = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event):
        pos = event.position().toPoint()

        # Connect-mode: click a SOURCE node, then a DESTINATION node.
        if self._connect_mode and event.button() == Qt.MouseButton.LeftButton:
            node = self._ancestor_node(self.itemAt(pos))
            if node is not None:
                self._handle_connect_click(node)
                event.accept()
                return
            # Clicking empty space in connect mode clears the current pick.
            if self._connect_source is not None:
                self._cancel_connect_source()
                self.status_message.emit(
                    "Connect cancelled — click a SOURCE device first.")
            event.accept()
            return

        # Middle button always pans. Space+left pans too; plain left-drag on
        # empty space now draws the selection rectangle (rubber band), so
        # multiple devices can be selected by dragging a box around them.
        wants_pan = (event.button() == Qt.MouseButton.MiddleButton) or (
            event.button() == Qt.MouseButton.LeftButton and self._space_pressed)
        if wants_pan:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning and event.button() in (
            Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton
        ):
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ================= background grid =================
    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        painter.save()
        painter.setPen(QPen(GRID_DOT, 1))
        step = 40
        x0 = int(rect.left()) - (int(rect.left()) % step)
        y0 = int(rect.top()) - (int(rect.top()) % step)
        points = []
        y = y0
        while y < rect.bottom():
            x = x0
            while x < rect.right():
                points.append(QPointF(x, y))
                x += step
            y += step
        if points:
            painter.drawPoints(points)
        painter.restore()

    # ================= node interaction =================
    def _on_node_dragged(self, item: NodeItem):
        for edge in self._edges:
            if edge.matches_node(item):
                edge.update_position()

    def _on_drag_finished(self, item: NodeItem):
        # EVE-NG's top coordinate grows downward, same as Qt's scene y —
        # no sign flip needed (this used to mirror the map upside down).
        pos = item.scene_pos()
        self.node_moved.emit(item.node_id, pos.x(), pos.y())

    def mouseDoubleClickEvent(self, event):
        if self._connect_mode:
            event.accept()  # no console-launching while wiring links
            return
        hit = self.itemAt(event.position().toPoint())
        node = self._ancestor_node(hit)
        if node is not None:
            self.node_invoked.emit(node.node_id, node.name)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    @staticmethod
    def _ancestor_node(item):
        while item is not None:
            if isinstance(item, NodeItem):
                return item
            item = item.parentItem()
        return None

    def contextMenuEvent(self, event):
        node = self._ancestor_node(self.itemAt(event.pos()))
        if node is None:
            return

        menu = QMenu(self)
        act_start = menu.addAction("▶ Start Device")
        act_stop = menu.addAction("■ Stop Device")
        act_console = menu.addAction(f"💻 Open Console ({node.name.splitlines()[0]})")
        act_ping = menu.addAction("📡 Ping From This Device...")
        act_capture = menu.addAction("🦈 Wireshark Capture...")
        menu.addSeparator()
        act_delete = menu.addAction("🗑 Delete Device")

        # Group commands for everything currently selected (the right-clicked
        # node is always included, even if it wasn't part of the selection).
        group_entries = []
        if self.group_actions_provider:
            sel_ids = sorted({i.node_id for i in self._scene.selectedItems()
                              if isinstance(i, NodeItem)} | {node.node_id})
            if len(sel_ids) >= 1:
                menu.addSeparator()
                group_entries = self.group_actions_provider(sel_ids, menu) or []

        chosen = menu.exec(event.globalPos())
        if chosen is None:
            return
        if chosen is act_start:
            self.node_start_requested.emit(node.node_id)
            return
        if chosen is act_stop:
            self.node_stop_requested.emit(node.node_id)
            return
        for act, handler in group_entries:
            if chosen is act:
                handler()
                return
        if chosen is act_console:
            self.node_invoked.emit(node.node_id, node.name)
        elif chosen is act_capture:
            self.node_capture_requested.emit(node.node_id, node.name)
        elif chosen is act_delete:
            self.node_delete_requested.emit(node.node_id, node.name)

    def _handle_connect_click(self, node: NodeItem):
        if self._connect_source is None:
            self._connect_source = node
            node.is_connect_source = True
            node.update()
            self.status_message.emit(f"Source: {node.name} — now click the DESTINATION device")
        elif self._connect_source is node:
            # Same node clicked twice: cancel.
            self._cancel_connect_source()
            self.status_message.emit("Connect cancelled — click a SOURCE device first.")
        else:
            src = self._connect_source
            dst = node
            self._cancel_connect_source()
            self.nodes_connect_requested.emit(src.name, src.node_id, dst.name, dst.node_id)
