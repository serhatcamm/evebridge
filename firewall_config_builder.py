"""
Firewall / UTM Initial Configuration Wizard
---------------------------------------------
Generates the initial network setup scripts for:
  - pfSense / OPNsense — driven via their text console setup menu (numbered
    options + interactive prompts), not a Cisco-style CLI. Sent as discrete,
    labeled STEPS (see build_pfsense_opnsense_steps) rather than one blind
    blast of commands, so each stage's output can be checked before moving
    on and a failure is easy to pinpoint.
  - FortiGate (FortiOS) — driven via its standard `config ... edit ... end`
    CLI syntax, with support for hostname, admin password, DNS, a WAN
    default route, and any number of additional internal LAN segments
    (each with its own interface, IP, and optional DHCP scope), instead of
    a single fixed WAN/LAN pair.

Both platforms also support detecting real interface names from a live
console session (parse_fortigate_interfaces / parse_bsd_interface_list),
instead of the person having to guess/type "port1"/"em0" blindly.

IMPORTANT: pfSense/OPNsense console menu wording and prompt order vary
between versions. This generates a best-effort, widely-applicable sequence
based on the stock community-edition console menu; always review the
generated script in the wizard before sending it to a device, especially
on unfamiliar versions.
"""

import re


# =====================================================================
# Interface detection (parsing console output into interface name lists)
# =====================================================================

def parse_fortigate_interfaces(output: str) -> list:
    """
    Parses the output of FortiOS's `get system interface physical` command,
    which prints blocks like:
        == [ port1 ]
        name: port1
        ...
    Returns the list of interface names found, e.g. ['port1', 'port2', 'port3'].
    """
    return re.findall(r"==\s*\[\s*(\S+)\s*\]", output)


def parse_bsd_interface_list(output: str) -> list:
    """
    Parses the output of FreeBSD's `ifconfig -l` (a single line of
    space-separated interface names, as used by pfSense/OPNsense's
    underlying shell). Filters out loopback/internal pseudo-interfaces
    that are never valid WAN/LAN picks.
    """
    ignore = {"lo0", "pflog0", "pfsync0", "enc0"}
    names = []
    for line in output.splitlines():
        line = line.strip()
        if not line or " " not in line and len(line) > 40:
            continue  # skip obviously-not-the-list lines (e.g. shell prompts)
        for token in line.split():
            token = token.strip()
            if token and token not in ignore and token not in names and re.match(r"^[a-zA-Z]+\d", token):
                names.append(token)
    return names


# =====================================================================
# pfSense / OPNsense — staged console-menu automation
# =====================================================================

def build_pfsense_opnsense_steps(
    wan_interface: str,
    lan_interface: str,
    lan_ip: str,
    lan_bits: str = "24",
    enable_dhcp: bool = True,
    dhcp_start: str = "",
    dhcp_end: str = "",
    enable_ssh: bool = True,
    optional_interfaces: list = None,
) -> list:
    """
    Returns an ordered list of (step_label, [console_lines]) tuples so each
    stage of the console-menu flow can be sent and checked independently
    instead of blasting the whole sequence at once. `optional_interfaces`
    is a list of extra interface names to assign as OPT1, OPT2, ... (the
    real console menu prompts for these one at a time after WAN/LAN).
    """
    optional_interfaces = optional_interfaces or []
    steps = []

    # --- Step 1: Assign Interfaces ---
    assign_lines = ["1", "n", wan_interface, lan_interface]
    for opt_if in optional_interfaces:
        assign_lines.append(opt_if)
    assign_lines.append("")   # blank = stop adding optional interfaces
    assign_lines.append("y")  # confirm assignment
    steps.append(("Assign Interfaces (WAN/LAN" + (f" + {len(optional_interfaces)} optional" if optional_interfaces else "") + ")", assign_lines))

    # --- Step 2: Set LAN IP address + DHCP ---
    # Stock pfSense CE console asks, in order: interface number -> "Configure
    # IPv4 address via DHCP?" -> IP -> bit count -> upstream gateway (LAN:
    # leave blank) -> "Configure IPv6 ... ?" -> enable DHCP server on LAN?
    # (start/end) -> "revert to HTTP?" -> press ENTER.
    # The DHCP-v4 question comes BEFORE the manual IP entry — sending the
    # answers in the wrong order desyncs every later prompt, which is why
    # this is one discrete step you can verify on its own.
    ip_lines = ["2", "2", "n", lan_ip, str(lan_bits), "", "n"]
    if enable_dhcp:
        ip_lines += ["y", dhcp_start, dhcp_end]
    else:
        ip_lines += ["n"]
    ip_lines += ["n", ""]  # keep HTTPS as webConfigurator protocol; press ENTER to continue
    steps.append(("Set LAN IP Address" + (" + DHCP Server" if enable_dhcp else ""), ip_lines))

    # --- Step 3: Enable SSH (optional) ---
    if enable_ssh:
        # Numbered '14' on stock pfSense; OPNsense may number this differently —
        # sent as its own step specifically so a mismatch here doesn't derail
        # the earlier (more important) interface/IP steps.
        steps.append(("Enable Secure Shell (sshd)", ["14", ""]))

    return steps


def flatten_steps(steps: list) -> list:
    """Flattens build_pfsense_opnsense_steps()'s output into a single line list (for a plain preview/edit box)."""
    lines = []
    for label, step_lines in steps:
        lines.append(f"# --- {label} ---")
        lines.extend(step_lines)
    return lines


