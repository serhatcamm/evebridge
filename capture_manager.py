"""
EVE-NG Packet Capture (Wireshark) Manager
-------------------------------------------
Runs `tcpdump` on the EVE-NG host over SSH (root) and streams the raw pcap
data into a locally-launched Wireshark process's stdin, giving a live
Wireshark capture window of traffic on a node's bridge/interface without
manually SSH'ing in and piping tcpdump by hand.

Log/status messages are pushed onto a thread-safe `queue.Queue` (self.log_queue)
rather than calling back into UI code directly, so the GUI can poll it safely
from a QTimer on the main thread instead of touching widgets from a worker thread.
"""

import os
import shutil
import subprocess
import threading
import queue

try:
    import paramiko
except ImportError:
    paramiko = None

DEFAULT_WIRESHARK_PATHS = [
    "wireshark",
    r"C:\Program Files\Wireshark\Wireshark.exe",
    r"C:\Program Files (x86)\Wireshark\Wireshark.exe",
    "/usr/bin/wireshark",
    "/Applications/Wireshark.app/Contents/MacOS/Wireshark",
]


def find_wireshark_executable(custom_path: str = "") -> str:
    """Return a usable Wireshark executable path, or '' if none found."""
    candidates = ([custom_path] if custom_path else []) + DEFAULT_WIRESHARK_PATHS
    for candidate in candidates:
        if not candidate:
            continue
        if shutil.which(candidate):
            return candidate
        if os.path.isfile(candidate):
            return candidate
    return ""


class EveNGPacketCapture:
    """
    Connects to the EVE-NG host over SSH, lists candidate interfaces, and can
    start/stop a live `tcpdump | wireshark` pipe for a chosen interface.
    """

    def __init__(self, host: str, username: str = "root", password: str = "", port: int = 22):
        if paramiko is None:
            raise RuntimeError("paramiko is required for packet capture. Install it with: pip install paramiko")
        self.host = host.strip()
        self.username = username
        self.password = password
        self.port = port
        self.ssh = None
        self.channel = None
        self.log_queue = queue.Queue()

        self._pump_thread = None
        self._wireshark_proc = None
        self._stop_event = threading.Event()
        self.is_capturing = False

    def connect(self):
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(
            self.host, port=self.port, username=self.username,
            password=self.password, timeout=10, banner_timeout=15,
        )

    def list_interfaces(self):
        """Return interface names visible on the EVE-NG host (excludes loopback)."""
        _stdin, stdout, _stderr = self.ssh.exec_command(
            "ip -o link show | awk -F': ' '{print $2}'", timeout=10
        )
        names = [n.strip() for n in stdout.read().decode("utf-8", errors="ignore").splitlines() if n.strip()]
        return [n for n in names if n != "lo"]

    def start_capture(self, interface: str, wireshark_path: str):
        """
        Start `tcpdump` on the remote `interface` and pipe its raw pcap
        output into a locally-launched Wireshark's stdin. Non-blocking —
        the pump loop runs in a background thread; call stop_capture() to end it.
        """
        if self.is_capturing:
            raise RuntimeError("A capture is already running. Stop it first.")
        if not wireshark_path:
            raise RuntimeError("Wireshark executable not found. Install Wireshark or set a custom path.")
        if not interface:
            raise RuntimeError("No interface selected.")

        transport = self.ssh.get_transport()
        self.channel = transport.open_session()
        self.channel.exec_command(f"tcpdump -i {interface} -s 0 -U -w - 2>/dev/null")

        self._wireshark_proc = subprocess.Popen([wireshark_path, "-k", "-i", "-"], stdin=subprocess.PIPE)

        self._stop_event.clear()
        self.is_capturing = True
        self.log_queue.put(f"Capturing on '{interface}' \u2192 streaming into Wireshark ({wireshark_path})...")

        self._pump_thread = threading.Thread(target=self._pump_loop, daemon=True)
        self._pump_thread.start()

    def _pump_loop(self):
        try:
            while not self._stop_event.is_set():
                if self.channel.recv_ready():
                    data = self.channel.recv(65536)
                    if not data:
                        break
                    try:
                        self._wireshark_proc.stdin.write(data)
                        self._wireshark_proc.stdin.flush()
                    except (BrokenPipeError, OSError):
                        self.log_queue.put("Wireshark window was closed; stopping capture.")
                        break
                elif self.channel.exit_status_ready():
                    break
                else:
                    self._stop_event.wait(0.05)
        except Exception as e:
            self.log_queue.put(f"[Capture error] {e}")
        finally:
            self.is_capturing = False
            self.log_queue.put("Capture stream ended.")

    def stop_capture(self):
        self._stop_event.set()
        self.is_capturing = False
        try:
            if self.channel:
                self.channel.close()
        except Exception:
            pass
        try:
            if self._wireshark_proc and self._wireshark_proc.stdin:
                self._wireshark_proc.stdin.close()
        except Exception:
            pass
        self.log_queue.put("Capture stopped.")

    def close(self):
        self.stop_capture()
        try:
            if self.ssh:
                self.ssh.close()
        except Exception:
            pass
