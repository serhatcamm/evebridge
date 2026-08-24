"""
EVE-NG Lab Automation & Management Suite — PyQt6 desktop client
Node monitoring, Router-on-a-Stick / VLAN / routing configurators, batch CLI,
image manager, Wireshark capture, firewall wizards, and an interactive
topology canvas.
"""

import sys
import os
import json
import shutil
import subprocess
import urllib.parse
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel, QLineEdit,
    QTextEdit, QGroupBox, QTabWidget, QSplitter, QHeaderView,
    QMessageBox, QSpinBox, QComboBox, QFormLayout, QProgressBar,
    QDialog, QDialogButtonBox, QCheckBox, QMenu, QFileDialog,
    QListWidget, QListWidgetItem, QInputDialog, QScrollArea, QLayout,
    QGridLayout, QStackedWidget, QTreeWidgetItem, QTreeWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSettings, QSize, QRect
from PyQt6.QtGui import QFont, QColor, QIcon, QKeySequence, QShortcut

from eve_api import EveNGClient
from config_builder import (
    NodeConsoleManager, generate_router_on_stick_config, generate_switch_vlan_config,
    generate_dhcp_pool_config, parse_show_ip_interface_brief,
    generate_static_route_config, generate_ospf_config, generate_eigrp_config,
    generate_rip_config, generate_bgp_config,
    generate_acl_config, generate_nat_config, generate_pat_config,
    generate_etherchannel_config, generate_standby_config,
    generate_aaa_config, build_aaa_server_bootstrap,
)
from image_uploader import EveImageUploader, QEMU_IMAGE_NAMING, find_qemu_naming, CONVERTIBLE_DISK_EXTENSIONS
from terminal_launcher import TERMINAL_CLIENTS, launch_telnet, launch_ssh, launch_vnc, find_putty_executable, find_vnc_executable
from capture_manager import EveNGPacketCapture, find_wireshark_executable
from firewall_config_builder import (
    generate_fortigate_config, build_pfsense_opnsense_steps, flatten_steps,
    parse_fortigate_interfaces, parse_bsd_interface_list,
)
from topology_canvas import TopologyCanvas, pretty_ifname
from lab_exporter import export_lab_zip, duplicate_lab_file
import ansible_gen
import ad_gpo_gen
import image_store
from ping_tool import PingWorker
from ai_assistant import (
    AiAssistant, PROVIDERS as AI_PROVIDERS, is_configured as ai_is_configured,
    get_api_key as ai_get_api_key, set_api_key as ai_set_api_key,
    get_base_url as ai_get_base_url, set_base_url as ai_set_base_url,
    get_model as ai_get_model, set_model as ai_set_model,
    get_selected_provider as ai_get_selected_provider, set_selected_provider as ai_set_selected_provider,
    needs_api_key as ai_needs_key,
)
import updater
import themes

# --- Styling System ---
# --- Styling System (see themes.py — this app supports multiple color themes) ---

class FlowLayout(QLayout):
    """
    A layout that arranges child widgets left-to-right, wrapping onto a new
    row when the available width runs out — used for the top toolbar rows so
    they stay fully usable (nothing clipped or hidden) when the window is
    resized narrow, e.g. docked next to Notepad or a browser on a NOC desk.
    Standard Qt "flow layout" recipe, adapted for PyQt6.
    """

    def __init__(self, parent=None, margin=0, h_spacing=8, v_spacing=8):
        super().__init__(parent)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._items = []
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def addSpacing(self, _size):
        pass  # FlowLayout already applies consistent spacing between items; explicit spacers are a no-op.

    def addStretch(self, _stretch=0):
        pass  # no stretch concept in a wrapping flow layout; items just flow left-to-right and wrap.

    def horizontalSpacing(self):
        return self._h_spacing

    def verticalSpacing(self):
        return self._v_spacing

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect, test_only):
        left, top, right, bottom = self.getContentsMargins()
        effective_rect = rect.adjusted(left, top, -right, -bottom)
        x = effective_rect.x()
        y = effective_rect.y()
        line_height = 0

        for item in self._items:
            widget = item.widget()
            if widget is not None and not widget.isVisible():
                continue
            space_x = self._h_spacing
            space_y = self._v_spacing
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > effective_rect.right() and line_height > 0:
                x = effective_rect.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(x, y, item.sizeHint().width(), item.sizeHint().height()))
            x = next_x
            line_height = max(line_height, item.sizeHint().height())

        return y + line_height - rect.y()


class WorkerThread(QThread):
    finished_signal = pyqtSignal(str, object)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            res = self.func(*self.args, **self.kwargs)
            self.finished_signal.emit("success", res)
        except Exception as e:
            self.finished_signal.emit("error", str(e))


class NodeBatchWorker(QThread):
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(list)  # list of node_ids that failed to start/stop (empty = all succeeded)

    def __init__(self, eve_client, lab_name, node_ids, action="start"):
        super().__init__()
        self.eve_client = eve_client
        self.lab_name = lab_name
        self.node_ids = node_ids
        self.action = action

    def run(self):
        total = len(self.node_ids)
        if total == 0:
            self.finished_signal.emit([])
            return

        failed = []
        for idx, nid in enumerate(self.node_ids):
            pct = int(((idx + 1) / total) * 100)
            if self.action == "start":
                self.progress_signal.emit(pct, f"Starting node {nid} ({idx+1}/{total})...")
                ok = self.eve_client.start_node(self.lab_name, nid)
            elif self.action == "stop":
                self.progress_signal.emit(pct, f"Stopping node {nid} ({idx+1}/{total})...")
                ok = self.eve_client.stop_node(self.lab_name, nid)
            else:
                ok = True
            if not ok:
                failed.append(nid)
            self.msleep(150)

        self.finished_signal.emit(failed)


class FirewallStagedWorker(QThread):
    """Sends a pfSense/OPNsense console-menu script in discrete, labeled steps
    (Assign Interfaces, then Set IP/DHCP, then Enable SSH, ...) instead of one
    blind blast — each step's output is reported as it completes, so a
    mis-numbered menu option in one step doesn't silently corrupt the rest
    and is easy to pinpoint."""
    step_output_signal = pyqtSignal(str, str)   # step label, output text
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal()

    def __init__(self, host, port, steps, connection_type="telnet"):
        super().__init__()
        self.host = host
        self.port = port
        self.steps = steps  # [(label, [lines]), ...]
        self.connection_type = connection_type

    def run(self):
        total = len(self.steps)
        for idx, (label, lines) in enumerate(self.steps):
            pct = int((idx / total) * 100) if total else 0
            self.progress_signal.emit(pct, f"Sending step {idx + 1}/{total}: {label}...")
            try:
                mgr = NodeConsoleManager(self.host, self.port, connection_type=self.connection_type)
                output = mgr.send_commands(lines)
                if not output.strip():
                    output = "(No data received for this step.)"
            except Exception as e:
                output = f"[ERROR] {e}"
            self.step_output_signal.emit(label, output)
        self.progress_signal.emit(100, "All steps sent.")
        self.finished_signal.emit()


class BatchCliWorker(QThread):
    """Runs a set of CLI commands against one or more nodes sequentially in the
    background, streaming output back per-device so the GUI never blocks and
    always shows *something* (including errors) instead of going silent."""
    output_signal = pyqtSignal(str, str)     # device label, output text
    progress_signal = pyqtSignal(int, str)   # percent, status message
    finished_signal = pyqtSignal()

    def __init__(self, host, targets, commands, connection_type="telnet", username="", password=""):
        super().__init__()
        self.host = host
        self.targets = targets  # list of (node_id, label)
        self.commands = commands
        self.connection_type = connection_type
        self.username = username
        self.password = password

    def run(self):
        total = len(self.targets)
        if total == 0:
            self.finished_signal.emit()
            return

        for idx, (node_id, label) in enumerate(self.targets):
            pct = int((idx / total) * 100)
            self.progress_signal.emit(pct, f"Running commands on {label} ({idx + 1}/{total})...")
            try:
                port = 32768 + int(node_id)
                mgr = NodeConsoleManager(
                    self.host, port, connection_type=self.connection_type,
                    username=self.username, password=self.password
                )
                output = mgr.send_commands(self.commands)
                if not output.strip():
                    output = ("(No data received. The node may be stopped, its console port may not be "
                               "reachable, or it needs a moment after boot before the console responds.)")
            except Exception as e:
                output = f"[ERROR] {e}"
            self.output_signal.emit(label, output)

        self.progress_signal.emit(100, "Batch CLI execution complete.")
        self.finished_signal.emit()


class UpdateWorker(QThread):
    """Downloads and applies a software update in the background, streaming
    progress so the download/install of a multi-MB package doesn't freeze the GUI."""
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool, str)  # success, backup_dir or error message

    def __init__(self, download_url: str, app_dir: str):
        super().__init__()
        self.download_url = download_url
        self.app_dir = app_dir

    def run(self):
        try:
            backup_dir = updater.download_and_apply_update(
                self.download_url, self.app_dir,
                progress_cb=lambda pct, msg: self.progress_signal.emit(pct, msg)
            )
            self.finished_signal.emit(True, backup_dir)
        except Exception as e:
            self.finished_signal.emit(False, str(e))


class ImageUploadWorker(QThread):
    """Background worker that uploads a node image to EVE-NG via SSH/SFTP
    and optionally runs fixpermissions, without freezing the GUI."""
    progress_signal = pyqtSignal(int, str)     # overall percent, status message
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)    # success, remote path or error message

    def __init__(self, host, ssh_user, ssh_pass, ssh_port, image_type, local_path, remote_name,
                 run_fixperms=True, convert_to_qcow2=None):
        super().__init__()
        self.host = host
        self.ssh_user = ssh_user
        self.ssh_pass = ssh_pass
        self.ssh_port = ssh_port
        self.image_type = image_type
        self.local_path = local_path
        self.remote_name = remote_name
        self.run_fixperms = run_fixperms
        self.convert_to_qcow2 = convert_to_qcow2

    def run(self):
        uploader = None
        try:
            uploader = EveImageUploader(self.host, self.ssh_user, self.ssh_pass, self.ssh_port)
            self.log_signal.emit(f"Connecting via SSH to {self.host}:{self.ssh_port} as '{self.ssh_user}'...")
            uploader.connect()
            self.log_signal.emit("SSH connection established.")

            def on_progress(file_idx, total_files, filename, pct):
                overall = int(((file_idx - 1) / total_files) * 100 + (pct / total_files))
                self.progress_signal.emit(overall, f"Uploading {filename} ({file_idx}/{total_files})... {pct}%")

            if self.image_type == "qemu":
                remote_path = uploader.upload_qemu_image(
                    self.local_path, self.remote_name, on_progress, convert_to_qcow2=self.convert_to_qcow2
                )
            elif self.image_type == "iol":
                remote_path = uploader.upload_iol_image(self.local_path, on_progress)
            else:
                remote_path = uploader.upload_dynamips_image(self.local_path, on_progress)

            self.log_signal.emit(f"Upload complete: {remote_path}")

            if self.run_fixperms:
                self.log_signal.emit("Running fixpermissions on EVE-NG server (this can take a moment)...")
                out = uploader.fix_permissions()
                if out:
                    self.log_signal.emit(f"fixpermissions output: {out}")
                self.log_signal.emit("Permissions fixed — the image should now appear as selectable in 'Add New Device'.")

            self.finished_signal.emit(True, remote_path)
        except Exception as e:
            self.finished_signal.emit(False, str(e))
        finally:
            if uploader:
                uploader.close()


