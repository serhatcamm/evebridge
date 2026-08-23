"""
Telnet / Serial automation worker for configuring Cisco Routers, Switches, and VPCS in EVE-NG.
Uses telnetlib3 / socket telnet to communicate directly with EVE-NG node console ports.
"""

import socket
import time
import re

class NodeConsoleManager:
    def __init__(self, host: str, port: int = 23, timeout: float = 8.0, connection_type: str = "telnet", username: str = "", password: str = ""):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.connection_type = connection_type.lower()
        self.username = username
        self.password = password

    def send_commands(self, commands: list[str]) -> str:
        """Sends commands via Telnet, SSH, or direct raw Socket depending on connection_type."""
        if self.connection_type == "ssh":
            return self._send_ssh(commands)
        else:
            return self._send_telnet(commands)

    def _send_telnet(self, commands: list[str]) -> str:
        output = ""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            s.connect((self.host, self.port))

            s.sendall(b"\r\n")
            time.sleep(0.5)

            banner = ""
            try:
                banner = s.recv(4096).decode('utf-8', errors='ignore')
                output += banner
            except socket.timeout:
                pass

            # Fresh devices (no startup-config) greet you with IOS's
            # "Would you like to enter the initial configuration dialog?"
            # Any command typed there is swallowed, so answer it first.
            output += self._skip_initial_dialog(s, banner)

            for cmd in commands:
                s.sendall((cmd + "\r\n").encode('utf-8'))
                time.sleep(0.6)

                try:
                    while True:
                        s.settimeout(1.2)
                        data = s.recv(4096).decode('utf-8', errors='ignore')
                        if not data:
                            break
                        output += data
                except socket.timeout:
                    pass

            s.close()
        except Exception as e:
            output += f"\n[Telnet Connection Error]: {e}"
        return output

    def _skip_initial_dialog(self, sock, seen: str = "") -> str:
        """
        Detects the IOS zero-touch prompts in the banner received so far and
        answers them ('no') until a normal prompt shows up. Handles:
          Would you like to enter the initial configuration dialog? [yes]:
          Would you like to terminate autoinstall? [yes]:
        `seen` is the banner read right after connect; returns the extra
        output produced by answering (may be '').
        """
        extra = ""
        for _ in range(4):
            low = (seen or "").lower()
            if (
                "initial configuration dialog" in low
                or "terminate autoinstall" in low
                or re.search(r"\[yes\]\s*:\s*$", low.strip())
            ):
                try:
                    sock.sendall(b"no\r\n")
                except Exception:
                    break
                time.sleep(1.0)
                try:
                    sock.settimeout(1.5)
                    chunk = sock.recv(4096).decode('utf-8', errors='ignore')
                    extra += chunk
                    seen = chunk
                    if not chunk:
                        break
                except socket.timeout:
                    break
            else:
                break
        return extra

    def _send_ssh(self, commands: list[str]) -> str:
        output = ""
        try:
            import paramiko
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(self.host, port=self.port if self.port != 23 else 22, username=self.username, password=self.password, timeout=self.timeout)
            
            chan = client.invoke_shell()
            time.sleep(1)
            
            for cmd in commands:
                chan.send(cmd + "\n")
                time.sleep(0.8)
                
            while chan.recv_ready():
                output += chan.recv(4096).decode('utf-8', errors='ignore')
                
            client.close()
        except Exception as e:
            output += f"\n[SSH Connection Error]: {e}"
        return output

