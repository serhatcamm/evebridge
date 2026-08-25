"""
Terminal Client Launcher
-------------------------
Launches an external terminal/SSH/Telnet/VNC client (PuTTY, Windows CMD,
PowerShell, Windows Terminal, a VNC viewer, or a fully custom command) to
open a console session to an EVE-NG node or the EVE-NG host itself, instead
of hardcoding a single PuTTY-then-cmd fallback.
"""

import os
import shutil
import subprocess
import sys

IS_LINUX = sys.platform.startswith("linux")

# (internal_key, display_label) pairs, in the order shown in the UI combo box.
TERMINAL_CLIENTS = [
    ("auto", "Auto-detect (PuTTY \u2192 CMD fallback)"),
    ("putty", "PuTTY"),
    ("cmd", "Windows Command Prompt (cmd)"),
    ("powershell", "Windows PowerShell"),
    ("wt", "Windows Terminal (wt)"),
    ("custom", "Custom command..."),
]

# Common install locations, since a plain "putty" or "vncviewer" call only
# works if the executable happens to be on PATH — which is frequently not
# the case for tools installed via the standard Windows installer/portable zip.
DEFAULT_PUTTY_PATHS = [
    "putty",
    r"C:\Program Files\PuTTY\Bin\putty.exe",
    r"C:\Program Files\ExtraPuTTY\Bin\putty.exe",
    r"C:\Program Files\PuTTY\putty.exe",
    r"C:\Program Files (x86)\PuTTY\putty.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\PuTTY\putty.exe"),
    "/usr/bin/putty",
    "/usr/local/bin/putty",
]

DEFAULT_VNC_PATHS = [
    "vncviewer",
    r"C:\Program Files\uvnc bvba\UltraVNC\vncviewer.exe",
    "tvnviewer",
    r"C:\Program Files\TightVNC\tvnviewer.exe",
    r"C:\Program Files (x86)\TightVNC\tvnviewer.exe",
    r"C:\Program Files\RealVNC\VNC Viewer\vncviewer.exe",
    r"C:\Program Files (x86)\RealVNC\VNC Viewer\vncviewer.exe",
    r"C:\Program Files\TigerVNC\vncviewer.exe",
    r"C:\Program Files (x86)\UltraVNC\vncviewer.exe",
    "/usr/bin/vncviewer",
    "/usr/bin/tigervncviewer",
    "/usr/bin/xtigervncviewer",
]

# Linux terminal emulators (tried in order for telnet/ssh fallback)
LINUX_TERMINALS = [
    "x-terminal-emulator", "gnome-terminal", "konsole",
    "xfce4-terminal", "mate-terminal", "xterm",
]


def _linux_terminal_cmd(cmd_str: str) -> list:
    """Wraps a shell command string in the first available Linux terminal emulator."""
    for term in LINUX_TERMINALS:
        if shutil.which(term):
            if term == "gnome-terminal":
                return [term, "--", "bash", "-c", f"{cmd_str}; echo Press Enter...; read"]
            return [term, "-e", f"bash -c '{cmd_str}; echo Press Enter...; read'"]
    return ["bash", "-c", cmd_str]


def _has(exe_name: str) -> bool:
    return shutil.which(exe_name) is not None


def _find_executable(custom_path: str, defaults: list) -> str:
    """Return the first usable executable path: a user-supplied override first
    (checked both on PATH and as a literal file path), then each default
    candidate in turn. Returns '' if nothing was found."""
    candidates = ([custom_path] if custom_path else []) + defaults
    for candidate in candidates:
        if not candidate:
            continue
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        if os.path.isfile(candidate):
            return candidate
    return ""


def find_putty_executable(custom_path: str = "") -> str:
    return _find_executable(custom_path, DEFAULT_PUTTY_PATHS)


def find_vnc_executable(custom_path: str = "") -> str:
    return _find_executable(custom_path, DEFAULT_VNC_PATHS)