# Kept for backwards compatibility with anything calling the old flat-list API.
def generate_pfsense_opnsense_wizard(wan_interface, lan_interface, lan_ip, lan_bits="24",
                                      enable_dhcp=True, dhcp_start="", dhcp_end="",
                                      enable_ssh=True, optional_interfaces=None) -> list:
    steps = build_pfsense_opnsense_steps(
        wan_interface, lan_interface, lan_ip, lan_bits, enable_dhcp,
        dhcp_start, dhcp_end, enable_ssh, optional_interfaces
    )
    lines = []
    for _label, step_lines in steps:
        lines.extend(step_lines)
    return lines


# =====================================================================
# FortiGate (FortiOS)
# =====================================================================

def generate_fortigate_config(
    wan_interface: str,
    wan_mode: str,               # "static" or "dhcp"
    wan_ip: str,
    wan_mask: str,
    wan_gateway: str = "",
    lan_interface: str = "",
    lan_ip: str = "",
    lan_mask: str = "",
    enable_dhcp: bool = True,
    dhcp_start: str = "",
    dhcp_end: str = "",
    allow_ssh_https_wan: bool = False,
    hostname: str = "",
    admin_password: str = "",
    dns_servers: list = None,
    enable_logging: bool = True,
    additional_lans: list = None,
) -> str:
    """
    Returns a multi-line FortiOS CLI configuration script covering hostname,
    admin password, DNS, WAN (static or DHCP + default route), a primary
    LAN, any number of `additional_lans`, and a NAT policy per LAN segment.

    additional_lans: list of dicts, each with keys:
        interface, ip, mask, enable_dhcp (bool), dhcp_start, dhcp_end
    """
    additional_lans = additional_lans or []
    dns_servers = dns_servers or []
    lines = []

    if hostname:
        lines.append(f'config system global')
        lines.append(f'    set hostname "{hostname}"')
        lines.append('end')
        lines.append('')

    if admin_password:
        lines.append('config system admin')
        lines.append('    edit "admin"')
        lines.append(f'        set password "{admin_password}"')
        lines.append('    next')
        lines.append('end')
        lines.append('')

    if dns_servers:
        lines.append('config system dns')
        if len(dns_servers) >= 1:
            lines.append(f'    set primary {dns_servers[0]}')
        if len(dns_servers) >= 2:
            lines.append(f'    set secondary {dns_servers[1]}')
        lines.append('end')
        lines.append('')

    # --- Interfaces: WAN + primary LAN + any additional LAN segments ---
    # (FortiOS 6/7: `set role` marks the port as WAN/LAN in the GUI instead
    # of leaving it "Undefined", and static mode also wants the gateway on
    # the interface via `set gateway` in config router static below.)
    lines.append("config system interface")
    lines.append(f'    edit "{wan_interface}"')
    lines.append("        set role wan")
    if wan_mode == "static":
        lines.append("        set mode static")
        lines.append(f"        set ip {wan_ip} {wan_mask}")
    else:
        lines.append("        set mode dhcp")
        lines.append("        set distance 5")
    wan_access = "ping https ssh" if allow_ssh_https_wan else "ping"
    lines.append(f"        set allowaccess {wan_access}")
    lines.append("    next")

    all_lans = [{"interface": lan_interface, "ip": lan_ip, "mask": lan_mask,
                 "enable_dhcp": enable_dhcp, "dhcp_start": dhcp_start, "dhcp_end": dhcp_end}] + additional_lans

    for lan in all_lans:
        if not lan.get("interface"):
            continue
        lines.append(f'    edit "{lan["interface"]}"')
        lines.append("        set role lan")
        lines.append("        set mode static")
        lines.append(f'        set ip {lan["ip"]} {lan["mask"]}')
        lines.append("        set allowaccess ping https ssh http")
        lines.append("    next")
    lines.append("end")
    lines.append("")

    if wan_mode == "static" and wan_gateway:
        lines.append("config router static")
        lines.append("    edit 1")
        lines.append(f"        set gateway {wan_gateway}")
        lines.append(f'        set device "{wan_interface}"')
        lines.append("    next")
        lines.append("end")
        lines.append("")

    # --- DHCP servers, one per LAN segment that wants one ---
    # (A pool without `default-gateway`/`dns-service` hands out leases with
    # no gateway or DNS — the most common reason "DHCP connects but there's
    # no internet" on freshly scripted FortiGates.)
    dhcp_entries = [lan for lan in all_lans if lan.get("interface") and lan.get("enable_dhcp")]
    if dhcp_entries:
        lines.append("config system dhcp server")
        for idx, lan in enumerate(dhcp_entries, start=1):
            lines.append(f"    edit {idx}")
            lines.append("        set status enable")
            lines.append(f'        set interface "{lan["interface"]}"')
            lines.append("        set dns-service default")
            lines.append(f'        set default-gateway {lan["ip"]}')
            lines.append("        config ip-range")
            lines.append("            edit 1")
            lines.append(f'                set start-ip {lan["dhcp_start"]}')
            lines.append(f'                set end-ip {lan["dhcp_end"]}')
            lines.append("            next")
            lines.append("        end")
            lines.append(f'        set netmask {lan["mask"]}')
            lines.append("        set lease-time 86400")
            lines.append("    next")
        lines.append("end")
        lines.append("")

    # --- One NAT policy per LAN segment, LAN -> WAN ---
    lines.append("config firewall policy")
    policy_id = 1
    for lan in all_lans:
        if not lan.get("interface"):
            continue
        lines.append(f"    edit {policy_id}")
        lines.append(f'        set srcintf "{lan["interface"]}"')
        lines.append(f'        set dstintf "{wan_interface}"')
        lines.append('        set srcaddr "all"')
        lines.append('        set dstaddr "all"')
        lines.append("        set action accept")
        lines.append('        set schedule "always"')
        lines.append('        set service "ALL"')
        lines.append("        set nat enable")
        if enable_logging:
            lines.append("        set logtraffic all")
        lines.append("    next")
        policy_id += 1
    lines.append("end")

    return "\n".join(lines)