def generate_dhcp_pool_config(
    pool_name: str,
    network: str,
    subnet_mask: str,
    default_router: str,
    dns_servers: list = None,
    lease_days: int = 1,
    lease_infinite: bool = False,
    domain_name: str = "",
    excluded_start: str = "",
    excluded_end: str = "",
) -> list[str]:
    """
    Generates Cisco IOS commands to configure a DHCP server pool.
    dns_servers: list of DNS server IPs, e.g. ['8.8.8.8', '8.8.4.4']
    """
    cmds = ["enable", "configure terminal"]

    if excluded_start:
        if excluded_end and excluded_end != excluded_start:
            cmds.append(f"ip dhcp excluded-address {excluded_start} {excluded_end}")
        else:
            cmds.append(f"ip dhcp excluded-address {excluded_start}")

    cmds.append(f"ip dhcp pool {pool_name}")
    cmds.append(f"network {network} {subnet_mask}")
    if default_router:
        cmds.append(f"default-router {default_router}")
    if dns_servers:
        cmds.append("dns-server " + " ".join(dns_servers))
    if domain_name:
        cmds.append(f"domain-name {domain_name}")
    if lease_infinite:
        cmds.append("lease infinite")
    else:
        cmds.append(f"lease {lease_days}")
    cmds.append("exit")
    cmds.extend(["end", "write memory"])
    return cmds


def generate_router_on_stick_config(main_intf: str, vlan_configs: list[dict]) -> list[str]:
    """
    Generates Cisco IOS commands for Router-on-a-Stick setup.
    vlan_configs: list of dicts with keys: 'vlan_id', 'ip', 'subnet'
    Example: [{'vlan_id': 10, 'ip': '192.168.10.1', 'subnet': '255.255.255.0'}]
    """
    cmds = [
        "enable",
        "configure terminal",
        f"interface {main_intf}",
        "no shutdown",
        "exit"
    ]
    for cfg in vlan_configs:
        vlan_id = cfg['vlan_id']
        ip = cfg['ip']
        subnet = cfg.get('subnet', '255.255.255.0')
        cmds.extend([
            f"interface {main_intf}.{vlan_id}",
            f"encapsulation dot1Q {vlan_id}",
            f"ip address {ip} {subnet}",
            "no shutdown",
            "exit"
        ])
    cmds.extend(["end", "write memory"])
    return cmds

def generate_switch_vlan_config(trunk_interfaces: list[str], access_interfaces: list[dict], vlans: list[int]) -> list[str]:
    """
    Generates Cisco IOS Switch VLAN & Trunk configuration.
    access_interfaces: [{'interface': 'FastEthernet0/1', 'vlan_id': 10}]
    """
    cmds = [
        "enable",
        "configure terminal"
    ]
    # Create VLANs
    for v_id in vlans:
        cmds.extend([
            f"vlan {v_id}",
            f"name VLAN_{v_id}",
            "exit"
        ])
    # Configure Trunk Ports
    for trunk in trunk_interfaces:
        cmds.extend([
            f"interface {trunk}",
            "switchport trunk encapsulation dot1q",
            "switchport mode trunk",
            "no shutdown",
            "exit"
        ])
    # Configure Access Ports
    for acc in access_interfaces:
        intf = acc['interface']
        v_id = acc['vlan_id']
        cmds.extend([
            f"interface {intf}",
            "switchport mode access",
            f"switchport access vlan {v_id}",
            "no shutdown",
            "exit"
        ])
    cmds.extend(["end", "write memory"])
    return cmds


def parse_show_ip_interface_brief(output: str) -> list[str]:
    """
    Parses Cisco IOS 'show ip interface brief' output and returns the list
    of physical/logical interface names found (e.g. ['FastEthernet0/0',
    'FastEthernet0/1', 'GigabitEthernet0/0']). Filters out Vlan SVIs, Null0,
    Loopback interfaces, echoed commands, and bare console prompts — telnet
    console output typically includes both alongside the real table rows.
    """
    interfaces = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        # Real rows have at least: name, ip-address, ok?, method, status (status
        # can be 2 words like "administratively down"), protocol — so >=5 tokens.
        # This also filters out echoed commands and bare "R1#" style prompts.
        if len(parts) < 5:
            continue
        first_token = parts[0]
        if first_token.lower() == "interface":
            continue
        if "#" in first_token or ":" in first_token:
            continue
        lowered = first_token.lower()
        if lowered.startswith(("vlan", "null", "loopback", "nvi")):
            continue
        if not any(ch.isdigit() for ch in first_token):
            continue
        interfaces.append(first_token)
    return interfaces


# =====================================================================
# Routing protocol configuration generators (Static, OSPF, EIGRP, BGP, RIP)
# =====================================================================

