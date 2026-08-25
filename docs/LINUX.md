# 🐧 Linux Guide

EveBridge runs natively on Linux. Everything works — no WSL or VM needed.

## Quick Start

```bash
git clone https://github.com/serhatcamm/EveBridge.git
cd EveBridge
pip install -r requirements.txt
python3 main_app.py
```

## Requirements

| Package | Install | Used for |
|---|---|---|
| Python 3.10+ | `apt install python3 python3-pip` | Runtime |
| PyQt6 | `pip install PyQt6` | GUI (Wayland + X11) |
| requests | `pip install requests` | EVE-NG API, AI assistant |
| paramiko | `pip install paramiko` | SSH/SFTP (image upload, export, capture) |

## What Works on Linux

| Feature | Status |
|---|---|
| All 11 tabs | ✅ Full |
| Node start/stop/wipe | ✅ |
| Topology canvas | ✅ |
| Config generators (OSPF, ACL, NAT, HSRP…) | ✅ |
| Batch CLI | ✅ |
| Wireshark capture | ✅ (uses system Wireshark) |
| Image Manager + Online Store | ✅ |
| Export Lab | ✅ |
| Ansible | ✅ Native — no WSL needed |
| AD & GPO generators | ✅ (PowerShell scripts are for Windows targets) |
| Terminal launcher | ✅ (uses gnome-terminal / konsole / xterm) |
| VNC viewer | ✅ (TigerVNC / RealVNC) |
| AI Assistant | ✅ |

## What Differs from Windows

| Feature | Windows | Linux |
|---|---|---|
| Terminal | PuTTY / CMD / PowerShell | gnome-terminal / konsole / xterm |
| VNC | UltraVNC / TightVNC | TigerVNC / RealVNC |
| .exe build | PyInstaller | N/A (run from source or use `python3 -m PyInstaller`) |
| Ansible | WSL required | Native `ansible-playbook` |

## Ansible on Linux

```bash
sudo apt install ansible ansible-network-collection  # or:
sudo ansible-galaxy collection install cisco.ios
```

Then use the Ansible tab → Generate → Run in Terminal. No WSL needed.

## Wireshark Capture

```bash
sudo apt install wireshark
# Add yourself to the wireshark group to capture without sudo:
sudo usermod -aG wireshark $USER
# Log out and back in, then use the 🦈 Wireshark Capture button.
```

## Troubleshooting

**PyQt6 install fails:**
```bash
pip install PyQt6 --only-binary :all:
```

**No terminal emulator found:**
```bash
sudo apt install xterm
```

**Wireshark permissions:**
```bash
sudo dpkg-reconfigure wireshark-common
# Select "Yes" to allow non-root capture
```
