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

from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsObject, QMenu
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import (
    QColor, QPen, QBrush, QPainter, QFont, QFontMetricsF, QPolygonF,
)

NODE_RADIUS = 26
EDGE_COLOR = QColor("#38bdf8")
GRID_BG = QColor("#0f172a")
GRID_DOT = QColor(148, 163, 184, 38)
HIGHLIGHT_COLOR = QColor("#f97316")


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
    """One draggable device node: colored circle + label underneath."""

    dragged_to = pyqtSignal(object)       # self, emitted while moving (edge refresh)
    drag_finished = pyqtSignal(object)    # self, emitted once on mouse release

    def __init__(self, node_id: int, name: str, color: str, parent=None):
        super().__init__(parent)
        self.node_id = node_id
        self.name = name
        self.base_color = QColor(color)
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

        self._label_item = None

    # ----- geometry -----
    def boundingRect(self):
        w = max(NODE_RADIUS * 2, self._label_width())
        return QRectF(-w / 2 - 4, -NODE_RADIUS - 4, w + 8, NODE_RADIUS * 2 + 22)

    def _label_width(self):
        fm = QFontMetricsF(QFont("Segoe UI", 8, QFont.Weight.Bold))
        return fm.horizontalAdvance(self.name)

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

        # Small inner ring for depth
        painter.setPen(QPen(QColor(255, 255, 255, 60), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(0, 0), r - 4, r - 4)

        # Label below the circle
        font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        painter.setFont(font)
        fm = QFontMetricsF(font)
        text_w = fm.horizontalAdvance(self.name)
        painter.setPen(QPen(QColor("#e2e8f0")))
        painter.drawText(QPointF(-text_w / 2, r + fm.ascent() + 3), self.name)

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
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setOptimizationFlags(QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing)

        self._panning = False
        self._pan_start = QPointF()
        self._connect_mode = False
        self._connect_source = None      # NodeItem or None

        self._nodes = {}                 # key -> NodeItem
        self._edges = []                 # [EdgeItem]

    # ================= graph building =================
    def clear_graph(self):
        self._scene.clear()
        self._nodes.clear()
        self._edges.clear()
        self._connect_source = None

    def set_graph(self, nodes: dict, links: list):
        """
        nodes: {key: {"id": int, "name": str, "color": "#rrggbb", "left": x, "top": y}}
               (left/top already in scene coordinates)
        links: [(src_key, dst_key, edge_label), ...]
        """
        self.clear_graph()

        for key, info in nodes.items():
            item = NodeItem(int(info["id"]), info["name"], info.get("color", "#64748b"))
            item.setPos(float(info.get("left", 0)), float(info.get("top", 0)))
            item.dragged_to.connect(self._on_node_dragged)
            item.drag_finished.connect(self._on_drag_finished)
            self._scene.addItem(item)
            self._nodes[key] = item

        for src_key, dst_key, label in links:
            src = self._nodes.get(src_key)
            dst = self._nodes.get(dst_key)
            if src is None or dst is None:
                continue
            self._edges.append(EdgeItem(self._scene, src, dst, label))

        self.status_message.emit(
            f"{len(self._nodes)} devices · {len(self._edges)} links · "
            f"double-click a device to connect"
        )

    def set_connect_mode(self, enabled: bool):
        self._connect_mode = enabled
        self._cancel_connect_source()
        for item in self._nodes.values():
            item.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIsMovable, not enabled)

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

    # ================= panning =================
    def mousePressEvent(self, event):
        # Connect-mode: click a SOURCE node, then a DESTINATION node.
        if self._connect_mode and event.button() == Qt.MouseButton.LeftButton:
            node = self._ancestor_node(self.itemAt(event.position().toPoint()))
            if node is not None:
                self._handle_connect_click(node)
                event.accept()
                return

        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.itemAt(event.position().toPoint()) is None:
            # Drag empty space to pan (feels like the EVE-NG client).
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
        act_console = menu.addAction(f"💻 Open Console ({node.name})")
        act_capture = menu.addAction("🦈 Wireshark Capture...")
        menu.addSeparator()
        act_delete = menu.addAction("🗑 Delete Device")

        chosen = menu.exec(event.globalPos())
        if chosen is None:
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