def generate_static_route_config(routes: list) -> list[str]:
    """
    routes: list of dicts, each with keys:
        network, mask, next_hop, distance (optional, '' = default), name (optional)
    """
    cmds = ["enable", "configure terminal"]
    for r in routes:
        network = r.get("network", "").strip()
        mask = r.get("mask", "").strip()
        next_hop = r.get("next_hop", "").strip()
        if not (network and mask and next_hop):
            continue
        line = f"ip route {network} {mask} {next_hop}"
        distance = str(r.get("distance", "")).strip()
        if distance:
            line += f" {distance}"
        name = r.get("name", "").strip()
        if name:
            line += f" name {name}"
        cmds.append(line)
    cmds.extend(["end", "write memory"])
    return cmds


def generate_ospf_config(
    process_id: str,
    router_id: str,
    networks: list,
    passive_interfaces: list = None,
    default_originate: bool = False,
) -> list[str]:
    """
    networks: list of dicts with keys: network, wildcard, area
    """
    passive_interfaces = passive_interfaces or []
    cmds = ["enable", "configure terminal", f"router ospf {process_id}"]
    if router_id.strip():
        cmds.append(f"router-id {router_id.strip()}")
    for n in networks:
        network = n.get("network", "").strip()
        wildcard = n.get("wildcard", "").strip()
        area = n.get("area", "0").strip() or "0"
        if network and wildcard:
            cmds.append(f"network {network} {wildcard} area {area}")
    for intf in passive_interfaces:
        intf = intf.strip()
        if intf:
            cmds.append(f"passive-interface {intf}")
    if default_originate:
        cmds.append("default-information originate")
    cmds.extend(["exit", "end", "write memory"])
    return cmds


def generate_eigrp_config(
    as_number: str,
    networks: list,
    no_auto_summary: bool = True,
    passive_interfaces: list = None,
) -> list[str]:
    """
    networks: list of dicts with keys: network, wildcard (wildcard optional)
    """
    passive_interfaces = passive_interfaces or []
    cmds = ["enable", "configure terminal", f"router eigrp {as_number}"]
    for n in networks:
        network = n.get("network", "").strip()
        wildcard = n.get("wildcard", "").strip()
        if not network:
            continue
        cmds.append(f"network {network} {wildcard}" if wildcard else f"network {network}")
    if no_auto_summary:
        cmds.append("no auto-summary")
    for intf in passive_interfaces:
        intf = intf.strip()
        if intf:
            cmds.append(f"passive-interface {intf}")
    cmds.extend(["exit", "end", "write memory"])
    return cmds


def generate_rip_config(
    version: str,
    networks: list,
    no_auto_summary: bool = True,
    passive_interfaces: list = None,
) -> list[str]:
    """networks: list of plain network strings (classful), e.g. ['10.0.0.0', '192.168.1.0']"""
    passive_interfaces = passive_interfaces or []
    cmds = ["enable", "configure terminal", "router rip"]
    if version.strip():
        cmds.append(f"version {version.strip()}")
    for net in networks:
        net = net.strip()
        if net:
            cmds.append(f"network {net}")
    if no_auto_summary:
        cmds.append("no auto-summary")
    for intf in passive_interfaces:
        intf = intf.strip()
        if intf:
            cmds.append(f"passive-interface {intf}")
    cmds.extend(["exit", "end", "write memory"])
    return cmds


def generate_bgp_config(
    as_number: str,
    router_id: str,
    neighbors: list,
    networks: list,
) -> list[str]:
    """
    neighbors: list of dicts with keys: ip, remote_as, description (optional)
    networks: list of dicts with keys: network, mask
    """
    cmds = ["enable", "configure terminal", f"router bgp {as_number}"]
    if router_id.strip():
        cmds.append(f"bgp router-id {router_id.strip()}")
    for nb in neighbors:
        ip = nb.get("ip", "").strip()
        remote_as = nb.get("remote_as", "").strip()
        if not (ip and remote_as):
            continue
        cmds.append(f"neighbor {ip} remote-as {remote_as}")
        desc = nb.get("description", "").strip()
        if desc:
            cmds.append(f'neighbor {ip} description {desc}')
    for n in networks:
        network = n.get("network", "").strip()
        mask = n.get("mask", "").strip()
        if network and mask:
            cmds.append(f"network {network} mask {mask}")
    cmds.extend(["exit", "end", "write memory"])
    return cmds


