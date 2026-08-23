"""
Ansible Artifacts Generator
------------------------------
Turns the current EVE-NG lab's node list into ready-to-use Ansible material:

  - inventory.ini  grouped by device role (routers / switches / firewalls /
    linux), with cisco.ios network_cli defaults and per-host ansible_host
    placeholders you fill in with each device's management IP once cloud0 is
    attached.
  - A small playbook set: gather facts, back up all running configs, push a
    commands file, and save configs (write memory).

This GENERATES files only - it never connects to devices itself. Run the
playbooks with your own Ansible install (or the "Run Playbook" button, which
shells out to ansible-playbook when it's on PATH).
"""

PLAYBOOKS = {
    "01-gather-facts.yml": """\
---
# Collect facts from every network device in the lab inventory.
- name: Gather facts from lab devices
  hosts: all
  gather_facts: no
  tasks:
    - name: Collect IOS facts
      cisco.ios.ios_facts:
        gather_subset: min
    - name: Show summary
      debug:
        msg: "{{ ansible_net_hostname }} runs {{ ansible_net_version }}"
""",
    "02-backup-configs.yml": """\
---
# Back up every device's running config into ./backups/<host>.cfg
- name: Back up running configs
  hosts: all
  gather_facts: no
  tasks:
    - name: Save current config locally
      cisco.ios.ios_config:
        backup: yes
        backup_options:
          dir_path: ./backups
          filename: "{{ inventory_hostname }}.cfg"
""",
    "03-push-commands.yml": """\
---
# Push every line of commands.txt to all devices in config mode.
# Edit commands.txt next to this playbook, then run it.
- name: Push configuration commands
  hosts: all
  gather_facts: no
  tasks:
    - name: Apply commands
      cisco.ios.ios_config:
        lines: "{{ lookup('file', 'commands.txt').splitlines() }}"
      register: result
    - name: Report what changed
      debug:
        var: result.updates
      when: result.updates is defined
""",
    "04-save-config.yml": """\
---
# Persist running-config to startup-config on every device.
- name: Save configurations
  hosts: all
  gather_facts: no
  tasks:
    - name: write memory
      cisco.ios.ios_command:
        commands: write memory
""",
}

COMMANDS_TXT_SAMPLE = """\
! One IOS command per line - sent in config mode by 03-push-commands.yml
service timestamps log datetime msec
no ip domain-lookup
"""


def _role_for(info: dict) -> str:
    ntype = str(info.get("type", "")).lower()
    template = str(info.get("template", "")).lower()
    name = str(info.get("name", "")).lower()
    if "firewall" in template or "pfsense" in template or "fortinet" in template or "opnsense" in template:
        return "firewalls"
    if "switch" in template or "switch" in name or ("iol" == ntype):
        return "switches"
    if "router" in template or "3725" in template or "dynamips" in ntype:
        return "routers"
    if "vpcs" in ntype or "pc" in template:
        return "endpoints"
    return "linux_vms"


def build_inventory(nodes: dict, manage_user: str = "admin",
                    manage_pass: str = "", become_pass: str = "") -> str:
    """
    nodes: {id: {id,name,type,template,...}} as returned by the EVE-NG API.
    Produces a commented INI inventory. ansible_host starts at the EVE host
    placeholder 'CHANGEME' because each node needs its own mgmt-network IP.
    """
    groups = {"routers": [], "switches": [], "firewalls": [], "linux_vms": [], "endpoints": []}
    for nid, info in nodes.items():
        role = _role_for(info)
        if role == "endpoints":
            continue  # VPCS PCs can't run SSH/Ansible - listed in a comment below
        groups[role].append((info.get("id"), info.get("name", f"node{nid}")))

    lines = [
        "# EveBridge generated inventory",
        "# Fill in each host's ansible_host with its management-network IP",
        "# (attach the nodes to a cloud / pnet0 bridge first). Delete hosts you",
        "# don't want Ansible touching.",
        "",
    ]
    for role in ("routers", "switches", "firewalls", "linux_vms"):
        lines.append(f"[{role}]")
        for nid, name in sorted(groups[role], key=lambda t: str(t[1])):
            safe = str(name).replace(" ", "_")
            lines.append(f"{safe} ansible_host=CHANGEME # EVE node id {nid}")
        lines.append("")
    if groups["endpoints"]:
        names = ", ".join(str(n[1]) for n in groups["endpoints"])
        lines.append(f"# VPCS endpoints skipped (no SSH): {names}")
        lines.append("")

    lines.extend([
        "[all:vars]",
        "ansible_connection=network_cli",
        "ansible_network_os=cisco.ios.ios",
        "# For Linux VMs override per host: ansible_connection=ssh ansible_network_os=*",
        f"ansible_user={manage_user or 'admin'}",
    ])
    if manage_pass:
        lines.append(f"ansible_password={manage_pass}")
    lines.append("ansible_become=yes")
    lines.append("ansible_become_method=enable")
    if become_pass:
        lines.append(f"ansible_become_password={become_pass}")
    lines.append("")
    return "\n".join(lines)


def write_artifacts(out_dir: str, inventory_text: str,
                    selected_playbooks: list) -> list:
    """Writes inventory.ini plus the selected playbooks (+commands.txt sample).
    Returns the list of file paths written."""
    import os
    os.makedirs(out_dir, exist_ok=True)
    written = []

    inv_path = os.path.join(out_dir, "inventory.ini")
    with open(inv_path, "w", encoding="utf-8") as f:
        f.write(inventory_text)
    written.append(inv_path)

    for key in selected_playbooks:
        path = os.path.join(out_dir, key)
        with open(path, "w", encoding="utf-8") as f:
            f.write(PLAYBOOKS[key])
        written.append(path)

    cmds = os.path.join(out_dir, "commands.txt")
    if not os.path.exists(cmds):
        with open(cmds, "w", encoding="utf-8") as f:
            f.write(COMMANDS_TXT_SAMPLE)
        written.append(cmds)
    return written