def launch_telnet(client: str, host: str, port: int, custom_template: str = "", putty_path: str = "") -> str:
    """
    Launch a Telnet session to host:port using the selected terminal client.
    Returns a short human-readable description of what was launched (for the log).
    Raises RuntimeError if the client couldn't be started.
    """
    if client == "custom":
        if not custom_template.strip():
            raise RuntimeError("Custom terminal command template is empty. Set one in the field next to the selector.")
        cmd = custom_template.format(host=host, ip=host, port=port, protocol="telnet")
        subprocess.Popen(cmd, shell=True)
        return f"Custom command: {cmd}"

    if client == "putty" or client == "auto":
        putty_exe = find_putty_executable(putty_path)
        if putty_exe:
            subprocess.Popen([putty_exe, "-telnet", host, str(port)])
            return f"PuTTY ({putty_exe}) -telnet {host} {port}"
        elif client == "putty":
            raise RuntimeError(
                "Could not find putty.exe. It isn't on PATH and wasn't found in the usual install "
                "locations. Set a custom PuTTY path in the field provided, or install PuTTY."
            )
        # client == "auto" and PuTTY not found: fall through to next option

    if client == "wt" or (client == "auto" and _has("wt")):
        try:
            subprocess.Popen(["wt", "telnet", host, str(port)])
            return f"Windows Terminal: telnet {host} {port}"
        except FileNotFoundError as e:
            if client == "wt":
                raise RuntimeError(f"Could not launch Windows Terminal: {e}")

    if client == "powershell" and not IS_LINUX:
        try:
            subprocess.Popen(["powershell", "-NoExit", "-Command", f"telnet {host} {port}"])
            return f"PowerShell: telnet {host} {port}"
        except FileNotFoundError as e:
            raise RuntimeError(f"Could not launch PowerShell: {e}")

    if IS_LINUX:
        term_cmd = f"telnet {host} {port}"
        for term in LINUX_TERMINALS:
            if shutil.which(term):
                subprocess.Popen(_linux_terminal_cmd(term_cmd))
                return f"Linux terminal ({term}): {term_cmd}"
        raise RuntimeError("No terminal emulator found on Linux. Install xterm or gnome-terminal.")

    # cmd, or final "auto" fallback (Windows only)
    if not IS_LINUX:
        try:
            subprocess.Popen(f"start cmd /k telnet {host} {port}", shell=True)
            return f"cmd /k telnet {host} {port}"
        except FileNotFoundError as e:
            raise RuntimeError(f"Could not launch '{client}': {e}")


def launch_ssh(client: str, host: str, user: str, port: int = 22, custom_template: str = "", putty_path: str = "") -> str:
    """Launch an SSH session using the selected terminal client."""
    if client == "custom":
        if not custom_template.strip():
            raise RuntimeError("Custom terminal command template is empty. Set one in the field next to the selector.")
        cmd = custom_template.format(host=host, ip=host, port=port, user=user, protocol="ssh")
        subprocess.Popen(cmd, shell=True)
        return f"Custom command: {cmd}"

    if client == "putty" or client == "auto":
        putty_exe = find_putty_executable(putty_path)
        if putty_exe:
            subprocess.Popen([putty_exe, "-ssh", f"{user}@{host}", "-P", str(port)])
            return f"PuTTY ({putty_exe}) -ssh {user}@{host} -P {port}"
        elif client == "putty":
            raise RuntimeError(
                "Could not find putty.exe. It isn't on PATH and wasn't found in the usual install "
                "locations. Set a custom PuTTY path in the field provided, or install PuTTY."
            )

    if client == "wt" or (client == "auto" and _has("wt")):
        try:
            subprocess.Popen(["wt", "ssh", f"{user}@{host}", "-p", str(port)])
            return f"Windows Terminal: ssh {user}@{host} -p {port}"
        except FileNotFoundError as e:
            if client == "wt":
                raise RuntimeError(f"Could not launch Windows Terminal: {e}")

    if client == "powershell":
        try:
            subprocess.Popen(["powershell", "-NoExit", "-Command", f"ssh {user}@{host} -p {port}"])
            return f"PowerShell: ssh {user}@{host} -p {port}"
        except FileNotFoundError as e:
            raise RuntimeError(f"Could not launch PowerShell: {e}")

    try:
        subprocess.Popen(f"start cmd /k ssh {user}@{host} -p {port}", shell=True)
        return f"cmd /k ssh {user}@{host} -p {port}"
    except FileNotFoundError as e:
        raise RuntimeError(f"Could not launch '{client}': {e}")


def launch_vnc(host: str, port: int, vnc_path: str = "", custom_template: str = "") -> str:
    """
    Launch a VNC viewer session to host:port. Tries a user-supplied override
    path first, then common TightVNC/RealVNC/TigerVNC/UltraVNC install
    locations. Raises RuntimeError with actionable guidance if none is found
    — it no longer silently falls back to a `cmd` window that just prints
    the target address.
    """
    if custom_template.strip():
        cmd = custom_template.format(host=host, ip=host, port=port)
        subprocess.Popen(cmd, shell=True)
        return f"Custom command: {cmd}"

    vnc_exe = find_vnc_executable(vnc_path)
    if not vnc_exe:
        raise RuntimeError(
            "No VNC viewer found (checked PATH and the usual TightVNC/RealVNC/TigerVNC/UltraVNC "
            "install locations). Install one of these, or set a custom VNC viewer path."
        )

    subprocess.Popen([vnc_exe, f"{host}::{port}"])
    return f"VNC ({vnc_exe}) \u2192 {host}::{port}"

