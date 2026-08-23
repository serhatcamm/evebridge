# EVE-NG Lab Automation & Management Suite

A PyQt6 desktop application for managing, monitoring, and configuring an
[EVE-NG](https://www.eve-ng.net/) network-emulation lab from Windows — node
control, Cisco IOS configurators (Router-on-a-Stick, VLANs/trunking, routing
protocols, DHCP), batch CLI execution, image management, live Wireshark
capture, firewall/UTM wizards, and an interactive topology map.

> **No credentials are bundled.** The app ships with empty connection fields —
> you provide your own EVE-NG server IP and login on first run.

## Features

- **Live EVE-NG Integration** — REST API connection for node status, CPU/RAM/disk
  monitors, start/stop/wipe nodes, add devices, edit RAM/NVRAM/CPU/ports.
- **🗺️ Interactive Topology Canvas** — native Qt map of your lab: drag devices,
  zoom/pan, double-click a device to open its console, right-click for actions,
  Connect Mode to create links between devices, and drag positions save back to
  the lab.
- **Router-on-a-Stick Auto-Configurator** — unlimited VLAN rows, real interface
  detection via `show ip interface brief`, generated `dot1Q` subinterface script.
- **Switch VLAN & Trunk Configurator** — unlimited VLANs with access-port lists,
  trunk configuration, interface detection.
- **Routing & Services Config** — Static routes, OSPF, EIGRP, RIP, and BGP sub-tabs,
  plus network-services sub-tabs: **ACLs** (standard/extended + interface apply),
  **NAT** (static entries + dynamic pool), **PAT** (interface or pool overload),
  **EtherChannel** (LACP/PAgP/static), and **Standby/HSRP** (groups, priority,
  preempt) — every list fully customizable; preview or push to the console.
- **Batch CLI Console** — run commands across any number of checked devices in
  the background, with per-device labeled output, plus one-click presets
  (enable password, hostname, SSH, DHCP pool, save config, show commands,
  erase & reload). Right-click the node table anywhere for refresh/actions.
- **🤖 AI Assistant (open & free providers)** — optional panel in the Batch CLI tab that turns
  plain English into CLI commands (loaded into the input box for review — never auto-run) and
  explains console output. Works with any OpenAI-compatible endpoint via built-in presets:

  | Provider | Base URL | Cost |
  |---|---|---|
  | **OpenCode Zen** | `https://opencode.ai/zen/v1` | Free models available ([get a key](https://opencode.ai/auth)) |
  | **OpenRouter** | `https://openrouter.ai/api/v1` | Many free/open models |
  | **Groq** | `https://api.groq.com/openai/v1` | Free tier |
  | **Ollama** (local) | `http://localhost:11434/v1` | Fully local, no API key |
  | Custom | your endpoint | any OpenAI-compatible server |

  Uses plain HTTP — no extra SDKs. Keys are stored locally in QSettings per provider.
- **📦 Image Manager** — upload QEMU/IOL/Dynamips/Linux images over SSH/SFTP
  following EVE-NG's documented procedures: vendor-correct folder + disk naming
  (106 vendors), a dedicated **🐧 Linux VM** flow (`linux-` prefix handled
  automatically, qcow2/vmdk conversion, ISO hand-off to the install wizard),
  remote `qemu-img convert`, IOL `.bin` fix + iourc license writing, Dynamips
  decompression, automatic `fixpermissions`, an ISO-install wizard, and a
  Dynamips Idle-PC helper.
- **🧱 Firewall/UTM Wizard** — initial config generation for pfSense, OPNsense
  (staged console-menu steps in stock prompt order), and FortiGate (full CLI:
  interface roles, complete DHCP pools with gateway/DNS/lease, NAT policies)
  with real interface detection.
- **Telnet Console Launcher** — PuTTY / CMD / PowerShell / Windows Terminal /
  custom command templates, with auto-detection.
- **🎨 UI Themes** — nine color themes, remembered between runs.
- **🔄 Software Updates** — optional manifest-URL update checker with automatic
  backups of replaced files.
- **🚀 One-Click EXE Build** — package everything into a single standalone
  `.exe` with PyInstaller.

## Requirements

- Windows (for the terminal launchers and EXE build)
- Python 3.10+
- A reachable EVE-NG server (Community or PRO)

```bash
pip install -r requirements.txt
python main_app.py
```

## Getting Started

1. Launch the app and fill in your EVE-NG server's **IP**, **username**
   (default EVE-NG install: `admin`), and **password**, then click
   **🔌 Connect / Login**.
2. Pick a lab from the dropdown — the node table fills automatically.
3. For Image Manager / Wireshark capture, the app uses the EVE-NG host's
   **root SSH** account (separate from the API login).

## Building the standalone .exe

Double-click **`build_exe.bat`** on a Windows machine with Python installed.
It installs the dependencies plus PyInstaller, cleans previous builds, and
produces **`dist\EVE-NG-Lab-Automation.exe`** — a single portable file, no
Python needed on the target machine.

## Project Layout

| File | Purpose |
|---|---|
| `main_app.py` | GUI application (all tabs, dialogs, worker threads) |
| `eve_api.py` | EVE-NG REST API client |
| `config_builder.py` | Console automation + Cisco IOS config generators |
| `topology_canvas.py` | Interactive QGraphicsView topology map |
| `image_uploader.py` | SSH/SFTP image installation per EVE-NG howtos |
| `capture_manager.py` | Remote tcpdump → local Wireshark piping |
| `firewall_config_builder.py` | pfSense/OPNsense/FortiGate config generators |
| `terminal_launcher.py` | External terminal/VNC client launching |
| `updater.py` | Manifest-based self-update with backups |
| `themes.py` | UI color themes |

## Security Notes

- No API keys, passwords, or server addresses are hardcoded anywhere — the
  connection bar starts empty and credentials are only held in memory.
- The AI Assistant is strictly opt-in and off by default: it only talks to
  whichever open provider *you* configure (OpenCode Zen, OpenRouter, Groq,
  local Ollama, or your own endpoint), using your own key stored locally.
  Generated commands are never executed automatically — they land in the CLI
  input box for review first.
- The app makes no other third-party cloud calls other than the EVE-NG server
  you configure and the optional update-manifest URL you set yourself.
- Update packages are backed up to a timestamped `backup_*/` folder before
  being applied, so any update can be rolled back manually.

## Author / Links

- 🐙 GitHub: <https://github.com/serhatcamm>
- 💼 LinkedIn: <https://www.linkedin.com/in/serhatcammm/>
- 📖 EVE-NG Documentation: <https://www.eve-ng.net/index.php/documentation/>

## License

Provided as-is for educational/lab use. Use at your own risk when pushing
configurations to devices.
