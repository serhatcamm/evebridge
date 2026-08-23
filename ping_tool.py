"""
Built-in Ping Tester
----------------------
Runs the OS ping utility as a subprocess and streams every reply line back to
the GUI in real time (color-classified), with live sent/received/loss/avg
stats. Supports one-shot counts and continuous mode (-t / unlimited loop).

The worker never touches widgets - everything goes through signals, so it
can run from any dialog without freezing the UI.
"""

import os
import re
import subprocess

from PyQt6.QtCore import QThread, pyqtSignal

# kind: "ok" | "fail" | "summary" | "info"
_LINE_RE = re.compile(r"time\s*[<=]\s*(\d+)\s*ms", re.IGNORECASE)
_FAIL_KEYWORDS = (
    "request timed out",
    "destination host unreachable",
    "destination net unreachable",
    "general failure",
    "could not find host",
    "transmit failed",
    "unreachable",
)


class PingWorker(QThread):
    line_signal = pyqtSignal(str, str)                 # text, kind
    stats_signal = pyqtSignal(int, int, float, float)  # sent, recv, loss_pct, avg_ms
    finished_sig = pyqtSignal()

    def __init__(self, host: str, count: int = 4,
                 timeout_ms: int = 1000, parent=None):
        super().__init__(parent)
        self.host = host.strip()
        self.count = max(0, int(count))       # 0 => continuous
        self.timeout_ms = max(100, int(timeout_ms))
        self._proc = None
        self._stop_requested = False

    # ---------------- control ----------------
    def stop(self):
        self._stop_requested = True
        proc = self._proc
        if proc is not None:
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        capture_output=True, timeout=5)
                else:
                    proc.terminate()
            except Exception:
                pass

    def _build_cmd(self):
        if os.name == "nt":
            if self.count == 0:  # continuous
                return ["ping", "-t", "-w", str(self.timeout_ms), self.host]
            return ["ping", "-n", str(self.count), "-w", str(self.timeout_ms), self.host]
        # POSIX
        count = self.count if self.count > 0 else 1000000
        wait_s = max(1, round(self.timeout_ms / 1000))
        return ["ping", "-c", str(count), "-W", str(wait_s), self.host]

    # ---------------- parsing ----------------
    @staticmethod
    def parse_line(line: str):
        """Classifies one ping output line. Returns (kind, rtt_ms_or_None)."""
        s = line.strip()
        low = s.lower()
        if not low:
            return "info", None
        m = _LINE_RE.search(low)
        if m and ("reply from" in low or "bytes from" in low or "time" in low) \
                and "unreachable" not in low:
            try:
                return "ok", int(m.group(1))
            except ValueError:
                return "ok", 0
        for kw in _FAIL_KEYWORDS:
            if kw in low:
                return "fail", None
        if "minimum =" in low or "packets:" in low or "round-trip" in low:
            return "summary", None
        return "info", None

    # ---------------- worker ----------------
    def run(self):
        if not self.host:
            self.line_signal.emit("No target entered.", "fail")
            self.finished_sig.emit()
            return

        cmd = self._build_cmd()
        mode = "continuous" if self.count == 0 else f"{self.count} packets"
        self.line_signal.emit(f"Pinging {self.host} ({mode})...", "info")

        sent = recv = 0
        times = []

        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, errors="ignore",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as e:
            self.line_signal.emit(f"Failed to start ping: {e}", "fail")
            self.finished_sig.emit()
            return

        for raw in self._proc.stdout:
            if self._stop_requested:
                break
            line = raw.rstrip()
            if not line:
                continue
            kind, ms = self.parse_line(line)
            if kind == "ok":
                sent += 1
                recv += 1
                if ms is not None and ms >= 0:
                    times.append(ms)
            elif kind == "fail":
                sent += 1
            self.line_signal.emit(line, kind)
            if sent:
                avg = sum(times) / len(times) if times else 0.0
                self.stats_signal.emit(sent, recv, (sent - recv) / sent * 100.0, avg)

        self.stop()  # ensure the child process is gone
        avg = sum(times) / len(times) if times else 0.0
        loss = ((sent - recv) / sent * 100.0) if sent else 0.0
        if sent == 0:
            self.line_signal.emit("Stopped.", "info")
        else:
            self.line_signal.emit(
                f"Done: sent {sent}, received {recv}, loss {loss:.0f}%, "
                f"avg {avg:.1f} ms", "summary")
        self.stats_signal.emit(sent, recv, loss, avg)
        self.finished_sig.emit()