# =====================================================================
# ACL / NAT / PAT / EtherChannel / HSRP generators
# =====================================================================

def generate_acl_config(acl_number: str, acl_type: str, rules: list,
                        apply_interface: str = "", direction: str = "in") -> list:
    """
    acl_type: 'standard' or 'extended'.
    rules (standard): dicts with action, source, wildcard, log(bool)
    rules (extended): dicts with action, protocol, source, src_wildcard,
                      destination, dst_wildcard, port (optional), log(bool)
    Optionally applies the ACL to an interface with `ip access-group`.
    """
    cmds = ["enable", "configure terminal"]
    acl_number = acl_number.strip() or ("100" if acl_type == "extended" else "10")
    for r in rules:
        action = r.get("action", "permit").strip().lower() or "permit"
        log = " log" if r.get("log") else ""
        if acl_type == "extended":
            proto = r.get("protocol", "ip").strip().lower() or "ip"
            src = r.get("source", "").strip()
            swc = r.get("src_wildcard", "").strip()
            dst = r.get("destination", "").strip()
            dwc = r.get("dst_wildcard", "").strip()
            port = r.get("port", "").strip()
            if not (src and dst):
                continue
            line = f"access-list {acl_number} {action} {proto} {src}"
            line += f" {swc}" if swc else ""
            line += f" {dst}"
            line += f" {dwc}" if dwc else ""
            if proto in ("tcp", "udp") and port:
                line += f" eq {port}"
            cmds.append(line + log)
        else:
            src = r.get("source", "").strip()
            if not src:
                continue
            wc = r.get("wildcard", "").strip()
            line = f"access-list {acl_number} {action} {src}"
            line += f" {wc}" if wc else ""
            cmds.append(line + log)
    if apply_interface.strip():
        cmds.extend([
            f"interface {apply_interface.strip()}",
            f"ip access-group {acl_number} {direction}",
            "exit",
        ])
    cmds.extend(["end", "write memory"])
    return cmds


def generate_nat_config(inside_intf: str, outside_intf: str,
                        static_entries: list, dynamic: dict = None) -> list:
    """
    static_entries: dicts with inside_local, inside_global.
    dynamic: optional dict with acl_id, network, wildcard, pool_name,
             pool_start, pool_end, pool_mask -> classic dynamic NAT pool.
    """
    cmds = ["enable", "configure terminal"]
    for intf, role in ((inside_intf, "inside"), (outside_intf, "outside")):
        if intf.strip():
            cmds.extend([f"interface {intf.strip()}", f"ip nat {role}", "exit"])
    for e in static_entries:
        local = e.get("inside_local", "").strip()
        glob = e.get("inside_global", "").strip()
        if local and glob:
            cmds.append(f"ip nat inside source static {local} {glob}")
    d = dynamic or {}
    if all(str(d.get(k, "")).strip() for k in ("acl_id", "network", "wildcard")):
        acl = str(d["acl_id"]).strip()
        cmds.append(f"access-list {acl} permit {d['network'].strip()} {d['wildcard'].strip()}")
        pool_keys = ("pool_name", "pool_start", "pool_end", "pool_mask")
        if all(str(d.get(k, "")).strip() for k in pool_keys):
            name = d["pool_name"].strip()
            cmds.append(f"ip nat pool {name} {d['pool_start'].strip()} "
                        f"{d['pool_end'].strip()} netmask {d['pool_mask'].strip()}")
            cmds.append(f"ip nat inside source list {acl} pool {name}")
    cmds.extend(["end", "write memory"])
    return cmds