class AddNodeDialog(QDialog):
    def __init__(self, parent, eve_client, lab_name):
        super().__init__(parent)
        self.setWindowTitle("Add New Device to Lab")
        self.setMinimumWidth(450)
        self.eve_client = eve_client
        self.lab_name = lab_name
        self.template_details = {}

        self.init_ui()
        self.load_templates()

    def init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.cmb_template = QComboBox()
        self.cmb_template.setEnabled(False)
        self.cmb_template.addItem("Loading templates...")
        self.cmb_template.currentIndexChanged.connect(self.on_template_changed)
        form.addRow("Node Template:", self.cmb_template)

        self.cmb_image = QComboBox()
        form.addRow("Image:", self.cmb_image)

        self.txt_name = QLineEdit("Node")
        form.addRow("Name Prefix:", self.txt_name)

        self.cmb_template.setFixedHeight(60)
        self.cmb_image.setFixedHeight(60)

        self.spin_count = QSpinBox()
        self.spin_count.setRange(1, 100)
        self.spin_count.setValue(1)
        form.addRow("Quantity:", self.spin_count)

        self.spin_ram = QSpinBox()
        self.spin_ram.setRange(128, 65536)
        self.spin_ram.setSingleStep(128)
        self.spin_ram.setSuffix(" MB")
        form.addRow("RAM:", self.spin_ram)

        self.spin_cpu = QSpinBox()
        self.spin_cpu.setRange(1, 32)
        form.addRow("CPU Cores:", self.spin_cpu)

        self.spin_eth = QSpinBox()
        self.spin_eth.setRange(0, 32)
        form.addRow("Ethernet Ports:", self.spin_eth)

        layout.addLayout(form)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setObjectName("warn")
        self.lbl_status.setVisible(False)
        layout.addWidget(self.lbl_status)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        layout.addWidget(self.buttons)

    def load_templates(self):
        """Fetches the template list in the background instead of blocking the
        whole app while the dialog opens — a slow/unresponsive EVE-NG server
        used to freeze this dialog with no feedback, which looked like the
        template dropdown 'not working'."""
        self._templates_worker = WorkerThread(self.eve_client.get_templates)
        self._templates_worker.finished_signal.connect(self._on_templates_loaded)
        self._templates_worker.start()

    def _on_templates_loaded(self, status, result):
        self.cmb_template.clear()
        if status != "success" or not result:
            self.cmb_template.addItem("(failed to load templates)")
            self.cmb_template.setEnabled(False)
            detail = f": {result}" if status != "success" else ""
            self.lbl_status.setText(
                f"⚠ Couldn't load the template list from EVE-NG{detail}. Check that you're "
                f"connected, then close and reopen this dialog to retry."
            )
            self.lbl_status.setVisible(True)
            return

        self.cmb_template.setEnabled(True)
        self.cmb_template.blockSignals(True)
        entries = []
        for name, desc in result.items():
            label = self._friendly_template_label(name, desc)
            entries.append((label.lower(), label, name))
        for _sort_key, label, name in sorted(entries):
            self.cmb_template.addItem(label, name)
            self.cmb_template.setItemData(self.cmb_template.count() - 1, f"Template ID: {name}", Qt.ItemDataRole.ToolTipRole)
        self.cmb_template.blockSignals(False)
        if self.cmb_template.count() > 0:
            self.on_template_changed(0)

    @staticmethod
    def _friendly_template_label(name: str, desc: str) -> str:
        """
        EVE-NG's template list is full of internal noise — raw keys with
        underscores (e.g. 'macos_simple_kvm'), and descriptions that end in
        '.missing' or even '.svg' when the server lacks an icon. Show people
        a clean product name instead; the raw key stays as the item's data.
        """
        import re
        d = str(desc or "").strip()
        d = re.sub(r"\.(missing|svg|png)$", "", d, flags=re.IGNORECASE).strip()
        if not d or d.lower() == "new image":
            d = re.sub(r"[-_]+", " ", str(name)).strip().title()
        return d

    def on_template_changed(self, index):
        template_name = self.cmb_template.currentData()
        if not template_name:
            return

        self.cmb_image.clear()
        self.cmb_image.addItem("Loading images...")
        self.cmb_image.setEnabled(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

        self._details_worker = WorkerThread(self.eve_client.get_template_details, template_name)
        self._details_worker.finished_signal.connect(self._on_template_details_loaded)
        self._details_worker.start()

    def _on_template_details_loaded(self, status, result):
        self.cmb_image.clear()
        self.cmb_image.setEnabled(True)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

        if status != "success" or not result:
            self.cmb_image.addItem("(no images found)")
            detail = f": {result}" if status != "success" else ""
            self.lbl_status.setText(
                f"⚠ Couldn't load details for this template{detail}. You can still add the "
                f"node, but RAM/CPU/image defaults may be off — set them manually."
            )
            self.lbl_status.setVisible(True)
            self.template_details = {}
            return

        self.lbl_status.setVisible(False)
        self.template_details = result
        options = result.get("options", {})

        image_opt = options.get("image", {})
        image_choices = image_opt.get("list") or image_opt.get("options", {})
        if image_choices:
            for img_val in sorted(image_choices.keys()):
                self.cmb_image.addItem(img_val, img_val)
            default_img = image_opt.get("value")
            if default_img:
                idx = self.cmb_image.findText(default_img)
                if idx >= 0:
                    self.cmb_image.setCurrentIndex(idx)
        else:
            self.cmb_image.addItem("(no images found for this template — install one in Image Manager)")

        self.spin_ram.setValue(int(options.get("ram", {}).get("value", 512) or 512))
        self.spin_cpu.setValue(int(options.get("cpu", {}).get("value", 1) or 1))
        self.spin_eth.setValue(int(options.get("ethernet", {}).get("value", 4) or 4))
        self.txt_name.setText(options.get("name", {}).get("value", "Node"))

    def get_node_data(self):
        template = self.cmb_template.currentData()
        options = self.template_details.get("options", {})
        
        # Start with a base set of data from template defaults
        data = {
            "template": template,
            "type": self.template_details.get("type", "qemu"),
            "image": self.cmb_image.currentText(),
            "name": self.txt_name.text(),
            "ram": self.spin_ram.value(),
            "cpu": self.spin_cpu.value(),
            "ethernet": self.spin_eth.value(),
            "left": "35%",
            "top": "25%",
            "delay": 0,
            "console": options.get("console", {}).get("value", "telnet"),
            "icon": options.get("icon", {}).get("value", "Router.png")
        }
        config_val = options.get("config", {}).get("value")
        if config_val is not None:
            data["config"] = config_val

        # Include other defaults from options if not already set
        for key, opt in options.items():
            if key not in data and "value" in opt:
                data[key] = opt["value"]

        return data


class EditNodeDialog(QDialog):
    """Lets you edit RAM/NVRAM/CPU/Ethernet for an existing node without
    deleting and re-adding it. Changes generally need the node (and often
    the whole lab) stopped before they take effect on next start."""

    def __init__(self, parent, node_info: dict):
        super().__init__(parent)
        node_name = node_info.get("name", f"Node-{node_info.get('id')}")
        self.setWindowTitle(f"Edit Node: {node_name}")
        self.setMinimumWidth(380)
        self.node_info = node_info

        layout = QVBoxLayout(self)

        is_running = node_info.get("status") in (1, 2)
        if is_running:
            warn = QLabel(
                "⚠ This node is currently running. EVE-NG may reject changes to a running node, "
                "or the new values won't apply until it's stopped and started again."
            )
            warn.setWordWrap(True)
            warn.setObjectName("warn")
            layout.addWidget(warn)

        form = QFormLayout()

        self.spin_ram = QSpinBox()
        self.spin_ram.setRange(32, 131072)
        self.spin_ram.setSingleStep(128)
        self.spin_ram.setSuffix(" MB")
        self.spin_ram.setValue(int(node_info.get("ram", 512) or 512))
        form.addRow("RAM:", self.spin_ram)

        self.spin_nvram = QSpinBox()
        self.spin_nvram.setRange(0, 1048576)
        self.spin_nvram.setSingleStep(64)
        self.spin_nvram.setSuffix(" KB")
        self.spin_nvram.setValue(int(node_info.get("nvram", 0) or 0))
        form.addRow("NVRAM:", self.spin_nvram)
        nvram_hint = QLabel("Mainly applies to Dynamips/IOL nodes; ignored by platforms that don't use it.")
        nvram_hint.setWordWrap(True)
        nvram_hint.setObjectName("muted")
        form.addRow("", nvram_hint)

        self.spin_cpu = QSpinBox()
        self.spin_cpu.setRange(1, 32)
        self.spin_cpu.setValue(int(node_info.get("cpu", 1) or 1))
        form.addRow("CPU Cores:", self.spin_cpu)

        self.spin_eth = QSpinBox()
        self.spin_eth.setRange(0, 32)
        self.spin_eth.setValue(int(node_info.get("ethernet", 4) or 4))
        form.addRow("Ethernet Ports:", self.spin_eth)

        layout.addLayout(form)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def get_changed_fields(self) -> dict:
        """Returns only the fields that actually changed, to keep the PUT payload minimal."""
        changes = {}
        if self.spin_ram.value() != int(self.node_info.get("ram", 512) or 512):
            changes["ram"] = self.spin_ram.value()
        if self.spin_nvram.value() != int(self.node_info.get("nvram", 0) or 0):
            changes["nvram"] = self.spin_nvram.value()
        if self.spin_cpu.value() != int(self.node_info.get("cpu", 1) or 1):
            changes["cpu"] = self.spin_cpu.value()
        if self.spin_eth.value() != int(self.node_info.get("ethernet", 4) or 4):
            changes["ethernet"] = self.spin_eth.value()
        return changes


class CaptureDialog(QDialog):
    """
    Wireshark packet capture dialog. Connects to the EVE-NG host over SSH
    (root), lists candidate bridge/interfaces, and pipes a live `tcpdump`
    stream into a locally-launched Wireshark window.
    """

    def __init__(self, parent, default_host: str, default_ssh_user: str = "root",
                 default_ssh_pass: str = "", default_ssh_port: int = 22):
        super().__init__(parent)
        self.setWindowTitle("Wireshark Packet Capture")
        self.setMinimumWidth(480)
        self.capture = None
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(300)
        self.poll_timer.timeout.connect(self.poll_log_queue)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        ssh_row = QHBoxLayout()
        self.txt_host = QLineEdit(default_host)
        self.txt_host.setFixedWidth(120)
        ssh_row.addWidget(self.txt_host)
        ssh_row.addWidget(QLabel("Port:"))
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(default_ssh_port)
        self.spin_port.setFixedWidth(70)
        ssh_row.addWidget(self.spin_port)
        ssh_row.addWidget(QLabel("User:"))
        self.txt_user = QLineEdit(default_ssh_user)
        self.txt_user.setFixedWidth(80)
        ssh_row.addWidget(self.txt_user)
        ssh_row.addWidget(QLabel("Pass:"))
        self.txt_pass = QLineEdit(default_ssh_pass)
        self.txt_pass.setEchoMode(QLineEdit.EchoMode.Password)
        ssh_row.addWidget(self.txt_pass)
        form.addRow("EVE-NG SSH (root):", ssh_row)

        iface_row = QHBoxLayout()
        self.cmb_interface = QComboBox()
        self.cmb_interface.setEditable(True)
        iface_row.addWidget(self.cmb_interface)
        self.btn_detect = QPushButton("Detect Interfaces")
        self.btn_detect.clicked.connect(self.detect_interfaces)
        iface_row.addWidget(self.btn_detect)
        form.addRow("Interface:", iface_row)

        ws_row = QHBoxLayout()
        self.txt_wireshark_path = QLineEdit(find_wireshark_executable())
        self.txt_wireshark_path.setPlaceholderText("Path to Wireshark executable")
        ws_row.addWidget(self.txt_wireshark_path)
        self.btn_browse_ws = QPushButton("Browse...")
        self.btn_browse_ws.clicked.connect(self.browse_wireshark)
        ws_row.addWidget(self.btn_browse_ws)
        form.addRow("Wireshark Path:", ws_row)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self.btn_start = QPushButton("▶ Start Capture")
        self.btn_start.setObjectName("btnPrimary")
        self.btn_start.clicked.connect(self.start_capture)
        btn_row.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⏹ Stop Capture")
        self.btn_stop.setObjectName("btnDanger")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_capture)
        btn_row.addWidget(self.btn_stop)
        layout.addLayout(btn_row)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(140)
        layout.addWidget(self.txt_log)

        note = QLabel(
            "Note: requires a local Wireshark install and reachable SSH/root access "
            "to the EVE-NG host. The capture runs on the host's network namespace, "
            "so choose the bridge/interface matching the link you want to sniff."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)

    def _log(self, msg: str):
        self.txt_log.append(f"> {msg}")

    def _make_capture(self) -> EveNGPacketCapture:
        return EveNGPacketCapture(
            self.txt_host.text().strip(),
            username=self.txt_user.text().strip(),
            password=self.txt_pass.text(),
            port=self.spin_port.value(),
        )

    def browse_wireshark(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Wireshark Executable")
        if path:
            self.txt_wireshark_path.setText(path)

    def detect_interfaces(self):
        self._log("Connecting via SSH to detect interfaces...")
        self.btn_detect.setEnabled(False)

        def _run():
            cap = self._make_capture()
            cap.connect()
            ifaces = cap.list_interfaces()
            cap.close()
            return ifaces

        self._detect_worker = WorkerThread(_run)

        def _done(status, res):
            self.btn_detect.setEnabled(True)
            if status == "success":
                self.cmb_interface.clear()
                self.cmb_interface.addItems(res)
                self._log(f"Found {len(res)} interface(s) on the EVE-NG host.")
            else:
                self._log(f"Error detecting interfaces: {res}")

        self._detect_worker.finished_signal.connect(_done)
        self._detect_worker.start()

    def start_capture(self):
        wireshark_path = self.txt_wireshark_path.text().strip()
        if not wireshark_path:
            QMessageBox.warning(self, "Wireshark Not Found",
                                 "Could not auto-detect Wireshark. Please browse to the executable.")
            return
        interface = self.cmb_interface.currentText().strip()
        if not interface:
            QMessageBox.warning(self, "No Interface", "Please select or type an interface to capture on.")
            return

        self.btn_start.setEnabled(False)
        self._log(f"Connecting via SSH to start capture on '{interface}'...")

        def _run():
            cap = self._make_capture()
            cap.connect()
            cap.start_capture(interface, wireshark_path)
            return cap

        self._start_worker = WorkerThread(_run)

        def _done(status, res):
            if status == "success":
                self.capture = res
                self.btn_stop.setEnabled(True)
                self.poll_timer.start()
                self._log("Capture started. A Wireshark window should now be showing live traffic.")
            else:
                self.btn_start.setEnabled(True)
                self._log(f"Failed to start capture: {res}")
                QMessageBox.critical(self, "Capture Failed", str(res))

        self._start_worker.finished_signal.connect(_done)
        self._start_worker.start()

    def poll_log_queue(self):
        if not self.capture:
            return
        try:
            while True:
                msg = self.capture.log_queue.get_nowait()
                self._log(msg)
        except Exception:
            pass  # queue empty

    def stop_capture(self):
        if self.capture:
            self.capture.close()
        self.poll_timer.stop()
        self.btn_stop.setEnabled(False)
        self.btn_start.setEnabled(True)
        self._log("Capture stopped.")

    def closeEvent(self, event):
        if self.capture:
            self.capture.close()
        self.poll_timer.stop()
        super().closeEvent(event)


class PingDialog(QDialog):
    """
    Built-in ping tester: one-shot or continuous, streaming color-coded
    output with live sent/received/loss/avg stats.
    """

    def __init__(self, parent, default_target: str = ""):
        super().__init__(parent)
        self.setWindowTitle("📡 Ping Tester")
        self.setMinimumWidth(560)
        self.worker = None

        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Target:"))
        self.txt_target = QLineEdit(default_target)
        self.txt_target.setPlaceholderText("IP or hostname, e.g. 192.168.1.1")
        self.txt_target.returnPressed.connect(self.start_ping)
        row.addWidget(self.txt_target, 1)

        row.addWidget(QLabel("Count:"))
        self.spin_count = QSpinBox()
        self.spin_count.setRange(0, 9999)
        self.spin_count.setValue(4)
        self.spin_count.setSpecialValueText("∞ (continuous)")
        row.addWidget(self.spin_count)
        self.btn_start = QPushButton("▶ Start")
        self.btn_start.setObjectName("btnPrimary")
        self.btn_start.clicked.connect(self.start_ping)
        row.addWidget(self.btn_start)
        self.btn_stop = QPushButton("⏹ Stop")
        self.btn_stop.setObjectName("btnDanger")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_ping)
        row.addWidget(self.btn_stop)
        layout.addLayout(row)

        self.lbl_stats = QLabel("Sent 0 · Received 0 · Loss —% · Avg — ms")
        self.lbl_stats.setObjectName("muted")
        layout.addWidget(self.lbl_stats)

        self.txt_output = QTextEdit()
        self.txt_output.setFont(QFont("Consolas", 10))
        self.txt_output.setReadOnly(True)
        layout.addWidget(self.txt_output, 1)

        hint = QLabel(
            "Runs your OS ping utility from this PC - useful to sanity-check "
            "management reachability before pushing configs."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    _COLORS = {"ok": "#22c55e", "fail": "#ef4444",
               "summary": "#38bdf8", "info": "#94a3b8"}

    def start_ping(self):
        if self.worker is not None and self.worker.isRunning():
            return
        target = self.txt_target.text().strip()
        if not target:
            QMessageBox.warning(self, "No Target", "Enter an IP or hostname first.")
            return
        self.txt_output.clear()
        self.worker = PingWorker(target, count=self.spin_count.value())
        self.worker.line_signal.connect(self.append_line)
        self.worker.stats_signal.connect(self.update_stats)
        self.worker.finished_sig.connect(lambda: (
            self.btn_start.setEnabled(True), self.btn_stop.setEnabled(False)))
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.worker.start()

    def stop_ping(self):
        if self.worker is not None:
            self.worker.stop()

    def append_line(self, text: str, kind: str):
        color = self._COLORS.get(kind, "#e2e8f0")
        safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.txt_output.append(f'<span style="color:{color};">{safe}</span>')

    def update_stats(self, sent: int, recv: int, loss: float, avg: float):
        loss_txt = f"{loss:.0f}%" if sent else "—"
        avg_txt = f"{avg:.1f}" if recv else "—"
        self.lbl_stats.setText(
            f"Sent {sent} · Received {recv} · Loss {loss_txt} · Avg {avg_txt} ms")

    def closeEvent(self, event):
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait(2000)
        super().closeEvent(event)


class TopoPingDialog(QDialog):
    """
    Ping FROM a device through its console: pick source device, optional
    source interface (auto-detected via 'show ip interface brief'),
    destination, and repeat count. VPCS devices get a plain ping.
    """

    def __init__(self, mainwin, preselect_node=None):
        super().__init__(mainwin)
        self.mw = mainwin
        self.setWindowTitle("📡 Ping From Device")
        self.setMinimumWidth(640)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.cmb_tp_device = QComboBox()
        for nid, info in self.mw.nodes_data.items():
            name = info.get("name", f"Node-{nid}")
            self.cmb_tp_device.addItem(f"{name} (ID: {nid})", int(nid))
        if self.cmb_tp_device.count() == 0:
            self.cmb_tp_device.addItem("(no devices loaded)", None)
        form.addRow("Source Device:", self.cmb_tp_device)

        intf_row = QHBoxLayout()
        self.cmb_tp_intf = QComboBox()
        self.cmb_tp_intf.setEditable(True)
        self.cmb_tp_intf.addItem("")  # blank = default source
        intf_row.addWidget(self.cmb_tp_intf, 1)
        self.btn_tp_detect = QPushButton("🔍 Detect")
        self.btn_tp_detect.setToolTip("Reads the device's real interfaces from its console.")
        self.btn_tp_detect.clicked.connect(self.detect_interfaces)
        intf_row.addWidget(self.btn_tp_detect)
        form.addRow("Source Interface:", intf_row)

        dst_row = QHBoxLayout()
        self.txt_tp_dst = QLineEdit()
        self.txt_tp_dst.setPlaceholderText("Destination IP, e.g. 10.0.0.2")
        dst_row.addWidget(self.txt_tp_dst, 1)
        dst_row.addWidget(QLabel("Count:"))
        self.spin_tp_count = QSpinBox()
        self.spin_tp_count.setRange(1, 500)
        self.spin_tp_count.setValue(5)
        dst_row.addWidget(self.spin_tp_count)
        form.addRow("Destination:", dst_row)
        layout.addLayout(form)

        run_row = QHBoxLayout()
        self.btn_tp_run = QPushButton("▶ Run Ping")
        self.btn_tp_run.setObjectName("btnPrimary")
        self.btn_tp_run.clicked.connect(self.run_ping)
        run_row.addWidget(self.btn_tp_run)
        self.lbl_tp_status = QLabel("")
        self.lbl_tp_status.setObjectName("muted")
        run_row.addWidget(self.lbl_tp_status, 1)
        layout.addLayout(run_row)

        self.txt_tp_out = QTextEdit()
        self.txt_tp_out.setFont(QFont("Consolas", 10))
        self.txt_tp_out.setReadOnly(True)
        self.txt_tp_out.setPlaceholderText(
            "Console output of the ping will appear here...\n"
            "Tip: use the device's own interfaces as source to test specific paths.")
        layout.addWidget(self.txt_tp_out, 1)

        hint = QLabel(
            "Runs the ping on the device itself over its console (device must be running). "
            "VPCS devices ignore source-interface/repeat options.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        if preselect_node is not None:
            idx = self.cmb_tp_device.findData(int(preselect_node))
            if idx >= 0:
                self.cmb_tp_device.setCurrentIndex(idx)
        elif self.cmb_tp_device.count() > 0:
            self.detect_interfaces()

    def _selected_info(self):
        nid = self.cmb_tp_device.currentData()
        if nid is None:
            return None
        for info in self.mw.nodes_data.values():
            if int(info.get("id", -1)) == int(nid):
                return info
        return None

    def _is_vpcs(self, info) -> bool:
        if not info:
            return False
        return ("vpcs" in str(info.get("type", "")).lower()
                or "vpcs" in str(info.get("template", "")).lower())

    def detect_interfaces(self):
        info = self._selected_info()
        host = self.mw.txt_ip.text().strip()
        nid = self.cmb_tp_device.currentData()
        if not info or not nid or not host:
            QMessageBox.warning(self, "Cannot Detect", "Select a device (and connect to EVE-NG) first.")
            return
        if self._is_vpcs(info):
            self.lbl_tp_status.setText("VPCS: no named interfaces — source option not available.")
            return

        self.btn_tp_detect.setEnabled(False)
        port = 32768 + int(nid)

        def _run():
            mgr = NodeConsoleManager(host, port, timeout=10.0)
            return mgr.send_commands(["enable", "terminal length 0", "show ip interface brief"])

        self._tp_detect_worker = WorkerThread(_run)

        def _done(status, result):
            self.btn_tp_detect.setEnabled(True)
            if status != "success":
                QMessageBox.warning(self, "Detection Failed", str(result))
                return
            from config_builder import parse_show_ip_interface_brief
            ifaces = parse_show_ip_interface_brief(result)
            current = self.cmb_tp_intf.currentText()
            self.cmb_tp_intf.clear()
            self.cmb_tp_intf.addItem("")  # default source first
            self.cmb_tp_intf.addItems(ifaces)
            if current:
                i = self.cmb_tp_intf.findText(current)
                if i >= 0:
                    self.cmb_tp_intf.setCurrentIndex(i)
            self.lbl_tp_status.setText(f"Detected {len(ifaces)} interface(s).")

        self._tp_detect_worker.finished_signal.connect(_done)
        self._tp_detect_worker.start()

    def run_ping(self):
        info = self._selected_info()
        nid = self.cmb_tp_device.currentData()
        dst = self.txt_tp_dst.text().strip()
        if not nid:
            QMessageBox.warning(self, "No Device", "Select a source device first.")
            return
        if not dst:
            QMessageBox.warning(self, "No Destination", "Enter a destination IP first.")
            return
        host = self.mw.txt_ip.text().strip()
        if not host:
            QMessageBox.warning(self, "Not Connected", "Connect to EVE-NG first.")
            return

        is_vpcs = self._is_vpcs(info)
        src_intf = "" if is_vpcs else self.cmb_tp_intf.currentText().strip()
        count = self.spin_tp_count.value()
        port = 32768 + int(nid)
        name = self.cmb_tp_device.currentText()

        self.btn_tp_run.setEnabled(False)
        self.txt_tp_out.clear()
        self.lbl_tp_status.setText(f"Pinging {dst} from {name.split(' (')[0]}...")
        self.log(f"Console ping from {name} → {dst} "
                 f"(src={src_intf or 'default'}, count={count})...")

        def _run():
            mgr = NodeConsoleManager(host, port, timeout=10.0)
            return mgr.send_console_ping(dst, src_intf, count, is_vpcs=is_vpcs)

        self._tp_ping_worker = WorkerThread(_run)

        def _done(status, result):
            self.btn_tp_run.setEnabled(True)
            text = result if status == "success" else f"[ERROR] {result}"
            self.txt_tp_out.setPlainText(text)
            import re as _re
            m = _re.search(r"Success rate is \((\d+) percent[^)]*\)", text)
            if m:
                self.lbl_tp_status.setText(f"Result: Success rate {m.group(1)}%")
                self.log(f"Console ping {name.split(' (')[0]} → {dst}: success rate {m.group(1)}%")
            else:
                self.lbl_tp_status.setText("Done (no summary line — check output).")

        self._tp_ping_worker.finished_signal.connect(_done)
        self._tp_ping_worker.start()


class LabMetaDialog(QDialog):
    """Collects metadata for a brand-new lab."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("🗂 Create New Lab")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("e.g. CCNA-Practice-2")
        form.addRow("Lab Name:", self.txt_name)

        meta_row = QHBoxLayout()
        self.txt_author = QLineEdit()
        self.txt_author.setPlaceholderText("(optional)")
        meta_row.addWidget(self.txt_author, 1)
        self.txt_version = QLineEdit("1.0")
        self.txt_version.setFixedWidth(60)
        meta_row.addWidget(QLabel("Version:"))
        meta_row.addWidget(self.txt_version)
        form.addRow("Author:", meta_row)

        self.txt_desc = QLineEdit()
        self.txt_desc.setPlaceholderText("(optional) what this lab covers")
        form.addRow("Description:", self.txt_desc)

        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value_name(self): return self.txt_name.text().strip()
    def value_author(self): return self.txt_author.text().strip()
    def value_version(self): return self.txt_version.text().strip() or "1.0"
    def value_desc(self): return self.txt_desc.text().strip()


class DhcpConfigDialog(QDialog):
    """Collects parameters for a Cisco IOS DHCP server pool and returns the
    generated command list via get_commands() after the dialog is accepted."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Configure DHCP Server")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.txt_pool_name = QLineEdit("LAN-POOL")
        form.addRow("Pool Name:", self.txt_pool_name)

        self.txt_network = QLineEdit("192.168.10.0")
        form.addRow("Network Address:", self.txt_network)

        self.txt_mask = QLineEdit("255.255.255.0")
        form.addRow("Subnet Mask:", self.txt_mask)

        self.txt_router = QLineEdit("192.168.10.1")
        form.addRow("Default Gateway:", self.txt_router)

        self.txt_dns = QLineEdit("8.8.8.8, 8.8.4.4")
        self.txt_dns.setPlaceholderText("Comma-separated, e.g. 8.8.8.8, 8.8.4.4")
        form.addRow("DNS Server(s):", self.txt_dns)

        self.txt_domain = QLineEdit()
        self.txt_domain.setPlaceholderText("(optional) e.g. lab.local")
        form.addRow("Domain Name:", self.txt_domain)

        lease_row = QHBoxLayout()
        self.spin_lease_days = QSpinBox()
        self.spin_lease_days.setRange(0, 365)
        self.spin_lease_days.setValue(1)
        lease_row.addWidget(self.spin_lease_days)
        lease_row.addWidget(QLabel("day(s)"))
        self.chk_lease_infinite = QCheckBox("Infinite lease")
        self.chk_lease_infinite.stateChanged.connect(
            lambda state: self.spin_lease_days.setEnabled(state == 0)
        )
        lease_row.addWidget(self.chk_lease_infinite)
        form.addRow("Lease Time:", lease_row)

        self.txt_excl_start = QLineEdit()
        self.txt_excl_start.setPlaceholderText("(optional) e.g. 192.168.10.1")
        form.addRow("Exclude Range Start:", self.txt_excl_start)

        self.txt_excl_end = QLineEdit()
        self.txt_excl_end.setPlaceholderText("(optional) e.g. 192.168.10.10")
        form.addRow("Exclude Range End:", self.txt_excl_end)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_commands(self) -> list:
        dns_servers = [d.strip() for d in self.txt_dns.text().split(",") if d.strip()]
        return generate_dhcp_pool_config(
            pool_name=self.txt_pool_name.text().strip() or "LAN-POOL",
            network=self.txt_network.text().strip(),
            subnet_mask=self.txt_mask.text().strip(),
            default_router=self.txt_router.text().strip(),
            dns_servers=dns_servers,
            lease_days=self.spin_lease_days.value(),
            lease_infinite=self.chk_lease_infinite.isChecked(),
            domain_name=self.txt_domain.text().strip(),
            excluded_start=self.txt_excl_start.text().strip(),
            excluded_end=self.txt_excl_end.text().strip(),
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EveBridge \u2014 EVE-NG Lab Automation")
        self.resize(1280, 800)
        # Allows shrinking well below the default size (e.g. docked next to Notepad
        # or a browser on a NOC desk) while staying usable — see FlowLayout above
        # for how the busiest toolbar row stays fully reachable at narrow widths.
        self.setMinimumSize(760, 480)
        self.setWindowIcon(load_app_icon())

        self.current_theme = self._load_theme_setting()
        self.setStyleSheet(themes.get_stylesheet(self.current_theme))

        self.eve_client = None
        self.current_lab = None
        self.nodes_data = {}
        self.batch_worker = None
        self._responsive_buttons = []      # [(button, icon_only_text, full_text), ...]
        self._responsive_compact_state = None

        self.init_ui()

    def register_responsive_button(self, btn: QPushButton, icon_text: str, full_text: str):
        """
        Registers a button to automatically collapse to icon-only (tooltip
        still shows the full label) once the window gets narrow — used for
        the busiest action buttons so their text doesn't get silently
        clipped mid-word when the window/tab is shrunk (e.g. docked next to
        Notepad or a browser).
        """
        if not btn.toolTip():
            btn.setToolTip(full_text)
        self._responsive_buttons.append((btn, icon_text, full_text))
        self._apply_responsive_button_state(btn, icon_text, full_text, self._is_compact_width())

    def _is_compact_width(self) -> bool:
        return self.width() < 1000

    @staticmethod
    def _apply_responsive_button_state(btn: QPushButton, icon_text: str, full_text: str, compact: bool):
        btn.setText(icon_text if compact else full_text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self._is_compact_width()
        if compact == self._responsive_compact_state:
            return  # avoid redundant setText() calls on every resize tick
        self._responsive_compact_state = compact
        for btn, icon_text, full_text in self._responsive_buttons:
            self._apply_responsive_button_state(btn, icon_text, full_text, compact)

    def _load_theme_setting(self) -> str:
        settings = QSettings("EveNGLabAutomation", "UISettings")
        return settings.value("theme", themes.DEFAULT_THEME, type=str)

    def _save_theme_setting(self, theme_name: str):
        settings = QSettings("EveNGLabAutomation", "UISettings")
        settings.setValue("theme", theme_name)

    def apply_theme(self, theme_name: str):
        self.current_theme = theme_name
        self.setStyleSheet(themes.get_stylesheet(theme_name))
        self._save_theme_setting(theme_name)
        if hasattr(self, "settings_dialog"):
            self.settings_dialog.setStyleSheet(themes.get_stylesheet(theme_name))

    def setup_settings_dialog(self):
        """Builds the Settings dialog once (housing the less-frequently-used
        options: external client tool paths and software updates), keeping
        the main window's top area compact instead of stacking every option
        as a permanently-visible group box."""
        dialog = QDialog(self)
        dialog.setWindowTitle("⚙ Settings")
        dialog.setMinimumWidth(560)
        layout = QVBoxLayout(dialog)

        # --- External Client Tool Paths ---
        paths_group = QGroupBox("External Client Paths (optional — leave blank to auto-detect)")
        paths_form = QFormLayout(paths_group)

        putty_row = QHBoxLayout()
        self.txt_putty_path = QLineEdit()
        self.txt_putty_path.setPlaceholderText(find_putty_executable() or r"e.g. C:\Program Files\PuTTY\putty.exe")
        putty_row.addWidget(self.txt_putty_path)
        btn_browse_putty = QPushButton("Browse...")
        btn_browse_putty.clicked.connect(self.browse_putty_path)
        putty_row.addWidget(btn_browse_putty)
        paths_form.addRow("PuTTY Path:", putty_row)

        vnc_row = QHBoxLayout()
        self.txt_vnc_path = QLineEdit()
        self.txt_vnc_path.setPlaceholderText(find_vnc_executable() or r"e.g. C:\Program Files\TightVNC\tvnviewer.exe")
        vnc_row.addWidget(self.txt_vnc_path)
        btn_browse_vnc = QPushButton("Browse...")
        btn_browse_vnc.clicked.connect(self.browse_vnc_path)
        vnc_row.addWidget(btn_browse_vnc)
        paths_form.addRow("VNC Viewer Path:", vnc_row)

        layout.addWidget(paths_group)

        # --- Software Updates ---
        update_group = QGroupBox(f"Software Updates (current version: v{updater.APP_VERSION})")
        update_form = QFormLayout(update_group)

        self.txt_update_url = QLineEdit(self._load_update_url_setting())
        self.txt_update_url.setPlaceholderText(
            "https://raw.githubusercontent.com/<user>/<repo>/main/update-manifest.json"
        )
        self.txt_update_url.editingFinished.connect(self._save_update_url_setting)
        update_form.addRow("Manifest URL:", self.txt_update_url)

        update_btn_row = QHBoxLayout()
        self.btn_check_update = QPushButton("🔄 Check for Updates")
        self.btn_check_update.clicked.connect(self.check_for_updates)
        update_btn_row.addWidget(self.btn_check_update)
        self.bar_update_progress = QProgressBar()
        self.bar_update_progress.setRange(0, 100)
        self.bar_update_progress.setVisible(False)
        update_btn_row.addWidget(self.bar_update_progress)
        update_btn_row.addStretch()
        update_form.addRow("", update_btn_row)

        layout.addWidget(update_group)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dialog.close)
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_row.addWidget(btn_close)
        layout.addLayout(close_row)

        self.settings_dialog = dialog

    def open_settings_dialog(self):
        self.settings_dialog.setStyleSheet(themes.get_stylesheet(self.current_theme))
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def init_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # --- Header: branding left, socials/docs top-right ---
        header_row = QHBoxLayout()
        lbl_brand = QLabel('🌐 <b>EveBridge</b>&nbsp;&nbsp;<span style="color:#94a3b8;">EVE-NG Lab Automation</span>')
        header_row.addWidget(lbl_brand)
        header_row.addStretch()

        lbl_links = QLabel(
            '<a href="https://github.com/sponsors/serhatcamm" style="color:#f472b6; text-decoration:none;">💖 Sponsor</a>'
            '&nbsp;&nbsp;&nbsp;'
            '<a href="https://github.com/serhatcamm" style="color:#38bdf8; text-decoration:none;">🐙 GitHub</a>'
            '&nbsp;&nbsp;&nbsp;'
            '<a href="https://www.linkedin.com/in/serhatcammm/" style="color:#38bdf8; text-decoration:none;">💼 LinkedIn</a>'
            '&nbsp;&nbsp;&nbsp;'
            '<a href="https://www.eve-ng.net/index.php/documentation/" style="color:#94a3b8; text-decoration:none;">📖 Docs</a>'
        )
        lbl_links.setOpenExternalLinks(True)
        lbl_links.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        header_row.addWidget(lbl_links)

        main_layout.addLayout(header_row)

        # --- Top Connection Bar ---
        # Uses FlowLayout instead of a plain QHBoxLayout so all these controls
        # stay reachable (wrapping onto new rows) instead of getting clipped
        # when the window is resized narrow — e.g. docked next to Notepad or
        # a browser on a NOC desk.
        conn_group = QGroupBox("EVE-NG Connection & Lab Selection")
        conn_layout = FlowLayout(conn_group)

        conn_layout.addWidget(QLabel("EVE-NG IP:"))
        self.txt_ip = QLineEdit()
        self.txt_ip.setPlaceholderText("e.g. 192.168.1.100")
        self.txt_ip.setFixedWidth(120)
        self.txt_ip.returnPressed.connect(self.connect_eve)
        conn_layout.addWidget(self.txt_ip)

        conn_layout.addWidget(QLabel("User:"))
        self.txt_user = QLineEdit()
        self.txt_user.setPlaceholderText("admin")
        self.txt_user.setFixedWidth(80)
        self.txt_user.returnPressed.connect(self.connect_eve)
        conn_layout.addWidget(self.txt_user)

        # Remember the last successful connection (IP + username only — never
        # the password) so launching the app is one keystroke away from ready.
        conn_settings = QSettings("EveNGLabAutomation", "ConnectionSettings")
        self.txt_ip.setText(conn_settings.value("last_ip", "", type=str))
        self.txt_user.setText(conn_settings.value("last_user", "", type=str))

        conn_layout.addWidget(QLabel("Pass:"))
        self.txt_pass = QLineEdit()
        self.txt_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_pass.setFixedWidth(80)
        conn_layout.addWidget(self.txt_pass)

        self.btn_connect = QPushButton("Connect / Login")
        self.btn_connect.setToolTip("Log in to the EVE-NG API with the credentials above and load available labs.")
        self.btn_connect.setObjectName("btnPrimary")
        self.btn_connect.clicked.connect(self.connect_eve)
        self.register_responsive_button(self.btn_connect, "🔌", "Connect / Login")
        conn_layout.addWidget(self.btn_connect)

        conn_layout.addWidget(QLabel("Lab Selection:"))
        self.cmb_labs = QComboBox()
        self.cmb_labs.setMinimumWidth(200)
        self.cmb_labs.currentIndexChanged.connect(self.on_lab_selected)
        conn_layout.addWidget(self.cmb_labs)

        # --- Lab management (create / duplicate / delete the selected lab) ---
        self.btn_new_lab = QPushButton("🗂+")
        self.btn_new_lab.setToolTip("Create a new empty lab on the server")
        self.btn_new_lab.clicked.connect(self.manage_lab_create_dialog)
        conn_layout.addWidget(self.btn_new_lab)

        self.btn_dup_lab = QPushButton("⧉")
        self.btn_dup_lab.setToolTip("Duplicate the selected lab (server-side copy)")
        self.btn_dup_lab.clicked.connect(self.manage_lab_duplicate)
        conn_layout.addWidget(self.btn_dup_lab)

        self.btn_del_lab = QPushButton("🗑")
        self.btn_del_lab.setObjectName("btnDanger")
        self.btn_del_lab.setToolTip("Delete the selected lab (requires typing its name)")
        self.btn_del_lab.clicked.connect(self.manage_lab_delete)
        conn_layout.addWidget(self.btn_del_lab)

        conn_layout.addSpacing(10)
        conn_layout.addWidget(QLabel("Protocol:"))
        self.cmb_proto = QComboBox()
        self.cmb_proto.addItems(["Telnet (Console)", "SSH (Port 22/Node)", "HTML5 Web Console", "VNC Viewer"])
        conn_layout.addWidget(self.cmb_proto)

        conn_layout.addWidget(QLabel("Terminal:"))
        self.cmb_terminal = QComboBox()
        for key, label in TERMINAL_CLIENTS:
            self.cmb_terminal.addItem(label, key)
        self.cmb_terminal.setMinimumWidth(170)
        self.cmb_terminal.currentIndexChanged.connect(self.on_terminal_client_changed)
        conn_layout.addWidget(self.cmb_terminal)

        self.txt_custom_terminal = QLineEdit()
        self.txt_custom_terminal.setPlaceholderText("Custom cmd, e.g. wt.exe ssh {user}@{ip} -p {port}")
        self.txt_custom_terminal.setFixedWidth(220)
        self.txt_custom_terminal.setVisible(False)
        conn_layout.addWidget(self.txt_custom_terminal)

        self.btn_refresh = QPushButton("Refresh Labs & Nodes")
        self.btn_refresh.setToolTip("Reload the node list and status for the currently selected lab.")
        self.btn_refresh.clicked.connect(self.refresh_lab)
        self.register_responsive_button(self.btn_refresh, "🔄", "Refresh Labs & Nodes")
        conn_layout.addWidget(self.btn_refresh)

        main_layout.addWidget(conn_group)

        # --- Compact quick-access row: theme (used often) inline; everything else
        # rarely touched (client tool paths, update checks) lives in the Settings
        # dialog instead of permanently taking up window space. ---
        quick_row = QHBoxLayout()
        quick_row.addWidget(QLabel("Theme:"))
        self.cmb_theme = QComboBox()
        self.cmb_theme.addItems(themes.THEME_NAMES)
        self.cmb_theme.setCurrentText(self.current_theme)
        self.cmb_theme.currentTextChanged.connect(self.apply_theme)
        quick_row.addWidget(self.cmb_theme)

        quick_row.addStretch()

        self.lbl_version = QLabel(f"v{updater.APP_VERSION}")
        self.lbl_version.setObjectName("muted")
        quick_row.addWidget(self.lbl_version)

        self.btn_open_settings = QPushButton("⚙ Settings")
        self.btn_open_settings.setToolTip("Terminal client paths (PuTTY/VNC) and software update settings")
        self.btn_open_settings.clicked.connect(self.open_settings_dialog)
        quick_row.addWidget(self.btn_open_settings)

        main_layout.addLayout(quick_row)

        self.setup_settings_dialog()

        # --- Server Load Status Widget ---
        server_group = QGroupBox("EVE-NG Server Load & Hardware Monitor")
        server_layout = QHBoxLayout(server_group)

        server_layout.addWidget(QLabel("CPU Load:"))
        self.bar_cpu = QProgressBar()
        self.bar_cpu.setRange(0, 100)
        self.bar_cpu.setFixedWidth(110)
        server_layout.addWidget(self.bar_cpu)

        server_layout.addWidget(QLabel("RAM Usage:"))
        self.bar_ram = QProgressBar()
        self.bar_ram.setRange(0, 100)
        self.bar_ram.setFixedWidth(110)
        server_layout.addWidget(self.bar_ram)

        server_layout.addWidget(QLabel("Disk Usage:"))
        self.bar_disk = QProgressBar()
        self.bar_disk.setRange(0, 100)
        self.bar_disk.setFixedWidth(110)
        server_layout.addWidget(self.bar_disk)

        self.lbl_server_nodes = QLabel("Active Nodes: - (IOL: - | Dynamips: - | VPCS: - | QEMU: -)")
        self.lbl_server_nodes.setObjectName("accentText")
        server_layout.addWidget(self.lbl_server_nodes)

        server_layout.addStretch()
        main_layout.addWidget(server_group)

        # --- Main Tab Widget ---
        self.tabs = QTabWidget()

        # Tab 1: Node Control & Monitoring
        self.tab_nodes = QWidget()
        self.setup_nodes_tab()
        self.tabs.addTab(self.tab_nodes, "Nodes & Status")

        # Tab 2: Router-on-a-Stick Configurator
        self.tab_ros = QWidget()
        self.setup_ros_tab()
        self.tabs.addTab(self.tab_ros, "Router-on-a-Stick Auto-Config")

        # Tab 3: Switch VLAN Configurator
        self.tab_vlan = QWidget()
        self.setup_vlan_tab()
        self.tabs.addTab(self.tab_vlan, "Switch VLAN & Trunk Config")

        # Tab 3b: Routing Protocol & Network Services Configurator
        self.tab_routing = QWidget()
        self.setup_routing_tab()
        self.tabs.addTab(self.tab_routing, "🌐 Routing & Services")

        # Tab 4: Batch CLI Console Executor
        self.tab_cli = QWidget()
        self.setup_cli_tab()
        self.tabs.addTab(self.tab_cli, "Batch Console CLI")

        # Tab 5: Lab Topology Diagram View
        self.tab_topo = QWidget()
        self.setup_topo_tab()
        self.tabs.addTab(self.tab_topo, "🗺️ Lab Topology Diagram")

        # Tab 6: Image Manager (upload new node images to the server)
        self.tab_images = QWidget()
        self.setup_images_tab()
        self.tabs.addTab(self.tab_images, "📦 Image Manager")

        # Tab 7: Firewall/UTM Config Wizard (pfSense, OPNsense, FortiGate)
        self.tab_firewall = QWidget()
        self.setup_firewall_tab()
        self.tabs.addTab(self.tab_firewall, "🧱 Firewall/UTM Wizard")

        # Tab 8: Export Lab (download the lab folder as a local zip)
        self.tab_export = QWidget()
        self.setup_export_tab()
        self.tabs.addTab(self.tab_export, "📤 Export Lab")

        # Tab 9: Ansible artifacts generator
        self.tab_ansible = QWidget()
        self.setup_ansible_tab()
        self.tabs.addTab(self.tab_ansible, "⚙️ Ansible")

        # Tab 10: Active Directory / Group Policy helper
        self.tab_adgpo = QWidget()
        self.setup_adgpo_tab()
        self.tabs.addTab(self.tab_adgpo, "🪟 AD & GPO")

        main_layout.addWidget(self.tabs)

        # --- Status Bar / Log Output ---
        log_header_row = QHBoxLayout()
        log_header_row.addWidget(QLabel("Activity Log"))
        log_header_row.addStretch()
        btn_clear_log = QPushButton("Clear")
        btn_clear_log.setToolTip("Clear the activity log")
        btn_clear_log.setFixedWidth(64)
        btn_clear_log.clicked.connect(lambda: self.txt_log.clear())
        log_header_row.addWidget(btn_clear_log)
        main_layout.addLayout(log_header_row)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(140)
        self.txt_log.setPlaceholderText("System activity log...")
        main_layout.addWidget(self.txt_log)

        self.setCentralWidget(main_widget)

        # Ctrl+R refreshes the current lab from anywhere in the window.
        refresh_shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        refresh_shortcut.activated.connect(self.refresh_lab)

        # Auto connect on startup — only when connection details were
        # remembered from a previous successful login. Silent mode: failures
        # land in the activity log instead of popping a modal at launch.
        # Set EVEBRIDGE_NO_AUTOCONNECT=1 to skip (used by automated tests).
        if (not os.environ.get("EVEBRIDGE_NO_AUTOCONNECT")
                and self.txt_ip.text().strip() and self.txt_user.text().strip()):
            self.connect_eve(silent=True)

    def log(self, msg: str):
        timestamped = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        self.txt_log.append(f"> {timestamped}")

    def on_terminal_client_changed(self, _index):
        self.txt_custom_terminal.setVisible(self.cmb_terminal.currentData() == "custom")

    def browse_putty_path(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select PuTTY Executable", "", "Executable (putty.exe);;All Files (*)")
        if path:
            self.txt_putty_path.setText(path)

    def browse_vnc_path(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select VNC Viewer Executable", "", "Executable (*.exe);;All Files (*)")
        if path:
            self.txt_vnc_path.setText(path)

    # ------------------ SOFTWARE UPDATES ------------------
    def _load_update_url_setting(self) -> str:
        settings = QSettings("EveNGLabAutomation", "UpdateSettings")
        return settings.value("manifest_url", "", type=str)

    def _save_update_url_setting(self):
        settings = QSettings("EveNGLabAutomation", "UpdateSettings")
        settings.setValue("manifest_url", self.txt_update_url.text().strip())

    def check_for_updates(self):
        url = self.txt_update_url.text().strip()
        if not url:
            QMessageBox.information(
                self, "No Update URL",
                "Enter an update manifest URL first — a JSON file hosted somewhere reachable "
                "(e.g. a raw GitHub file) with 'version', 'changelog', and 'download_url' fields."
            )
            return

        self.btn_check_update.setEnabled(False)
        self.log(f"Checking for updates (current version: v{updater.APP_VERSION})...")

        def _run():
            return updater.check_for_update(url)

        self._update_check_worker = WorkerThread(_run)
        self._update_check_worker.finished_signal.connect(self._on_update_check_done)
        self._update_check_worker.start()

    def _on_update_check_done(self, status: str, result):
        self.btn_check_update.setEnabled(True)
        if status != "success":
            self.log(f"Update check failed: {result}")
            QMessageBox.warning(self, "Update Check Failed", str(result))
            return

        manifest = result
        if not manifest:
            self.log(f"Already on the latest version (v{updater.APP_VERSION}).")
            QMessageBox.information(self, "No Updates", f"You're already on the latest version (v{updater.APP_VERSION}).")
            return

        remote_version = manifest.get("version", "unknown")
        changelog = manifest.get("changelog", "(no changelog provided)")
        download_url = manifest.get("download_url", "")

        confirm = QMessageBox.question(
            self, "Update Available",
            f"A new version is available: v{remote_version} (you have v{updater.APP_VERSION}).\n\n"
            f"Changelog:\n{changelog}\n\nDownload and install now? Files that get replaced are "
            f"backed up automatically first.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        if not download_url:
            QMessageBox.warning(self, "Missing Download URL", "The update manifest doesn't include a 'download_url'.")
            return

        self.apply_update(download_url)

    def apply_update(self, download_url: str):
        app_dir = os.path.dirname(os.path.abspath(__file__))
        self.bar_update_progress.setVisible(True)
        self.bar_update_progress.setValue(0)
        self.btn_check_update.setEnabled(False)
        self.log("Downloading and applying update...")

        self._update_worker = UpdateWorker(download_url, app_dir)
        self._update_worker.progress_signal.connect(self._on_update_progress)
        self._update_worker.finished_signal.connect(self._on_update_finished)
        self._update_worker.start()

    def _on_update_progress(self, pct: int, msg: str):
        self.bar_update_progress.setValue(pct)
        self.log(msg)

    def _on_update_finished(self, success: bool, result: str):
        self.btn_check_update.setEnabled(True)
        if success:
            self.bar_update_progress.setValue(100)
            self.log(f"Update applied successfully. Replaced files were backed up to: {result}")
            restart = QMessageBox.question(
                self, "Update Complete",
                "The update was applied successfully. Restart the application now to use the new version?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if restart == QMessageBox.StandardButton.Yes:
                self.restart_application()
        else:
            self.bar_update_progress.setVisible(False)
            self.log(f"Update failed: {result}")
            QMessageBox.critical(self, "Update Failed", str(result))

    def restart_application(self):
        """Relaunches the current process in place so the newly-installed
        files take effect immediately, instead of asking the user to
        remember to restart manually."""
        python = sys.executable
        os.execv(python, [python] + sys.argv)

    # ------------------ CONNECTION & REFRESH ------------------
    def connect_eve(self, silent: bool = False):
        ip = self.txt_ip.text().strip()
        user = self.txt_user.text().strip()
        pwd = self.txt_pass.text()

        if not ip or not user:
            message = (
                "Enter your EVE-NG server's IP address and username first.\n"
                "(No credentials are bundled with this app — you provide your own.)"
            )
            if silent:
                self.log(f"Auto-connect skipped — {message.splitlines()[0]}")
            else:
                QMessageBox.warning(self, "Missing Connection Details", message)
            return

        self.eve_client = EveNGClient(host=ip, username=user, password=pwd)
        if self.eve_client.login():
            QSettings("EveNGLabAutomation", "ConnectionSettings").setValue("last_ip", ip)
            QSettings("EveNGLabAutomation", "ConnectionSettings").setValue("last_user", user)
            self.log(f"Successfully authenticated with EVE-NG at {ip} ({self.eve_client.scheme.upper()})")
            self.fetch_available_labs()
            self.refresh_lab()
        else:
            detail = getattr(self.eve_client, "last_error", "")
            self.log(f"FAILED to authenticate with EVE-NG at {ip} — {detail}")
            if silent:
                return
            QMessageBox.critical(
                self, "Connection Error",
                f"Couldn't connect to EVE-NG at {ip}.\n\n"
                f"Why: {detail}\n\n"
                f"Checklist:\n"
                f"  • Is the EVE-NG server powered on and reachable? (try: ping {ip})\n"
                f"  • Is the IP correct? Servers can change addresses after a DHCP renewal.\n"
                f"  • Are the username/password right?\n"
                f"  • HTTP and HTTPS are both tried automatically."
            )

    def fetch_available_labs(self):
        if not self.eve_client or not self.eve_client.is_logged_in:
            return
        
        labs = self.eve_client.get_labs()
        self._labs_cache = labs
        self.cmb_labs.blockSignals(True)
        self.cmb_labs.clear()

        for lab_info in labs:
            path = lab_info.get("path", "")
            file_name = lab_info.get("file", path)
            self.cmb_labs.addItem(f"📁 {file_name}", path)

        if labs:
            # Select the first available lab (no hardcoded default lab is bundled).
            self.cmb_labs.setCurrentIndex(0)
            self.current_lab = self.cmb_labs.currentData()
            self.log(f"Found {len(labs)} lab(s) on EVE-NG server.")
        else:
            self.log("No labs found on the EVE-NG server.")
        self.cmb_labs.blockSignals(False)

    def on_lab_selected(self, index: int):
        lab_path = self.cmb_labs.currentData()
        if lab_path:
            self.current_lab = lab_path
            self.log(f"Selected Lab: {lab_path}")
            self.refresh_lab()

    def update_server_status(self):
        if not self.eve_client or not self.eve_client.is_logged_in:
            return
        status = self.eve_client.get_server_status()
        if status:
            cpu = int(status.get("cpu", 0))
            mem = int(status.get("mem", 0))
            disk = int(status.get("disk", 0))

            self.bar_cpu.setValue(cpu)
            self.bar_ram.setValue(mem)
            self.bar_disk.setValue(disk)

            iol = status.get("iol", 0)
            dynamips = status.get("dynamips", 0)
            vpcs = status.get("vpcs", 0)
            qemu = status.get("qemu", 0)
            total = iol + dynamips + vpcs + qemu

            self.lbl_server_nodes.setText(f"Active Server Nodes: {total} (IOL: {iol} | Dynamips: {dynamips} | VPCS: {vpcs} | QEMU: {qemu})")

    def refresh_lab(self):
        if not self.eve_client or not self.eve_client.is_logged_in:
            self.log("Please login first.")
            return

        self.update_server_status()

        lab_name = self.current_lab
        if not lab_name:
            return
        self.log(f"Fetching lab nodes for: {lab_name}")

        nodes = self.eve_client.get_lab_nodes(lab_name)
        self.nodes_data = nodes
        self.populate_nodes_table(nodes)
        self.populate_ros_node_combos(nodes)
        if hasattr(self, "cmb_node_groups"):
            self.populate_group_combo()
        if hasattr(self, "cmb_exp_lab"):
            self.refresh_export_lab_combo()

    # ------------------ TAB 6: IMAGE MANAGER ------------------
    def setup_images_tab(self):
        layout = QVBoxLayout(self.tab_images)

        info = QLabel(
            "Upload and install new node images following EVE-NG's own documented procedures "
            "(<a href='https://www.eve-ng.net/index.php/documentation/howtos/'>eve-ng.net howtos</a>) — "
            "correct folder/disk naming, format conversion, IOL licensing, and Dynamips decompression "
            "are all handled automatically. Uses the server's <b>root SSH login</b>, separate from the "
            "API admin login used above."
        )
        info.setWordWrap(True)
        info.setOpenExternalLinks(True)
        info.setObjectName("muted")
        layout.addWidget(info)

        # --- SSH Credentials ---
        ssh_group = QGroupBox("EVE-NG SSH Access (root)")
        ssh_layout = QHBoxLayout(ssh_group)

        ssh_layout.addWidget(QLabel("Host:"))
        self.txt_ssh_host = QLineEdit()
        self.txt_ssh_host.setPlaceholderText("EVE-NG server IP")
        self.txt_ssh_host.setFixedWidth(120)
        ssh_layout.addWidget(self.txt_ssh_host)

        ssh_layout.addWidget(QLabel("Port:"))
        self.spin_ssh_port = QSpinBox()
        self.spin_ssh_port.setRange(1, 65535)
        self.spin_ssh_port.setValue(22)
        self.spin_ssh_port.setFixedWidth(70)
        ssh_layout.addWidget(self.spin_ssh_port)

        ssh_layout.addWidget(QLabel("User:"))
        self.txt_ssh_user = QLineEdit("root")
        self.txt_ssh_user.setFixedWidth(80)
        ssh_layout.addWidget(self.txt_ssh_user)

        ssh_layout.addWidget(QLabel("Pass:"))
        self.txt_ssh_pass = QLineEdit()
        self.txt_ssh_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_ssh_pass.setFixedWidth(110)
        ssh_layout.addWidget(self.txt_ssh_pass)

        ssh_layout.addStretch()
        layout.addWidget(ssh_group)

        img_tabs = QTabWidget()

        # ===================== Sub-tab: Standard Upload =====================
        std_tab = QWidget()
        std_layout = QVBoxLayout(std_tab)

        up_group = QGroupBox("Upload New Image")
        up_layout = QFormLayout(up_group)

        self.cmb_img_type = QComboBox()
        self.cmb_img_type.addItem("QEMU (Windows / vIOS / CSR1000v / ASAv / etc.)", "qemu")
        self.cmb_img_type.addItem("🐧 Linux VM (Ubuntu / Debian / any qcow2 or ISO)", "linux")
        self.cmb_img_type.addItem("IOL (Cisco IOL / IOU)", "iol")
        self.cmb_img_type.addItem("Dynamips (classic Cisco IOS .bin/.image)", "dynamips")
        self.cmb_img_type.currentIndexChanged.connect(self.on_image_type_changed)
        up_layout.addRow("Image Type:", self.cmb_img_type)

        self.cmb_qemu_vendor = QComboBox()
        self.cmb_qemu_vendor.setEditable(True)
        self.cmb_qemu_vendor.addItem("— Select a vendor to auto-fill naming —", None)
        for prefix, vendor, disks in QEMU_IMAGE_NAMING:
            self.cmb_qemu_vendor.addItem(f"{vendor}  ({prefix} → {disks[0]}.qcow2)", prefix)
        self.cmb_qemu_vendor.currentIndexChanged.connect(self.on_qemu_vendor_changed)
        up_layout.addRow("QEMU Vendor Preset:", self.cmb_qemu_vendor)

        path_row = QHBoxLayout()
        self.txt_local_path = QLineEdit()
        self.txt_local_path.setPlaceholderText("Select the image folder or file on your computer...")
        self.txt_local_path.textChanged.connect(self.on_local_path_changed)
        path_row.addWidget(self.txt_local_path)
        self.btn_browse_folder = QPushButton("Browse Folder...")
        self.btn_browse_folder.clicked.connect(lambda: self.browse_image_path(folder=True))
        path_row.addWidget(self.btn_browse_folder)
        self.btn_browse_file = QPushButton("Browse File...")
        self.btn_browse_file.clicked.connect(lambda: self.browse_image_path(folder=False))
        path_row.addWidget(self.btn_browse_file)
        up_layout.addRow("Local Path:", path_row)

        self.txt_remote_name = QLineEdit()
        up_layout.addRow("QEMU Folder Name:", self.txt_remote_name)

        self.lbl_disk_hint = QLabel("Required disk file: (select a vendor preset or type a known prefix above)")
        self.lbl_disk_hint.setObjectName("muted")
        up_layout.addRow("", self.lbl_disk_hint)

        self.chk_convert_qcow2 = QCheckBox(
            "Convert to qcow2 on server after upload (auto-detected from file extension; "
            "required for .vmdk/.raw/.img/.vhd/.vhdx/.ova sources)"
        )
        up_layout.addRow("", self.chk_convert_qcow2)

        self.chk_fixperms = QCheckBox("Run fixpermissions automatically after upload (recommended)")
        self.chk_fixperms.setChecked(True)
        up_layout.addRow("", self.chk_fixperms)

        std_layout.addWidget(up_group)

        # IOL license sub-section
        iol_group = QGroupBox("IOL/IOU License (iourc) — required for IOL/IOU nodes to start")
        iol_layout = QHBoxLayout(iol_group)
        self.txt_iourc = QLineEdit()
        self.txt_iourc.setPlaceholderText("[license]  unl01 = 0123456789abcdef;")
        iol_layout.addWidget(self.txt_iourc)
        btn_write_iourc = QPushButton("Write iourc License to Server")
        btn_write_iourc.clicked.connect(self.write_iol_license)
        iol_layout.addWidget(btn_write_iourc)
        std_layout.addWidget(iol_group)

        btn_row = QHBoxLayout()
        self.btn_upload = QPushButton("⬆️ Upload & Install Image")
        self.btn_upload.setObjectName("btnPrimary")
        self.btn_upload.clicked.connect(self.start_image_upload)
        btn_row.addWidget(self.btn_upload)

        self.btn_fixperms_only = QPushButton("🔧 Run Fix Permissions Only")
        self.btn_fixperms_only.clicked.connect(self.run_fixperms_only)
        btn_row.addWidget(self.btn_fixperms_only)

        self.btn_list_images = QPushButton("📋 Refresh Existing Images")
        self.btn_list_images.clicked.connect(self.refresh_existing_images)
        btn_row.addWidget(self.btn_list_images)
        btn_row.addStretch()
        std_layout.addLayout(btn_row)

        self.bar_upload = QProgressBar()
        self.bar_upload.setRange(0, 100)
        std_layout.addWidget(self.bar_upload)

        std_layout.addWidget(QLabel("Images already on the server for the selected type:"))
        self.list_existing_images = QTextEdit()
        self.list_existing_images.setReadOnly(True)
        self.list_existing_images.setPlaceholderText("Click 'Refresh Existing Images' to list what's already on the server...")
        std_layout.addWidget(self.list_existing_images)

        img_tabs.addTab(std_tab, "Standard Upload")

        # ===================== Sub-tab: ISO-Install Wizard =====================
        iso_tab = QWidget()
        iso_layout = QVBoxLayout(iso_tab)

        iso_info = QLabel(
            "For platforms distributed as an install ISO rather than a ready disk image "
            "(e.g. Cisco CSR1000v, XRv 9000, some Firepower builds): this prepares the working "
            "directory, uploads the ISO, and creates a blank disk exactly as EVE-NG's howto "
            "describes. The install itself is interactive (you'll watch the console and press keys "
            "per the vendor's installer), so step 2 opens a real terminal with the exact command "
            "copied to your clipboard — paste and run it there."
        )
        iso_info.setWordWrap(True)
        iso_info.setObjectName("muted")
        iso_layout.addWidget(iso_info)

        iso_form_group = QGroupBox("1) Prepare Install Environment")
        iso_form = QFormLayout(iso_form_group)

        iso_path_row = QHBoxLayout()
        self.txt_iso_path = QLineEdit()
        self.txt_iso_path.setPlaceholderText("Select the vendor install .iso...")
        iso_path_row.addWidget(self.txt_iso_path)
        btn_browse_iso = QPushButton("Browse ISO...")
        btn_browse_iso.clicked.connect(self.browse_iso_path)
        iso_path_row.addWidget(btn_browse_iso)
        iso_form.addRow("Install ISO:", iso_path_row)

        self.txt_iso_folder_name = QLineEdit()
        self.txt_iso_folder_name.setPlaceholderText("e.g. csr1000vng-universalk9.16.09.06.Fuji")
        iso_form.addRow("Final QEMU Folder Name:", self.txt_iso_folder_name)

        self.spin_iso_disk_size = QSpinBox()
        self.spin_iso_disk_size.setRange(1, 500)
        self.spin_iso_disk_size.setValue(8)
        self.spin_iso_disk_size.setSuffix(" GB")
        iso_form.addRow("Disk Size:", self.spin_iso_disk_size)

        self.spin_iso_ram = QSpinBox()
        self.spin_iso_ram.setRange(256, 65536)
        self.spin_iso_ram.setSingleStep(256)
        self.spin_iso_ram.setValue(4096)
        self.spin_iso_ram.setSuffix(" MB")
        iso_form.addRow("Install RAM:", self.spin_iso_ram)

        iso_layout.addWidget(iso_form_group)

        iso_btn_row = QHBoxLayout()
        self.btn_iso_prepare = QPushButton("1) Prepare & Create Blank Disk")
        self.btn_iso_prepare.setObjectName("btnPrimary")
        self.btn_iso_prepare.clicked.connect(self.iso_prepare_install)
        iso_btn_row.addWidget(self.btn_iso_prepare)

        self.btn_iso_open_console = QPushButton("2) Copy Install Command + Open SSH Console")
        self.btn_iso_open_console.setEnabled(False)
        self.btn_iso_open_console.clicked.connect(self.iso_open_install_console)
        iso_btn_row.addWidget(self.btn_iso_open_console)

        self.btn_iso_finalize = QPushButton("3) Finalize (Move Disk + Fix Permissions)")
        self.btn_iso_finalize.setEnabled(False)
        self.btn_iso_finalize.clicked.connect(self.iso_finalize_install)
        iso_btn_row.addWidget(self.btn_iso_finalize)
        iso_layout.addLayout(iso_btn_row)

        self.bar_iso_progress = QProgressBar()
        self.bar_iso_progress.setRange(0, 100)
        iso_layout.addWidget(self.bar_iso_progress)

        iso_layout.addWidget(QLabel("Install command (also copied to clipboard by step 2):"))
        self.txt_iso_command = QTextEdit()
        self.txt_iso_command.setFont(QFont("Consolas", 9))
        self.txt_iso_command.setReadOnly(True)
        self.txt_iso_command.setMaximumHeight(80)
        iso_layout.addWidget(self.txt_iso_command)

        img_tabs.addTab(iso_tab, "ISO-Install Wizard")

        # ===================== Sub-tab: Dynamips Idle-PC =====================
        idle_tab = QWidget()
        idle_layout = QVBoxLayout(idle_tab)

        idle_info = QLabel(
            "After uploading a Dynamips image (Standard Upload tab handles the required decompression "
            "automatically), it's recommended to calculate an Idle-PC value to keep CPU usage sane. "
            "This is interactive — copy the command below, run it in an SSH console, wait for the "
            "\"initial configuration dialog\" prompt, answer 'no', press Enter, then use ctrl+] then "
            "'i' to get suggested values. Pick the value with the highest count."
        )
        idle_info.setWordWrap(True)
        idle_info.setObjectName("muted")
        idle_layout.addWidget(idle_info)

        idle_form_group = QGroupBox("Idle-PC Calculation Command")
        idle_form = QFormLayout(idle_form_group)

        self.txt_idle_image_path = QLineEdit()
        self.txt_idle_image_path.setPlaceholderText("/opt/unetlab/addons/dynamips/c3725-adventerprisek9-mz.124-15.T14.image")
        idle_form.addRow("Image Path on Server:", self.txt_idle_image_path)

        self.cmb_idle_platform = QComboBox()
        self.cmb_idle_platform.addItems(["1710", "3725", "7200"])
        self.cmb_idle_platform.setCurrentText("3725")
        idle_form.addRow("Platform:", self.cmb_idle_platform)

        idle_layout.addWidget(idle_form_group)

        btn_idle_console = QPushButton("Copy Command + Open SSH Console")
        btn_idle_console.setObjectName("btnPrimary")
        btn_idle_console.clicked.connect(self.idlepc_open_console)
        idle_layout.addWidget(btn_idle_console)

        idle_layout.addWidget(QLabel("Command (also copied to clipboard):"))
        self.txt_idle_command = QTextEdit()
        self.txt_idle_command.setFont(QFont("Consolas", 9))
        self.txt_idle_command.setReadOnly(True)
        self.txt_idle_command.setMaximumHeight(60)
        idle_layout.addWidget(self.txt_idle_command)
        idle_layout.addStretch()

        img_tabs.addTab(idle_tab, "Dynamips Idle-PC")

        # ===================== Sub-tab: Online Store =====================
        store_tab = QWidget()
        store_layout = QVBoxLayout(store_tab)

        store_info = QLabel(
            "One-click install of community EVE-NG images (source: hegdepavankumar/"
            "Cisco-Images-for-GNS3-and-EVE-NG). Downloads to this PC, uploads to the "
            "server via SSH, extracts and fixes permissions automatically. "
            "Images are vendor-copyrighted — personal lab use only."
        )
        store_info.setWordWrap(True)
        store_info.setObjectName("muted")
        store_layout.addWidget(store_info)

        store_filter_row = QHBoxLayout()
        store_filter_row.addWidget(QLabel("Vendor:"))
        self.cmb_store_vendor = QComboBox()
        self.cmb_store_vendor.addItem("All vendors", None)
        for v in image_store.VENDORS[1:]:
            self.cmb_store_vendor.addItem(v, v)
        self.cmb_store_vendor.currentIndexChanged.connect(self.store_populate_list)
        store_filter_row.addWidget(self.cmb_store_vendor, 1)

        store_filter_row.addWidget(QLabel("Search:"))
        self.txt_store_search = QLineEdit()
        self.txt_store_search.setPlaceholderText("Filter by name...")
        self.txt_store_search.textChanged.connect(self.store_populate_list)
        store_filter_row.addWidget(self.txt_store_search, 1)
        store_layout.addLayout(store_filter_row)

        self.list_store = QListWidget()
        self.list_store.setToolTip("Select an image, then click Install.")
        store_layout.addWidget(self.list_store, 1)

        store_btn_row = QHBoxLayout()
        self.btn_store_install = QPushButton("⬇️ Install Selected Image")
        self.btn_store_install.setObjectName("btnPrimary")
        self.btn_store_install.clicked.connect(self.store_install_selected)
        store_btn_row.addWidget(self.btn_store_install)
        store_btn_row.addStretch()
        store_layout.addLayout(store_btn_row)

        self.bar_store_dl = QProgressBar()
        self.bar_store_dl.setRange(0, 100)
        store_layout.addWidget(self.bar_store_dl)
        self.lbl_store_status = QLabel("")
        self.lbl_store_status.setObjectName("muted")
        store_layout.addWidget(self.lbl_store_status)

        # custom URL installer
        custom_group = QGroupBox("Custom image (any direct URL)")
        cg_form = QFormLayout(custom_group)
        self.txt_store_url = QLineEdit()
        self.txt_store_url.setPlaceholderText("https://... / image.tgz or .qcow2")
        cg_form.addRow("URL:", self.txt_store_url)
        self.txt_store_folder = QLineEdit()
        self.txt_store_folder.setPlaceholderText("EVE-NG folder name, e.g. asav-984-10")
        cg_form.addRow("Folder:", self.txt_store_folder)
        btn_custom = QPushButton("⬇️ Install from URL")
        btn_custom.clicked.connect(self.store_install_custom)
        cg_form.addRow("", btn_custom)
        store_layout.addWidget(custom_group)

        img_tabs.addTab(store_tab, "🌐 Online Store")
        self.store_populate_list()

        layout.addWidget(img_tabs)
        self.on_image_type_changed(0)

    def on_image_type_changed(self, _index):
        img_type = self.cmb_img_type.currentData()
        is_qemu = img_type == "qemu"
        is_linux = img_type == "linux"
        # Linux images use the exact same QEMU pipeline — they just always
        # live in a folder whose name starts with EVE-NG's "linux-" prefix.
        self.txt_remote_name.setEnabled(is_qemu or is_linux)
        self.cmb_qemu_vendor.setEnabled(is_qemu or is_linux)
        self.btn_browse_folder.setEnabled(is_qemu or is_linux)
        self.chk_convert_qcow2.setEnabled(is_qemu or is_linux)
        if is_linux:
            # Auto-pick the Generic Linux vendor preset so the disk-name hint
            # (virtioa.qcow2) shows without the user hunting for it.
            idx = self.cmb_qemu_vendor.findData("linux-")
            if idx >= 0:
                self.cmb_qemu_vendor.setCurrentIndex(idx)
            self.txt_remote_name.setPlaceholderText("Required — e.g. linux-ubuntu-22.04")
            if not (self.txt_remote_name.text().strip().startswith("linux-") or
                    find_qemu_naming(self.txt_remote_name.text().strip())):
                self.lbl_disk_hint.setText("Required disk file: virtioa.qcow2 (folder name must start with 'linux-')")
        elif is_qemu:
            self.txt_remote_name.setPlaceholderText("Required — e.g. asav-984-10")
        else:
            self.txt_remote_name.setPlaceholderText("Not needed for this image type")
            self.txt_remote_name.clear()
            self.lbl_disk_hint.setText("(not applicable for this image type)")

    def on_qemu_vendor_changed(self, _index):
        prefix = self.cmb_qemu_vendor.currentData()
        if not prefix:
            return
        naming = find_qemu_naming(prefix)
        if not naming:
            return
        _, vendor, disks = naming
        current = self.txt_remote_name.text().strip()
        if not current or find_qemu_naming(current) is None:
            self.txt_remote_name.setText(prefix)
        self.lbl_disk_hint.setText(
            f"Required disk file: {disks[0]}.qcow2"
            + (f" (additional disks: {', '.join(d + '.qcow2' for d in disks[1:])})" if len(disks) > 1 else "")
        )

    def on_local_path_changed(self, text: str):
        if self.cmb_img_type.currentData() != "qemu":
            return
        _, ext = os.path.splitext(text.strip())
        self.chk_convert_qcow2.setChecked(ext.lower() in CONVERTIBLE_DISK_EXTENSIONS)
        # Update disk hint from whatever folder name is currently typed, if it matches a known prefix.
        remote_name = self.txt_remote_name.text().strip()
        naming = find_qemu_naming(remote_name) if remote_name else None
        if naming:
            _, vendor, disks = naming
            self.lbl_disk_hint.setText(f"Required disk file: {disks[0]}.qcow2  (matched vendor: {vendor})")

    def browse_image_path(self, folder: bool):
        img_type = self.cmb_img_type.currentData()
        path = ""
        if folder:
            path = QFileDialog.getExistingDirectory(self, "Select QEMU Image Folder")
        else:
            if img_type == "iol":
                filt = "IOL Binary (*.bin);;All Files (*)"
            elif img_type == "dynamips":
                filt = "Dynamips IOS Image (*.bin *.image);;All Files (*)"
            else:
                filt = "Disk Images (*.qcow2 *.img *.vmdk *.raw *.vhd *.vhdx *.ova);;All Files (*)"
            path, _ = QFileDialog.getOpenFileName(self, "Select Image File", "", filt)

        if path:
            self.txt_local_path.setText(path)
            if img_type == "qemu" and not self.txt_remote_name.text().strip():
                suggested = os.path.basename(path.rstrip("/\\"))
                self.txt_remote_name.setText(suggested)

    def start_image_upload(self):
        local_path = self.txt_local_path.text().strip()
        if not local_path or not os.path.exists(local_path):
            QMessageBox.warning(self, "Missing File", "Please select a valid local image file or folder first.")
            return

        img_type = self.cmb_img_type.currentData()
        remote_name = self.txt_remote_name.text().strip()

        # Linux VMs ride the QEMU pipeline with the mandatory "linux-" prefix.
        effective_type = img_type
        if img_type == "linux":
            if remote_name and not find_qemu_naming(remote_name) and not remote_name.startswith("linux-"):
                remote_name = f"linux-{remote_name}"
                self.txt_remote_name.setText(remote_name)
            if not remote_name.startswith("linux-"):
                QMessageBox.warning(
                    self, "Missing Folder Name",
                    "Linux images must go in a folder starting with 'linux-' (e.g. linux-ubuntu-22.04).\n"
                    "Type a name and it will be prefixed automatically."
                )
                return

            _, ext = os.path.splitext(local_path)
            if ext.lower() == ".iso":
                # ISOs need an interactive install — hand off to the ISO wizard
                # pre-filled so nothing has to be retyped.
                self.txt_iso_path.setText(local_path)
                if not self.txt_iso_folder_name.text().strip():
                    self.txt_iso_folder_name.setText(remote_name)
                self.log("ISO detected: fields copied to the ISO-Install Wizard tab "
                         "(create the blank disk there, run the installer, then finalize).")
                QMessageBox.information(
                    self, "Use the ISO-Install Wizard",
                    "A Linux .iso needs an interactive install (you watch the console).\n\n"
                    "The path and folder name were copied to the 'ISO-Install Wizard' sub-tab:\n"
                    "  1) Prepare & Create Blank Disk\n"
                    "  2) Copy Install Command + Open SSH Console\n"
                    "  3) Finalize"
                )
                return
            effective_type = "qemu"

        if effective_type == "qemu":
            if not remote_name:
                QMessageBox.warning(
                    self, "Missing Folder Name",
                    "QEMU images require a target folder name that follows EVE-NG's naming convention "
                    "(e.g. asav-984-10). Pick a Vendor Preset above to see the exact required prefix."
                )
                return
            if find_qemu_naming(remote_name) is None:
                proceed = QMessageBox.question(
                    self, "Unrecognized Folder Prefix",
                    f"'{remote_name}' doesn't match any known EVE-NG vendor prefix from the official "
                    f"naming table. EVE-NG may not recognize this as a valid image. Continue anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if proceed != QMessageBox.StandardButton.Yes:
                    return

        host = self.txt_ssh_host.text().strip()
        ssh_user = self.txt_ssh_user.text().strip()
        ssh_pass = self.txt_ssh_pass.text()
        ssh_port = self.spin_ssh_port.value()

        self.btn_upload.setEnabled(False)
        self.bar_upload.setValue(0)
        self.log(f"Starting upload of '{local_path}' as a {effective_type.upper()} image...")

        convert_flag = self.chk_convert_qcow2.isChecked() if effective_type == "qemu" else None
        self.img_worker = ImageUploadWorker(
            host, ssh_user, ssh_pass, ssh_port, effective_type, local_path, remote_name,
            run_fixperms=self.chk_fixperms.isChecked(), convert_to_qcow2=convert_flag
        )
        self.img_worker.progress_signal.connect(self.on_upload_progress)
        self.img_worker.log_signal.connect(self.log)
        self.img_worker.finished_signal.connect(self.on_upload_finished)
        self.img_worker.start()

    def on_upload_progress(self, pct: int, msg: str):
        self.bar_upload.setValue(pct)
        self.log(msg)

    def on_upload_finished(self, success: bool, message: str):
        self.btn_upload.setEnabled(True)
        if success:
            self.bar_upload.setValue(100)
            self.log(f"✅ Image uploaded successfully to: {message}")
            QMessageBox.information(
                self, "Upload Complete",
                f"Image uploaded to:\n{message}\n\nIt should now appear as a selectable image in "
                f"'Add New Device' → matching template (you may need to click 'Refresh Labs & Nodes')."
            )
            self.refresh_existing_images()
        else:
            self.log(f"❌ Upload failed: {message}")
            QMessageBox.critical(self, "Upload Failed", message)

    def write_iol_license(self):
        content = self.txt_iourc.text().strip()
        if not content:
            QMessageBox.warning(self, "Empty License", "Enter the iourc license file contents first.")
            return
        host = self.txt_ssh_host.text().strip()
        ssh_user = self.txt_ssh_user.text().strip()
        ssh_pass = self.txt_ssh_pass.text()
        ssh_port = self.spin_ssh_port.value()

        def _run():
            uploader = EveImageUploader(host, ssh_user, ssh_pass, ssh_port)
            uploader.connect()
            path = uploader.write_iol_license(content.replace("\\n", "\n"))
            uploader.close()
            return path

        self.log("Writing iourc license to server...")
        self._iourc_worker = WorkerThread(_run)
        self._iourc_worker.finished_signal.connect(
            lambda status, res: self.log(f"iourc license written to: {res}" if status == "success" else f"Error: {res}")
        )
        self._iourc_worker.start()

    def run_fixperms_only(self):
        host = self.txt_ssh_host.text().strip()
        ssh_user = self.txt_ssh_user.text().strip()
        ssh_pass = self.txt_ssh_pass.text()
        ssh_port = self.spin_ssh_port.value()

        def _run():
            uploader = EveImageUploader(host, ssh_user, ssh_pass, ssh_port)
            uploader.connect()
            out = uploader.fix_permissions()
            uploader.close()
            return out

        self.log("Running fixpermissions on EVE-NG server...")
        self._fixperms_worker = WorkerThread(_run)
        self._fixperms_worker.finished_signal.connect(
            lambda status, res: self.log(f"fixpermissions: {res}" if status == "success" else f"Error: {res}")
        )
        self._fixperms_worker.start()

    def refresh_existing_images(self):
        host = self.txt_ssh_host.text().strip()
        ssh_user = self.txt_ssh_user.text().strip()
        ssh_pass = self.txt_ssh_pass.text()
        ssh_port = self.spin_ssh_port.value()
        img_type = self.cmb_img_type.currentData()
        if img_type == "linux":
            img_type = "qemu"  # Linux VMs live in the QEMU addons folder

        def _run():
            uploader = EveImageUploader(host, ssh_user, ssh_pass, ssh_port)
            uploader.connect()
            images = uploader.list_images(img_type)
            uploader.close()
            return images

        def _done(status, res):
            if status == "success":
                self.list_existing_images.setPlainText("\n".join(res) if res else "(no images found)")
                self.log(f"Found {len(res)} existing {img_type} image(s) on server.")
            else:
                self.log(f"Error listing images: {res}")

        self._list_worker = WorkerThread(_run)
        self._list_worker.finished_signal.connect(_done)
        self._list_worker.start()

    # ---------- ISO-Install Wizard ----------
    def browse_iso_path(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Install ISO", "", "ISO Image (*.iso);;All Files (*)")
        if path:
            self.txt_iso_path.setText(path)
            if not self.txt_iso_folder_name.text().strip():
                base = os.path.splitext(os.path.basename(path))[0]
                self.txt_iso_folder_name.setText(base)

    def _iso_work_dir(self) -> str:
        return "/opt/unetlab/tmp/iso_install_work"

    def iso_prepare_install(self):
        iso_path = self.txt_iso_path.text().strip()
        folder_name = self.txt_iso_folder_name.text().strip()
        if not iso_path or not os.path.isfile(iso_path):
            QMessageBox.warning(self, "Missing ISO", "Select a valid local install ISO first.")
            return
        if not folder_name:
            QMessageBox.warning(self, "Missing Folder Name", "Enter the final QEMU folder name first.")
            return

        naming = find_qemu_naming(folder_name)
        disk_base = naming[2][0] if naming else "virtioa"
        disk_filename = f"{disk_base}.qcow2"

        host = self.txt_ssh_host.text().strip()
        ssh_user = self.txt_ssh_user.text().strip()
        ssh_pass = self.txt_ssh_pass.text()
        ssh_port = self.spin_ssh_port.value()
        work_dir = self._iso_work_dir()
        disk_size = self.spin_iso_disk_size.value()

        self.btn_iso_prepare.setEnabled(False)
        self.bar_iso_progress.setValue(0)
        self.log(f"Preparing ISO install environment for '{folder_name}'...")

        self._run_iso_prepare(iso_path, folder_name, disk_filename, work_dir, disk_size,
                               host, ssh_user, ssh_pass, ssh_port)

    def _run_iso_prepare(self, iso_path, folder_name, disk_filename, work_dir, disk_size,
                          host, ssh_user, ssh_pass, ssh_port):
        class IsoPrepareWorker(QThread):
            progress_signal = pyqtSignal(int, str)
            finished_signal = pyqtSignal(bool, str)

            def run(self):
                uploader = None
                try:
                    uploader = EveImageUploader(host, ssh_user, ssh_pass, ssh_port)
                    uploader.connect()

                    def on_progress(idx, total, name, pct):
                        self.progress_signal.emit(pct, f"Uploading {name}... {pct}%")

                    uploader.prepare_iso_install(iso_path, work_dir, disk_filename, disk_size, on_progress)
                    uploader.close()
                    self.finished_signal.emit(True, disk_filename)
                except Exception as e:
                    self.finished_signal.emit(False, str(e))
                finally:
                    if uploader:
                        uploader.close()

        self._iso_prepare_worker = IsoPrepareWorker()
        self._iso_prepare_worker.progress_signal.connect(lambda pct, msg: (self.bar_iso_progress.setValue(pct), self.log(msg)))

        def _done(success, result):
            self.btn_iso_prepare.setEnabled(True)
            if success:
                self.bar_iso_progress.setValue(100)
                self.log(f"ISO and blank disk ready in {self._iso_work_dir()}.")
                cmd = EveImageUploader.build_install_qemu_command(
                    self._iso_work_dir(), os.path.basename(iso_path), disk_filename,
                    ram_mb=self.spin_iso_ram.value()
                )
                self.txt_iso_command.setPlainText(cmd)
                self.btn_iso_open_console.setEnabled(True)
                self.btn_iso_finalize.setEnabled(True)
            else:
                self.log(f"ISO preparation failed: {result}")
                QMessageBox.critical(self, "Preparation Failed", str(result))

        self._iso_prepare_worker.finished_signal.connect(_done)
        self._iso_prepare_worker.start()

    def iso_open_install_console(self):
        cmd = self.txt_iso_command.toPlainText().strip()
        if cmd:
            QApplication.clipboard().setText(cmd)
            self.log("Install command copied to clipboard.")

        host = self.txt_ssh_host.text().strip()
        ssh_user = self.txt_ssh_user.text().strip()
        client = self.cmb_terminal.currentData() or "auto"
        putty_path = self.txt_putty_path.text().strip()
        try:
            desc = launch_ssh(client, host, ssh_user, self.spin_ssh_port.value(), "", putty_path)
            self.log(f"Opened SSH console via [{client}]: {desc}. Paste the install command (already on your clipboard) to begin.")
        except Exception as e:
            QMessageBox.warning(self, "Terminal Launch Failed", str(e))

    def iso_finalize_install(self):
        folder_name = self.txt_iso_folder_name.text().strip()
        naming = find_qemu_naming(folder_name)
        disk_base = naming[2][0] if naming else "virtioa"
        disk_filename = f"{disk_base}.qcow2"

        confirm = QMessageBox.question(
            self, "Finalize Install",
            "This moves the disk from the work directory into the final image folder and cleans up. "
            "Only continue after you've completed the interactive install and quit qemu ('ctrl+a' then "
            "'c', then 'quit'). Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        host = self.txt_ssh_host.text().strip()
        ssh_user = self.txt_ssh_user.text().strip()
        ssh_pass = self.txt_ssh_pass.text()
        ssh_port = self.spin_ssh_port.value()
        work_dir = self._iso_work_dir()

        self.log(f"Finalizing install: moving {disk_filename} into {folder_name}...")

        def _run():
            uploader = EveImageUploader(host, ssh_user, ssh_pass, ssh_port)
            uploader.connect()
            final_dir = uploader.finalize_iso_install(work_dir, disk_filename, folder_name)
            out = uploader.fix_permissions()
            uploader.close()
            return final_dir

        self._iso_finalize_worker = WorkerThread(_run)

        def _done(status, res):
            if status == "success":
                self.log(f"✅ Install finalized: {res}")
                QMessageBox.information(self, "Install Complete", f"Image installed to:\n{res}")
                self.btn_iso_open_console.setEnabled(False)
                self.btn_iso_finalize.setEnabled(False)
            else:
                self.log(f"Finalize failed: {res}")
                QMessageBox.critical(self, "Finalize Failed", str(res))

        self._iso_finalize_worker.finished_signal.connect(_done)
        self._iso_finalize_worker.start()

    # ---------- Dynamips Idle-PC ----------
    def idlepc_open_console(self):
        image_path = self.txt_idle_image_path.text().strip()
        if not image_path:
            QMessageBox.warning(self, "Missing Image Path", "Enter the image path on the server first.")
            return

        platform = self.cmb_idle_platform.currentText()
        cmd = EveImageUploader.build_idlepc_calc_command(image_path, platform)
        self.txt_idle_command.setPlainText(cmd)
        QApplication.clipboard().setText(cmd)
        self.log("Idle-PC command copied to clipboard.")

        host = self.txt_ssh_host.text().strip()
        ssh_user = self.txt_ssh_user.text().strip()
        client = self.cmb_terminal.currentData() or "auto"
        putty_path = self.txt_putty_path.text().strip()
        try:
            desc = launch_ssh(client, host, ssh_user, self.spin_ssh_port.value(), "", putty_path)
            self.log(f"Opened SSH console via [{client}]: {desc}. Paste the command (already on your clipboard).")
        except Exception as e:
            QMessageBox.warning(self, "Terminal Launch Failed", str(e))

    # ------------------ TAB 7: FIREWALL/UTM CONFIG WIZARD ------------------
    def setup_firewall_tab(self):
        layout = QVBoxLayout(self.tab_firewall)

        info = QLabel(
            "Generates an initial network configuration for pfSense, OPNsense, or FortiGate and can "
            "send it straight to the device's console. Use <b>🔍 Detect Interfaces</b> to pull real "
            "interface names from the device instead of guessing. <b>pfSense/OPNsense are configured "
            "through their numbered text-console menu</b> (not a Cisco-style CLI) and are sent as "
            "separate labeled steps so a failure in one step is easy to spot — exact prompt wording "
            "still varies by version, so review the generated script before sending."
        )
        info.setWordWrap(True)
        info.setObjectName("muted")
        layout.addWidget(info)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Device Type:"))
        self.cmb_fw_type = QComboBox()
        self.cmb_fw_type.addItems(["pfSense", "OPNsense", "FortiGate (FortiOS)"])
        self.cmb_fw_type.currentIndexChanged.connect(self.on_fw_type_changed)
        top_row.addWidget(self.cmb_fw_type)

        top_row.addWidget(QLabel("Target Device:"))
        self.cmb_fw_device = QComboBox()
        self.cmb_fw_device.setMinimumWidth(220)
        top_row.addWidget(self.cmb_fw_device)

        self.btn_fw_detect = QPushButton("🔍 Detect Interfaces")
        self.btn_fw_detect.setToolTip("Connects to the device's console and lists its real interface names.")
        self.btn_fw_detect.clicked.connect(self.fw_detect_interfaces)
        top_row.addWidget(self.btn_fw_detect)
        top_row.addStretch()
        layout.addLayout(top_row)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        form_group = QGroupBox("Network Settings")
        form = QFormLayout(form_group)

        self.cmb_fw_wan_if = QComboBox()
        self.cmb_fw_wan_if.setEditable(True)
        self.cmb_fw_wan_if.addItems(["em0", "port1"])
        form.addRow("WAN Interface:", self.cmb_fw_wan_if)

        self.cmb_fw_wan_mode = QComboBox()
        self.cmb_fw_wan_mode.addItems(["DHCP", "Static"])
        self.cmb_fw_wan_mode.currentIndexChanged.connect(self.on_fw_wan_mode_changed)
        form.addRow("WAN Mode (FortiGate only):", self.cmb_fw_wan_mode)

        self.txt_fw_wan_ip = QLineEdit("203.0.113.5")
        self.txt_fw_wan_ip.setEnabled(False)
        form.addRow("WAN IP (Static, FortiGate only):", self.txt_fw_wan_ip)

        self.txt_fw_wan_mask = QLineEdit("255.255.255.0")
        self.txt_fw_wan_mask.setEnabled(False)
        form.addRow("WAN Subnet Mask (Static, FortiGate only):", self.txt_fw_wan_mask)

        self.txt_fw_wan_gateway = QLineEdit("203.0.113.1")
        self.txt_fw_wan_gateway.setEnabled(False)
        form.addRow("WAN Gateway (Static, FortiGate only):", self.txt_fw_wan_gateway)

        self.cmb_fw_lan_if = QComboBox()
        self.cmb_fw_lan_if.setEditable(True)
        self.cmb_fw_lan_if.addItems(["em1", "port2"])
        form.addRow("LAN Interface:", self.cmb_fw_lan_if)

        self.txt_fw_lan_ip = QLineEdit("192.168.10.1")
        form.addRow("LAN IP Address:", self.txt_fw_lan_ip)

        self.txt_fw_lan_bits = QLineEdit("24")
        form.addRow("LAN Subnet Bits (pfSense/OPNsense):", self.txt_fw_lan_bits)

        self.txt_fw_lan_mask = QLineEdit("255.255.255.0")
        form.addRow("LAN Subnet Mask (FortiGate):", self.txt_fw_lan_mask)

        self.chk_fw_dhcp = QCheckBox("Enable DHCP server on LAN")
        self.chk_fw_dhcp.setChecked(True)
        form.addRow("", self.chk_fw_dhcp)

        self.txt_fw_dhcp_start = QLineEdit("192.168.10.100")
        form.addRow("DHCP Range Start:", self.txt_fw_dhcp_start)

        self.txt_fw_dhcp_end = QLineEdit("192.168.10.200")
        form.addRow("DHCP Range End:", self.txt_fw_dhcp_end)

        self.chk_fw_ssh = QCheckBox("Enable SSH (pfSense/OPNsense console option)")
        self.chk_fw_ssh.setChecked(True)
        form.addRow("", self.chk_fw_ssh)

        self.chk_fw_wan_access = QCheckBox("Allow SSH/HTTPS on WAN (FortiGate — off is safer)")
        self.chk_fw_wan_access.setChecked(False)
        form.addRow("", self.chk_fw_wan_access)

        self.txt_fw_hostname = QLineEdit()
        self.txt_fw_hostname.setPlaceholderText("(optional) e.g. FW1 — FortiGate only")
        form.addRow("Hostname (FortiGate):", self.txt_fw_hostname)

        self.txt_fw_admin_pass = QLineEdit()
        self.txt_fw_admin_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_fw_admin_pass.setPlaceholderText("(optional) leave blank to keep current admin password")
        form.addRow("Admin Password (FortiGate):", self.txt_fw_admin_pass)

        self.txt_fw_dns = QLineEdit("8.8.8.8, 8.8.4.4")
        self.txt_fw_dns.setPlaceholderText("Comma-separated — FortiGate only")
        form.addRow("DNS Servers (FortiGate):", self.txt_fw_dns)

        self.chk_fw_logging = QCheckBox("Enable traffic logging on policies (FortiGate)")
        self.chk_fw_logging.setChecked(True)
        form.addRow("", self.chk_fw_logging)

        scroll_layout.addWidget(form_group)

        # --- Additional LAN segments (FortiGate) ---
        self.fw_lan_group = QGroupBox("Additional LAN Segments (FortiGate only — add as many as you need)")
        fw_lan_group_layout = QVBoxLayout(self.fw_lan_group)
        self.fw_lan_container = QVBoxLayout()
        fw_lan_group_layout.addLayout(self.fw_lan_container)
        self.fw_lan_rows = []
        btn_add_lan = QPushButton("➕ Add LAN Segment")
        btn_add_lan.clicked.connect(lambda: self.fw_add_lan_row())
        fw_lan_group_layout.addWidget(btn_add_lan)
        scroll_layout.addWidget(self.fw_lan_group)

        # --- Optional interfaces (pfSense/OPNsense) ---
        self.fw_opt_group = QGroupBox("Optional Interfaces (pfSense/OPNsense only — assigned as OPT1, OPT2, ...)")
        fw_opt_group_layout = QVBoxLayout(self.fw_opt_group)
        self.fw_opt_container = QVBoxLayout()
        fw_opt_group_layout.addLayout(self.fw_opt_container)
        self.fw_opt_rows = []
        btn_add_opt = QPushButton("➕ Add Optional Interface")
        btn_add_opt.clicked.connect(lambda: self.fw_add_opt_row())
        fw_opt_group_layout.addWidget(btn_add_opt)
        scroll_layout.addWidget(self.fw_opt_group)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(scroll_widget)
        scroll_area.setMaximumHeight(430)
        layout.addWidget(scroll_area)

        btn_row = QHBoxLayout()
        btn_generate = QPushButton("⚙ Generate Config")
        btn_generate.clicked.connect(self.generate_firewall_config)
        btn_row.addWidget(btn_generate)

        self.btn_fw_send = QPushButton("▶ Send to Device Console")
        self.btn_fw_send.setObjectName("btnPrimary")
        self.btn_fw_send.clicked.connect(self.send_firewall_config)
        btn_row.addWidget(self.btn_fw_send)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.bar_fw_progress = QProgressBar()
        self.bar_fw_progress.setRange(0, 100)
        layout.addWidget(self.bar_fw_progress)

        layout.addWidget(QLabel("Generated Script (review/edit before sending):"))
        self.txt_fw_script = QTextEdit()
        self.txt_fw_script.setFont(QFont("Consolas", 10))
        layout.addWidget(self.txt_fw_script)

        layout.addWidget(QLabel("Console Output:"))
        self.txt_fw_output = QTextEdit()
        self.txt_fw_output.setFont(QFont("Consolas", 10))
        self.txt_fw_output.setReadOnly(True)
        self.txt_fw_output.setMaximumHeight(150)
        layout.addWidget(self.txt_fw_output)

        self.on_fw_type_changed(0)

    def fw_add_lan_row(self, interface: str = "", ip: str = "", mask: str = "255.255.255.0",
                        enable_dhcp: bool = True, dhcp_start: str = "", dhcp_end: str = ""):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)

        cmb_if = QComboBox()
        cmb_if.setEditable(True)
        if interface:
            cmb_if.addItem(interface)
        if hasattr(self, "fw_detected_interfaces") and self.fw_detected_interfaces:
            cmb_if.addItems([i for i in self.fw_detected_interfaces if i != interface])
        row_layout.addWidget(QLabel("If:"))
        row_layout.addWidget(cmb_if, 2)

        txt_ip = QLineEdit(ip)
        txt_ip.setPlaceholderText("IP")
        row_layout.addWidget(txt_ip, 2)

        txt_mask = QLineEdit(mask)
        row_layout.addWidget(txt_mask, 2)

        chk_dhcp = QCheckBox("DHCP")
        chk_dhcp.setChecked(enable_dhcp)
        row_layout.addWidget(chk_dhcp)

        txt_start = QLineEdit(dhcp_start)
        txt_start.setPlaceholderText("DHCP start")
        row_layout.addWidget(txt_start, 2)

        txt_end = QLineEdit(dhcp_end)
        txt_end.setPlaceholderText("DHCP end")
        row_layout.addWidget(txt_end, 2)

        btn_remove = QPushButton("✕")
        btn_remove.setFixedWidth(32)
        row_layout.addWidget(btn_remove)

        self.fw_lan_container.addWidget(row_widget)
        entry = {"widget": row_widget, "if": cmb_if, "ip": txt_ip, "mask": txt_mask,
                 "dhcp": chk_dhcp, "start": txt_start, "end": txt_end}
        self.fw_lan_rows.append(entry)

        def _remove():
            self.fw_lan_container.removeWidget(row_widget)
            row_widget.deleteLater()
            self.fw_lan_rows.remove(entry)

        btn_remove.clicked.connect(_remove)

    def fw_add_opt_row(self, interface: str = ""):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)

        cmb_if = QComboBox()
        cmb_if.setEditable(True)
        if interface:
            cmb_if.addItem(interface)
        if hasattr(self, "fw_detected_interfaces") and self.fw_detected_interfaces:
            cmb_if.addItems([i for i in self.fw_detected_interfaces if i != interface])
        row_layout.addWidget(QLabel(f"OPT{len(self.fw_opt_rows) + 1}:"))
        row_layout.addWidget(cmb_if, 3)

        btn_remove = QPushButton("✕")
        btn_remove.setFixedWidth(32)
        row_layout.addWidget(btn_remove)

        self.fw_opt_container.addWidget(row_widget)
        entry = {"widget": row_widget, "if": cmb_if}
        self.fw_opt_rows.append(entry)

        def _remove():
            self.fw_opt_container.removeWidget(row_widget)
            row_widget.deleteLater()
            self.fw_opt_rows.remove(entry)

        btn_remove.clicked.connect(_remove)

    def on_fw_type_changed(self, _index):
        is_forti = "FortiGate" in self.cmb_fw_type.currentText()
        self.cmb_fw_wan_mode.setEnabled(is_forti)
        self.txt_fw_lan_mask.setEnabled(is_forti)
        self.chk_fw_wan_access.setEnabled(is_forti)
        self.txt_fw_lan_bits.setEnabled(not is_forti)
        self.chk_fw_ssh.setEnabled(not is_forti)
        self.txt_fw_hostname.setEnabled(is_forti)
        self.txt_fw_admin_pass.setEnabled(is_forti)
        self.txt_fw_dns.setEnabled(is_forti)
        self.chk_fw_logging.setEnabled(is_forti)
        self.fw_lan_group.setEnabled(is_forti)
        self.fw_opt_group.setEnabled(not is_forti)
        is_static = is_forti and self.cmb_fw_wan_mode.currentText() == "Static"
        self.txt_fw_wan_gateway.setEnabled(is_static)

    def on_fw_wan_mode_changed(self, _index):
        is_static = self.cmb_fw_wan_mode.currentText() == "Static"
        self.txt_fw_wan_ip.setEnabled(is_static)
        self.txt_fw_wan_mask.setEnabled(is_static)
        self.txt_fw_wan_gateway.setEnabled(is_static and "FortiGate" in self.cmb_fw_type.currentText())

    # ------------------ TAB 8: EXPORT LAB ------------------
    def setup_export_tab(self):
        layout = QVBoxLayout(self.tab_export)

        info = QLabel(
            "Downloads the whole lab straight from the EVE-NG server into one local .zip — "
            "the topology file plus every saved node config (the configs/ folder). Great for "
            "backing up before big changes or moving a lab to another EVE-NG host: unzip it "
            "into /opt/unetlab/labs/ there and run fixpermissions."
        )
        info.setWordWrap(True)
        info.setObjectName("muted")
        layout.addWidget(info)

        form_group = QGroupBox("What to export")
        form = QFormLayout(form_group)

        self.cmb_exp_lab = QComboBox()
        self.cmb_exp_lab.setMinimumWidth(260)
        form.addRow("Lab:", self.cmb_exp_lab)

        self.chk_exp_configs = QCheckBox("Include saved node configs (configs/ folder)")
        self.chk_exp_configs.setChecked(True)
        form.addRow("", self.chk_exp_configs)

        dest_row = QHBoxLayout()
        default_dir = os.path.join(os.path.expanduser("~"), "Documents", "EveBridge-Exports")
        self.txt_exp_dest = QLineEdit(os.path.join(default_dir, "lab_export.zip"))
        dest_row.addWidget(self.txt_exp_dest, 1)
        btn_exp_browse = QPushButton("Browse...")
        btn_exp_browse.clicked.connect(self.browse_export_dest)
        dest_row.addWidget(btn_exp_browse)
        form.addRow("Save to:", dest_row)

        layout.addWidget(form_group)

        btn_row = QHBoxLayout()
        self.btn_export = QPushButton("📤 Export Lab to Zip")
        self.btn_export.setObjectName("btnPrimary")
        self.btn_export.clicked.connect(self.run_lab_export)
        btn_row.addWidget(self.btn_export)

        btn_open_folder = QPushButton("📂 Open Folder")
        btn_open_folder.setToolTip("Open the folder containing the exported zip.")
        btn_open_folder.clicked.connect(self.open_export_folder)
        btn_row.addWidget(btn_open_folder)
        btn_row.addStretch()
        layout.addBtnRow = None
        layout.addLayout(btn_row)

        self.bar_exp = QProgressBar()
        self.bar_exp.setRange(0, 100)
        layout.addWidget(self.bar_exp)
        layout.addStretch()

    # ---------- Manage Labs (connection-bar buttons) ----------
    def _selected_lab_file(self) -> str:
        path = self.cmb_labs.currentData() or ""
        name = path.rstrip("/").split("/")[-1]
        return name if name.endswith(".unl") else ""

    def _require_connection(self) -> bool:
        if not self.eve_client or not self.eve_client.is_logged_in:
            QMessageBox.warning(self, "Not Connected", "Connect to EVE-NG first.")
            return False
        return True

    def manage_lab_create_dialog(self):
        if not self._require_connection():
            return
        dlg = LabMetaDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name = dlg.value_name()
        if not name:
            QMessageBox.warning(self, "Missing Name", "Enter a lab name first.")
            return
        ok, msg = self.eve_client.create_lab(
            name, version=dlg.value_version(),
            author=dlg.value_author(), description=dlg.value_desc())
        if ok:
            self.log(f"\u2705 Lab created: {name}.unl \u2014 {msg}")
            self.fetch_available_labs()
            idx = self.cmb_labs.findData(f"/{name}.unl")
            if idx >= 0:
                self.cmb_labs.setCurrentIndex(idx)
            QMessageBox.information(
                self, "Lab Created",
                f"'{name}.unl' is now selected and ready. Add devices from the Nodes tab.")
        else:
            detail = msg or getattr(self.eve_client, "last_error", "")
            QMessageBox.critical(self, "Create Failed", f"EVE-NG said:\n{detail}")

    def manage_lab_duplicate(self):
        if not self._require_connection():
            return
        src = self._selected_lab_file()
        if not src:
            QMessageBox.warning(self, "Pick a Lab", "Select a lab in the dropdown first.")
            return
        host = self.txt_ssh_host.text().strip()
        pw = self.txt_ssh_pass.text()
        if not host or not pw:
            QMessageBox.warning(
                self, "SSH Credentials Needed",
                "Duplicating copies the lab file server-side via root SSH.\n"
                "Fill the Image Manager SSH host/password fields first.")
            return
        stem = src[:-len(".unl")]
        new_base, ok = QInputDialog.getText(self, "Duplicate Lab",
                                            f"New lab name (without .unl):",
                                            text=f"{stem}-copy")
        if not ok or not new_base.strip():
            return
        dst = new_base.strip() + ".unl"
        existing = {l.get("file") for l in getattr(self, "_labs_cache", [])}
        if dst in existing:
            QMessageBox.warning(self, "Already Exists", f"A lab named '{dst}' already exists.")
            return

        self.btn_dup_lab.setEnabled(False)
        self.log(f"Duplicating {src} \u2192 {dst}...")

        def _run():
            return duplicate_lab_file(host, self.txt_ssh_user.text().strip(), pw,
                                      self.spin_ssh_port.value(), src, dst)

        self._dup_worker = WorkerThread(_run)

        def _done(status, result):
            self.btn_dup_lab.setEnabled(True)
            if status == "success" and result:
                self.log(f"\u2705 Duplicated to {result}")
                self.fetch_available_labs()
                idx = self.cmb_labs.findData(f"/{dst}")
                if idx >= 0:
                    self.cmb_labs.setCurrentIndex(idx)
                QMessageBox.information(self, "Duplicated",
                                        f"{src} copied to {dst}\n(run fixpermissions if nodes misbehave)")
            else:
                detail = result if status != "success" else "unknown error"
                self.log(f"\u274c Duplicate failed: {detail}")
                QMessageBox.critical(self, "Duplicate Failed", str(detail))

        self._dup_worker.finished_signal.connect(_done)
        self._dup_worker.start()

    def manage_lab_delete(self):
        if not self._require_connection():
            return
        target = self._selected_lab_file()
        if not target:
            QMessageBox.warning(self, "Pick a Lab", "Select a lab in the dropdown first.")
            return
        typed, ok = QInputDialog.getText(
            self, "Delete Lab \u2014 Confirm",
            f"This permanently deletes '{target}' from the server.\n"
            f"Type its exact file name to confirm:", text="")
        if not ok:
            return
        if typed.strip() != target:
            QMessageBox.warning(self, "Name Mismatch",
                                f"You typed '{typed.strip()}' but the lab is '{target}'. Nothing was deleted.")
            return
        ok, msg = self.eve_client.delete_lab(target)
        if ok:
            self.log(f"\U0001F5D1 Deleted lab {target} \u2014 {msg}")
            was_current = target == self._current_lab_file() if hasattr(self, '_current_lab_file') else False
            self.fetch_available_labs()
            QMessageBox.information(self, "Deleted", f"{target} has been deleted.")
        else:
            detail = msg or getattr(self.eve_client, "last_error", "")
            QMessageBox.critical(self, "Delete Failed", f"EVE-NG said:\n{detail}")

    # ---------- Online Image Store ----------
    def store_populate_list(self):
        vendor = self.cmb_store_vendor.currentData()
        search = self.txt_store_search.text().strip().lower()
        self.list_store.clear()
        for e in image_store.CATALOG:
            if vendor and e["vendor"] != vendor:
                continue
            if search and search not in e["name"].lower() and search not in e["file"].lower():
                continue
            item = QListWidgetItem(f'{e["name"]}  [{e["fmt"].upper()}]  ({e["vendor"]})')
            item.setData(Qt.ItemDataRole.UserRole, e)
            self.list_store.addItem(item)

    def _store_ssh(self):
        host = self.txt_ssh_host.text().strip()
        pw = self.txt_ssh_pass.text()
        if not host or not pw:
            QMessageBox.warning(self, "SSH Credentials Needed",
                                "Fill the SSH host/password at the top of this tab first "
                                "(same root account as Image Manager).")
            return None
        return (host, self.txt_ssh_user.text().strip(), pw, self.spin_ssh_port.value())

    def store_install_selected(self):
        item = self.list_store.currentItem()
        if not item:
            QMessageBox.information(self, "No Image Selected", "Pick an image from the list first.")
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        self._store_install_entry(entry)

    def store_install_custom(self):
        url = self.txt_store_url.text().strip()
        folder = self.txt_store_folder.text().strip()
        if not url.startswith("http"):
            QMessageBox.warning(self, "Missing URL", "Enter a direct download URL first.")
            return
        if not folder:
            QMessageBox.warning(self, "Missing Folder", "Enter the EVE-NG folder name.")
            return
        fmt = "tgz" if ".tgz" in url.lower() or ".tar.gz" in url.lower() else \
              "iso" if ".iso" in url.lower() else "qcow2"
        fname = url.rstrip("/").split("/")[-1].split("?")[0] or "image.bin"
        self._store_install_entry({"vendor": "Custom", "name": fname, "file": fname,
                                   "url": url, "folder": folder, "fmt": fmt,
                                   "template": "qemu", "ram": 1024})

    def _store_install_entry(self, entry: dict):
        ssh = self._store_ssh()
        if not ssh:
            return
        if entry["fmt"] == "iso":
            QMessageBox.information(
                self, "ISO Image",
                "This is an install ISO — use the 'ISO-Install Wizard' sub-tab instead "
                "(ISOs need an interactive install).")
            return

        import tempfile
        tmpdir = tempfile.gettempdir()
        tmp_file = os.path.join(tmpdir, entry["file"])
        self.btn_store_install.setEnabled(False)
        self.bar_store_dl.setValue(0)
        self.lbl_store_status.setText(f"Downloading {entry['name']}...")
        self.log(f"Store: downloading {entry['name']}...")

        def _run():
            import image_store as store

            def dl_cb(pct, msg):
                QTimer.singleShot(0, lambda: (self.bar_store_dl.setValue(int(pct * 0.5)),
                                              self.lbl_store_status.setText(f"download: {msg}")))

            def ul_cb(idx, total, name, pct):
                QTimer.singleShot(0, lambda: (self.bar_store_dl.setValue(50 + int(pct * 0.4)),
                                              self.lbl_store_status.setText(f"upload: {name} {pct}%")))

            store.google_drive_download(entry["url"], tmp_file, progress_cb=dl_cb) \
                if "drive.google.com" in entry["url"] else \
                store.direct_download(entry["url"], tmp_file, progress_cb=dl_cb)

            def ul2_cb(idx, total, name, pct):
                QTimer.singleShot(0, lambda: (self.bar_store_dl.setValue(int(50 + pct * 0.4)),
                                              self.lbl_store_status.setText(f"upload: {name} {pct}%")))

            uploader = EveImageUploader(ssh[0], ssh[1], ssh[2], ssh[3])
            uploader.connect()
            try:
                if entry["fmt"] == "tgz":
                    uploader.upload_tgz_image(tmp_file, entry["folder"], progress_cb=ul2_cb)
                else:
                    uploader.upload_qemu_image(tmp_file, entry["folder"], progress_cb=ul2_cb)
                uploader.fix_permissions()
            finally:
                uploader.close()

            QTimer.singleShot(0, lambda: self.bar_store_dl.setValue(100))
            return entry["folder"]

        self._store_worker = WorkerThread(_run)

        def _done(status, result):
            self.btn_store_install.setEnabled(True)
            if status == "success":
                self.lbl_store_status.setText(f"✅ {entry['name']} installed as '{result}'")
                self.log(f"✅ Store: {entry['name']} installed as folder '{result}'")
                QMessageBox.information(self, "Image Installed",
                                        f"{entry['name']} installed.\n\n"
                                        f"It should now appear in 'Add New Device' → template "
                                        f"'{entry.get('template', 'qemu')}'.")
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass
            else:
                self.lbl_store_status.setText(f"❌ {result}")
                self.log(f"❌ Store install failed: {result}")
                QMessageBox.critical(self, "Install Failed", str(result))

        self._store_worker.finished_signal.connect(_done)
        self._store_worker.start()

    def refresh_export_lab_combo(self):
        current = None
        if hasattr(self, "_labs_cache"):
            self.cmb_exp_lab.clear()
            for lab_info in self._labs_cache:
                fname = lab_info.get("file") or lab_info.get("path", "").rstrip("/").split("/")[-1]
                if not fname:
                    continue
                self.cmb_exp_lab.addItem(fname, fname)
                if self.current_lab and fname in self.current_lab:
                    current = fname
        else:
            self.cmb_exp_lab.clear()
        stem = (self.current_lab or "").rstrip("/").split("/")[-1]
        target = current or (stem if stem.endswith(".unl") else None)
        if target:
            idx = self.cmb_exp_lab.findText(target)
            if idx >= 0:
                self.cmb_exp_lab.setCurrentIndex(idx)

    def browse_export_dest(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Lab As", self.txt_exp_dest.text().strip() or "lab_export.zip",
            "Zip archive (*.zip)")
        if path:
            if not path.lower().endswith(".zip"):
                path += ".zip"
            self.txt_exp_dest.setText(path)

    def run_lab_export(self):
        lab_name = self.cmb_exp_lab.currentData() or self.cmb_exp_lab.currentText().strip()
        if not lab_name.endswith(".unl"):
            QMessageBox.warning(self, "Pick a Lab", "Connect to EVE-NG first so the lab list can load.")
            return
        host = self.txt_ssh_host.text().strip()
        ssh_pass = self.txt_ssh_pass.text()
        if not host or not ssh_pass:
            QMessageBox.warning(
                self, "SSH Credentials Needed",
                "Lab export uses the server's root SSH account.\n"
                "Fill in the SSH host/password at the top of the Image Manager tab first.")
            return

        dest = self.txt_exp_dest.text().strip()
        if not dest.lower().endswith(".zip"):
            dest += ".zip"
        self.txt_exp_dest.setText(dest)

        include_cfgs = self.chk_exp_configs.isChecked()
        self.btn_export.setEnabled(False)
        self.bar_exp.setValue(0)
        self.log(f"Exporting {lab_name} from {host} ...")

        def _run():
            def cb(done, total, name):
                pct = int(done / max(total, 1) * 100)
                QTimer.singleShot(0, lambda: (self.bar_exp.setValue(pct),
                                              self.lbl_exp_file.setText(f"{done}/{total}  {name}")))
            return export_lab_zip(host, self.txt_ssh_user.text().strip(), ssh_pass,
                                  self.spin_ssh_port.value(), lab_name, dest,
                                  include_configs=include_cfgs, progress_cb=cb)

        self._export_worker = WorkerThread(_run)

        def _done(status, result):
            self.btn_export.setEnabled(True)
            self.bar_exp.setValue(100 if status == "success" else 0)
            self.lbl_exp_file.setText("")
            if status == "success":
                self.log(f"✅ Export complete: {result}")
                QMessageBox.information(self, "Export Complete",
                                        f"Lab exported to:\n{result}")
            else:
                self.log(f"❌ Export failed: {result}")
                QMessageBox.critical(self, "Export Failed", str(result))

        self._export_worker.finished_signal.connect(_done)
        self._export_worker.start()

    def open_export_folder(self):
        folder = os.path.dirname(os.path.abspath(self.txt_exp_dest.text().strip()))
        os.makedirs(folder, exist_ok=True)
        os.startfile(folder)  # Windows explorer

    # ------------------ TAB 9: ANSIBLE ------------------
    def setup_ansible_tab(self):
        layout = QHBoxLayout(self.tab_ansible)

        left = QWidget()
        left_layout = QVBoxLayout(left)

        info = QLabel(
            "Turns this lab's device list into Ansible material: an inventory grouped by role "
            "(routers / switches / firewalls) plus ready-made playbooks — gather facts, back up "
            "every running config, push a commands file, save configs.\n\n"
            "One step is on you: give each node a management IP (attach cloud0/pnet0), then put "
            "it in the generated inventory where it says CHANGEME. Devices also need SSH enabled "
            "(Batch CLI → Enable SSH preset does exactly that)."
        )
        info.setWordWrap(True)
        info.setObjectName("muted")
        left_layout.addWidget(info)

        creds_group = QGroupBox("Device credentials (written into the inventory)")
        creds_form = QFormLayout(creds_group)
        self.txt_ans_user = QLineEdit("admin")
        creds_form.addRow("ansible_user:", self.txt_ans_user)
        self.txt_ans_pass = QLineEdit()
        self.txt_ans_pass.setEchoMode(QLineEdit.EchoMode.Password)
        creds_form.addRow("ansible_password:", self.txt_ans_pass)
        self.txt_ans_become = QLineEdit()
        self.txt_ans_become.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_ans_become.setPlaceholderText("(optional) enable secret")
        creds_form.addRow("become password:", self.txt_ans_become)
        left_layout.addWidget(creds_group)

        out_group = QGroupBox("Output")
        out_form = QFormLayout(out_group)
        out_row = QHBoxLayout()
        self.txt_ans_outdir = QLineEdit(os.path.join(os.getcwd(), "ansible_output"))
        out_row.addWidget(self.txt_ans_outdir, 1)
        btn_ans_dir = QPushButton("Browse...")
        btn_ans_dir.clicked.connect(self.browse_ansible_outdir)
        out_row.addWidget(btn_ans_dir)
        out_form.addRow("Folder:", out_row)

        pb_row = QGridLayout()
        self.chk_ans_playbooks = {}
        for i, key in enumerate(ansible_gen.PLAYBOOKS):
            chk = QCheckBox(key)
            chk.setChecked(True)
            self.chk_ans_playbooks[key] = chk
            pb_row.addWidget(chk, i // 2, i % 2)
        out_form.addRow("Playbooks:", pb_row)
        left_layout.addWidget(out_group)

        btn_ans_generate = QPushButton("⚙ Generate Inventory + Playbooks")
        btn_ans_generate.setObjectName("btnPrimary")
        btn_ans_generate.clicked.connect(self.generate_ansible_artifacts)
        left_layout.addWidget(btn_ans_generate)

        run_row = QHBoxLayout()
        self.cmb_ans_run = QComboBox()
        for key in ansible_gen.PLAYBOOKS:
            self.cmb_ans_run.addItem(key, key)
        run_row.addWidget(self.cmb_ans_run, 1)
        self.chk_ans_dry = QCheckBox("--check (dry-run)")
        self.chk_ans_dry.setToolTip("Show what WOULD change without applying it.")
        run_row.addWidget(self.chk_ans_dry)
        self.btn_ans_run = QPushButton("▶ Run in Terminal")
        self.btn_ans_run.setToolTip(
            "Runs ansible-playbook -i inventory.ini <playbook> in a new console window. "
            "Offers to install Ansible if it's missing.")
        self.btn_ans_run.clicked.connect(self.run_ansible_playbook)
        run_row.addWidget(self.btn_ans_run)
        left_layout.addLayout(run_row)
        left_layout.addStretch()

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left)
        layout.addWidget(left_scroll, 1)

        preview_group = QGroupBox("inventory.ini Preview")
        pv_layout = QVBoxLayout(preview_group)
        self.txt_ans_preview = QTextEdit()
        self.txt_ans_preview.setFont(QFont("Consolas", 10))
        self.txt_ans_preview.setReadOnly(True)
        self.txt_ans_preview.setPlaceholderText("Click Generate to build the inventory from the current lab...")
        pv_layout.addWidget(self.txt_ans_preview)
        layout.addWidget(preview_group, 2)

    def browse_ansible_outdir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Output Folder", self.txt_ans_outdir.text().strip())
        if path:
            self.txt_ans_outdir.setText(path)

    def generate_ansible_artifacts(self):
        if not self.nodes_data:
            QMessageBox.warning(self, "No Devices", "Connect to EVE-NG and load a lab first.")
            return
        selected = [k for k, chk in self.chk_ans_playbooks.items() if chk.isChecked()]
        inv_text = ansible_gen.build_inventory(
            self.nodes_data,
            manage_user=self.txt_ans_user.text().strip(),
            manage_pass=self.txt_ans_pass.text(),
            become_pass=self.txt_ans_become.text(),
        )
        self.txt_ans_preview.setPlainText(inv_text)
        try:
            written = ansible_gen.write_artifacts(self.txt_ans_outdir.text().strip(), inv_text, selected)
        except Exception as e:
            QMessageBox.critical(self, "Write Failed", str(e))
            return
        self.log(f"✅ Ansible artifacts written: {len(written)} file(s) in {self.txt_ans_outdir.text().strip()}")
        QMessageBox.information(
            self, "Ansible Artifacts Ready",
            f"Wrote {len(written)} file(s):\n" + "\n".join(os.path.basename(w_) for w_ in written) +
            "\n\nNext steps:\n"
            "  1. Replace CHANGEME with each device's management IP\n"
            "  2. ansible-playbook -i inventory.ini " + (selected[0] if selected else "<playbook>"))

    def run_ansible_playbook(self):
        playbook = self.cmb_ans_run.currentData()
        out_dir = self.txt_ans_outdir.text().strip()
        inv = os.path.join(out_dir, "inventory.ini")
        pb = os.path.join(out_dir, playbook)
        if not os.path.isfile(inv) or not os.path.isfile(pb):
            QMessageBox.warning(self, "Nothing to Run", "Generate the artifacts first (they're missing from the output folder).")
            return

        if os.name != "nt":
            # POSIX control node - Ansible runs natively.
            if shutil.which("ansible-playbook"):
                import subprocess as _sp
                _sp.Popen(["x-terminal-emulator", "-e",
                           f"ansible-playbook -i inventory.ini {playbook}"],
                          cwd=out_dir)
                self.log(f"Launched ansible-playbook ({playbook}).")
            else:
                self._install_pip_ansible_then_run(playbook)
            return

        # ---- Windows: Ansible does NOT run natively anymore (it crashes in
        # check_blocking_io), so WSL is the supported route. ----
        if not self._wsl_available():
            QMessageBox.warning(
                self, "WSL Required",
                "Ansible can no longer run natively on Windows - it needs WSL.\n\n"
                "One-time setup (run in an Administrator PowerShell):\n"
                "  1.  wsl --install\n"
                "  2.  Reboot when prompted, create your Linux user\n"
                "  3.  Come back here and press Run again -\n"
                "      EveBridge will install Ansible inside WSL for you.")
            return

        if self._wsl_has_ansible():
            self._launch_wsl_ansible(playbook)
            return

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Ansible Missing in WSL")
        box.setText(
            "WSL is installed, but Ansible isn't inside it yet.\n"
            "Install it now? (runs as root via apt - takes a few minutes)")
        btn_install = box.addButton("Install in WSL", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is btn_install:
            self._install_wsl_ansible_then_run(playbook)

    # ---------- ansible helpers ----------
    # ---------- ansible helpers ----------
    def _wsl_available(self) -> bool:
        try:
            r = subprocess.run(["wsl.exe", "--status"], capture_output=True, timeout=15)
            return r.returncode == 0
        except Exception:
            return False

    def _wsl_has_ansible(self) -> bool:
        try:
            r = subprocess.run(
                ["wsl.exe", "-e", "bash", "-lc", "command -v ansible-playbook"],
                capture_output=True, timeout=20)
            return r.returncode == 0
        except Exception:
            return False

    def _launch_wsl_ansible(self, playbook: str):
        """Runs the playbook through WSL by mapping the output folder to /mnt/..."""
        win_dir = os.path.abspath(self.txt_ans_outdir.text().strip())
        wsl_dir = f"/mnt/{win_dir[0].lower()}/{win_dir[2:].replace(os.sep, '/')}"
        check = " --check" if self.chk_ans_dry.isChecked() else ""
        script = f"cd '{wsl_dir}' && ansible-playbook -i inventory.ini '{playbook}'{check}"
        try:
            subprocess.Popen(
                ["wsl.exe", "-e", "bash", "-lc", script],
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            mode = " (dry-run)" if check else ""
            self.log(f"Launched ansible in WSL for {playbook}{mode} (dir mapped to {wsl_dir}).")
        except Exception as e:
            QMessageBox.critical(self, "WSL Launch Failed", str(e))

    def _install_wsl_ansible_then_run(self, playbook: str):
        """Installs Ansible inside the default WSL distro (as root, no sudo
        password prompt) then launches the playbook."""
        self.btn_ans_run.setEnabled(False)
        old_text = self.btn_ans_run.text()
        self.btn_ans_run.setText("\u23f3 Installing in WSL...")
        self.log("Installing Ansible inside WSL via apt (a few minutes)...")

        def _run():
            proc = subprocess.run(
                ["wsl.exe", "-u", "root", "-e", "bash", "-lc",
                 "export DEBIAN_FRONTEND=noninteractive; "
                 "apt-get update -y && apt-get install -y ansible"],
                capture_output=True, text=True, timeout=3600)
            tail = ((proc.stdout or "")[-800:] + "\n" + (proc.stderr or "")[-400:]).strip()
            return proc.returncode, tail

        self._ans_install_worker = WorkerThread(_run)

        def _done(status, result):
            self.btn_ans_run.setEnabled(True)
            self.btn_ans_run.setText(old_text)
            ok = status == "success" and result[0] == 0 and self._wsl_has_ansible()
            if ok:
                self.log("\u2705 Ansible installed inside WSL.")
                self._launch_wsl_ansible(playbook)
            else:
                detail = result[1] if status == "success" else str(result)
                self.log(f"\u274c WSL ansible install failed: {detail[:200]}")
                QMessageBox.critical(
                    self, "Install Failed",
                    f"Couldn't install Ansible inside WSL.\n\n{detail[:600]}\n\n"
                    f"You can also open a WSL terminal yourself and run:\n"
                    f"  sudo apt update && sudo apt install -y ansible")

        self._ans_install_worker.finished_signal.connect(_done)
        self._ans_install_worker.start()

    def _spawn_native_ansible(self, playbook: str):
        extra = ["--check"] if self.chk_ans_dry.isChecked() else []
        import subprocess as _sp
        _sp.Popen(["cmd", "/k", "ansible-playbook", "-i", "inventory.ini"] + extra + [playbook],
                  cwd=self.txt_ans_outdir.text().strip(),
                  creationflags=getattr(_sp, "CREATE_NEW_CONSOLE", 0))
        mode = " (dry-run)" if extra else ""
        self.log(f"Launched ansible-playbook ({playbook}){mode} in a new console window.")

    def _install_pip_ansible_then_run(self, playbook: str):
        """POSIX-only fallback: pip-installs Ansible, then re-launches."""
        self.btn_ans_run.setEnabled(False)
        old_text = self.btn_ans_run.text()
        self.btn_ans_run.setText("\u23f3 Installing Ansible...")

        def _run():
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "ansible"],
                capture_output=True, text=True, timeout=3600)
            tail = ((proc.stdout or "")[-800:] + "\n" + (proc.stderr or "")[-400:]).strip()
            return proc.returncode, tail

        self._ans_install_worker = WorkerThread(_run)

        def _done(status, result):
            self.btn_ans_run.setEnabled(True)
            self.btn_ans_run.setText(old_text)
            if status == "success" and result[0] == 0:
                self._spawn_native_ansible(playbook)
            else:
                detail = result[1] if status == "success" else str(result)
                QMessageBox.critical(self, "Install Failed",
                                     f"pip couldn't install Ansible.\n\n{detail}")

        self._ans_install_worker.finished_signal.connect(_done)
        self._ans_install_worker.start()

    def setup_adgpo_tab(self):
        layout = QHBoxLayout(self.tab_adgpo)

        left = QWidget()
        left_layout = QVBoxLayout(left)

        info = QLabel(
            "Generates elevated PowerShell for your Windows lab — everything is cmdlet-based "
            "and works on Server Core with no GUI. Promote a DC, join machines to the domain, "
            "create the lab users/groups (the same accounts NPS/RADIUS uses on the AAA tab), "
            "and build a linked baseline GPO."
        )
        info.setWordWrap(True)
        info.setObjectName("muted")
        left_layout.addWidget(info)

        form_group = QGroupBox("Lab parameters")
        form = QFormLayout(form_group)
        self.txt_ad_domain = QLineEdit("lab.local")
        form.addRow("Domain FQDN:", self.txt_ad_domain)
        self.txt_ad_netbios = QLineEdit("LAB")
        form.addRow("NetBIOS name:", self.txt_ad_netbios)
        dc_row = QHBoxLayout()
        self.txt_ad_dc_ip = QLineEdit()
        self.txt_ad_dc_ip.setPlaceholderText("e.g. 10.0.0.10")
        dc_row.addWidget(self.txt_ad_dc_ip, 1)
        form.addRow("DC IP:", dc_row)
        self.txt_ad_dsrm = QLineEdit("Dsrmlab!123")
        self.txt_ad_dsrm.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("DSRM password:", self.txt_ad_dsrm)
        user_row = QHBoxLayout()
        self.txt_ad_admin_user = QLineEdit("netadmin")
        user_row.addWidget(self.txt_ad_admin_user, 1)
        self.txt_ad_admin_pass = QLineEdit("Cisc0123!")
        user_row.addWidget(self.txt_ad_admin_pass, 1)
        form.addRow("Sample user / pass:", user_row)
        self.txt_ad_gpo_name = QLineEdit("Lab-Base")
        form.addRow("GPO name:", self.txt_ad_gpo_name)
        left_layout.addWidget(form_group)

        btn_grid = QGridLayout()
        buttons = [
            ("1) Promote Domain Controller", lambda: self.adgpo_generate("dc")),
            ("2) Join Machine to Domain", lambda: self.adgpo_generate("join")),
            ("3) Create OUs / Groups / Users", lambda: self.adgpo_generate("users")),
            ("4) Baseline GPO + Link", lambda: self.adgpo_generate("gpo")),
        ]
        for i, (label, handler) in enumerate(buttons):
            btn = QPushButton(label)
            btn.clicked.connect(handler)
            btn_grid.addWidget(btn, i // 2, i % 2)
        left_layout.addLayout(btn_grid)
        left_layout.addStretch()

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left)
        layout.addWidget(left_scroll, 1)

        right_group = QGroupBox("Generated PowerShell (also copied to clipboard — run as Administrator)")
        rv = QVBoxLayout(right_group)
        self.txt_ad_preview = QTextEdit()
        self.txt_ad_preview.setFont(QFont("Consolas", 10))
        self.txt_ad_preview.setReadOnly(True)
        self.txt_ad_preview.setPlaceholderText("Pick a step on the left and the script appears here...")
        rv.addWidget(self.txt_ad_preview)
        layout.addWidget(right_group, 2)

    def adgpo_generate(self, which: str):
        domain = self.txt_ad_domain.text().strip() or "lab.local"
        netbios = self.txt_ad_netbios.text().strip() or domain.split(".")[0].upper()
        builders = {
            "dc": lambda: ad_gpo_gen.build_dc_promo(domain, netbios, self.txt_ad_dsrm.text()),
            "join": lambda: ad_gpo_gen.build_domain_join(domain, self.txt_ad_dc_ip.text()),
            "users": lambda: ad_gpo_gen.build_users_groups(
                domain, netbios,
                self.txt_ad_admin_user.text().strip() or "netadmin",
                self.txt_ad_admin_pass.text() or "Cisc0123!"),
            "gpo": lambda: ad_gpo_gen.build_gpo_starter(self.txt_ad_gpo_name.text(), domain),
        }
        text = builders[which]()
        self.txt_ad_preview.setPlainText(text)
        QApplication.clipboard().setText(text)
        self.log(f"AD/GPO script generated ({which}) — copied to clipboard.")


    def fw_detect_interfaces(self):
        node_id = self.cmb_fw_device.currentData()
        if not node_id:
            QMessageBox.warning(self, "No Device Selected", "Select a target device first.")
            return

        is_forti = "FortiGate" in self.cmb_fw_type.currentText()
        ip = self.txt_ip.text().strip()
        port = 32768 + int(node_id)
        self.btn_fw_detect.setEnabled(False)
        self.log("Detecting firewall interfaces...")

        def _run():
            mgr = NodeConsoleManager(ip, port)
            if is_forti:
                output = mgr.send_commands(["get system interface physical"])
                return parse_fortigate_interfaces(output)
            else:
                output = mgr.send_commands(["8", "ifconfig -l", "exit"])
                return parse_bsd_interface_list(output)

        self._fw_detect_worker = WorkerThread(_run)

        def _done(status, result):
            self.btn_fw_detect.setEnabled(True)
            if status != "success":
                self.log(f"Interface detection failed: {result}")
                QMessageBox.warning(self, "Detection Failed", str(result))
                return
            if not result:
                self.log("No interfaces detected — device may be stopped or still booting.")
                QMessageBox.information(self, "No Interfaces Found",
                                         "Couldn't detect any interfaces. Make sure the device is running and try again.")
                return
            self.fw_detected_interfaces = result
            self.cmb_fw_wan_if.clear()
            self.cmb_fw_wan_if.addItems(result)
            self.cmb_fw_lan_if.clear()
            self.cmb_fw_lan_if.addItems(result)
            self.log(f"Detected {len(result)} interface(s): {', '.join(result)}")

        self._fw_detect_worker.finished_signal.connect(_done)
        self._fw_detect_worker.start()

    def build_firewall_script(self):
        fw_type = self.cmb_fw_type.currentText()

        if "FortiGate" in fw_type:
            dns_servers = [d.strip() for d in self.txt_fw_dns.text().split(",") if d.strip()]
            additional_lans = []
            for row in self.fw_lan_rows:
                additional_lans.append({
                    "interface": row["if"].currentText().strip(),
                    "ip": row["ip"].text().strip(),
                    "mask": row["mask"].text().strip(),
                    "enable_dhcp": row["dhcp"].isChecked(),
                    "dhcp_start": row["start"].text().strip(),
                    "dhcp_end": row["end"].text().strip(),
                })
            script = generate_fortigate_config(
                wan_interface=self.cmb_fw_wan_if.currentText().strip(),
                wan_mode="static" if self.cmb_fw_wan_mode.currentText() == "Static" else "dhcp",
                wan_ip=self.txt_fw_wan_ip.text().strip(),
                wan_mask=self.txt_fw_wan_mask.text().strip(),
                wan_gateway=self.txt_fw_wan_gateway.text().strip(),
                lan_interface=self.cmb_fw_lan_if.currentText().strip(),
                lan_ip=self.txt_fw_lan_ip.text().strip(),
                lan_mask=self.txt_fw_lan_mask.text().strip(),
                enable_dhcp=self.chk_fw_dhcp.isChecked(),
                dhcp_start=self.txt_fw_dhcp_start.text().strip(),
                dhcp_end=self.txt_fw_dhcp_end.text().strip(),
                allow_ssh_https_wan=self.chk_fw_wan_access.isChecked(),
                hostname=self.txt_fw_hostname.text().strip(),
                admin_password=self.txt_fw_admin_pass.text(),
                dns_servers=dns_servers,
                enable_logging=self.chk_fw_logging.isChecked(),
                additional_lans=additional_lans,
            )
            return script, None  # (flat script, staged steps) — FortiGate has no staged mode
        else:
            optional_interfaces = [row["if"].currentText().strip() for row in self.fw_opt_rows if row["if"].currentText().strip()]
            steps = build_pfsense_opnsense_steps(
                wan_interface=self.cmb_fw_wan_if.currentText().strip(),
                lan_interface=self.cmb_fw_lan_if.currentText().strip(),
                lan_ip=self.txt_fw_lan_ip.text().strip(),
                lan_bits=self.txt_fw_lan_bits.text().strip(),
                enable_dhcp=self.chk_fw_dhcp.isChecked(),
                dhcp_start=self.txt_fw_dhcp_start.text().strip(),
                dhcp_end=self.txt_fw_dhcp_end.text().strip(),
                enable_ssh=self.chk_fw_ssh.isChecked(),
                optional_interfaces=optional_interfaces,
            )
            script = "\n".join(flatten_steps(steps))
            return script, steps

    def generate_firewall_config(self):
        script, _steps = self.build_firewall_script()
        self.txt_fw_script.setPlainText(script)
        self.log(f"Generated {self.cmb_fw_type.currentText()} initial configuration script.")

    def send_firewall_config(self):
        node_id = self.cmb_fw_device.currentData()
        if not node_id:
            QMessageBox.warning(self, "No Device Selected", "Please select a target device first.")
            return

        fw_type = self.cmb_fw_type.currentText()
        script, steps = self.build_firewall_script()
        self.txt_fw_script.setPlainText(script)
        ip = self.txt_ip.text().strip()
        port = 32768 + int(node_id)

        if "FortiGate" in fw_type:
            cmds = script.split("\n")
            self.txt_fw_output.clear()
            self.btn_fw_send.setEnabled(False)
            self.bar_fw_progress.setValue(0)
            self.log(f"Sending FortiGate configuration to Node {node_id}...")

            def _run():
                mgr = NodeConsoleManager(ip, port)
                return mgr.send_commands(cmds)

            self._fw_worker = WorkerThread(_run)

            def _done(status, res):
                self.btn_fw_send.setEnabled(True)
                self.bar_fw_progress.setValue(100)
                if status == "success":
                    output = res if res.strip() else "(No data received — check the device is running and reachable.)"
                    self.txt_fw_output.setPlainText(output)
                    self.log("FortiGate configuration sent.")
                else:
                    self.txt_fw_output.setPlainText(f"[ERROR] {res}")
                    self.log(f"Failed to send configuration: {res}")

            self._fw_worker.finished_signal.connect(_done)
            self._fw_worker.start()
        else:
            confirm = QMessageBox.question(
                self, "Confirm Send",
                "pfSense/OPNsense console menus vary by version. This sends the script as separate "
                "labeled steps (Assign Interfaces, then Set IP/DHCP, then Enable SSH) so you can see "
                "exactly where any mismatch happens. Review the script above and continue only if it "
                "looks right for your version. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

            self.txt_fw_output.clear()
            self.btn_fw_send.setEnabled(False)
            self.bar_fw_progress.setValue(0)
            self.log(f"Sending {fw_type} configuration to Node {node_id} in {len(steps)} step(s)...")

            self._fw_staged_worker = FirewallStagedWorker(ip, port, steps)
            self._fw_staged_worker.step_output_signal.connect(self.on_fw_step_output)
            self._fw_staged_worker.progress_signal.connect(self.on_fw_staged_progress)
            self._fw_staged_worker.finished_signal.connect(lambda: (self.btn_fw_send.setEnabled(True), self.log("All steps sent.")))
            self._fw_staged_worker.start()

    def on_fw_step_output(self, label: str, output: str):
        self.txt_fw_output.append(f"\n===== {label} =====\n{output}\n")

    def on_fw_staged_progress(self, pct: int, msg: str):
        self.bar_fw_progress.setValue(pct)
        self.log(msg)

    # ------------------ TAB 1: NODES & STATUS ------------------
    def setup_nodes_tab(self):
        layout = QVBoxLayout(self.tab_nodes)

        # Global Actions & Filter Bar
        act_layout = QHBoxLayout()
        
        btn_add_node = QPushButton("➕ Add New Device")
        btn_add_node.setObjectName("btnPrimary")
        btn_add_node.clicked.connect(self.open_add_node_dialog)
        self.register_responsive_button(btn_add_node, "➕", "➕ Add New Device")
        act_layout.addWidget(btn_add_node)

        act_layout.addSpacing(10)

        btn_start_all = QPushButton("▶ Start Filtered Nodes")
        btn_start_all.setObjectName("btnSuccess")
        btn_start_all.setToolTip("Starts every node currently visible in the table below.\n"
                                  "Clear the Filter Type / Search box first to target the whole lab.")
        btn_start_all.clicked.connect(self.start_all_nodes)
        self.register_responsive_button(btn_start_all, "▶", "▶ Start Filtered Nodes")
        act_layout.addWidget(btn_start_all)

        btn_stop_all = QPushButton("⏹ Stop Filtered Nodes")
        btn_stop_all.setObjectName("btnDanger")
        btn_stop_all.setToolTip("Stops every node currently visible in the table below.\n"
                                 "Clear the Filter Type / Search box first to target the whole lab.")
        btn_stop_all.clicked.connect(self.stop_all_nodes)
        self.register_responsive_button(btn_stop_all, "⏹", "⏹ Stop Filtered Nodes")
        act_layout.addWidget(btn_stop_all)

        act_layout.addSpacing(10)

        btn_wireshark = QPushButton("🦈 Wireshark Capture")
        btn_wireshark.setToolTip("Sniff live traffic on an EVE-NG host interface, streamed into a local Wireshark window.")
        btn_wireshark.clicked.connect(self.open_capture_dialog)
        self.register_responsive_button(btn_wireshark, "🦈", "🦈 Wireshark Capture")
        act_layout.addWidget(btn_wireshark)

        btn_ping = QPushButton("📡 Ping Tester")
        btn_ping.setToolTip("Ping any host from this PC - one-shot or continuous, with live stats.")
        btn_ping.clicked.connect(self.open_ping_dialog)
        self.register_responsive_button(btn_ping, "📡", "📡 Ping Tester")
        act_layout.addWidget(btn_ping)

        act_layout.addSpacing(20)
        act_layout.addWidget(QLabel("Filter Type:"))
        
        self.cmb_filter_type = QComboBox()
        self.cmb_filter_type.setMinimumWidth(140)
        self.cmb_filter_type.addItems(["All Types", "Routers (dynamips)", "Switches (iol)", "PCs (vpcs)", "VMs (qemu)"])
        self.cmb_filter_type.currentIndexChanged.connect(self.apply_node_filters)
        act_layout.addWidget(self.cmb_filter_type)

        act_layout.addWidget(QLabel("Search:"))
        self.txt_filter_search = QLineEdit()
        self.txt_filter_search.setPlaceholderText("Filter by name or ID...")
        self.txt_filter_search.setFixedWidth(160)
        self.txt_filter_search.textChanged.connect(self.apply_node_filters)
        act_layout.addWidget(self.txt_filter_search)

        self.lbl_device_count = QLabel("")
        self.lbl_device_count.setObjectName("muted")
        act_layout.addWidget(self.lbl_device_count)

        act_layout.addStretch()
        layout.addLayout(act_layout)

        # --- Device Groups: save the current selection under a name, then
        # start/stop the whole group with one click (stored per lab). ---
        grp_layout = QHBoxLayout()
        grp_layout.addWidget(QLabel("Device Groups:"))
        self.cmb_node_groups = QComboBox()
        self.cmb_node_groups.setMinimumWidth(180)
        self.cmb_node_groups.setToolTip("Saved selections for this lab.")
        grp_layout.addWidget(self.cmb_node_groups)

        btn_grp_save = QPushButton("💾 Save Selection...")
        btn_grp_save.setToolTip("Store the rows currently selected in the table as a named group.")
        btn_grp_save.clicked.connect(self.on_group_save)
        grp_layout.addWidget(btn_grp_save)

        btn_grp_delete = QPushButton("🗑 Delete Group")
        btn_grp_delete.clicked.connect(self.on_group_delete)
        grp_layout.addWidget(btn_grp_delete)

        grp_layout.addSpacing(12)
        btn_grp_start = QPushButton("▶ Start Group")
        btn_grp_start.setObjectName("btnSuccess")
        btn_grp_start.setToolTip("Start every device in the selected group.")
        btn_grp_start.clicked.connect(lambda: self._run_group_action(start=True))
        grp_layout.addWidget(btn_grp_start)

        btn_grp_stop = QPushButton("⏹ Stop Group")
        btn_grp_stop.setObjectName("btnDanger")
        btn_grp_stop.setToolTip("Stop every device in the selected group.")
        btn_grp_stop.clicked.connect(lambda: self._run_group_action(start=False))
        grp_layout.addWidget(btn_grp_stop)

        grp_layout.addStretch()
        layout.addLayout(grp_layout)
        self.populate_group_combo()

        # --- View switcher: classic table or hierarchical tree (groups as
        # folders with their member devices nested underneath) ---
        view_row = QHBoxLayout()
        view_row.addWidget(QLabel("View:"))
        self.btn_view_table = QPushButton("📋 Table")
        self.btn_view_table.setCheckable(True)
        self.btn_view_table.setChecked(True)
        self.btn_view_table.clicked.connect(self.show_nodes_table_view)
        view_row.addWidget(self.btn_view_table)

        self.btn_view_tree = QPushButton("🌲 Tree")
        self.btn_view_tree.setCheckable(True)
        self.btn_view_tree.setToolTip(
            "Hierarchy: each saved group is a folder with its members underneath; "
            "ungrouped devices stay at the top level. Double-click a device to open its console.")
        self.btn_view_tree.clicked.connect(self.show_nodes_tree_view)
        view_row.addWidget(self.btn_view_tree)
        view_row.addStretch()
        layout.addLayout(view_row)

        # Progress Bar Layout
        prog_layout = QVBoxLayout()
        self.lbl_progress = QLabel("Ready")
        self.lbl_progress.setObjectName("accentText")
        prog_layout.addWidget(self.lbl_progress)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        prog_layout.addWidget(self.progress_bar)
        layout.addLayout(prog_layout)

        # Table
        self.tbl_nodes = QTableWidget()
        self.tbl_nodes.setColumnCount(9)
        self.tbl_nodes.setHorizontalHeaderLabels([
            "ID", "Name", "Type", "Template", "📁 Groups",
            "Status", "RAM", "Connection Method", "Actions"
        ])
        hdr = self.tbl_nodes.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col, mode in ((0, QHeaderView.ResizeMode.ResizeToContents),
                          (1, QHeaderView.ResizeMode.Stretch),
                          (2, QHeaderView.ResizeMode.ResizeToContents),
                          (3, QHeaderView.ResizeMode.ResizeToContents),
                          (4, QHeaderView.ResizeMode.ResizeToContents),
                          (5, QHeaderView.ResizeMode.ResizeToContents),
                          (6, QHeaderView.ResizeMode.ResizeToContents),
                          (7, QHeaderView.ResizeMode.Fixed),
                          (8, QHeaderView.ResizeMode.Fixed)):
            hdr.setSectionResizeMode(col, mode)
        self.tbl_nodes.setColumnWidth(7, 150)
        self.tbl_nodes.setColumnWidth(8, 236)
        hdr.setStretchLastSection(False)

        # Roomy rows so the embedded Start/Stop/Connect buttons render at
        # full height with their labels visible (never vertically clipped).
        self.tbl_nodes.verticalHeader().setDefaultSectionSize(38)
        self.tbl_nodes.verticalHeader().setMinimumSectionSize(38)
        self.tbl_nodes.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_nodes.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.tbl_nodes.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tbl_nodes.customContextMenuRequested.connect(self.show_table_context_menu)

        # Stacked view: table (index 0) / hierarchy tree (index 1)
        self.nodes_view_stack = QStackedWidget()
        self.nodes_view_stack.addWidget(self.tbl_nodes)

        self.tree_nodes = QTreeWidget()
        self.tree_nodes.setColumnCount(1)
        self.tree_nodes.setHeaderLabel("Devices & Groups")
        self.tree_nodes.setIndentation(24)
        self.tree_nodes.setStyleSheet(
            "QTreeWidget{font-size:12px;}"
            "QTreeWidget::item{height:30px; padding:2px 4px; border-radius:4px;}"
            "QTreeWidget::item:hover{background:rgba(148,163,184,60);}"
            "QTreeWidget::item:selected{background:#0284c7; color:white;}")
        self.tree_nodes.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_nodes.customContextMenuRequested.connect(self.show_tree_context_menu)
        self.tree_nodes.itemDoubleClicked.connect(self._on_tree_item_double_clicked)
        self.nodes_view_stack.addWidget(self.tree_nodes)

        layout.addWidget(self.nodes_view_stack, 1)

    def populate_nodes_table(self, nodes: dict):
        # id -> "📁 Group A · 📁 Group B" (from the per-lab saved groups)
        membership = {}
        for gname, ids in self._load_groups().items():
            for i in ids:
                membership.setdefault(str(i), []).append(f"📁 {gname}")

        self.tbl_nodes.setRowCount(0)
        for node_id, info in nodes.items():
            row = self.tbl_nodes.rowCount()
            self.tbl_nodes.insertRow(row)

            self.tbl_nodes.setItem(row, 0, QTableWidgetItem(str(info.get("id"))))
            self.tbl_nodes.setItem(row, 1, QTableWidgetItem(str(info.get("name"))))
            self.tbl_nodes.setItem(row, 2, QTableWidgetItem(str(info.get("type"))))
            self.tbl_nodes.setItem(row, 3, QTableWidgetItem(str(info.get("template"))))

            groups_item = QTableWidgetItem(" ".join(membership.get(str(info.get("id")), [])))
            if membership.get(str(info.get("id"))):
                groups_item.setForeground(QColor("#7dd3fc"))
                groups_item.setToolTip("Groups this device belongs to (edit via Device Groups row or the Topology map)")
            else:
                groups_item.setToolTip("Not in any group — select rows and use 'Save Selection...'")
            self.tbl_nodes.setItem(row, 4, groups_item)

            try:
                node_state = int(str(info.get("status", 0)).strip() or 0)
            except (TypeError, ValueError):
                node_state = 0
            running = node_state in (1, 2)
            status_str = "\u25cf RUNNING" if running else "\u25cb STOPPED"
            status_item = QTableWidgetItem(status_str)
            if running:
                status_item.setForeground(QColor("#22c55e"))
            else:
                status_item.setForeground(QColor("#ef4444"))
            self.tbl_nodes.setItem(row, 5, status_item)

            self.tbl_nodes.setItem(row, 6, QTableWidgetItem(f"{info.get('ram', 0)} MB"))
            
            # Connection Method Dropdown per node row (Auto-detect default protocol by node type)
            cmb_node_proto = QComboBox()
            cmb_node_proto.addItems(["Telnet (Console)", "SSH (Port 22)", "HTML5 Web", "VNC Viewer"])
            
            console_type = str(info.get("console", "")).lower()
            ntype = str(info.get("type", "")).lower()
            template = str(info.get("template", "")).lower()
            
            # Default protocol auto-detection
            if "win" in template or ("qemu" in ntype and "vnc" in console_type):
                cmb_node_proto.setCurrentText("VNC Viewer")
            elif "html5" in console_type:
                cmb_node_proto.setCurrentText("HTML5 Web")
            else:
                cmb_node_proto.setCurrentText("Telnet (Console)")

            self.tbl_nodes.setCellWidget(row, 7, cmb_node_proto)

            # Actions Cell
            action_widget = QWidget()
            btn_box = QHBoxLayout(action_widget)
            btn_box.setContentsMargins(4, 4, 4, 4)
            btn_box.setSpacing(6)

            nid = int(info.get("id"))
            btn_start = QPushButton("Start")
            btn_start.setObjectName("btnSuccess")
            btn_start.clicked.connect(lambda _, n=nid: self.start_single_node(n))

            btn_stop = QPushButton("Stop")
            btn_stop.setObjectName("btnDanger")
            btn_stop.clicked.connect(lambda _, n=nid: self.stop_single_node(n))

            btn_start.setMinimumWidth(62)
            btn_stop.setMinimumWidth(58)

            btn_telnet = QPushButton("Connect")
            btn_telnet.setObjectName("btnPrimary")
            btn_telnet.setMinimumWidth(84)
            btn_telnet.clicked.connect(lambda _, n=nid, r=row: self.open_node_console_with_row_proto(n, r))

            btn_box.addWidget(btn_start)
            btn_box.addWidget(btn_stop)
            btn_box.addWidget(btn_telnet)

            self.tbl_nodes.setCellWidget(row, 8, action_widget)

        self.tbl_nodes.resizeRowsToContents()
        self.apply_node_filters()
        if hasattr(self, "tree_nodes"):
            self.populate_nodes_tree()

    def apply_node_filters(self):
        filter_type = self.cmb_filter_type.currentText().lower()
        search_txt = self.txt_filter_search.text().strip().lower()

        visible = 0
        total = self.tbl_nodes.rowCount()
        for row in range(total):
            def cell_text(col: int) -> str:
                item = self.tbl_nodes.item(row, col)
                return item.text().lower() if item else ""
            nid = cell_text(0)
            name = cell_text(1)
            ntype = cell_text(2)
            template = cell_text(3)

            # Type Filter check
            type_match = True
            if "router" in filter_type:
                type_match = ("dynamips" in ntype or "3725" in template or "router" in template)
            elif "switch" in filter_type:
                type_match = ("iol" in ntype or "switch" in template)
            elif "pc" in filter_type:
                type_match = ("vpcs" in ntype or "pc" in template)
            elif "vm" in filter_type:
                type_match = ("qemu" in ntype or "win" in template or "linux" in template)

            # Search Text check
            search_match = True
            if search_txt:
                search_match = (search_txt in nid or search_txt in name or search_txt in ntype or search_txt in template)

            # Show/Hide Row
            if type_match and search_match:
                self.tbl_nodes.setRowHidden(row, False)
                visible += 1
            else:
                self.tbl_nodes.setRowHidden(row, True)

        if total:
            self.lbl_device_count.setText(f"{visible} of {total} devices shown")
        else:
            self.lbl_device_count.setText("")

    def show_table_context_menu(self, pos):
        selected_rows = self.tbl_nodes.selectionModel().selectedRows()

        selected_node_ids = []
        for index in selected_rows:
            row = index.row()
            nid_item = self.tbl_nodes.item(row, 0)
            name_item = self.tbl_nodes.item(row, 1)
            if nid_item:
                selected_node_ids.append(int(nid_item.text()))

        menu = QMenu(self)

        # Always available: refresh (works whether or not rows are selected).
        act_refresh = menu.addAction("🔄 Refresh Nodes")
        if selected_node_ids:
            title_action = menu.addAction(f"Actions for {len(selected_node_ids)} selected device(s)")
            title_action.setEnabled(False)

        act_save_group = menu.addAction("💾 Save Selection as Group...")
        add_menu = menu.addMenu("➕ Add to Group")
        groups = self._load_groups()
        if not groups:
            act_add_empty = add_menu.addAction("(no groups yet)")
            act_add_empty.setEnabled(False)
            add_target = None
        else:
            add_target = {}
            for gname in sorted(groups):
                act = add_menu.addAction(f"📁 {gname}")
                add_target[act] = gname

        # Groups that contain at least one selected device
        selected_set = set(selected_node_ids)
        containing = {}
        for gname, gids in groups.items():
            hit = [g for g in gids if g in selected_set]
            if hit:
                containing[gname] = hit
        rm_menu = menu.addMenu("➖ Remove from Group")
        rm_target = {}
        if not containing:
            act_rm_none = rm_menu.addAction("(selection not in any group)")
            act_rm_none.setEnabled(False)
        else:
            for gname, hit in sorted(containing.items()):
                act = rm_menu.addAction(f"📁 {gname}  ({len(hit)} of selection)")
                rm_target[act] = (gname, hit)
            if len(containing) > 1:
                act = rm_menu.addAction("All Groups")
                rm_target[act] = ("__all__", sorted(selected_set))
        menu.addSeparator()

        act_start = menu.addAction("▶ Start Selected")
        act_stop = menu.addAction("⏹ Stop Selected")
        act_wipe = menu.addAction("🧹 Wipe Selected (NVRAM)")
        for a in (act_start, act_stop, act_wipe):
            a.setEnabled(bool(selected_node_ids))

        menu.addSeparator()
        if len(selected_node_ids) == 1:
            nid0 = selected_node_ids[0]
            act_telnet = menu.addAction("💻 Open Telnet Console")
            act_telnet.triggered.connect(lambda: self.open_telnet_console(nid0))

            act_capture = menu.addAction("🦈 Wireshark Capture...")
            act_capture.triggered.connect(lambda: self.open_capture_dialog(preselect_node_id=nid0))

            act_edit = menu.addAction("✏️ Edit RAM/NVRAM/CPU...")
            act_edit.triggered.connect(lambda: self.open_edit_node_dialog(nid0))
            menu.addSeparator()

        chosen = menu.exec(self.tbl_nodes.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is act_refresh:
            self.refresh_lab()
        elif chosen is act_save_group:
            self.on_group_save()
        elif add_target and chosen in add_target:
            self._add_selection_to_group(add_target[chosen])
        elif rm_target and chosen in rm_target:
            gname, ids = rm_target[chosen]
            if gname == "__all__":
                for g in list(containing):
                    self._remove_ids_from_group(g, ids)
            else:
                self._remove_ids_from_group(gname, ids)
        elif chosen is act_start and selected_node_ids:
            self.start_selected_nodes(selected_node_ids)
        elif chosen is act_stop and selected_node_ids:
            self.stop_selected_nodes(selected_node_ids)
        elif chosen is act_wipe and selected_node_ids:
            self.wipe_selected_nodes(selected_node_ids)

    def _add_selection_to_group(self, gname: str):
        """Merges the currently selected devices into an existing group."""
        ids = self.get_selected_node_ids()
        if not ids:
            QMessageBox.information(self, "Nothing Selected",
                                    "Select rows in the table first.")
            return
        groups = self._load_groups()
        merged = sorted(set(groups.get(gname, [])) | set(ids))
        groups[gname] = merged
        self._save_groups(groups)
        self.populate_group_combo()
        self.populate_nodes_table(self.nodes_data)  # refresh Groups column
        self.log(f"📁 Added {len(ids)} device(s) to group '{gname}' "
                 f"(now {len(merged)} members).")

    def _remove_ids_from_group(self, gname: str, ids: list):
        """Drops specific devices from a group; deletes the group outright
        when its last member leaves."""
        ids = set(ids)
        groups = self._load_groups()
        remaining = [i for i in groups.get(gname, []) if i not in ids]
        if remaining:
            groups[gname] = remaining
            msg = f"'{gname}' now has {len(remaining)} member(s)."
        else:
            groups.pop(gname, None)
            msg = f"'{gname}' became empty and was deleted."
        self._save_groups(groups)
        self.populate_group_combo()
        self.populate_nodes_table(self.nodes_data)
        self.log(f"➖ Removed device(s) {sorted(ids)} from group '{gname}'. {msg}")

    def start_selected_nodes(self, node_ids: list[int]):
        self.log(f"Starting {len(node_ids)} selected node(s): {node_ids}")
        self.progress_bar.setValue(0)
        self.batch_worker = NodeBatchWorker(self.eve_client, self.current_lab, node_ids, action="start")
        self.batch_worker.progress_signal.connect(self.on_batch_progress)
        self.batch_worker.finished_signal.connect(self.on_batch_finished)
        self.batch_worker.start()

    def stop_selected_nodes(self, node_ids: list[int]):
        self.log(f"Stopping {len(node_ids)} selected node(s): {node_ids}")
        self.progress_bar.setValue(0)
        self.batch_worker = NodeBatchWorker(self.eve_client, self.current_lab, node_ids, action="stop")
        self.batch_worker.progress_signal.connect(self.on_batch_progress)
        self.batch_worker.finished_signal.connect(self.on_batch_finished)
        self.batch_worker.start()

    def wipe_selected_nodes(self, node_ids: list[int]):
        confirm = QMessageBox.question(
            self, "Confirm Wipe",
            f"Are you sure you want to wipe startup config for {len(node_ids)} selected node(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            failed = []
            for nid in node_ids:
                self.log(f"Wiping node {nid}...")
                if not self.eve_client.wipe_node(self.current_lab, nid):
                    failed.append(nid)
                    self.log(f"❌ Failed to wipe node {nid}.")
            if failed:
                self.log(f"Wipe completed with {len(failed)} failure(s): nodes {failed}")
                QMessageBox.warning(
                    self, "Some Wipes Failed",
                    f"{len(failed)} of {len(node_ids)} node(s) could not be wiped: {failed}\n\n"
                    f"Check the log for details — they may still be running (stop them first)."
                )
            else:
                self.log("Wipe completed.")
            self.refresh_lab()

    def open_add_node_dialog(self):
        if not self.eve_client or not self.eve_client.is_logged_in:
            QMessageBox.warning(self, "Not Connected", "Please connect to EVE-NG first.")
            return

        dialog = AddNodeDialog(self, self.eve_client, self.current_lab)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            node_data = dialog.get_node_data()
            count = dialog.spin_count.value()
            self.log(f"Adding {count} device(s) of template '{node_data['template']}'...")

            failures = []
            for i in range(count):
                if count > 1:
                    self.log(f"  adding node {i + 1}/{count}...")
                ok, msg = self.eve_client.add_node(self.current_lab, dict(node_data))
                if not ok:
                    failures.append(msg)
            if failures:
                self.log(f"\u274c {len(failures)} of {count} node(s) failed. EVE-NG said: {failures[0]}")
                QMessageBox.critical(self, "Add Failed",
                                     f"{len(failures)} of {count} node(s) failed.\n\nEVE-NG said:\n{failures[0]}")
            else:
                self.log(f"\u2705 Added {count} device(s).")
            self.refresh_lab()
            # Keep the topology diagram in sync too, if it's ever been rendered.
            if hasattr(self, "topo_canvas"):
                self.render_topology_diagram()

    def start_single_node(self, node_id: int):
        self.log(f"Attempting to start node {node_id}...")
        try:
            res = self.eve_client.start_node(self.current_lab, node_id)
            if res:
                self.log(f"SUCCESS: Node {node_id} started.")
                self.refresh_lab()
                # EVE-NG flips the state asynchronously; re-check shortly so
                # the row turns green instead of showing a stale STOPPED.
                QTimer.singleShot(2500, self.refresh_lab)
            else:
                detail = getattr(self.eve_client, "last_error", "")
                self.log(f"FAILED: Node {node_id} start returned False. {detail}")
                QMessageBox.warning(self, "Start Failed", f"Node {node_id} did not start.\n\n{detail}")
        except Exception as e:
            import traceback
            err_msg = f"EXCEPTION in start_single_node({node_id}): {e}\n{traceback.format_exc()}"
            self.log(err_msg)
            print(err_msg)

    def stop_single_node(self, node_id: int):
        self.log(f"Attempting to stop node {node_id}...")
        try:
            res = self.eve_client.stop_node(self.current_lab, node_id)
            if res:
                self.log(f"SUCCESS: Node {node_id} stopped.")
                self.refresh_lab()
                QTimer.singleShot(2500, self.refresh_lab)
            else:
                detail = getattr(self.eve_client, "last_error", "")
                self.log(f"FAILED: Node {node_id} stop returned False. {detail}")
                QMessageBox.warning(self, "Stop Failed", f"Node {node_id} could not be stopped.\n\n{detail}")
        except Exception as e:
            import traceback
            err_msg = f"EXCEPTION in stop_single_node({node_id}): {e}\n{traceback.format_exc()}"
            self.log(err_msg)
            print(err_msg)

    def start_all_nodes(self):
        """Start every node currently matching the active Filter Type / Search
        (i.e. every *visible* row), not the entire lab regardless of filter."""
        node_ids = self.get_visible_node_ids()
        if not node_ids:
            self.log("No nodes match the current filter/search — nothing to start. Clear the filter to target all nodes.")
            return

        self.log(f"Starting {len(node_ids)} node(s) matching the current filter/search...")
        self.progress_bar.setValue(0)
        self.batch_worker = NodeBatchWorker(self.eve_client, self.current_lab, node_ids, action="start")
        self.batch_worker.progress_signal.connect(self.on_batch_progress)
        self.batch_worker.finished_signal.connect(self.on_batch_finished)
        self.batch_worker.start()

    def stop_all_nodes(self):
        """Stop every node currently matching the active Filter Type / Search
        (i.e. every *visible* row), not the entire lab regardless of filter."""
        node_ids = self.get_visible_node_ids()
        if not node_ids:
            self.log("No nodes match the current filter/search — nothing to stop. Clear the filter to target all nodes.")
            return

        self.log(f"Stopping {len(node_ids)} node(s) matching the current filter/search...")
        self.progress_bar.setValue(0)
        self.batch_worker = NodeBatchWorker(self.eve_client, self.current_lab, node_ids, action="stop")
        self.batch_worker.progress_signal.connect(self.on_batch_progress)
        self.batch_worker.finished_signal.connect(self.on_batch_finished)
        self.batch_worker.start()

    def get_visible_node_ids(self) -> list:
        """Returns node IDs for rows currently visible in the table (i.e. not
        hidden by the Filter Type / Search box)."""
        ids = []
        for row in range(self.tbl_nodes.rowCount()):
            if not self.tbl_nodes.isRowHidden(row):
                nid_item = self.tbl_nodes.item(row, 0)
                if nid_item:
                    ids.append(int(nid_item.text()))
        return ids

    def on_batch_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        self.lbl_progress.setText(msg)
        self.log(msg)

    def on_batch_finished(self, failed_node_ids: list = None):
        failed_node_ids = failed_node_ids or []
        if failed_node_ids:
            self.lbl_progress.setText(f"Batch operation complete — {len(failed_node_ids)} node(s) failed.")
            self.log(f"❌ Batch operation completed with failures — node(s) {failed_node_ids} did not respond as expected.")
            QMessageBox.warning(
                self, "Some Nodes Failed",
                f"{len(failed_node_ids)} node(s) did not start/stop successfully: {failed_node_ids}\n\n"
                f"They may still be booting, out of resources, or have a missing/corrupt image. "
                f"Check their status in the table and try again individually if needed."
            )
        else:
            self.lbl_progress.setText("Batch operation complete!")
            self.log("Batch operation completed.")
        self.refresh_lab()
        QTimer.singleShot(3000, self.refresh_lab)

    def open_node_console_with_row_proto(self, node_id: int, row: int):
        cell_widget = self.tbl_nodes.cellWidget(row, 7)
        if cell_widget and isinstance(cell_widget, QComboBox):
            selected_proto = cell_widget.currentText()
        else:
            selected_proto = "Telnet (Console)"
            
        self.open_telnet_console(node_id, proto_override=selected_proto)

    def open_telnet_console(self, node_id: int, proto_override: str = None):
        proto = proto_override if proto_override else self.cmb_proto.currentText()
        ip = self.txt_ip.text().strip()
        node_info = self.nodes_data.get(str(node_id), {})
        node_url = node_info.get("url", "")
        client = self.cmb_terminal.currentData() or "auto"
        custom_tpl = self.txt_custom_terminal.text()
        putty_path = self.txt_putty_path.text().strip()
        vnc_path = self.txt_vnc_path.text().strip()

        if "HTML5" in proto and node_url:
            full_html5_url = f"http://{ip}{node_url}"
            self.log(f"Opening HTML5 Web Console for Node {node_id}: {full_html5_url}")
            import webbrowser
            webbrowser.open(full_html5_url)
        elif "SSH" in proto:
            try:
                desc = launch_ssh(client, ip, self.txt_user.text().strip(), 22, custom_tpl, putty_path)
                self.log(f"Opening SSH connection to Node {node_id} via [{client}]: {desc}")
            except Exception as e:
                self.log(f"Failed to open SSH console for Node {node_id}: {e}")
                QMessageBox.warning(self, "Terminal Launch Failed", str(e))
        elif "VNC" in proto:
            port = 5900 + int(node_id)
            try:
                desc = launch_vnc(ip, port, vnc_path, custom_tpl if client == "custom" else "")
                self.log(f"Opening VNC connection to Node {node_id}: {desc}")
            except Exception as e:
                self.log(f"Failed to open VNC viewer for Node {node_id} ({ip}:{port}): {e}")
                QMessageBox.warning(self, "VNC Launch Failed", str(e))
        else:
            # Default Telnet Console (Port 32768 + node_id)
            port = 32768 + int(node_id)
            try:
                desc = launch_telnet(client, ip, port, custom_tpl, putty_path)
                self.log(f"Opening Telnet Console for Node {node_id} via [{client}]: {desc}")
            except Exception as e:
                self.log(f"Local terminal launch failed ({e}). Opening HTML5 console fallback...")
                if node_url:
                    import webbrowser
                    webbrowser.open(f"http://{ip}{node_url}")
                else:
                    QMessageBox.warning(self, "Terminal Launch Failed", str(e))

    def open_capture_dialog(self, preselect_node_id: int = None):
        """Open the Wireshark packet capture dialog, prefilled with the
        same root SSH credentials used by the Image Manager tab, if set."""
        default_host = getattr(self, "txt_ssh_host", None)
        host = default_host.text().strip() if default_host and default_host.text().strip() else self.txt_ip.text().strip()
        ssh_user = self.txt_ssh_user.text().strip() if hasattr(self, "txt_ssh_user") and self.txt_ssh_user.text().strip() else "root"
        ssh_pass = self.txt_ssh_pass.text() if hasattr(self, "txt_ssh_pass") else ""
        ssh_port = self.spin_ssh_port.value() if hasattr(self, "spin_ssh_port") else 22

        dialog = CaptureDialog(self, host, ssh_user, ssh_pass, ssh_port)
        dialog.exec()

    def open_ping_dialog(self):
        """Built-in ping tester, prefilled with the EVE-NG server IP."""
        dlg = PingDialog(self, default_target=self.txt_ip.text().strip())
        dlg.exec()

    def open_edit_node_dialog(self, node_id: int):
        node_info = self.nodes_data.get(str(node_id))
        if not node_info:
            QMessageBox.warning(self, "Node Not Found", "Couldn't find this node's current data — try refreshing the lab first.")
            return

        dialog = EditNodeDialog(self, node_info)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        changes = dialog.get_changed_fields()
        if not changes:
            self.log("No changes made.")
            return

        self.log(f"Updating node {node_id} ({node_info.get('name')}): {changes}")

        def _run():
            return self.eve_client.update_node(self.current_lab, node_id, changes)

        self._edit_node_worker = WorkerThread(_run)

        def _done(status, result):
            if status == "success" and result:
                self.log(f"✅ Node {node_id} updated successfully: {changes}")
                self.refresh_lab()
            else:
                msg = result if status == "error" else "EVE-NG rejected the change (node may need to be stopped first)."
                self.log(f"❌ Failed to update node {node_id}: {msg}")
                QMessageBox.warning(self, "Update Failed", str(msg))

        self._edit_node_worker.finished_signal.connect(_done)
        self._edit_node_worker.start()

    # ------------------ DEVICE GROUPS ------------------
    def _groups_settings_key(self) -> str:
        return f"lab:{self.current_lab or ''}"

    def _load_groups(self) -> dict:
        raw = QSettings("EveNGLabAutomation", "NodeGroups").value(
            self._groups_settings_key(), "", type=str)
        try:
            data = json.loads(raw) if raw else {}
            return {str(k): [int(i) for i in v] for k, v in data.items()}
        except (ValueError, TypeError):
            return {}

    def _save_groups(self, groups: dict):
        QSettings("EveNGLabAutomation", "NodeGroups").setValue(
            self._groups_settings_key(), json.dumps(groups))

    def populate_group_combo(self):
        groups = self._load_groups()
        self.cmb_node_groups.blockSignals(True)
        self.cmb_node_groups.clear()
        for name in sorted(groups):
            count = len(groups[name])
            live = sum(1 for i in groups[name] if str(i) in self.nodes_data)
            suffix = "" if live == count else f", {live} still in lab"
            self.cmb_node_groups.addItem(f"{name} ({count}{suffix})", name)
        self.cmb_node_groups.blockSignals(False)

    def get_selected_node_ids(self) -> list:
        """IDs of the rows currently selected in the nodes table."""
        ids = []
        for index in self.tbl_nodes.selectionModel().selectedRows():
            item = self.tbl_nodes.item(index.row(), 0)
            if item:
                try:
                    ids.append(int(item.text()))
                except ValueError:
                    pass
        return ids

    def on_group_save(self):
        ids = self.get_selected_node_ids()
        if not ids:
            QMessageBox.information(
                self, "Nothing Selected",
                "Select one or more rows in the table first, then save them as a group.")
            return
        self._prompt_and_save_group(ids)

    def _prompt_and_save_group(self, ids: list):
        suggested = f"Group {len(self._load_groups()) + 1}"
        name, ok = QInputDialog.getText(
            self, "Save Device Group",
            f"Name for these {len(ids)} device(s):", text=suggested)
        if ok and name.strip():
            self._write_group(name.strip(), ids)

    def _write_group(self, name: str, ids: list):
        groups = self._load_groups()
        if name in groups:
            confirm = QMessageBox.question(
                self, "Overwrite Group",
                f"A group named '{name}' already exists. Replace it with the current selection?")
            if confirm != QMessageBox.StandardButton.Yes:
                return
        groups[name] = list(ids)
        self._save_groups(groups)
        self.populate_group_combo()
        self.populate_nodes_table(self.nodes_data)  # refresh the Groups column
        self.log(f"💾 Saved group '{name}' with device(s): {sorted(ids)}")

    def _build_topology_group_actions(self, ids: list, menu):
        """Appends group commands (save/add/remove) to the topology node
        context menu; returns [(action, handler)] for dispatch."""
        actions = []

        act_save = menu.addAction(f"💾 Save {len(ids)} Selected as Group...")
        actions.append((act_save, lambda: self._prompt_and_save_group(list(ids))))

        groups = self._load_groups()

        add_menu = menu.addMenu("➕ Add Selected to Group")
        if not groups:
            a = add_menu.addAction("(no groups yet)")
            a.setEnabled(False)
        else:
            for gname in sorted(groups):
                act = add_menu.addAction(f"📁 {gname}")
                actions.append((act, lambda checked=False, g=gname:
                                self._add_ids_to_group(g, ids)))

        hits = {g: [i for i in gids if i in ids] for g, gids in groups.items()
                if any(i in ids for i in gids)}
        rm_menu = menu.addMenu("➖ Remove Selected from Group")
        if not hits:
            a = rm_menu.addAction("(selection not in any group)")
            a.setEnabled(False)
        else:
            for gname, hit in sorted(hits.items()):
                act = rm_menu.addAction(f"📁 {gname}  ({len(hit)})")
                actions.append((act, lambda checked=False, g=gname, h=hit:
                                self._remove_ids_from_group(g, h)))
        return actions

    def _add_ids_to_group(self, gname: str, ids: list):
        groups = self._load_groups()
        merged = sorted(set(groups.get(gname, [])) | set(int(i) for i in ids))
        groups[gname] = merged
        self._save_groups(groups)
        self.populate_group_combo()
        self.populate_nodes_table(self.nodes_data)
        self.log(f"📁 Added {len(ids)} device(s) to group '{gname}' "
                 f"(now {len(merged)} members).")

    def on_group_delete(self):
        name = self.cmb_node_groups.currentData()
        if not name:
            QMessageBox.information(self, "No Group Selected", "Pick a group to delete first.")
            return
        confirm = QMessageBox.question(
            self, "Delete Group",
            f"Delete group '{name}'? (Devices themselves are not touched.)")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        groups = self._load_groups()
        groups.pop(name, None)
        self._save_groups(groups)
        self.populate_group_combo()
        self.populate_nodes_table(self.nodes_data)  # refresh the Groups column
        self.log(f"🗑 Deleted group '{name}'.")

    def _run_group_action(self, start: bool):
        name = self.cmb_node_groups.currentData()
        if not name:
            QMessageBox.information(self, "No Group Selected", "Pick a group first.")
            return
        stored = self._load_groups().get(name, [])
        ids = [i for i in stored if str(i) in self.nodes_data]
        skipped = len(stored) - len(ids)
        if not ids:
            QMessageBox.warning(
                self, "Group Is Empty",
                f"None of the devices saved in '{name}' exist in this lab anymore.")
            return
        verb = "Starting" if start else "Stopping"
        extra = f" ({skipped} no longer in lab — skipped)" if skipped else ""
        self.log(f"{verb} group '{name}': {ids}{extra}")
        if start:
            self.start_selected_nodes(ids)
        else:
            self.stop_selected_nodes(ids)

    # ------------------ TREE VIEW (hierarchy) ------------------
    def populate_nodes_tree(self):
        """Renders the hierarchy: each saved group is a 📁 folder with its
        member devices nested underneath; ungrouped devices stay top-level."""
        self.tree_nodes.clear()
        nodes = self.nodes_data or {}
        groups = self._load_groups()

        member_ids = set()
        for name in sorted(groups):
            ids = groups[name]
            parent = QTreeWidgetItem([f"📁 {name}  ({len(ids)})"])
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            parent.setForeground(0, QColor("#7dd3fc"))
            parent.setData(0, Qt.ItemDataRole.UserRole, ("group", name))
            live = 0
            for nid in sorted(ids):
                info = nodes.get(str(nid))
                if not info:
                    child = QTreeWidgetItem([f"   ⚠ ID {nid} (not in lab)"])
                    child.setForeground(0, QColor("#94a3b8"))
                    parent.addChild(child)
                    continue
                live += 1
                parent.addChild(self._make_device_item(info))
            parent.setText(0, f"📁 {name}  ({live})")
            self.tree_nodes.addTopLevelItem(parent)
            member_ids.update(str(i) for i in ids)

        # Ungrouped devices at top level
        def sort_key(pair):
            try:
                return int(pair[0])
            except ValueError:
                return 10 ** 9
        for nid_key, info in sorted(nodes.items(), key=sort_key):
            if nid_key in member_ids:
                continue
            self.tree_nodes.addTopLevelItem(self._make_device_item(info))

        self.tree_nodes.expandAll()

    def _make_device_item(self, info: dict) -> QTreeWidgetItem:
        _color, emoji = self._classify_device(info)
        nid = info.get("id")
        item = QTreeWidgetItem([f"{emoji} {info.get('name', f'Node-{nid}')}  (ID {nid})"])
        item.setData(0, Qt.ItemDataRole.UserRole, ("device", int(nid)))
        try:
            running = int(str(info.get("status", 0)).strip() or 0) in (1, 2)
        except (TypeError, ValueError):
            running = False
        item.setForeground(0, QColor("#22c55e" if running else "#cbd5e1"))
        item.setToolTip(0, "Double-click: open console · Right-click: actions")
        return item

    def show_nodes_table_view(self):
        self.nodes_view_stack.setCurrentIndex(0)
        self.btn_view_table.setChecked(True)
        self.btn_view_tree.setChecked(False)

    def show_nodes_tree_view(self):
        self.populate_nodes_tree()
        self.nodes_view_stack.setCurrentIndex(1)
        self.btn_view_table.setChecked(False)
        self.btn_view_tree.setChecked(True)

    def _on_tree_item_double_clicked(self, item, _col):
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if payload and payload[0] == "device":
            self.open_telnet_console(payload[1])

    def show_tree_context_menu(self, pos):
        item = self.tree_nodes.itemAt(pos)
        menu = QMenu(self)
        if item is None:
            act_refresh = menu.addAction("🔄 Refresh Tree")
            chosen = menu.exec(self.tree_nodes.viewport().mapToGlobal(pos))
            if chosen is act_refresh:
                self.refresh_lab()
            return

        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not payload:
            return
        kind, value = payload

        if kind == "group":
            act_start = menu.addAction(f"▶ Start Group '{value}'")
            act_stop = menu.addAction(f"⏹ Stop Group '{value}'")
            menu.addSeparator()
            act_refresh = menu.addAction("🔄 Refresh Tree")
            chosen = menu.exec(self.tree_nodes.viewport().mapToGlobal(pos))
            if chosen is None:
                return
            idx = self.cmb_node_groups.findData(value)
            if idx >= 0:
                self.cmb_node_groups.setCurrentIndex(idx)
            if chosen is act_start:
                self._run_group_action(start=True)
            elif chosen is act_stop:
                self._run_group_action(start=False)
            elif chosen is act_refresh:
                self.refresh_lab()
        else:
            node_id = value
            name = item.text(0).split("  (ID")[0]
            act_con = menu.addAction(f"💻 Open Console ({name})")
            act_start = menu.addAction("▶ Start")
            act_stop = menu.addAction("⏹ Stop")

            parent = item.parent()
            parent_payload = parent.data(0, Qt.ItemDataRole.UserRole) if parent else None
            act_rm = None
            if parent_payload and parent_payload[0] == "group":
                menu.addSeparator()
                act_rm = menu.addAction(f"➖ Remove from '{parent_payload[1]}'")

            chosen = menu.exec(self.tree_nodes.viewport().mapToGlobal(pos))
            if chosen is None:
                return
            if chosen is act_con:
                self.open_telnet_console(node_id)
            elif chosen is act_start:
                self.start_single_node(node_id)
            elif chosen is act_stop:
                self.stop_single_node(node_id)
            elif act_rm is not None and chosen is act_rm:
                self._remove_ids_from_group(parent_payload[1], [node_id])

    # ------------------ TAB 2: ROUTER-ON-A-STICK ------------------
    def setup_ros_tab(self):
        layout = QHBoxLayout(self.tab_ros)

        # Left Form
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        top_form_group = QGroupBox("Router-on-a-Stick Configuration")
        top_form = QFormLayout(top_form_group)

        self.cmb_ros_router = QComboBox()
        top_form.addRow("Select Target Router:", self.cmb_ros_router)

        intf_row = QHBoxLayout()
        self.cmb_ros_main_intf = QComboBox()
        self.cmb_ros_main_intf.setEditable(True)
        self.cmb_ros_main_intf.addItem("FastEthernet0/0")
        intf_row.addWidget(self.cmb_ros_main_intf)
        self.btn_ros_detect = QPushButton("🔍 Detect Interfaces")
        self.btn_ros_detect.setToolTip("Connects to the selected router's console and runs 'show ip interface brief' to list real interfaces.")
        self.btn_ros_detect.clicked.connect(self.ros_detect_interfaces)
        intf_row.addWidget(self.btn_ros_detect)
        top_form.addRow("Physical Interface:", intf_row)

        left_layout.addWidget(top_form_group)

        # --- Customizable VLAN list ---
        vlan_group = QGroupBox("VLANs (add as many as you need)")
        vlan_group_layout = QVBoxLayout(vlan_group)

        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("VLAN ID"), 1)
        header_row.addWidget(QLabel("Gateway IP"), 2)
        header_row.addWidget(QLabel("Subnet Mask"), 2)
        header_row.addWidget(QLabel(""), 0)  # spacer for remove button column
        vlan_group_layout.addLayout(header_row)

        self.ros_vlan_container = QVBoxLayout()
        vlan_group_layout.addLayout(self.ros_vlan_container)

        self.ros_vlan_rows = []
        for vid, ip in [(10, "192.168.10.1"), (20, "192.168.20.1"), (30, "192.168.30.1")]:
            self.ros_add_vlan_row(vid, ip)

        btn_add_vlan = QPushButton("➕ Add VLAN")
        btn_add_vlan.clicked.connect(lambda: self.ros_add_vlan_row())
        vlan_group_layout.addWidget(btn_add_vlan)

        left_layout.addWidget(vlan_group)

        btn_gen_ros = QPushButton("Generate CLI Script")
        btn_gen_ros.clicked.connect(self.generate_ros_script)
        left_layout.addWidget(btn_gen_ros)

        btn_push_ros = QPushButton("Push Config to Router Console")
        btn_push_ros.setObjectName("btnPrimary")
        btn_push_ros.clicked.connect(self.push_ros_config)
        left_layout.addWidget(btn_push_ros)

        left_layout.addStretch()

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left_widget)
        layout.addWidget(left_scroll, 1)

        # Right Preview Box
        preview_group = QGroupBox("Generated Cisco IOS Commands Preview")
        preview_layout = QVBoxLayout(preview_group)

        self.txt_ros_preview = QTextEdit()
        self.txt_ros_preview.setFont(QFont("Consolas", 10))
        preview_layout.addWidget(self.txt_ros_preview)

        layout.addWidget(preview_group, 2)

    def ros_add_vlan_row(self, vlan_id: int = None, ip: str = "", mask: str = "255.255.255.0"):
        """Adds one removable VLAN row (ID + Gateway IP + Subnet Mask) to the ROS tab."""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)

        spin_vlan_id = QSpinBox()
        spin_vlan_id.setRange(1, 4094)
        if vlan_id is None:
            # Suggest the next multiple of 10 above the highest existing VLAN ID.
            existing = [r["vlan_id"].value() for r in self.ros_vlan_rows] if hasattr(self, "ros_vlan_rows") else []
            vlan_id = (max(existing) + 10) if existing else 10
        spin_vlan_id.setValue(vlan_id)
        row_layout.addWidget(spin_vlan_id, 1)

        txt_ip = QLineEdit(ip)
        txt_ip.setPlaceholderText("e.g. 192.168.10.1")
        row_layout.addWidget(txt_ip, 2)

        txt_mask = QLineEdit(mask)
        row_layout.addWidget(txt_mask, 2)

        btn_remove = QPushButton("✕")
        btn_remove.setFixedWidth(32)
        btn_remove.setToolTip("Remove this VLAN")
        row_layout.addWidget(btn_remove, 0)

        self.ros_vlan_container.addWidget(row_widget)
        row_entry = {"widget": row_widget, "vlan_id": spin_vlan_id, "ip": txt_ip, "mask": txt_mask}
        self.ros_vlan_rows.append(row_entry)

        def _remove():
            self.ros_vlan_container.removeWidget(row_widget)
            row_widget.deleteLater()
            self.ros_vlan_rows.remove(row_entry)

        btn_remove.clicked.connect(_remove)

    def ros_detect_interfaces(self):
        node_id = self.cmb_ros_router.currentData()
        if not node_id:
            QMessageBox.warning(self, "No Router Selected", "Select a target router first.")
            return

        ip = self.txt_ip.text().strip()
        port = 32768 + int(node_id)
        self.btn_ros_detect.setEnabled(False)
        self.log(f"Detecting interfaces on router (node {node_id})...")

        def _run():
            mgr = NodeConsoleManager(ip, port)
            return mgr.send_commands(["enable", "show ip interface brief"])

        self._ros_detect_worker = WorkerThread(_run)

        def _done(status, result):
            self.btn_ros_detect.setEnabled(True)
            if status != "success":
                self.log(f"Interface detection failed: {result}")
                QMessageBox.warning(self, "Detection Failed", str(result))
                return
            interfaces = parse_show_ip_interface_brief(result)
            if not interfaces:
                self.log("No interfaces found in console output — the router may be stopped or still booting.")
                QMessageBox.information(self, "No Interfaces Found",
                                         "Couldn't parse any interfaces from the console output. "
                                         "Make sure the router is running and try again.")
                return
            current_text = self.cmb_ros_main_intf.currentText()
            self.cmb_ros_main_intf.clear()
            self.cmb_ros_main_intf.addItems(interfaces)
            if current_text in interfaces:
                self.cmb_ros_main_intf.setCurrentText(current_text)
            self.log(f"Found {len(interfaces)} interface(s): {', '.join(interfaces)}")

        self._ros_detect_worker.finished_signal.connect(_done)
        self._ros_detect_worker.start()

    def populate_ros_node_combos(self, nodes: dict):
        self.cmb_ros_router.clear()
        self.cmb_vlan_sw.clear()
        self.list_cli_devices.clear()
        self.cmb_fw_device.clear()
        self.cmb_route_router.clear()

        for nid, info in nodes.items():
            name = info.get("name", f"Node-{nid}")
            item_str = f"{name} (ID: {nid})"

            list_item = QListWidgetItem(item_str)
            list_item.setData(Qt.ItemDataRole.UserRole, nid)
            list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            list_item.setCheckState(Qt.CheckState.Unchecked)
            self.list_cli_devices.addItem(list_item)

            # Every node is selectable for the Firewall Wizard, since pfSense/
            # OPNsense/FortiGate template naming varies too much to filter reliably.
            self.cmb_fw_device.addItem(item_str, nid)

            template = info.get("template", "").lower()
            if "3725" in template or "router" in template or "iol" in template:
                self.cmb_ros_router.addItem(item_str, nid)
                self.cmb_vlan_sw.addItem(item_str, nid)
                self.cmb_route_router.addItem(item_str, nid)

    def generate_ros_script(self):
        main_intf = self.cmb_ros_main_intf.currentText().strip()
        if not main_intf:
            QMessageBox.warning(self, "Missing Interface", "Enter or detect a physical interface first.")
            return

        vlan_cfgs = []
        seen_ids = set()
        for row in self.ros_vlan_rows:
            vid = row["vlan_id"].value()
            ip = row["ip"].text().strip()
            mask = row["mask"].text().strip()
            if not ip:
                continue
            if vid in seen_ids:
                QMessageBox.warning(self, "Duplicate VLAN ID", f"VLAN {vid} is listed more than once — remove the duplicate first.")
                return
            seen_ids.add(vid)
            vlan_cfgs.append({"vlan_id": vid, "ip": ip, "subnet": mask or "255.255.255.0"})

        if not vlan_cfgs:
            QMessageBox.warning(self, "No VLANs", "Add at least one VLAN with a gateway IP first.")
            return

        cmds = generate_router_on_stick_config(main_intf, vlan_cfgs)
        self.txt_ros_preview.setText("\n".join(cmds))

    def push_ros_config(self):
        self.generate_ros_script()
        cmds = self.txt_ros_preview.toPlainText().splitlines()
        if not cmds:
            return
        node_id = self.cmb_ros_router.currentData()

        if not node_id:
            QMessageBox.warning(self, "No Router Selected", "Please select a target router.")
            return

        ip = self.txt_ip.text().strip()
        port = 32768 + int(node_id)

        self.log(f"Pushing Router-on-a-Stick config to {ip}:{port}...")
        mgr = NodeConsoleManager(ip, port)
        output = mgr.send_commands(cmds)
        self.txt_ros_preview.setText(f"--- EXECUTED CLI OUTPUT ---\n{output}")
        self.log("Push complete.")

    # ------------------ TAB 3: SWITCH VLAN ------------------
    def setup_vlan_tab(self):
        layout = QHBoxLayout(self.tab_vlan)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        top_form_group = QGroupBox("Switch VLAN & 802.1Q Trunk Setup")
        top_form = QFormLayout(top_form_group)

        self.cmb_vlan_sw = QComboBox()
        top_form.addRow("Target Switch:", self.cmb_vlan_sw)

        trunk_row = QHBoxLayout()
        self.txt_trunks = QLineEdit("Ethernet0/0")
        self.txt_trunks.setPlaceholderText("Comma-separated, e.g. Ethernet0/0, Ethernet0/3")
        trunk_row.addWidget(self.txt_trunks)
        self.btn_vlan_detect = QPushButton("🔍 Detect Interfaces")
        self.btn_vlan_detect.setToolTip("Connects to the selected switch's console and runs 'show ip interface brief' to list real interfaces.")
        self.btn_vlan_detect.clicked.connect(self.vlan_detect_interfaces)
        trunk_row.addWidget(self.btn_vlan_detect)
        top_form.addRow("Trunk Interfaces:", trunk_row)

        self.lbl_vlan_detected = QLabel("Click 'Detect Interfaces' to list the switch's real ports here.")
        self.lbl_vlan_detected.setWordWrap(True)
        self.lbl_vlan_detected.setObjectName("muted")
        top_form.addRow("", self.lbl_vlan_detected)

        left_layout.addWidget(top_form_group)

        # --- Customizable VLAN list (same pattern as Router-on-a-Stick tab) ---
        vlan_group = QGroupBox("VLANs (add as many as you need)")
        vlan_group_layout = QVBoxLayout(vlan_group)

        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("VLAN ID"), 1)
        header_row.addWidget(QLabel("Access Ports (comma-separated)"), 3)
        header_row.addWidget(QLabel(""), 0)
        vlan_group_layout.addLayout(header_row)

        self.vlan_container = QVBoxLayout()
        vlan_group_layout.addLayout(self.vlan_container)

        self.vlan_rows = []
        for vid, ports in [(10, "Ethernet0/1"), (20, "Ethernet0/2")]:
            self.vlan_add_row(vid, ports)

        btn_add_vlan = QPushButton("➕ Add VLAN")
        btn_add_vlan.clicked.connect(lambda: self.vlan_add_row())
        vlan_group_layout.addWidget(btn_add_vlan)

        left_layout.addWidget(vlan_group)

        btn_gen_vlan = QPushButton("Generate Switch Script")
        btn_gen_vlan.clicked.connect(self.generate_vlan_script)
        left_layout.addWidget(btn_gen_vlan)

        btn_push_vlan = QPushButton("Push Config to Switch Console")
        btn_push_vlan.setObjectName("btnPrimary")
        btn_push_vlan.clicked.connect(self.push_vlan_config)
        left_layout.addWidget(btn_push_vlan)

        left_layout.addStretch()

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left_widget)
        layout.addWidget(left_scroll, 1)

        preview_group = QGroupBox("Generated Switch Commands Preview")
        preview_layout = QVBoxLayout(preview_group)

        self.txt_vlan_preview = QTextEdit()
        self.txt_vlan_preview.setFont(QFont("Consolas", 10))
        preview_layout.addWidget(self.txt_vlan_preview)

        layout.addWidget(preview_group, 2)

    def vlan_add_row(self, vlan_id: int = None, ports: str = ""):
        """Adds one removable VLAN row (ID + comma-separated access ports) to the Switch VLAN tab."""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)

        spin_vlan_id = QSpinBox()
        spin_vlan_id.setRange(1, 4094)
        if vlan_id is None:
            existing = [r["vlan_id"].value() for r in self.vlan_rows] if hasattr(self, "vlan_rows") else []
            vlan_id = (max(existing) + 10) if existing else 10
        spin_vlan_id.setValue(vlan_id)
        row_layout.addWidget(spin_vlan_id, 1)

        txt_ports = QLineEdit(ports)
        txt_ports.setPlaceholderText("e.g. Ethernet0/1, Ethernet0/4")
        row_layout.addWidget(txt_ports, 3)

        btn_remove = QPushButton("✕")
        btn_remove.setFixedWidth(32)
        btn_remove.setToolTip("Remove this VLAN")
        row_layout.addWidget(btn_remove, 0)

        self.vlan_container.addWidget(row_widget)
        row_entry = {"widget": row_widget, "vlan_id": spin_vlan_id, "ports": txt_ports}
        self.vlan_rows.append(row_entry)

        def _remove():
            self.vlan_container.removeWidget(row_widget)
            row_widget.deleteLater()
            self.vlan_rows.remove(row_entry)

        btn_remove.clicked.connect(_remove)

    def vlan_detect_interfaces(self):
        node_id = self.cmb_vlan_sw.currentData()
        if not node_id:
            QMessageBox.warning(self, "No Switch Selected", "Select a target switch first.")
            return

        ip = self.txt_ip.text().strip()
        port = 32768 + int(node_id)
        self.btn_vlan_detect.setEnabled(False)
        self.log(f"Detecting interfaces on switch (node {node_id})...")

        def _run():
            mgr = NodeConsoleManager(ip, port)
            return mgr.send_commands(["enable", "show ip interface brief"])

        self._vlan_detect_worker = WorkerThread(_run)

        def _done(status, result):
            self.btn_vlan_detect.setEnabled(True)
            if status != "success":
                self.log(f"Interface detection failed: {result}")
                QMessageBox.warning(self, "Detection Failed", str(result))
                return
            interfaces = parse_show_ip_interface_brief(result)
            if not interfaces:
                self.log("No interfaces found — the switch may be stopped or still booting.")
                QMessageBox.information(self, "No Interfaces Found",
                                         "Couldn't parse any interfaces from the console output. "
                                         "Make sure the switch is running and try again.")
                return
            self.lbl_vlan_detected.setText("Available interfaces: " + ", ".join(interfaces))
            self.lbl_vlan_detected.setObjectName("accentText")
            self.log(f"Found {len(interfaces)} interface(s): {', '.join(interfaces)}")

        self._vlan_detect_worker.finished_signal.connect(_done)
        self._vlan_detect_worker.start()

    def generate_vlan_script(self):
        trunks = [i.strip() for i in self.txt_trunks.text().split(",") if i.strip()]
        if not trunks:
            QMessageBox.warning(self, "Missing Trunk Interface", "Enter at least one trunk interface first.")
            return

        access_ports = []
        vlan_ids = []
        seen_ids = set()
        for row in self.vlan_rows:
            vid = row["vlan_id"].value()
            ports_text = row["ports"].text().strip()
            if vid in seen_ids:
                QMessageBox.warning(self, "Duplicate VLAN ID", f"VLAN {vid} is listed more than once — remove the duplicate first.")
                return
            seen_ids.add(vid)
            vlan_ids.append(vid)
            for p in ports_text.split(","):
                if p.strip():
                    access_ports.append({"interface": p.strip(), "vlan_id": vid})

        if not vlan_ids:
            QMessageBox.warning(self, "No VLANs", "Add at least one VLAN first.")
            return

        cmds = generate_switch_vlan_config(trunks, access_ports, vlan_ids)
        self.txt_vlan_preview.setText("\n".join(cmds))

    def push_vlan_config(self):
        self.generate_vlan_script()
        cmds = self.txt_vlan_preview.toPlainText().splitlines()
        if not cmds:
            return
        node_id = self.cmb_vlan_sw.currentData()

        if not node_id:
            QMessageBox.warning(self, "No Switch Selected", "Please select a target switch.")
            return

        ip = self.txt_ip.text().strip()
        port = 32768 + int(node_id)

        self.log(f"Pushing Switch VLAN config to {ip}:{port}...")
        mgr = NodeConsoleManager(ip, port)
        output = mgr.send_commands(cmds)
        self.txt_vlan_preview.setText(f"--- EXECUTED CLI OUTPUT ---\n{output}")
        self.log("Push complete.")

    # ------------------ TAB 3b: ROUTING PROTOCOL CONFIG ------------------
    def setup_routing_tab(self):
        layout = QVBoxLayout(self.tab_routing)

        info = QLabel(
            "Generate and push routing configuration to any router in the lab. Every list below "
            "(networks, routes, neighbors) is fully customizable — add or remove as many entries as "
            "you need with the ➕ / ✕ buttons."
        )
        info.setWordWrap(True)
        info.setObjectName("muted")
        layout.addWidget(info)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Target Router:"))
        self.cmb_route_router = QComboBox()
        self.cmb_route_router.setMinimumWidth(220)
        top_row.addWidget(self.cmb_route_router)

        self.btn_route_detect = QPushButton("🔍 Detect Interfaces")
        self.btn_route_detect.setToolTip("Connects to the selected router's console and lists its real interfaces — handy for filling in network/passive-interface fields.")
        self.btn_route_detect.clicked.connect(self.route_detect_interfaces)
        top_row.addWidget(self.btn_route_detect)
        top_row.addStretch()
        layout.addLayout(top_row)

        self.lbl_route_detected = QLabel("Click 'Detect Interfaces' to list the router's real interfaces here.")
        self.lbl_route_detected.setWordWrap(True)
        self.lbl_route_detected.setObjectName("muted")
        layout.addWidget(self.lbl_route_detected)

        self.routing_subtabs = QTabWidget()
        self.setup_static_route_subtab()
        self.setup_ospf_subtab()
        self.setup_eigrp_subtab()
        self.setup_rip_subtab()
        self.setup_bgp_subtab()
        self.setup_acl_subtab()
        self.setup_nat_subtab()
        self.setup_pat_subtab()
        self.setup_etherchannel_subtab()
        self.setup_standby_subtab()
        self.setup_aaa_subtab()
        layout.addWidget(self.routing_subtabs, 1)

        btn_row = QHBoxLayout()
        btn_gen_route = QPushButton("Generate CLI Script")
        btn_gen_route.clicked.connect(self.generate_routing_script)
        btn_row.addWidget(btn_gen_route)

        btn_push_route = QPushButton("Push Config to Router Console")
        btn_push_route.setObjectName("btnPrimary")
        btn_push_route.clicked.connect(self.push_routing_config)
        btn_row.addWidget(btn_push_route)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addWidget(QLabel("Generated Commands Preview:"))
        self.txt_route_preview = QTextEdit()
        self.txt_route_preview.setFont(QFont("Consolas", 10))
        self.txt_route_preview.setMaximumHeight(200)
        layout.addWidget(self.txt_route_preview)

    def route_detect_interfaces(self):
        node_id = self.cmb_route_router.currentData()
        if not node_id:
            QMessageBox.warning(self, "No Router Selected", "Select a target router first.")
            return

        ip = self.txt_ip.text().strip()
        port = 32768 + int(node_id)
        self.btn_route_detect.setEnabled(False)
        self.log(f"Detecting interfaces on router (node {node_id})...")

        def _run():
            mgr = NodeConsoleManager(ip, port)
            return mgr.send_commands(["enable", "show ip interface brief"])

        self._route_detect_worker = WorkerThread(_run)

        def _done(status, result):
            self.btn_route_detect.setEnabled(True)
            if status != "success":
                self.log(f"Interface detection failed: {result}")
                QMessageBox.warning(self, "Detection Failed", str(result))
                return
            interfaces = parse_show_ip_interface_brief(result)
            if not interfaces:
                self.log("No interfaces found — the router may be stopped or still booting.")
                return
            self.lbl_route_detected.setText("Available interfaces: " + ", ".join(interfaces))
            self.lbl_route_detected.setObjectName("accentText")
            self.log(f"Found {len(interfaces)} interface(s): {', '.join(interfaces)}")

        self._route_detect_worker.finished_signal.connect(_done)
        self._route_detect_worker.start()

    # ---------- Generic dynamic-row helper ----------
    def _add_dynamic_row(self, container_layout, rows_list, fields: list, on_remove=None):
        """
        Adds one removable row of QLineEdit/QWidget fields to `container_layout`,
        tracking it in `rows_list`. `fields` is a list of (key, widget) tuples
        already constructed by the caller. Returns the row's entry dict.
        """
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)

        entry = {"widget": row_widget}
        for key, widget, stretch in fields:
            row_layout.addWidget(widget, stretch)
            entry[key] = widget

        btn_remove = QPushButton("✕")
        btn_remove.setFixedWidth(32)
        row_layout.addWidget(btn_remove, 0)

        container_layout.addWidget(row_widget)
        rows_list.append(entry)

        def _remove():
            container_layout.removeWidget(row_widget)
            row_widget.deleteLater()
            rows_list.remove(entry)
            if on_remove:
                on_remove()

        btn_remove.clicked.connect(_remove)
        return entry

    # ---------- Static Routes sub-tab ----------
    def setup_static_route_subtab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        header = QHBoxLayout()
        header.addWidget(QLabel("Network"), 3)
        header.addWidget(QLabel("Mask"), 3)
        header.addWidget(QLabel("Next-Hop"), 3)
        header.addWidget(QLabel("Distance"), 1)
        header.addWidget(QLabel("Name"), 2)
        layout.addLayout(header)

        self.static_route_container = QVBoxLayout()
        layout.addLayout(self.static_route_container)
        self.static_route_rows = []

        btn_add = QPushButton("➕ Add Static Route")
        btn_add.clicked.connect(lambda: self.static_route_add_row())
        layout.addWidget(btn_add)
        layout.addStretch()

        self.static_route_add_row("10.0.0.0", "255.255.255.0", "192.168.1.1")

        self.routing_subtabs.addTab(tab, "Static")

    def static_route_add_row(self, network="", mask="255.255.255.0", next_hop="", distance="", name=""):
        txt_net = QLineEdit(network)
        txt_mask = QLineEdit(mask)
        txt_hop = QLineEdit(next_hop)
        txt_hop.setPlaceholderText("Next-hop IP")
        txt_dist = QLineEdit(distance)
        txt_dist.setPlaceholderText("(opt)")
        txt_name = QLineEdit(name)
        txt_name.setPlaceholderText("(opt)")
        self._add_dynamic_row(
            self.static_route_container, self.static_route_rows,
            [("network", txt_net, 3), ("mask", txt_mask, 3), ("next_hop", txt_hop, 3),
             ("distance", txt_dist, 1), ("name", txt_name, 2)]
        )

    # ---------- OSPF sub-tab ----------
    def setup_ospf_subtab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()
        self.txt_ospf_pid = QLineEdit("1")
        form.addRow("Process ID:", self.txt_ospf_pid)
        self.txt_ospf_rid = QLineEdit()
        self.txt_ospf_rid.setPlaceholderText("(optional) e.g. 1.1.1.1")
        form.addRow("Router ID:", self.txt_ospf_rid)
        self.txt_ospf_passive = QLineEdit()
        self.txt_ospf_passive.setPlaceholderText("Comma-separated, e.g. GigabitEthernet0/0")
        form.addRow("Passive Interfaces:", self.txt_ospf_passive)
        self.chk_ospf_default_orig = QCheckBox("Advertise default route (default-information originate)")
        form.addRow("", self.chk_ospf_default_orig)
        layout.addLayout(form)

        header = QHBoxLayout()
        header.addWidget(QLabel("Network"), 3)
        header.addWidget(QLabel("Wildcard Mask"), 3)
        header.addWidget(QLabel("Area"), 1)
        layout.addLayout(header)

        self.ospf_network_container = QVBoxLayout()
        layout.addLayout(self.ospf_network_container)
        self.ospf_network_rows = []

        btn_add = QPushButton("➕ Add Network")
        btn_add.clicked.connect(lambda: self.ospf_network_add_row())
        layout.addWidget(btn_add)
        layout.addStretch()

        self.ospf_network_add_row("192.168.1.0", "0.0.0.255", "0")

        self.routing_subtabs.addTab(tab, "OSPF")

    def ospf_network_add_row(self, network="", wildcard="0.0.0.255", area="0"):
        txt_net = QLineEdit(network)
        txt_wild = QLineEdit(wildcard)
        txt_area = QLineEdit(area)
        self._add_dynamic_row(
            self.ospf_network_container, self.ospf_network_rows,
            [("network", txt_net, 3), ("wildcard", txt_wild, 3), ("area", txt_area, 1)]
        )

    # ---------- EIGRP sub-tab ----------
    def setup_eigrp_subtab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()
        self.txt_eigrp_as = QLineEdit("100")
        form.addRow("AS Number:", self.txt_eigrp_as)
        self.txt_eigrp_passive = QLineEdit()
        self.txt_eigrp_passive.setPlaceholderText("Comma-separated, e.g. GigabitEthernet0/0")
        form.addRow("Passive Interfaces:", self.txt_eigrp_passive)
        self.chk_eigrp_auto_summary = QCheckBox("Disable auto-summary (recommended)")
        self.chk_eigrp_auto_summary.setChecked(True)
        form.addRow("", self.chk_eigrp_auto_summary)
        layout.addLayout(form)

        header = QHBoxLayout()
        header.addWidget(QLabel("Network"), 3)
        header.addWidget(QLabel("Wildcard Mask (optional)"), 3)
        layout.addLayout(header)

        self.eigrp_network_container = QVBoxLayout()
        layout.addLayout(self.eigrp_network_container)
        self.eigrp_network_rows = []

        btn_add = QPushButton("➕ Add Network")
        btn_add.clicked.connect(lambda: self.eigrp_network_add_row())
        layout.addWidget(btn_add)
        layout.addStretch()

        self.eigrp_network_add_row("192.168.1.0", "0.0.0.255")

        self.routing_subtabs.addTab(tab, "EIGRP")

    def eigrp_network_add_row(self, network="", wildcard=""):
        txt_net = QLineEdit(network)
        txt_wild = QLineEdit(wildcard)
        txt_wild.setPlaceholderText("(optional)")
        self._add_dynamic_row(
            self.eigrp_network_container, self.eigrp_network_rows,
            [("network", txt_net, 3), ("wildcard", txt_wild, 3)]
        )

    # ---------- RIP sub-tab ----------
    def setup_rip_subtab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()
        self.cmb_rip_version = QComboBox()
        self.cmb_rip_version.addItems(["2", "1"])
        form.addRow("Version:", self.cmb_rip_version)
        self.txt_rip_passive = QLineEdit()
        self.txt_rip_passive.setPlaceholderText("Comma-separated, e.g. GigabitEthernet0/0")
        form.addRow("Passive Interfaces:", self.txt_rip_passive)
        self.chk_rip_auto_summary = QCheckBox("Disable auto-summary (recommended)")
        self.chk_rip_auto_summary.setChecked(True)
        form.addRow("", self.chk_rip_auto_summary)
        layout.addLayout(form)

        header = QHBoxLayout()
        header.addWidget(QLabel("Network (classful)"), 1)
        layout.addLayout(header)

        self.rip_network_container = QVBoxLayout()
        layout.addLayout(self.rip_network_container)
        self.rip_network_rows = []

        btn_add = QPushButton("➕ Add Network")
        btn_add.clicked.connect(lambda: self.rip_network_add_row())
        layout.addWidget(btn_add)
        layout.addStretch()

        self.rip_network_add_row("192.168.1.0")

        self.routing_subtabs.addTab(tab, "RIP")

    def rip_network_add_row(self, network=""):
        txt_net = QLineEdit(network)
        self._add_dynamic_row(self.rip_network_container, self.rip_network_rows, [("network", txt_net, 1)])

    # ---------- BGP sub-tab ----------
    def setup_bgp_subtab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()
        self.txt_bgp_as = QLineEdit("65001")
        form.addRow("Local AS Number:", self.txt_bgp_as)
        self.txt_bgp_rid = QLineEdit()
        self.txt_bgp_rid.setPlaceholderText("(optional) e.g. 1.1.1.1")
        form.addRow("Router ID:", self.txt_bgp_rid)
        layout.addLayout(form)

        layout.addWidget(QLabel("Neighbors:"))
        nb_header = QHBoxLayout()
        nb_header.addWidget(QLabel("Neighbor IP"), 3)
        nb_header.addWidget(QLabel("Remote AS"), 2)
        nb_header.addWidget(QLabel("Description"), 3)
        layout.addLayout(nb_header)

        self.bgp_neighbor_container = QVBoxLayout()
        layout.addLayout(self.bgp_neighbor_container)
        self.bgp_neighbor_rows = []

        btn_add_nb = QPushButton("➕ Add Neighbor")
        btn_add_nb.clicked.connect(lambda: self.bgp_neighbor_add_row())
        layout.addWidget(btn_add_nb)

        layout.addWidget(QLabel("Networks to Advertise:"))
        net_header = QHBoxLayout()
        net_header.addWidget(QLabel("Network"), 3)
        net_header.addWidget(QLabel("Mask"), 3)
        layout.addLayout(net_header)

        self.bgp_network_container = QVBoxLayout()
        layout.addLayout(self.bgp_network_container)
        self.bgp_network_rows = []

        btn_add_net = QPushButton("➕ Add Network")
        btn_add_net.clicked.connect(lambda: self.bgp_network_add_row())
        layout.addWidget(btn_add_net)
        layout.addStretch()

        self.bgp_neighbor_add_row("192.168.1.2", "65002")
        self.bgp_network_add_row("10.0.0.0", "255.255.255.0")

        self.routing_subtabs.addTab(tab, "BGP")

    def bgp_neighbor_add_row(self, ip="", remote_as="", description=""):
        txt_ip = QLineEdit(ip)
        txt_as = QLineEdit(remote_as)
        txt_desc = QLineEdit(description)
        txt_desc.setPlaceholderText("(optional)")
        self._add_dynamic_row(
            self.bgp_neighbor_container, self.bgp_neighbor_rows,
            [("ip", txt_ip, 3), ("remote_as", txt_as, 2), ("description", txt_desc, 3)]
        )

    def bgp_network_add_row(self, network="", mask="255.255.255.0"):
        txt_net = QLineEdit(network)
        txt_mask = QLineEdit(mask)
        self._add_dynamic_row(
            self.bgp_network_container, self.bgp_network_rows,
            [("network", txt_net, 3), ("mask", txt_mask, 3)]
        )

    # ---------- ACL sub-tab ----------
    def setup_acl_subtab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()
        acl_row = QHBoxLayout()
        self.txt_acl_number = QLineEdit("101")
        self.txt_acl_number.setPlaceholderText("e.g. 10 (std) / 101 (ext)")
        acl_row.addWidget(self.txt_acl_number)
        self.cmb_acl_type = QComboBox()
        self.cmb_acl_type.addItems(["Extended", "Standard"])
        acl_row.addWidget(self.cmb_acl_type)
        form.addRow("ACL Number / Type:", acl_row)

        apply_row = QHBoxLayout()
        self.chk_acl_apply = QCheckBox("Apply to interface:")
        self.txt_acl_intf = QLineEdit()
        self.txt_acl_intf.setPlaceholderText("e.g. GigabitEthernet0/0")
        apply_row.addWidget(self.chk_acl_apply)
        apply_row.addWidget(self.txt_acl_intf, 1)
        self.cmb_acl_dir = QComboBox()
        self.cmb_acl_dir.addItems(["in", "out"])
        apply_row.addWidget(self.cmb_acl_dir)
        form.addRow("", apply_row)
        layout.addLayout(form)

        header = QHBoxLayout()
        header.addWidget(QLabel("Action"), 1)
        header.addWidget(QLabel("Proto"), 1)
        header.addWidget(QLabel("Source"), 2)
        header.addWidget(QLabel("Src WC"), 2)
        header.addWidget(QLabel("Destination"), 2)
        header.addWidget(QLabel("Dst WC"), 2)
        header.addWidget(QLabel("Port"), 1)
        header.addWidget(QLabel("Log"), 0)
        layout.addLayout(header)

        self.acl_container = QVBoxLayout()
        layout.addLayout(self.acl_container)
        self.acl_rows = []

        btn_add = QPushButton("➕ Add ACL Rule")
        btn_add.clicked.connect(lambda: self.acl_add_row())
        layout.addWidget(btn_add)
        layout.addStretch()

        self.acl_add_row()
        self.routing_subtabs.addTab(tab, "ACL")

    def acl_add_row(self, action="permit", proto="tcp", src="", swc="0.0.0.255",
                    dst="", dwc="0.0.0.0", port=""):
        cmb_action = QComboBox()
        cmb_action.addItems(["permit", "deny"])
        cmb_action.setCurrentText(action)
        cmb_proto = QComboBox()
        cmb_proto.addItems(["ip", "tcp", "udp", "icmp", "gre", "esp"])
        cmb_proto.setCurrentText(proto)
        txt_src = QLineEdit(src); txt_src.setPlaceholderText("any / host x.x.x.x / net")
        txt_swc = QLineEdit(swc); txt_swc.setPlaceholderText("(opt)")
        txt_dst = QLineEdit(dst); txt_dst.setPlaceholderText("any / host x.x.x.x / net")
        txt_dwc = QLineEdit(dwc); txt_dwc.setPlaceholderText("(opt)")
        txt_port = QLineEdit(port); txt_port.setPlaceholderText("(opt) e.g. 443")
        chk_log = QCheckBox()
        self._add_dynamic_row(
            self.acl_container, self.acl_rows,
            [("action", cmb_action, 1), ("protocol", cmb_proto, 1),
             ("source", txt_src, 2), ("src_wildcard", txt_swc, 2),
             ("destination", txt_dst, 2), ("dst_wildcard", txt_dwc, 2),
             ("port", txt_port, 1), ("log", chk_log, 0)]
        )

    # ---------- NAT sub-tab ----------
    def setup_nat_subtab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        intf_form = QFormLayout()
        self.txt_nat_inside = QLineEdit("GigabitEthernet0/0")
        intf_form.addRow("Inside Interface:", self.txt_nat_inside)
        self.txt_nat_outside = QLineEdit("GigabitEthernet0/1")
        intf_form.addRow("Outside Interface:", self.txt_nat_outside)
        layout.addLayout(intf_form)

        static_group = QGroupBox("Static NAT (one public IP per host)")
        static_layout = QVBoxLayout(static_group)
        sh = QHBoxLayout()
        sh.addWidget(QLabel("Inside Local"), 1)
        sh.addWidget(QLabel("Inside Global (public)"), 1)
        static_layout.addLayout(sh)

        self.nat_static_container = QVBoxLayout()
        static_layout.addLayout(self.nat_static_container)
        self.nat_static_rows = []

        btn_add = QPushButton("➕ Add Static Entry")
        btn_add.clicked.connect(lambda: self.nat_static_add_row())
        static_layout.addWidget(btn_add)
        layout.addWidget(static_group)

        dyn_group = QGroupBox("Dynamic NAT Pool (optional — no overload)")
        dyn_form = QFormLayout(dyn_group)
        self.chk_nat_dynamic = QCheckBox("Enable dynamic NAT pool")
        dyn_form.addRow(self.chk_nat_dynamic)
        self.txt_nat_dyn_acl = QLineEdit("7")
        dyn_form.addRow("Access-list #:", self.txt_nat_dyn_acl)
        self.txt_nat_dyn_net = QLineEdit("192.168.10.0")
        dyn_form.addRow("Permitted Network:", self.txt_nat_dyn_net)
        self.txt_nat_dyn_wc = QLineEdit("0.0.0.255")
        dyn_form.addRow("Wildcard Mask:", self.txt_nat_dyn_wc)
        self.txt_nat_pool_name = QLineEdit("PUBLIC-POOL")
        dyn_form.addRow("Pool Name:", self.txt_nat_pool_name)
        self.txt_nat_pool_start = QLineEdit("203.0.113.100")
        dyn_form.addRow("Pool Start IP:", self.txt_nat_pool_start)
        self.txt_nat_pool_end = QLineEdit("203.0.113.110")
        dyn_form.addRow("Pool End IP:", self.txt_nat_pool_end)
        self.txt_nat_pool_mask = QLineEdit("255.255.255.240")
        dyn_form.addRow("Pool Netmask:", self.txt_nat_pool_mask)
        layout.addWidget(dyn_group)
        layout.addStretch()

        self.nat_static_add_row()
        self.routing_subtabs.addTab(tab, "NAT")

    def nat_static_add_row(self, local="", glob=""):
        txt_local = QLineEdit(local); txt_local.setPlaceholderText("e.g. 10.0.0.5")
        txt_glob = QLineEdit(glob); txt_glob.setPlaceholderText("e.g. 203.0.113.5")
        self._add_dynamic_row(
            self.nat_static_container, self.nat_static_rows,
            [("inside_local", txt_local, 1), ("inside_global", txt_glob, 1)]
        )

    # ---------- PAT sub-tab ----------
    def setup_pat_subtab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()
        self.txt_pat_inside = QLineEdit("GigabitEthernet0/0")
        form.addRow("Inside Interface:", self.txt_pat_inside)
        self.txt_pat_outside = QLineEdit("GigabitEthernet0/1")
        form.addRow("Outside Interface:", self.txt_pat_outside)
        self.txt_pat_acl = QLineEdit("1")
        form.addRow("Access-list #:", self.txt_pat_acl)
        self.txt_pat_net = QLineEdit("192.168.10.0")
        form.addRow("Permitted Network:", self.txt_pat_net)
        self.txt_pat_wc = QLineEdit("0.0.0.255")
        form.addRow("Wildcard Mask:", self.txt_pat_wc)
        self.cmb_pat_mode = QComboBox()
        self.cmb_pat_mode.addItem("Interface Overload (share outside IP)", "interface")
        self.cmb_pat_mode.addItem("Pool Overload (share a pool of IPs)", "pool")
        self.cmb_pat_mode.currentIndexChanged.connect(self.on_pat_mode_changed)
        form.addRow("Overload Mode:", self.cmb_pat_mode)
        layout.addLayout(form)

        pool_group = QGroupBox("NAT Pool (used only in Pool Overload mode)")
        pool_form = QFormLayout(pool_group)
        self.txt_pat_pool_name = QLineEdit("PAT-POOL")
        pool_form.addRow("Pool Name:", self.txt_pat_pool_name)
        self.txt_pat_pool_start = QLineEdit("203.0.113.100")
        pool_form.addRow("Pool Start IP:", self.txt_pat_pool_start)
        self.txt_pat_pool_end = QLineEdit("203.0.113.110")
        pool_form.addRow("Pool End IP:", self.txt_pat_pool_end)
        self.txt_pat_pool_mask = QLineEdit("255.255.255.240")
        pool_form.addRow("Pool Netmask:", self.txt_pat_pool_mask)
        layout.addWidget(pool_group)
        layout.addStretch()

        self.pat_pool_group = pool_group
        self.on_pat_mode_changed(0)
        self.routing_subtabs.addTab(tab, "PAT")

    def on_pat_mode_changed(self, _index):
        self.pat_pool_group.setEnabled(self.cmb_pat_mode.currentData() == "pool")

    # ---------- EtherChannel sub-tab ----------
    def setup_etherchannel_subtab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()
        self.cmb_ec_protocol = QComboBox()
        self.cmb_ec_protocol.addItem("LACP (802.3ad)", "lacp")
        self.cmb_ec_protocol.addItem("PAgP (Cisco)", "pagp")
        self.cmb_ec_protocol.addItem("On (static, no negotiation)", "on")
        form.addRow("Protocol:", self.cmb_ec_protocol)
        self.spin_ec_group = QSpinBox()
        self.spin_ec_group.setRange(1, 256)
        self.spin_ec_group.setValue(1)
        form.addRow("Channel Group #:", self.spin_ec_group)
        po_row = QHBoxLayout()
        self.cmb_ec_po_mode = QComboBox()
        self.cmb_ec_po_mode.addItems(["Trunk", "Access"])
        self.cmb_ec_po_mode.currentIndexChanged.connect(self.on_ec_po_mode_changed)
        po_row.addWidget(self.cmb_ec_po_mode)
        self.txt_ec_allowed_vlans = QLineEdit()
        self.txt_ec_allowed_vlans.setPlaceholderText("Trunk only, optional: e.g. 10,20,30")
        po_row.addWidget(self.txt_ec_allowed_vlans, 1)
        self.txt_ec_access_vlan = QLineEdit()
        self.txt_ec_access_vlan.setPlaceholderText("Access VLAN ID")
        self.txt_ec_access_vlan.setVisible(False)
        po_row.addWidget(self.txt_ec_access_vlan)
        form.addRow("Port-channel Mode:", po_row)
        layout.addLayout(form)

        layout.addWidget(QLabel("Member Interfaces (one per row):"))
        self.ec_container = QVBoxLayout()
        layout.addLayout(self.ec_container)
        self.ec_rows = []

        btn_add = QPushButton("➕ Add Member Interface")
        btn_add.clicked.connect(lambda: self.ec_add_member_row())
        layout.addWidget(btn_add)
        layout.addStretch()

        self.ec_add_member_row(); self.ec_add_member_row()
        self.routing_subtabs.addTab(tab, "EtherChannel")

    def ec_add_member_row(self, intf=""):
        txt = QLineEdit(intf); txt.setPlaceholderText("e.g. Ethernet0/1")
        self._add_dynamic_row(self.ec_container, self.ec_rows, [("interface", txt, 1)])

    def on_ec_po_mode_changed(self, _index):
        is_trunk = self.cmb_ec_po_mode.currentText() == "Trunk"
        self.txt_ec_allowed_vlans.setVisible(is_trunk)
        self.txt_ec_access_vlan.setVisible(not is_trunk)

    # ---------- Standby (HSRP) sub-tab ----------
    def setup_standby_subtab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()
        self.cmb_hsrp_version = QComboBox()
        self.cmb_hsrp_version.addItems(["2", "1"])
        form.addRow("HSRP Version:", self.cmb_hsrp_version)
        layout.addLayout(form)

        header = QHBoxLayout()
        header.addWidget(QLabel("Interface"), 2)
        header.addWidget(QLabel("Group"), 1)
        header.addWidget(QLabel("Virtual IP"), 2)
        header.addWidget(QLabel("Priority"), 1)
        header.addWidget(QLabel("Preempt"), 0)
        layout.addLayout(header)

        self.hsrp_container = QVBoxLayout()
        layout.addLayout(self.hsrp_container)
        self.hsrp_rows = []

        btn_add = QPushButton("➕ Add HSRP Group")
        btn_add.clicked.connect(lambda: self.hsrp_add_row())
        layout.addWidget(btn_add)
        layout.addStretch()

        self.hsrp_add_row(priority="110")
        self.routing_subtabs.addTab(tab, "Standby (HSRP)")

    def hsrp_add_row(self, intf="", group="1", vip="", priority="", preempt=True):
        txt_if = QLineEdit(intf); txt_if.setPlaceholderText("e.g. GigabitEthernet0/0")
        txt_g = QLineEdit(group); txt_g.setPlaceholderText("#")
        txt_vip = QLineEdit(vip); txt_vip.setPlaceholderText("e.g. 192.168.1.254")
        txt_p = QLineEdit(priority); txt_p.setPlaceholderText("default 100")
        chk_pre = QCheckBox(); chk_pre.setChecked(preempt)
        self._add_dynamic_row(
            self.hsrp_container, self.hsrp_rows,
            [("interface", txt_if, 2), ("group", txt_g, 1),
             ("virtual_ip", txt_vip, 2), ("priority", txt_p, 1),
             ("preempt", chk_pre, 0)]
        )

    # ---------- AAA (TACACS+/RADIUS) sub-tab ----------
    def setup_aaa_subtab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()
        self.cmb_aaa_proto = QComboBox()
        self.cmb_aaa_proto.addItem("TACACS+", "tacacs")
        self.cmb_aaa_proto.addItem("RADIUS", "radius")
        form.addRow("Protocol:", self.cmb_aaa_proto)

        srv_row = QHBoxLayout()
        self.txt_aaa_srv1 = QLineEdit()
        self.txt_aaa_srv1.setPlaceholderText("Primary server IP, e.g. 10.0.0.50")
        srv_row.addWidget(self.txt_aaa_srv1, 1)
        self.txt_aaa_srv2 = QLineEdit()
        self.txt_aaa_srv2.setPlaceholderText("(optional) backup server IP")
        srv_row.addWidget(self.txt_aaa_srv2, 1)
        form.addRow("AAA Server(s):", srv_row)

        self.txt_aaa_key = QLineEdit("cisco123")
        form.addRow("Shared Key:", self.txt_aaa_key)

        rescue_row = QHBoxLayout()
        self.txt_aaa_rescue_user = QLineEdit("rescue")
        rescue_row.addWidget(self.txt_aaa_rescue_user, 1)
        self.txt_aaa_rescue_pass = QLineEdit("cisco")
        rescue_row.addWidget(self.txt_aaa_rescue_pass, 1)
        form.addRow("Local Rescue Account:", rescue_row)

        opts_row = QHBoxLayout()
        self.chk_aaa_accounting = QCheckBox("Exec accounting")
        self.chk_aaa_accounting.setChecked(True)
        opts_row.addWidget(self.chk_aaa_accounting)
        self.chk_aaa_cmd_authz = QCheckBox("Command authorization (level 15)")
        opts_row.addWidget(self.chk_aaa_cmd_authz)
        self.chk_aaa_console_local = QCheckBox("Console always local (anti-lockout)")
        self.chk_aaa_console_local.setChecked(True)
        opts_row.addWidget(self.chk_aaa_console_local)
        opts_row.addStretch()
        form.addRow("", opts_row)
        layout.addLayout(form)

        srv_group = QGroupBox("Server-side bootstrap (copy to the AAA server — not pushed to devices)")
        srv_layout = QVBoxLayout(srv_group)
        srv_pick = QHBoxLayout()
        srv_pick.addWidget(QLabel("Platform:"))
        self.cmb_aaa_server_kind = QComboBox()
        self.cmb_aaa_server_kind.addItem("Windows Server / Core — NPS (RADIUS)", "windows-nps")
        self.cmb_aaa_server_kind.addItem("Linux — tac_plus (TACACS+)", "linux-tacplus")
        self.cmb_aaa_server_kind.addItem("Linux — FreeRADIUS", "linux-freeradius")
        srv_pick.addWidget(self.cmb_aaa_server_kind, 1)
        btn_srv_gen = QPushButton("Build Instructions")
        btn_srv_gen.clicked.connect(self.generate_aaa_server_bootstrap)
        srv_pick.addWidget(btn_srv_gen)
        srv_layout.addLayout(srv_pick)

        self.txt_aaa_server = QTextEdit()
        self.txt_aaa_server.setFont(QFont("Consolas", 9))
        self.txt_aaa_server.setPlaceholderText("Pick a platform and click Build Instructions...")
        self.txt_aaa_server.setMaximumHeight(150)
        srv_layout.addWidget(self.txt_aaa_server)
        layout.addWidget(srv_group)

        layout.addStretch()
        self.routing_subtabs.addTab(tab, "AAA")

    def generate_aaa_server_bootstrap(self):
        text = build_aaa_server_bootstrap(
            self.cmb_aaa_server_kind.currentData(),
            shared_key=self.txt_aaa_key.text().strip() or "cisco123",
            rescue_user=self.txt_aaa_rescue_user.text().strip(),
            rescue_pass=self.txt_aaa_rescue_pass.text(),
        )
        self.txt_aaa_server.setPlainText(text)
        QApplication.clipboard().setText(text)
        self.log(f"AAA server bootstrap ({self.cmb_aaa_server_kind.currentText()}) copied to clipboard.")

    # ---------- Generate / Push (dispatches on active sub-tab) ----------
    def generate_routing_script(self) -> bool:
        idx = self.routing_subtabs.currentIndex()
        protocol = self.routing_subtabs.tabText(idx)

        if protocol == "Static":
            routes = [
                {"network": r["network"].text().strip(), "mask": r["mask"].text().strip(),
                 "next_hop": r["next_hop"].text().strip(), "distance": r["distance"].text().strip(),
                 "name": r["name"].text().strip()}
                for r in self.static_route_rows
            ]
            if not any(r["network"] and r["next_hop"] for r in routes):
                QMessageBox.warning(self, "No Routes", "Add at least one static route with a network and next-hop.")
                return False
            cmds = generate_static_route_config(routes)

        elif protocol == "OSPF":
            pid = self.txt_ospf_pid.text().strip()
            if not pid:
                QMessageBox.warning(self, "Missing Process ID", "Enter an OSPF process ID first.")
                return False
            networks = [
                {"network": r["network"].text().strip(), "wildcard": r["wildcard"].text().strip(), "area": r["area"].text().strip()}
                for r in self.ospf_network_rows
            ]
            if not any(n["network"] for n in networks):
                QMessageBox.warning(self, "No Networks", "Add at least one network statement.")
                return False
            passive = [i.strip() for i in self.txt_ospf_passive.text().split(",") if i.strip()]
            cmds = generate_ospf_config(pid, self.txt_ospf_rid.text(), networks, passive, self.chk_ospf_default_orig.isChecked())

        elif protocol == "EIGRP":
            asn = self.txt_eigrp_as.text().strip()
            if not asn:
                QMessageBox.warning(self, "Missing AS Number", "Enter an EIGRP AS number first.")
                return False
            networks = [{"network": r["network"].text().strip(), "wildcard": r["wildcard"].text().strip()} for r in self.eigrp_network_rows]
            if not any(n["network"] for n in networks):
                QMessageBox.warning(self, "No Networks", "Add at least one network statement.")
                return False
            passive = [i.strip() for i in self.txt_eigrp_passive.text().split(",") if i.strip()]
            cmds = generate_eigrp_config(asn, networks, self.chk_eigrp_auto_summary.isChecked(), passive)

        elif protocol == "RIP":
            networks = [r["network"].text().strip() for r in self.rip_network_rows]
            if not any(networks):
                QMessageBox.warning(self, "No Networks", "Add at least one network statement.")
                return False
            passive = [i.strip() for i in self.txt_rip_passive.text().split(",") if i.strip()]
            cmds = generate_rip_config(self.cmb_rip_version.currentText(), networks, self.chk_rip_auto_summary.isChecked(), passive)

        elif protocol == "BGP":
            asn = self.txt_bgp_as.text().strip()
            if not asn:
                QMessageBox.warning(self, "Missing AS Number", "Enter a local AS number first.")
                return False
            neighbors = [
                {"ip": r["ip"].text().strip(), "remote_as": r["remote_as"].text().strip(), "description": r["description"].text().strip()}
                for r in self.bgp_neighbor_rows
            ]
            networks = [{"network": r["network"].text().strip(), "mask": r["mask"].text().strip()} for r in self.bgp_network_rows]
            if not any(n["ip"] for n in neighbors) and not any(n["network"] for n in networks):
                QMessageBox.warning(self, "Nothing to Configure", "Add at least one neighbor or network to advertise.")
                return False
            cmds = generate_bgp_config(asn, self.txt_bgp_rid.text(), neighbors, networks)

        elif protocol == "ACL":
            acl_type = self.cmb_acl_type.currentText().lower()
            rules = []
            for r in self.acl_rows:
                rule = {
                    "action": r["action"].currentText(),
                    "protocol": r["protocol"].currentText(),
                    "source": r["source"].text().strip(),
                    "src_wildcard": r["src_wildcard"].text().strip(),
                    "destination": r["destination"].text().strip(),
                    "dst_wildcard": r["dst_wildcard"].text().strip(),
                    "port": r["port"].text().strip(),
                    "log": r["log"].isChecked(),
                    "wildcard": r["src_wildcard"].text().strip(),
                }
                if acl_type == "extended" and not (rule["source"] and rule["destination"]):
                    continue
                if acl_type == "standard" and not rule["source"]:
                    continue
                rules.append(rule)
            if not rules:
                QMessageBox.warning(self, "No Rules", "Add at least one ACL rule with a source (and destination for extended).")
                return False
            cmds = generate_acl_config(
                self.txt_acl_number.text(),
                acl_type,
                rules,
                apply_interface=self.txt_acl_intf.text() if self.chk_acl_apply.isChecked() else "",
                direction=self.cmb_acl_dir.currentText(),
            )

        elif protocol == "NAT":
            dynamic = None
            if self.chk_nat_dynamic.isChecked():
                dynamic = {
                    "acl_id": self.txt_nat_dyn_acl.text(),
                    "network": self.txt_nat_dyn_net.text(),
                    "wildcard": self.txt_nat_dyn_wc.text(),
                    "pool_name": self.txt_nat_pool_name.text(),
                    "pool_start": self.txt_nat_pool_start.text(),
                    "pool_end": self.txt_nat_pool_end.text(),
                    "pool_mask": self.txt_nat_pool_mask.text(),
                }
                if not all(str(v).strip() for v in dynamic.values()):
                    QMessageBox.warning(self, "Incomplete Dynamic NAT", "Fill every dynamic NAT pool field, or untick 'Enable dynamic NAT pool'.")
                    return False
            static_entries = [
                {"inside_local": r["inside_local"].text(), "inside_global": r["inside_global"].text()}
                for r in self.nat_static_rows
            ]
            static_entries = [e for e in static_entries if e["inside_local"] and e["inside_global"]]
            if not static_entries and not dynamic:
                QMessageBox.warning(self, "Nothing to Configure", "Add a static entry or enable the dynamic NAT pool.")
                return False
            cmds = generate_nat_config(self.txt_nat_inside.text(), self.txt_nat_outside.text(),
                                       static_entries, dynamic)

        elif protocol == "PAT":
            cmds = generate_pat_config(
                self.txt_pat_inside.text(), self.txt_pat_outside.text(),
                self.txt_pat_acl.text(), self.txt_pat_net.text(), self.txt_pat_wc.text(),
                overload_mode=self.cmb_pat_mode.currentData(),
                pool_name=self.txt_pat_pool_name.text(),
                pool_start=self.txt_pat_pool_start.text(),
                pool_end=self.txt_pat_pool_end.text(),
                pool_mask=self.txt_pat_pool_mask.text(),
            )

        elif protocol == "EtherChannel":
            members = [r["interface"].text().strip() for r in self.ec_rows if r["interface"].text().strip()]
            if len(members) < 1:
                QMessageBox.warning(self, "No Members", "Add at least one member interface.")
                return False
            cmds = generate_etherchannel_config(
                self.cmb_ec_protocol.currentData(),
                self.spin_ec_group.value(),
                members,
                po_mode=self.cmb_ec_po_mode.currentText().lower(),
                allowed_vlans=self.txt_ec_allowed_vlans.text(),
                access_vlan=self.txt_ec_access_vlan.text(),
            )

        elif protocol == "AAA":
            servers = []
            for i, field in enumerate((self.txt_aaa_srv1, self.txt_aaa_srv2), start=1):
                ip = field.text().strip()
                if ip:
                    servers.append({"name": f"TAC{i}" if self.cmb_aaa_proto.currentData() == "tacacs" else f"RAD{i}", "ip": ip})
            if not servers:
                QMessageBox.warning(self, "No Server", "Enter at least one AAA server IP.")
                return False
            if not self.txt_aaa_key.text().strip():
                QMessageBox.warning(self, "Missing Key", "Enter the shared key first.")
                return False
            cmds = generate_aaa_config(
                protocol_kind := self.cmb_aaa_proto.currentData(),
                servers,
                shared_key=self.txt_aaa_key.text(),
                fallback_user=self.txt_aaa_rescue_user.text(),
                fallback_pass=self.txt_aaa_rescue_pass.text(),
                enable_accounting=self.chk_aaa_accounting.isChecked(),
                authorize_commands=self.chk_aaa_cmd_authz.isChecked(),
                apply_console_local=self.chk_aaa_console_local.isChecked(),
            )

        else:  # Standby (HSRP)
            groups = [
                {"interface": r["interface"].text(), "group": r["group"].text(),
                 "virtual_ip": r["virtual_ip"].text(), "priority": r["priority"].text(),
                 "preempt": r["preempt"].isChecked()}
                for r in self.hsrp_rows
            ]
            groups = [g for g in groups if g["interface"].strip() and g["group"].strip() and g["virtual_ip"].strip()]
            if not groups:
                QMessageBox.warning(self, "No Groups", "Add at least one HSRP group with interface, group number, and virtual IP.")
                return False
            cmds = generate_standby_config(self.cmb_hsrp_version.currentText(), groups)

        self.txt_route_preview.setPlainText("\n".join(cmds))
        self.log(f"Generated {protocol} configuration script.")
        return True

    def push_routing_config(self):
        if not self.generate_routing_script():
            return
        cmds = self.txt_route_preview.toPlainText().splitlines()
        node_id = self.cmb_route_router.currentData()
        if not node_id:
            QMessageBox.warning(self, "No Router Selected", "Please select a target router.")
            return

        ip = self.txt_ip.text().strip()
        port = 32768 + int(node_id)
        protocol = self.routing_subtabs.tabText(self.routing_subtabs.currentIndex())

        self.log(f"Pushing {protocol} config to {ip}:{port}...")
        mgr = NodeConsoleManager(ip, port)
        output = mgr.send_commands(cmds)
        self.txt_route_preview.setPlainText(f"--- EXECUTED CLI OUTPUT ---\n{output}")
        self.log("Push complete.")

    # ------------------ TAB 4: BATCH CLI ------------------
    def setup_cli_tab(self):
        layout = QVBoxLayout(self.tab_cli)

        # --- Device Selector ---
        dev_group = QGroupBox("Target Devices (check one or more)")
        dev_layout = QVBoxLayout(dev_group)

        dev_btn_row = QHBoxLayout()
        btn_sel_all = QPushButton("Select All")
        btn_sel_all.clicked.connect(lambda: self.set_all_cli_device_checks(True))
        dev_btn_row.addWidget(btn_sel_all)
        btn_sel_none = QPushButton("Select None")
        btn_sel_none.clicked.connect(lambda: self.set_all_cli_device_checks(False))
        dev_btn_row.addWidget(btn_sel_none)
        dev_btn_row.addStretch()
        dev_layout.addLayout(dev_btn_row)

        self.list_cli_devices = QListWidget()
        self.list_cli_devices.setMaximumHeight(100)
        dev_layout.addWidget(self.list_cli_devices)

        layout.addWidget(dev_group)

        # --- AI Assistant (opt-in; free/open providers via OpenAI-compatible APIs) ---
        ai_group = QGroupBox("🤖 AI Assistant (optional — generates commands for you to review, never runs them automatically)")
        ai_layout = QVBoxLayout(ai_group)

        ai_row1 = QHBoxLayout()
        ai_row1.addWidget(QLabel("Provider:"))
        self.cmb_ai_provider = QComboBox()
        for key, label, _base, _model, _need in AI_PROVIDERS:
            self.cmb_ai_provider.addItem(label, key)
        saved_provider = ai_get_selected_provider()
        pidx = self.cmb_ai_provider.findData(saved_provider)
        if pidx >= 0:
            self.cmb_ai_provider.setCurrentIndex(pidx)
        self.cmb_ai_provider.currentIndexChanged.connect(self.on_ai_provider_changed)
        ai_row1.addWidget(self.cmb_ai_provider)

        ai_row1.addWidget(QLabel("API Key:"))
        self.txt_ai_api_key = QLineEdit()
        self.txt_ai_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_ai_api_key.setFixedWidth(150)
        self.txt_ai_api_key.editingFinished.connect(self.save_ai_settings)
        ai_row1.addWidget(self.txt_ai_api_key)
        self.lbl_ai_status = QLabel()
        ai_row1.addWidget(self.lbl_ai_status)
        ai_row1.addStretch()
        ai_layout.addLayout(ai_row1)

        ai_row2 = QHBoxLayout()
        ai_row2.addWidget(QLabel("Base URL:"))
        self.txt_ai_base_url = QLineEdit()
        self.txt_ai_base_url.editingFinished.connect(self.save_ai_settings)
        ai_row2.addWidget(self.txt_ai_base_url, 2)
        ai_row2.addWidget(QLabel("Model:"))
        self.txt_ai_model = QLineEdit()
        self.txt_ai_model.editingFinished.connect(self.save_ai_settings)
        ai_row2.addWidget(self.txt_ai_model, 1)
        ai_layout.addLayout(ai_row2)

        ai_gen_row = QHBoxLayout()
        self.txt_ai_request = QLineEdit()
        self.txt_ai_request.setPlaceholderText(
            "Describe what you want, e.g. 'enable OSPF area 0 on Gi0/0 and Gi0/1 with process ID 1'"
        )
        ai_gen_row.addWidget(self.txt_ai_request)
        self.btn_ai_generate = QPushButton("✨ Generate Commands")
        self.btn_ai_generate.setToolTip("Sends your request to the selected provider and loads the resulting commands below for review.")
        self.btn_ai_generate.clicked.connect(self.ai_generate_commands)
        ai_gen_row.addWidget(self.btn_ai_generate)
        self.btn_ai_explain = QPushButton("🔍 Explain Output")
        self.btn_ai_explain.setToolTip("Plain-English explanation of whatever is in the Console Output box.")
        self.btn_ai_explain.clicked.connect(self.ai_explain_output)
        ai_gen_row.addWidget(self.btn_ai_explain)
        ai_layout.addLayout(ai_gen_row)

        ai_note = QLabel(
            "Free options: OpenCode Zen (opencode.ai/auth) and OpenRouter have free models; Groq is "
            "free-tier; Ollama runs locally with no key. Generated commands land in the input box for "
            "you to review — they are never sent to a device automatically."
        )
        ai_note.setWordWrap(True)
        ai_note.setObjectName("muted")
        ai_layout.addWidget(ai_note)

        layout.addWidget(ai_group)
        self.on_ai_provider_changed(self.cmb_ai_provider.currentIndex())

        # Quick Command Presets Bar — clicking these loads AND immediately
        # runs the commands on every checked device above (true one-click).
        preset_group = QGroupBox("One-Click Config Presets (applies to checked devices above)")
        preset_layout = QHBoxLayout(preset_group)

        presets = [
            ("🔑 Set Enable Password", self.preset_set_password),
            ("🏷️ Set Hostname", self.preset_set_hostname),
            ("🌍 Set Interface IP", self.preset_set_interface_ip),
            ("🔐 Enable SSH", self.preset_enable_ssh),
            ("💾 Save Config", self.preset_save_config),
            ("📄 Show Running Config", self.preset_show_running_config),
            ("📋 Show Interfaces", lambda: self.run_preset_commands("enable\nshow ip interface brief")),
            ("🌐 Show VLANs", lambda: self.run_preset_commands("enable\nshow vlan brief")),
            ("🗺️ Show IP Route", lambda: self.run_preset_commands("enable\nshow ip route")),
            ("🔎 Show CDP Neighbors", lambda: self.run_preset_commands("enable\nshow cdp neighbors detail")),
            ("🖧 Configure DHCP Server", self.preset_configure_dhcp),
            ("♻️ Erase & Reload", self.preset_erase_reload),
        ]
        for label, handler in presets:
            btn = QPushButton(label)
            btn.clicked.connect(handler)
            preset_layout.addWidget(btn)

        layout.addWidget(preset_group)

        # --- Progress bar for multi-device runs ---
        self.bar_cli_progress = QProgressBar()
        self.bar_cli_progress.setRange(0, 100)
        layout.addWidget(self.bar_cli_progress)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # Input Commands
        in_group = QGroupBox("Enter Commands (One per line)")
        in_layout = QVBoxLayout(in_group)
        self.txt_cli_input = QTextEdit()
        self.txt_cli_input.setFont(QFont("Consolas", 10))
        self.txt_cli_input.setText("show ip interface brief\nshow vlan brief\nshow ip route")
        in_layout.addWidget(self.txt_cli_input)

        run_row = QHBoxLayout()
        btn_run = QPushButton("▶ Run CLI Commands on Checked Devices")
        btn_run.setObjectName("btnPrimary")
        btn_run.clicked.connect(self.run_batch_cli)
        run_row.addWidget(btn_run)
        btn_clear_output = QPushButton("Clear Output")
        btn_clear_output.clicked.connect(lambda: self.txt_cli_output.clear())
        run_row.addWidget(btn_clear_output)
        run_row.addStretch()
        in_layout.addLayout(run_row)

        splitter.addWidget(in_group)

        # Output Results
        out_group = QGroupBox("Console Output Results")
        out_layout = QVBoxLayout(out_group)
        self.txt_cli_output = QTextEdit()
        self.txt_cli_output.setFont(QFont("Consolas", 10))
        self.txt_cli_output.setReadOnly(True)
        self.txt_cli_output.setPlaceholderText(
            "Output from each checked device will appear here after you run commands or click a preset..."
        )
        out_layout.addWidget(self.txt_cli_output)
        splitter.addWidget(out_group)

        layout.addWidget(splitter)

    # ---------- Device selector helpers ----------
    def set_all_cli_device_checks(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.list_cli_devices.count()):
            self.list_cli_devices.item(i).setCheckState(state)

    def get_selected_cli_targets(self):
        """Returns [(node_id, label), ...] for every checked device."""
        targets = []
        for i in range(self.list_cli_devices.count()):
            item = self.list_cli_devices.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                targets.append((item.data(Qt.ItemDataRole.UserRole), item.text()))
        return targets

    def set_cli_text(self, text: str):
        self.txt_cli_input.setText(text)

    # ---------- AI Assistant ----------
    def on_ai_provider_changed(self, _index):
        provider = self.cmb_ai_provider.currentData()
        if not provider:
            return
        ai_set_selected_provider(provider)
        for field, getter in ((self.txt_ai_api_key, ai_get_api_key),
                              (self.txt_ai_base_url, ai_get_base_url),
                              (self.txt_ai_model, ai_get_model)):
            field.blockSignals(True)
            field.setText(getter(provider))
            field.blockSignals(False)
        self.txt_ai_api_key.setEnabled(ai_needs_key(provider))
        self.txt_ai_api_key.setPlaceholderText("not needed" if not ai_needs_key(provider) else "")
        self._update_ai_status()

    def save_ai_settings(self):
        provider = self.cmb_ai_provider.currentData()
        if not provider:
            return
        ai_set_api_key(provider, self.txt_ai_api_key.text())
        ai_set_base_url(provider, self.txt_ai_base_url.text())
        ai_set_model(provider, self.txt_ai_model.text())
        self._update_ai_status()

    def _update_ai_status(self):
        provider = self.cmb_ai_provider.currentData()
        ok = ai_is_configured(provider)
        self.lbl_ai_status.setText("✅ Ready" if ok else "⚠ Not configured")
        self.lbl_ai_status.setStyleSheet(
            "color: #22c55e; font-weight: bold;" if ok else "color: #f59e0b;")

    def _make_ai_assistant(self) -> AiAssistant:
        # Persist whatever is currently typed so the worker sees the latest values.
        self.save_ai_settings()
        return AiAssistant(provider=self.cmb_ai_provider.currentData())

    def ai_generate_commands(self):
        request_text = self.txt_ai_request.text().strip()
        if not request_text:
            QMessageBox.warning(self, "Nothing to Generate", "Describe what you want to configure first.")
            return
        try:
            assistant = self._make_ai_assistant()
        except RuntimeError as e:
            QMessageBox.warning(self, "AI Assistant Not Configured", str(e))
            return

        self.btn_ai_generate.setEnabled(False)
        self.log(f"Asking {self.cmb_ai_provider.currentText()} to generate commands...")

        def _run():
            return assistant.generate_cli_commands(request_text)

        self._ai_generate_worker = WorkerThread(_run)

        def _done(status, result):
            self.btn_ai_generate.setEnabled(True)
            if status == "success":
                self.txt_cli_input.setPlainText(result)
                self.log("AI-generated commands loaded into the input box below — review before running.")
            else:
                self.log(f"AI generation failed: {result}")
                QMessageBox.critical(self, "AI Generation Failed", str(result))

        self._ai_generate_worker.finished_signal.connect(_done)
        self._ai_generate_worker.start()

    def ai_explain_output(self):
        output_text = self.txt_cli_output.toPlainText().strip()
        if not output_text:
            QMessageBox.information(self, "No Output Yet", "Run some commands first, then ask for an explanation.")
            return
        try:
            assistant = self._make_ai_assistant()
        except RuntimeError as e:
            QMessageBox.warning(self, "AI Assistant Not Configured", str(e))
            return

        self.btn_ai_explain.setEnabled(False)
        self.log(f"Asking {self.cmb_ai_provider.currentText()} to explain the console output...")

        def _run():
            return assistant.explain_output(output_text)

        self._ai_explain_worker = WorkerThread(_run)

        def _done(status, result):
            self.btn_ai_explain.setEnabled(True)
            if status == "success":
                QMessageBox.information(self, "AI Explanation", result)
                self.log("AI explanation shown.")
            else:
                self.log(f"AI explanation failed: {result}")
                QMessageBox.critical(self, "AI Explanation Failed", str(result))

        self._ai_explain_worker.finished_signal.connect(_done)
        self._ai_explain_worker.start()

    # ---------- One-click config presets ----------
    def run_preset_commands(self, cmds: str):
        """Load a preset command block into the input box and run it immediately
        against every checked device — this is what makes a preset 'one-click'."""
        self.txt_cli_input.setText(cmds)
        self.run_batch_cli()

    def preset_set_password(self):
        pwd, ok = QInputDialog.getText(self, "Set Cisco Enable Password", "Enter new enable secret password:", QLineEdit.EchoMode.Password)
        if ok and pwd:
            cmds = (f"enable\nconfigure terminal\nenable secret {pwd}\nline vty 0 4\npassword {pwd}\nlogin\n"
                     f"exit\nline con 0\npassword {pwd}\nlogin\nexit\nend\nwrite memory")
            self.run_preset_commands(cmds)

    def preset_set_hostname(self):
        name, ok = QInputDialog.getText(self, "Set Device Hostname", "Enter new hostname:")
        if ok and name:
            cmds = f"enable\nconfigure terminal\nhostname {name}\nend\nwrite memory"
            self.run_preset_commands(cmds)

    def preset_set_interface_ip(self):
        intf, ok1 = QInputDialog.getText(self, "Set Interface IP", "Interface (e.g. FastEthernet0/0):")
        if not (ok1 and intf.strip()):
            return
        ip_addr, ok2 = QInputDialog.getText(self, "Set Interface IP", "IP Address:")
        if not (ok2 and ip_addr.strip()):
            return
        mask, ok3 = QInputDialog.getText(self, "Set Interface IP", "Subnet Mask:", text="255.255.255.0")
        if not (ok3 and mask.strip()):
            return
        cmds = (f"enable\nconfigure terminal\ninterface {intf.strip()}\n"
                 f"ip address {ip_addr.strip()} {mask.strip()}\nno shutdown\nend\nwrite memory")
        self.run_preset_commands(cmds)

    def preset_enable_ssh(self):
        domain, ok = QInputDialog.getText(self, "Enable SSH", "Domain name for RSA key generation:", text="lab.local")
        if ok and domain.strip():
            cmds = (f"enable\nconfigure terminal\nip domain-name {domain.strip()}\n"
                     "crypto key generate rsa modulus 1024\nip ssh version 2\n"
                     "line vty 0 4\ntransport input ssh\nlogin local\nexit\nend\nwrite memory")
            self.run_preset_commands(cmds)

    def preset_configure_dhcp(self):
        dialog = DhcpConfigDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                cmds = dialog.get_commands()
            except Exception as e:
                QMessageBox.warning(self, "Invalid DHCP Settings", str(e))
                return
            self.run_preset_commands("\n".join(cmds))

    def preset_save_config(self):
        self.run_preset_commands("enable\nwrite memory")

    def preset_show_running_config(self):
        self.run_preset_commands("enable\nshow running-config")

    def preset_erase_reload(self):
        confirm = QMessageBox.question(
            self, "Erase & Reload",
            "This will ERASE the startup-config and RELOAD every checked device.\n\n"
            "This cannot be undone. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.run_preset_commands("enable\nerase startup-config\nreload\ny\n")

    # ---------- Batch execution ----------
    def run_batch_cli(self):
        targets = self.get_selected_cli_targets()
        if not targets:
            QMessageBox.warning(self, "No Devices Selected",
                                 "Please check at least one target device in the list above.")
            return

        cmds = [c.strip() for c in self.txt_cli_input.toPlainText().splitlines() if c.strip()]
        if not cmds:
            QMessageBox.warning(self, "No Commands", "Please enter at least one command to run.")
            return

        ip = self.txt_ip.text().strip()
        self.txt_cli_output.clear()
        self.bar_cli_progress.setValue(0)
        self.log(f"Executing batch CLI commands on {len(targets)} device(s)...")

        self.cli_worker = BatchCliWorker(ip, targets, cmds)
        self.cli_worker.output_signal.connect(self.append_cli_output)
        self.cli_worker.progress_signal.connect(self.on_cli_progress)
        self.cli_worker.finished_signal.connect(lambda: self.log("Batch CLI finished."))
        self.cli_worker.start()

    def append_cli_output(self, label: str, output: str):
        self.txt_cli_output.append(f"\n===== {label} =====\n{output}\n")

    def on_cli_progress(self, pct: int, msg: str):
        self.bar_cli_progress.setValue(pct)
        self.log(msg)

    # ------------------ TAB 5: TOPOLOGY CANVAS ------------------
    def setup_topo_tab(self):
        layout = QVBoxLayout(self.tab_topo)

        top_bar = QHBoxLayout()
        btn_render_topo = QPushButton("🔄 Redraw Topology")
        btn_render_topo.setObjectName("btnPrimary")
        btn_render_topo.setToolTip("Reload devices and links from EVE-NG and rebuild the map.")
        btn_render_topo.clicked.connect(self.render_topology_diagram)
        top_bar.addWidget(btn_render_topo)

        self.btn_connect_mode = QPushButton("🔗 Connect Mode: OFF")
        self.btn_connect_mode.setCheckable(True)
        self.btn_connect_mode.toggled.connect(self.toggle_connect_mode)
        top_bar.addWidget(self.btn_connect_mode)

        btn_add_node = QPushButton("➕ Add Device")
        btn_add_node.setObjectName("btnSuccess")
        btn_add_node.clicked.connect(self.open_add_node_dialog)
        top_bar.addWidget(btn_add_node)

        btn_del_node = QPushButton("🗑 Delete Selected")
        btn_del_node.setObjectName("btnDanger")
        btn_del_node.setToolTip("Deletes the device currently selected on the map (or right-click it → Delete Device).")
        btn_del_node.clicked.connect(self.delete_selected_topo_node)
        top_bar.addWidget(btn_del_node)

        btn_topo_ping = QPushButton("📡 Ping From...")
        btn_topo_ping.setToolTip("Run a ping FROM a device via its console — pick source interface, destination, and count.")
        btn_topo_ping.clicked.connect(lambda: self._open_topo_ping(None))
        top_bar.addWidget(btn_topo_ping)


        top_bar.addStretch()

        legend = QLabel("  📡 Router   🔀 Switch   💻 VPCS   🖥️ VM/Other   🛡️ Firewall   (● green = running)")
        legend.setStyleSheet("color: #94a3b8; font-size: 11px;")
        top_bar.addWidget(legend)

        layout.addLayout(top_bar)

        # --- The interactive canvas ---
        hint = ("  Scroll to zoom · Drag a box to select devices (Ctrl-click adds) · "
                "Drag devices to rearrange · Double-click a device to open its console")
        self.lbl_topo_hint = QLabel(hint)
        self.lbl_topo_hint.setWordWrap(True)
        self.lbl_topo_hint.setObjectName("muted")

        zoom_row = QHBoxLayout()
        lbl_view = QLabel("View:")
        lbl_view.setStyleSheet("color: #94a3b8;")
        zoom_row.addWidget(lbl_view)

        btn_zoom_in = QPushButton("🔍+ Zoom In")
        btn_zoom_in.setToolTip("Zoom in (mouse wheel also works).")
        zoom_row.addWidget(btn_zoom_in)

        btn_zoom_out = QPushButton("🔍− Zoom Out")
        btn_zoom_out.setToolTip("Zoom out (mouse wheel also works).")
        zoom_row.addWidget(btn_zoom_out)

        btn_zoom_fit = QPushButton("⤢ Fit")
        btn_zoom_fit.setToolTip("Zoom so every device is visible.")
        zoom_row.addWidget(btn_zoom_fit)

        btn_zoom_reset = QPushButton("1:1")
        btn_zoom_reset.setToolTip("Reset zoom to 100%.")
        zoom_row.addWidget(btn_zoom_reset)

        zoom_row.addStretch()
        zoom_row.addWidget(self.lbl_topo_hint, 1)
        layout.addLayout(zoom_row)

        self.topo_canvas = TopologyCanvas()
        self.topo_canvas.node_invoked.connect(self._on_topo_node_invoked)
        self.topo_canvas.node_capture_requested.connect(
            lambda nid, name: self.open_capture_dialog(preselect_node_id=nid))
        self.topo_canvas.node_delete_requested.connect(self._on_topo_delete_requested)
        self.topo_canvas.nodes_connect_requested.connect(self._show_connection_dialog)
        self.topo_canvas.node_moved.connect(self._on_topo_node_moved)
        self.topo_canvas.node_start_requested.connect(lambda nid: self._on_topo_power_toggle(nid, True))
        self.topo_canvas.node_stop_requested.connect(lambda nid: self._on_topo_power_toggle(nid, False))
        self.topo_canvas.nodes_start_requested.connect(lambda ids: self._on_topo_power_toggle_many(ids, True))
        self.topo_canvas.nodes_stop_requested.connect(lambda ids: self._on_topo_power_toggle_many(ids, False))
        self.topo_canvas.node_ping_requested.connect(self._open_topo_ping)
        self.topo_canvas.group_actions_provider = self._build_topology_group_actions
        self.topo_canvas.status_message.connect(
            lambda msg: self.lbl_topo_hint.setText(f"  {msg}"))
        btn_zoom_in.clicked.connect(lambda: self.topo_canvas.zoom_in())
        btn_zoom_out.clicked.connect(lambda: self.topo_canvas.zoom_out())
        btn_zoom_fit.clicked.connect(lambda: self.topo_canvas.zoom_fit())
        btn_zoom_reset.clicked.connect(lambda: self.topo_canvas.zoom_reset())
        layout.addWidget(self.topo_canvas, 1)

    def toggle_connect_mode(self, checked: bool):
        if hasattr(self, "topo_canvas"):
            self.topo_canvas.set_connect_mode(checked)
        if checked:
            self.btn_connect_mode.setText("🔗 Connect Mode: ON  (click source → destination)")
            self.lbl_topo_hint.setText(
                "  Click a SOURCE device, then click DESTINATION device to create a link. "
                "Toggle off to go back to dragging.")
            self.lbl_topo_hint.setObjectName("warn")
            self.lbl_topo_hint.style().unpolish(self.lbl_topo_hint)
            self.lbl_topo_hint.style().polish(self.lbl_topo_hint)
        else:
            self.btn_connect_mode.setText("🔗 Connect Mode: OFF")
            self.lbl_topo_hint.setText(
                "  Scroll to zoom · Drag a box to select devices (Ctrl-click adds) · "
                "Drag devices to rearrange · Double-click a device to open its console")
            self.lbl_topo_hint.setObjectName("muted")

    def _on_topo_node_invoked(self, node_id: int, name: str):
        self.log(f"Topology → opening console for {name.replace(chr(10), ' ')}...")
        self.open_telnet_console(node_id)

    @staticmethod
    def _classify_device(info: dict) -> tuple:
        """Returns (color_hex, emoji) for a node based on its type/template."""
        ntype = str(info.get("type", "")).lower()
        template = str(info.get("template", "")).lower()
        name = str(info.get("name", "")).lower()

        if any(k in template for k in ("fortinet", "pfsense", "opnsense", "firepower", "asa")) \
                or "firewall" in name or "fw" in name.split("-"):
            return "#f97316", "🛡️"
        if "dynamips" in ntype or "3725" in template or "router" in template or "router" in name:
            return "#0284c7", "📡"
        if "iol" in ntype or "switch" in template or "switch" in name:
            return "#16a34a", "🔀"
        if "vpcs" in ntype or "pc" in template:
            return "#eab308", "💻"
        return "#a855f7", "🖥️"

    def _on_topo_delete_requested(self, node_id: int, name: str):
        confirm = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete device '{name}' (ID: {node_id}) from the lab?\n\nThis is irreversible!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return

        lab_path = self.current_lab.lstrip('/')
        url = f"{self.eve_client.base_url}/labs/{urllib.parse.quote(lab_path)}/nodes/{node_id}"
        try:
            resp = self.eve_client.session.delete(url, timeout=10)
            if resp.status_code in (200, 204):
                self.log(f"✅ Device '{name}' deleted.")
                self.refresh_lab()
                self.render_topology_diagram()
            else:
                self.log(f"Delete failed: {resp.text[:200]}")
                try:
                    msg = resp.json().get("message", resp.text[:200])
                except ValueError:
                    msg = resp.text[:200]
                QMessageBox.critical(self, "Delete Failed", str(msg))
        except Exception as e:
            self.log(f"Delete exception: {e}")

    def delete_selected_topo_node(self):
        """Deletes whatever device is currently selected on the canvas."""
        info = None
        if hasattr(self, "topo_canvas"):
            info = self.topo_canvas.selected_node_info()
        if not info:
            QMessageBox.information(
                self, "No Selection",
                "Click a device on the map first (or right-click it → Delete Device), then press Delete.")
            return
        node_id, name = info
        self._on_topo_delete_requested(node_id, name)

    def _open_topo_ping(self, node_id=None):
        """Console ping from a device — launched from the toolbar or the
        canvas context menu (preselects that device)."""
        if not self.nodes_data:
            QMessageBox.warning(self, "No Devices", "Connect to EVE-NG and load a lab first.")
            return
        dlg = TopoPingDialog(self, preselect_node=node_id)
        dlg.exec()

    def _on_topo_power_toggle(self, node_id: int, start: bool):
        """Start/stop toggle from the topology canvas (▶/■ mini buttons)."""
        if not self.eve_client or not self.eve_client.is_logged_in:
            QMessageBox.warning(self, "Not Connected", "Connect to EVE-NG first.")
            return
        verb = "start" if start else "stop"
        self.log(f"Topology → {verb} node {node_id}...")

        def _run():
            if start:
                return self.eve_client.start_node(self.current_lab, node_id)
            return self.eve_client.stop_node(self.current_lab, node_id)

        self._topo_power_worker = WorkerThread(_run)

        def _done(status, result):
            ok = status == "success" and result
            if ok:
                self.topo_canvas.set_node_running(node_id, start)
                self.log(f"Node {node_id} {verb}ed.")
                # EVE-NG flips state asynchronously - re-check shortly.
                QTimer.singleShot(2500, self.refresh_lab)
            else:
                detail = getattr(self.eve_client, "last_error", "")
                self.log(f"❌ Failed to {verb} node {node_id}. {detail}")

        self._topo_power_worker.finished_signal.connect(_done)
        self._topo_power_worker.start()

    def _on_topo_power_toggle_many(self, node_ids: list, start: bool):
        """Start/stop every selected device via the existing batch runner."""
        if not self.eve_client or not self.eve_client.is_logged_in:
            QMessageBox.warning(self, "Not Connected", "Connect to EVE-NG first.")
            return
        ids = [i for i in node_ids if str(i) in self.nodes_data]
        if not ids:
            return
        verb = "start" if start else "stop"
        self.log(f"Topology → {verb}ing {len(ids)} device(s): {ids}")
        self.batch_worker = NodeBatchWorker(self.eve_client, self.current_lab,
                                            ids, action=verb)
        self.batch_worker.progress_signal.connect(self.on_batch_progress)
        self.batch_worker.finished_signal.connect(self.on_batch_finished)
        self.batch_worker.start()

    def _on_topo_node_moved(self, node_id: int, left: float, top: float):
        """Persist a device's new on-map position back to EVE-NG (best effort —
        EVE-NG may reject moves while nodes are running; failures are logged
        softly instead of interrupting the user)."""
        if not self.eve_client or not self.current_lab:
            return
        payload = {"left": int(round(left)), "top": int(round(top))}

        def _run():
            return self.eve_client.update_node(self.current_lab, node_id, payload)

        self._topo_move_worker = WorkerThread(_run)

        def _done(status, result):
            if status != "success" or not result:
                self.log(f"(Position of node {node_id} couldn't be saved — EVE-NG may require "
                         f"the lab/nodes to be stopped. The map keeps the local position.)")

        self._topo_move_worker.finished_signal.connect(_done)
        self._topo_move_worker.start()

    def render_topology_diagram(self):
        if not hasattr(self, "topo_canvas"):
            return
        if not self.eve_client or not self.current_lab:
            QMessageBox.warning(
                self, "Not Connected",
                "Connect to EVE-NG and select a lab first, then redraw the topology.")
            return

        self.log("Fetching topology links and node coordinates...")
        topo_links = self.eve_client.get_lab_topology(self.current_lab)
        nodes = self.nodes_data

        canvas_nodes = {}
        canvas_links = []

        for nid_key, info in nodes.items():
            nid_str = str(info.get("id", nid_key))
            name = info.get("name", f"N{nid_str}")
            node_key = f"node{nid_str}"

            left = float(info.get("left", 500))
            top = float(info.get("top", 500))

            color, icon = self._classify_device(info)
            try:
                running = int(str(info.get("status", 0)).strip() or 0) in (1, 2)
            except (TypeError, ValueError):
                running = False

            canvas_nodes[node_key] = {
                "id": int(nid_str), "name": f"{name}\n({nid_str})",
                "color": color, "icon": icon, "running": running,
                "left": left, "top": top,
            }

        for link in topo_links:
            src = link.get("source")
            dst = link.get("destination")
            sl = pretty_ifname(link.get("source_label", ""))
            dl = pretty_ifname(link.get("destination_label", ""))
            label = f"{sl} ⇄ {dl}" if (sl or dl) else ""
            canvas_links.append((src, dst, label))

        self.topo_canvas.set_graph(canvas_nodes, canvas_links)
        self.log(f"Topology drawn: {len(canvas_nodes)} device(s), {len(canvas_links)} link(s).")


    def _show_connection_dialog(self, src_name, src_id, dst_name, dst_id):
        from PyQt6.QtWidgets import QInputDialog
        if not self.eve_client or not self.eve_client.is_logged_in:
            QMessageBox.warning(self, "Not Connected",
                                "Connect to EVE-NG before creating links.")
            return

        src_intfs, src_note = self._get_node_free_interfaces(src_id)
        dst_intfs, dst_note = self._get_node_free_interfaces(dst_id)

        problems = []
        if not src_intfs:
            problems.append(f"{src_name}: {src_note or 'no interfaces available'}")
        if not dst_intfs:
            problems.append(f"{dst_name}: {dst_note or 'no interfaces available'}")
        if problems:
            QMessageBox.warning(self, "No Interfaces",
                                "Couldn't list interfaces:\n  • "
                                + "\n  • ".join(problems)
                                + "\n\nCheck the device exists in this lab and that "
                                  "EVE-NG is responding (Activity Log has details).")
            return
        for label, note in ((src_name.splitlines()[0], src_note),
                            (dst_name.splitlines()[0], dst_note)):
            if note:
                self.log(f"ℹ {label}: {note}")

        pretty = lambda lst: [pretty_ifname(i) for i in lst]
        src_intfs, dst_intfs = pretty(src_intfs), pretty(dst_intfs)

        src_intf, ok1 = QInputDialog.getItem(self, f"Source Interface on {src_name}",
            f"Select interface for {src_name}:", src_intfs, 0, False)
        if not ok1:
            return

        dst_intf, ok2 = QInputDialog.getItem(self, f"Destination Interface on {dst_name}",
            f"Select interface for {dst_name}:", dst_intfs, 0, False)
        if not ok2:
            return

        self.log(f"Creating link: {src_name}[{src_intf}] ↔ {dst_name}[{dst_intf}]...")
        self._create_eve_link(src_id, src_intf, dst_id, dst_intf, src_name, dst_name)

    def _get_node_free_interfaces(self, node_id):
        """
        Returns (interfaces, note). interfaces = free (unconnected) ports if
        any, otherwise ALL ports of the device (so you can still cable an
        extra link by reusing a port). note explains what happened when the
        list comes back empty instead of guessing 'start the nodes'.
        Uses the hardened API helper (auto-retry + re-auth, longer timeout).
        """
        if not self.eve_client or not self.eve_client.is_logged_in:
            return [], "not connected to EVE-NG"
        lab_path = urllib.parse.quote(self.current_lab.lstrip('/'))
        try:
            resp = self.eve_client._api(
                "GET", f"/labs/{lab_path}/nodes/{node_id}/interfaces", timeout=15)
        except Exception as e:
            self.log(f"Interface fetch error (node {node_id}): {e.__class__.__name__}")
            return [], f"server didn't answer ({e.__class__.__name__}) - try again"

        if resp.status_code != 200:
            detail = getattr(self.eve_client, "last_error", "") or f"HTTP {resp.status_code}"
            self.log(f"Interface fetch failed (node {node_id}): {detail}")
            return [], detail

        try:
            data = resp.json().get("data", {})
        except ValueError:
            return [], "server sent a non-JSON response"

        eth = data.get("ethernet")
        entries = []
        if isinstance(eth, dict):
            entries = list(eth.values())
        elif isinstance(eth, list):
            entries = eth

        names, free = [], []
        for entry in entries:
            name = entry.get("name") if isinstance(entry, dict) else None
            if not name:
                continue
            names.append(name)
            net_id = entry.get("network_id", 0)
            try:
                unconnected = int(net_id or 0) == 0
            except (TypeError, ValueError):
                unconnected = True
            if unconnected:
                free.append(name)

        if not names:
            # Serial-only devices or unusual templates: report honestly.
            serial = data.get("serial")
            if isinstance(serial, dict) and serial:
                snames = [v.get("name", "?") for v in serial.values()
                          if isinstance(v, dict)]
                return snames, "serial interfaces only"
            return [], "device reported no ethernet interfaces"

        if free:
            return free, ""
        # Everything already cabled - still offer every port so the user
        # can reuse one (EVE-NG allows multiple links per interface).
        return names, "all ports are already cabled - you may reuse any of them"

    def _create_eve_link(self, src_id, src_intf, dst_id, dst_intf, src_name, dst_name):
        """Create a network bridge and attach both nodes via EVE-NG REST API."""
        try:
            lab_path = self.current_lab.lstrip('/')
            import urllib.parse
            base = f"{self.eve_client.base_url}/labs/{urllib.parse.quote(lab_path)}"

            # Create new network bridge
            net_resp = self.eve_client.session.post(
                f"{base}/networks",
                json={"type": "bridge", "name": f"Net-{src_name}-{dst_name}", "visibility": "0"},
                timeout=5
            )
            if net_resp.status_code not in (200, 201):
                self.log(f"Network creation failed: {net_resp.text}")
                return

            net_id = net_resp.json().get("data", {}).get("id")
            if not net_id:
                self.log("Could not retrieve new network ID.")
                return

            self.log(f"Created bridge network ID: {net_id}")

            # Connect source interface to new network
            src_if_index = self._intf_name_to_index(src_id, src_intf)
            dst_if_index = self._intf_name_to_index(dst_id, dst_intf)

            if src_if_index is None or dst_if_index is None:
                failed_side = f"{src_name}[{src_intf}]" if src_if_index is None else f"{dst_name}[{dst_intf}]"
                self.log(f"❌ Link creation aborted: couldn't resolve interface {failed_side} to a slot index.")
                # The bridge network above was already created — clean it up rather
                # than leaving an orphaned, unconnected network cluttering the lab.
                try:
                    self.eve_client.session.delete(f"{base}/networks/{net_id}", timeout=5)
                    self.log(f"Cleaned up orphaned bridge network {net_id}.")
                except Exception as cleanup_err:
                    self.log(f"Note: also failed to clean up orphaned bridge network {net_id}: {cleanup_err}")
                QMessageBox.critical(
                    self, "Link Creation Failed",
                    f"Couldn't find interface {failed_side} on the device — the link was NOT created "
                    f"(no interface was connected). This can happen if the interface was renamed, "
                    f"the node isn't reachable, or the lookup timed out. Check the log and try again."
                )
                return

            self.eve_client.session.put(
                f"{base}/nodes/{src_id}/interfaces",
                json={str(src_if_index): str(net_id)}, timeout=5
            )
            self.eve_client.session.put(
                f"{base}/nodes/{dst_id}/interfaces",
                json={str(dst_if_index): str(net_id)}, timeout=5
            )

            self.log(f"✅ Connected {src_name}[{src_intf}] ↔ {dst_name}[{dst_intf}] via bridge {net_id}")
            QMessageBox.information(self, "Connection Created",
                f"✅ Link created!\n\n{src_name}[{src_intf}] ↔ {dst_name}[{dst_intf}]\n\nRedraw the diagram to see the new link.")
            self.render_topology_diagram()

        except Exception as e:
            import traceback
            self.log(f"Link creation error: {e}\n{traceback.format_exc()}")

    def _intf_name_to_index(self, node_id, intf_name: str):
        """Map interface name back to its slot index for the EVE-NG API PUT call.
        Returns None if the lookup fails or the interface isn't found — NEVER
        falls back to a default index. Slot 0 is a real, valid interface index,
        so silently returning 0 on failure would let the caller attach the
        WRONG interface (whatever happens to be in slot 0) while still
        reporting success, which is worse than just failing visibly."""
        lab_path = self.current_lab.lstrip('/')
        import urllib.parse
        url = f"{self.eve_client.base_url}/labs/{urllib.parse.quote(lab_path)}/nodes/{node_id}/interfaces"
        try:
            resp = self.eve_client.session.get(url, timeout=5)
        except Exception as e:
            self.log(f"Interface lookup failed for node {node_id} ({intf_name}): {e}")
            return None

        if resp.status_code != 200:
            self.log(f"Interface lookup for node {node_id} returned HTTP {resp.status_code}")
            return None

        try:
            eth = resp.json().get("data", {}).get("ethernet", {})
        except ValueError:
            self.log(f"Interface lookup for node {node_id} returned non-JSON response")
            return None

        for idx, v in eth.items():
            if v.get("name") == intf_name:
                return int(idx)

        self.log(f"Interface '{intf_name}' not found on node {node_id} — it may have been renamed or removed.")
        return None


    def delete_selected_topo_node(self):
        """Delete the right-click selected node from EVE-NG lab."""
        if not self._selected_node:
            QMessageBox.information(self, "No Selection",
                "Right-click a node on the diagram first to select it, then click Delete.")
            return

        node_id  = self._topo_node_ids.get(self._selected_node)
        node_name = self._topo_node_labels.get(self._selected_node, self._selected_node)

        if not node_id:
            return

        confirm = QMessageBox.question(self, "Confirm Delete",
            f"Delete node '{node_name}' (ID: {node_id}) from lab?\n\nThis is irreversible!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return

        import urllib.parse
        lab_path = self.current_lab.lstrip('/')
        url = f"{self.eve_client.base_url}/labs/{urllib.parse.quote(lab_path)}/nodes/{node_id}"
        try:
            resp = self.eve_client.session.delete(url, timeout=10)
            if resp.status_code in (200, 204):
                self.log(f"✅ Node '{node_name}' deleted.")
                self._selected_node = None
                self.lbl_topo_hint.setText("  Scroll to zoom · Drag to pan · Click node to open console")
                self.lbl_topo_hint.setObjectName("muted")
                self.refresh_lab()
                self.render_topology_diagram()
            else:
                self.log(f"Delete failed: {resp.text[:200]}")
                QMessageBox.critical(self, "Delete Failed", resp.json().get("message", resp.text[:200]))
        except Exception as e:
            self.log(f"Delete exception: {e}")



def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    import traceback
    err_str = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    print(f"\n--- UNHANDLED EXCEPTION DETECTED ---\n{err_str}")
    with open("app_debug.log", "a", encoding="utf-8") as f:
        f.write(f"\n[CRASH LOG]:\n{err_str}\n")

sys.excepthook = handle_exception

def get_app_icon_path() -> str:
    """
    Locate the app icon (icon.ico), handling both normal script execution
    and a PyInstaller-frozen standalone .exe (where bundled data files like
    icon.ico are extracted to a temporary sys._MEIPASS directory at runtime
    instead of living next to a real .py file).
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        app_dir = sys._MEIPASS
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(app_dir, "icon.ico")


def load_app_icon() -> QIcon:
    """
    Builds a multi-size QIcon from icon.ico. Explicitly registers each common
    Windows icon size (rather than relying only on Qt's automatic .ico frame
    detection) since some Qt/Windows combinations only pick up a single frame
    from an .ico otherwise, leaving the taskbar to fall back to a blank or
    generic icon even though the file itself contains the right size.
    """
    icon_path = get_app_icon_path()
    icon = QIcon()
    if os.path.isfile(icon_path):
        for size in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256):
            icon.addFile(icon_path, QSize(size, size))
    return icon


if __name__ == "__main__":
    # On Windows, without this the taskbar groups/represents the app under
    # python.exe's generic icon instead of our own, even after setWindowIcon().
    # This MUST run before QApplication is constructed.
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("EveBridge.DesktopApp.1")
        except Exception:
            pass

    app = QApplication(sys.argv)

    app_icon = load_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    window = MainWindow()
    if not app_icon.isNull():
        window.setWindowIcon(app_icon)
    window.show()
    sys.exit(app.exec())