def generate_pat_config(inside_intf: str, outside_intf: str,
                        acl_id: str, network: str, wildcard: str,
                        overload_mode: str = "interface",
                        pool_name: str = "", pool_start: str = "",
                        pool_end: str = "", pool_mask: str = "") -> list:
    """
    PAT (NAT overloading). overload_mode:
      - 'interface': all inside hosts share the outside interface's IP.
      - 'pool': share a pool of addresses (still port-overloaded).
    """
    cmds = ["enable", "configure terminal"]
    for intf, role in ((inside_intf, "inside"), (outside_intf, "outside")):
        if intf.strip():
            cmds.extend([f"interface {intf.strip()}", f"ip nat {role}", "exit"])
    acl_id = acl_id.strip() or "1"
    if network.strip():
        wc = wildcard.strip() or "0.0.0.255"
        cmds.append(f"access-list {acl_id} permit {network.strip()} {wc}")
    if overload_mode == "pool" and all(x.strip() for x in (pool_name, pool_start, pool_end, pool_mask)):
        cmds.append(f"ip nat pool {pool_name.strip()} {pool_start.strip()} "
                    f"{pool_end.strip()} netmask {pool_mask.strip()}")
        cmds.append(f"ip nat inside source list {acl_id} pool {pool_name.strip()} overload")
    else:
        cmds.append(f"ip nat inside source list {acl_id} interface "
                    f"{outside_intf.strip()} overload")
    cmds.extend(["end", "write memory"])
    return cmds


def generate_etherchannel_config(protocol: str, group: int,
                                 member_interfaces: list,
                                 po_mode: str = "trunk",
                                 allowed_vlans: str = "", access_vlan: str = "") -> list:
    """
    LACP / PAgP / static EtherChannel.
      - 'lacp' -> channel-group N mode active
      - 'pagp' -> channel-group N mode desirable
      - 'on'   -> channel-group N mode on (static, no negotiation)
    po_mode: 'trunk' (optionally restricted to allowed_vlans) or 'access'.
    """
    neg_mode = {"lacp": "active", "pagp": "desirable"}.get(protocol.lower(), "on")
    cmds = ["enable", "configure terminal"]

    # Logical Port-channel first so members bind cleanly onto it.
    cmds.append(f"interface Port-channel {group}")
    if po_mode == "trunk":
        cmds.append(" switchport trunk encapsulation dot1q")
        cmds.append(" switchport mode trunk")
        if allowed_vlans.strip():
            cmds.append(f" switchport trunk allowed vlan {allowed_vlans.strip()}")
    elif access_vlan.strip():
        cmds.append(" switchport mode access")
        cmds.append(f" switchport access vlan {access_vlan.strip()}")
    cmds.extend([" no shutdown", " exit"])

    for intf in member_interfaces:
        intf = intf.strip()
        if not intf:
            continue
        cmds.append(f"interface {intf}")
        if po_mode == "trunk":
            cmds.append(" switchport trunk encapsulation dot1q")
        else:
            cmds.append(" switchport mode access")
        cmds.append(f" channel-group {group} mode {neg_mode}")
        cmds.extend([" no shutdown", " exit"])
    cmds.extend(["end", "write memory"])
    return cmds


def generate_standby_config(version: str, groups: list) -> list:
    """
    HSRP (standby). version: '1' or '2'.
    groups: dicts with interface, group, virtual_ip, priority (optional),
            preempt(bool).
    """
    cmds = ["enable", "configure terminal"]
    per_intf = {}
    for g in groups:
        intf = g.get("interface", "").strip()
        gid = str(g.get("group", "")).strip()
        vip = g.get("virtual_ip", "").strip()
        if not (intf and gid and vip):
            continue
        block = per_intf.setdefault(intf, [])
        if not block:
            block.append(f"standby version {version.strip() or '2'}")
        block.append(f"standby {gid} ip {vip}")
        prio = str(g.get("priority", "")).strip()
        if prio:
            block.append(f"standby {gid} priority {prio}")
        if g.get("preempt"):
            block.append(f"standby {gid} preempt")
    for intf, block in per_intf.items():
        cmds.append(f"interface {intf}")
        cmds.extend(block)
        cmds.append("exit")
    cmds.extend(["end", "write memory"])
    return cmds
