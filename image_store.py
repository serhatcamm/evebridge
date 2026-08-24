"""
EVE-NG Online Image Store
---------------------------
Curated catalog of community EVE-NG images (sourced from the public
hegdepavankumar/Cisco-Images-for-GNS3-and-EVE-NG repository) with direct
download URLs, plus a Google Drive downloader that handles the large-file
confirmation flow.

Images are vendor-copyrighted — personal lab use only, per the source
repository's own terms.

Entry fields:
    vendor   - family label for filtering
    name     - display name
    file     - archive/file name (defines the EVE-NG folder name)
    url      - direct download URL
    template - EVE-NG template key (for Add-Device hints)
    ram      - recommended RAM in MB
    fmt      - tgz | qcow2 | iso
"""

import re

CATALOG = []


def _add(vendor, name, file, url, template, ram, fmt=None):
    fmt = fmt or ("iso" if file.endswith(".iso") else
                  "qcow2" if file.endswith(".qcow2") else "tgz")
    folder = re.sub(r"\.(tgz|tar\.gz|iso|qcow2)$", "", file, flags=re.I)
    CATALOG.append({
        "vendor": vendor, "name": name, "file": file, "url": url,
        "folder": folder, "template": template, "ram": ram, "fmt": fmt,
    })


# ---------------- Cisco ----------------
_add("Cisco vIOS", "vIOS 15.8(3)M2", "vios-adventerprisek9-m.spa.158-3.m2.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20IOSv/vios-adventerprisek9-m.spa.158-3.m2.tgz", "vios", 1024)
_add("Cisco vIOS", "vIOS 15.9(3)M6", "vios-adventerprisek9-m.SPA.159-3.M6.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20IOSv/vios-adventerprisek9-m.SPA.159-3.M6.tgz", "vios", 1024)
_add("Cisco vIOS", "vIOS 15.9(3)M4", "vios-adventerprisek9-m.SPA.159-3.M4.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20IOSv/vios-adventerprisek9-m.SPA.159-3.M4.tgz", "vios", 1024)
_add("Cisco vIOS-L2", "vIOS-L2 high-iron 2020", "viosl2-adventerprisek9-m.ssa.high_iron_20200929.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20IOSvL2/viosl2-adventerprisek9-m.SSA.high_iron_20180619.tgz", "viosl2", 1024)
_add("Cisco vIOS-L2", "vIOS-L2 high-iron 2018", "viosl2-adventerprisek9-m.SSA.high_iron_20180619.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20IOSvL2/viosl2-adventerprisek9-m.SSA.high_iron_20180619.tgz", "viosl2", 1024)
_add("Cisco ASAv", "ASAv 9.17.1", "asav-9-17-1-10.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20ASAv/asav-917-1-10.tgz", "asav", 2048)
_add("Cisco ASAv", "ASAv 9.18.1", "asav-9-18-1.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20ASAv/asav-9-18-1.tgz", "asav", 2048)
_add("Cisco ASAv", "ASAv 9.16.1-28", "asav-916-1-28.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20ASAv/asav-916-1-28.tgz", "asav", 2048)
_add("Cisco ASAv", "ASAv 9.10.1-100", "asav-9101-100.tar.gz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20ASAv/asav-9101-100.tar.gz", "asav", 2048)
_add("Cisco CSR1000v", "CSR1000v 17.03.05", "csr1000vng-universalk9.17.03.05-serial.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20CSR1000v/csr1000vng-universalk9.17.03.05-serial.tgz", "csr1000vng", 4096)
_add("Cisco CSR1000v", "CSR1000v 17.03.03", "csr1000vng-universalk9.17.03.03-serial.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20CSR1000v/csr1000vng-universalk9.17.03.03-serial.tgz", "csr1000vng", 4096)
_add("Cisco CSR1000v", "CSR1000v 16.12.05", "csr1000vng-universalk9.16.12.05-serial.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20CSR1000v/csr1000vng-universalk9.16.12.05-serial.tgz", "csr1000vng", 4096)
_add("Cisco Cat8000v", "Catalyst 8000v 17.06.03", "c8000v-17.06.03.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20C8000v/c8000v-17.06.03.tgz", "c8000v", 4096)
_add("Cisco Cat8000v", "Catalyst 8000v 17.04.01", "catalyst8000v-17.04.01.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20C8000v/catalyst8000v-17.04.01.tgz", "c8000v", 4096)
_add("Cisco Cat9000v", "Catalyst 9000v 17.10.01", "cat9kv-17.10.01-prd7.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20Catalyst%209000v/cat9kv-17.10.01-prd7.tgz", "cat9kv", 6144)
_add("Cisco ISRv", "ISRv 17.01.01", "isrv-17.01.01.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20ISRv/isrv-17.01.01.tgz", "isrv", 4096)
_add("Cisco Nexus", "NX-OSv Titanium 7.3.0", "titanium-final.7.3.0.D1.1.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20Nexus%20Titanium/titanium-final.7.3.0.D1.1.tgz", "titanium", 4096)
_add("Cisco vWLC", "vWLC 8.7.102", "vwlc-8.7.102.tar.gz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20vWLC/vwlc-8.7.102.tar.gz", "vwlc", 2048)
_add("Cisco ISE", "ISE 3.1.0.518", "ise-3.1.0.518.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20ISE/ise-3.1.0.518.tgz", "ise", 16384)
_add("Cisco ESA", "ESA 14.2.1-020", "phoebe-14-2-1-020-C100V.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20ESA/phoebe-14-2-1-020-C100V.tgz", "phoebe", 4096)
_add("Cisco WSA", "WSA 15.2.0-116", "coeus-15-2-0-116-S100V.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20WSA/coeus-15-2-0-116-S100V.tgz", "coeus", 4096)
_add("Cisco Viptela", "vBond 20.7.1", "vtbond-20.7.1.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20Viptela/vtbond-20.7.1.tgz", "vtbond", 4096)
_add("Cisco Viptela", "vEdge 20.7.1", "vtedge-20.7.1.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20Viptela/vtedge-20.7.1.tgz", "vtedge", 4096)
_add("Cisco Viptela", "vManage 20.7.1", "vtmgmt-20.7.1-002.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20Viptela/vtmgmt-20.7.1-002.tgz", "vtmgmt", 16384)
_add("Cisco Viptela", "vSmart 20.7.1", "vtsmart-20.7.1.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20Viptela/vtsmart-20.7.1.tgz", "vtsmart", 4096)

# ---------------- Firewalls ----------------
_add("Fortinet", "FortiGate 7.2.0", "fortinet-FGT-v7.2.0-build1157.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Fortinet/fortinet-FGT-v7.2.0-build1157.tgz", "fortinet", 2048)
_add("Fortinet", "FortiManager 7.2.2", "fortinet-FMG-v7.2.2-build1334.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Fortinet/fortinet-FMG-v7.2.2-build1334.tgz", "fortinet", 4096)
_add("Palo Alto", "PAN-OS 10.2.5 (eval)", "paloalto-10.2.5-Pre-Licensed-Eval.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Palo%20Alto/paloalto-10.2.5-Pre-Licensed-Eval.tgz", "paloalto", 4096)
_add("Palo Alto", "Panorama 9.1.2", "panorama-9.1.2.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Palo%20Alto/panorama-9.1.2.tgz", "panorama", 4096)
_add("Check Point", "R81.20 (install ISO)", "Check_Point_R81.20_T634.iso",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Check%20Point/Check_Point_R81.20_T634.iso", "cpsg", 4096, "iso")
_add("Barracuda", "Barracuda FW 8.0.3", "barracuda-fw8.0.3.0137-20200426.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Barracuda/barracuda-fw8.0.3.0137-20200426.tgz", "barracuda", 2048)
_add("Sophos", "Sophos UTM 9.704-3", "sophosutm-UTM-9.704-3.1.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Sophos%20UTM/sophosutm-UTM-9.704-3.1.tgz", "sophosutm", 1024)
_add("F5", "BIGIP 17.0.0", "bigip-17.0.0-0.0.22.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/F5%20BIGIP/bigip-17.0.0-0.0.22.tgz", "bigip", 8192)

# ---------------- Routers / switches / others ----------------
_add("Arista", "vEOS 4.28.0F", "veos-4.28.0F.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Arista/veos-4.28.0F.tgz", "veos", 2048)
_add("Aruba", "Aruba CX 10.07", "arubacx-10.07.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Aruba%20CX/arubacx-10.07.tgz", "arubacx", 4096)
_add("Aruba", "ClearPass 6.8.0", "clearpass-6.8.0.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Aruba%20ClearPass/clearpass-6.8.0.tgz", "clearpass", 8192)
_add("MikroTik", "RouterOS 7.5", "mikrotik-7.5.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Mikrotik/mikrotik-7.5.tgz", "mikrotik", 512)
_add("Citrix", "Netscaler 14.1-12.30", "nsvpx-14.1-12.30.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Citrix%20Netscaler/nsvpx-14.1-12.30.tgz", "nsvpx", 4096)
_add("Versa", "FlexVNF 21.1.2", "versafvnf-21.1.2.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Versa%20Networks%20SD-WAN/versafvnf-21.1.2.tgz", "versafvnf", 4096)
_add("Alienvault", "OSSIM 5.8.5", "alienvault-ossim-5.8.5.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Alienvault/alienvault-ossim-5.8.5.tgz", "alienvault", 8192)

# ---------------- Linux ----------------
_add("Linux", "Ubuntu Server 20.04", "linux-ubuntu-server-20.04.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Linux/linux-ubuntu-server-20.04.tgz", "linux", 1024)
_add("Linux", "Ubuntu Server 18.04.4", "linux-ubuntu-server-18.04.4.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Linux/linux-ubuntu-server-18.04.4.tgz", "linux", 1024)
_add("Linux", "Debian 10.3", "linux-debian-10.3.0.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Linux/linux-debian-10.3.0.tgz", "linux", 1024)
_add("Linux", "Kali 2019.3 (large)", "linux-kali-large-2019.3.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Linux/linux-kali-large-2019.3.tgz", "linux", 2048)
_add("Linux", "CentOS 8", "linux-centos-8.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Linux/linux-centos-8.tgz", "linux", 1024)
_add("Linux", "RHEL 8.4", "linux-rhel-8.4.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Linux/linux-rhel-8.4.tgz", "linux", 1024)

# ---------------- Windows ----------------
_add("Windows", "Server 2019 R2 x64", "winserver-S2019-R2-x64-rev3.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Windows/winserver-S2019-R2-x64-rev3.tgz", "winserver", 4096)
_add("Windows", "Windows 10 x64 21H1", "win-10-x64-21H1v1.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Windows/win-10-x64-21H1v1.tgz", "win", 4096)

# ---------------- LabHub.eu.org (verified live) ----------------
_LH = "https://legacy.labhub.eu.org/1:/addons/qemu"

_add("Fortinet", "FortiGate 7.4.4", "fortinet-FGT-v7.4.4-build2571.tgz",
     f"{_LH}/Fortinet/fortinet-FGT-v7.4.4-build2571.tgz", "fortinet", 2048)
_add("Fortinet", "FortiGate 7.4.3", "fortinet-FGT-v7.4.3-build2532.tgz",
     f"{_LH}/Fortinet/fortinet-FGT-v7.4.3-build2532.tgz", "fortinet", 2048)
_add("Fortinet", "FortiGate 7.2.5", "fortinet-FGT-v7.2.5-build1396.tgz",
     f"{_LH}/Fortinet/fortinet-FGT-v7.2.5-build1396.tgz", "fortinet", 2048)
_add("Fortinet", "FortiManager 7.4.1", "fortinet-FMG-v7.4.1-build2512.tgz",
     f"{_LH}/Fortinet/fortinet-FMG-v7.4.1-build2512.tgz", "fortinet", 4096)
_add("Palo Alto", "PAN-OS 11.1.2", "paloalto-11.1.2.tar.gz",
     f"{_LH}/Palo%20Alto/paloalto-11.1.2.tar.gz", "paloalto", 4096)
_add("Palo Alto", "PAN-OS 11.0.3", "paloalto-11.0.3.tar.gz",
     f"{_LH}/Palo%20Alto/paloalto-11.0.3.tar.gz", "paloalto", 4096)
_add("Palo Alto", "PAN-OS 10.2.9", "paloalto-10.2.9.tar.gz",
     f"{_LH}/Palo%20Alto/paloalto-10.2.9.tar.gz", "paloalto", 4096)
_add("Palo Alto", "PAN-OS 11.1.0", "paloalto-11.1.0.tar.gz",
     f"{_LH}/Palo%20Alto/paloalto-11.1.0.tar.gz", "paloalto", 4096)
_add("Palo Alto", "Panorama 10.2.3", "panorama-10.2.3.tar.gz",
     f"{_LH}/Palo%20Alto/panorama-10.2.3.tar.gz", "panorama", 4096)
_add("Cisco vIOS", "vIOS 15.9(3)M5", "vios-adventerprisek9-m.SPA.159-3.M5.tgz",
     f"{_LH}/Cisco%20IOSv/vios-adventerprisek9-m.SPA.159-3.M5.tgz", "vios", 1024)
_add("Cisco vIOS-L2", "vIOS-L2 2023-07", "viosl2-adventerprisek9-m.SSA.20230712.tgz",
     f"{_LH}/Cisco%20IOSvL2/viosl2-adventerprisek9-m.SSA.20230712.tgz", "viosl2", 1024)
_add("Cisco CSR1000v", "CSR1000v 17.06.05", "csr1000vng-universalk9.17.06.05-serial.tgz",
     f"{_LH}/Cisco%20CSR1000v/csr1000vng-universalk9.17.06.05-serial.tgz", "csr1000vng", 4096)
_add("Cisco CSR1000v", "CSR1000v 17.06.03a", "csr1000vng-universalk9.17.06.03a-serial.tgz",
     f"{_LH}/Cisco%20CSR1000v/csr1000vng-universalk9.17.06.03a-serial.tgz", "csr1000vng", 4096)
_add("Cisco Cat8000v", "Cat8000v 17.12.01a", "c8000v-17.12.01a.tgz",
     f"{_LH}/Cisco%20C8000v/c8000v-17.12.01a.tgz", "c8000v", 4096)
_add("Cisco Cat8000v", "Cat8000v 17.11.01a", "c8000v-17.11.01a.tgz",
     f"{_LH}/Cisco%20C8000v/c8000v-17.11.01a.tgz", "c8000v", 4096)
_add("Cisco Cat8000v", "Cat8000v 17.10.01a", "c8000v-17.10.01a.tgz",
     f"{_LH}/Cisco%20C8000v/c8000v-17.10.01a.tgz", "c8000v", 4096)
_add("Cisco ISE", "ISE 3.2.0.542", "ise-3.2.0.542.tgz",
     f"{_LH}/Cisco%20ISE/ise-3.2.0.542.tgz", "ise", 16384)
_add("Cisco ISE", "ISE 3.3.0.531", "ise-3.3.0.531.tgz",
     f"{_LH}/Cisco%20ISE/ise-3.3.0.531.tgz", "ise", 16384)
_add("Cisco FirePOWER", "FTD 7.2.3-64", "firepower7-FTD-7.2.3-64.tgz",
     f"{_LH}/Cisco%20FirePOWER/firepower7-FTD-7.2.3-64.tgz", "firepower7", 8192)
_add("Cisco FirePOWER", "FMC 7.0.1-84", "firepower6-FMC-7.0.1-84.tgz",
     f"{_LH}/Cisco%20FirePOWER/firepower6-FMC-7.0.1-84.tgz", "firepower6", 16384)
_add("Cisco Nexus", "NX-OS 9000v 9.3.3", "nexus-9000v-9.3.3.tgz",
     f"{_LH}/Cisco%20NX-OS%20Titanium/nexus-9000v-9.3.3.tgz", "titanium", 4096)
_add("Linux", "Ubuntu Server 22.04", "linux-ubuntu-server-22.04.tgz",
     f"{_LH}/Linux/linux-ubuntu-server-22.04.tgz", "linux", 1024)
_add("Linux", "Ubuntu Server 24.04", "linux-ubuntu-server-24.04.tgz",
     f"{_LH}/Linux/linux-ubuntu-server-24.04.tgz", "linux", 1024)
_add("Linux", "Ubuntu Desktop 22.04", "linux-ubuntu-desktop-22.04.tgz",
     f"{_LH}/Linux/linux-ubuntu-desktop-22.04.tgz", "linux", 2048)
_add("Linux", "Debian 11", "linux-debian-11.tgz",
     f"{_LH}/Linux/linux-debian-11.tgz", "linux", 1024)
_add("Linux", "Kali 2024.1", "linux-kali-2024.1.tgz",
     f"{_LH}/Linux/linux-kali-2024.1.tgz", "linux", 2048)
_add("Linux", "CentOS 9", "linux-centos-9.tgz",
     f"{_LH}/Linux/linux-centos-9.tgz", "linux", 1024)
_add("MikroTik", "RouterOS 7.15.3", "mikrotik-7.15.3.tgz",
     f"{_LH}/Mikrotik/mikrotik-7.15.3.tgz", "mikrotik", 512)
_add("MikroTik", "RouterOS 7.14.3", "mikrotik-7.14.3.tgz",
     f"{_LH}/Mikrotik/mikrotik-7.14.3.tgz", "mikrotik", 512)
_add("MikroTik", "RouterOS 7.13.5", "mikrotik-7.13.5.tgz",
     f"{_LH}/Mikrotik/mikrotik-7.13.5.tgz", "mikrotik", 512)
_add("MikroTik", "RouterOS 7.12.1", "mikrotik-7.12.1.tgz",
     f"{_LH}/Mikrotik/mikrotik-7.12.1.tgz", "mikrotik", 512)
_add("Windows", "Server 2022 x64", "winserver-S2022-x64.tgz",
     f"{_LH}/Windows/winserver-S2022-x64.tgz", "winserver", 4096)
_add("Windows", "Server 2016 x64", "winserver-S2016-x64.tgz",
     f"{_LH}/Windows/winserver-S2016-x64.tgz", "winserver", 4096)
_add("Windows", "Windows 11 22H2", "win-11-x64-22H2v2.tgz",
     f"{_LH}/Windows/win-11-x64-22H2v2.tgz", "win", 4096)
_add("Windows", "Windows 10 22H2", "win-10-x64-22H2v1.tgz",
     f"{_LH}/Windows/win-10-x64-22H2v1.tgz", "win", 4096)
_add("Arista", "vEOS 4.31.1F", "veos-4.31.1F.tgz",
     f"{_LH}/Arista/veos-4.31.1F.tgz", "veos", 2048)
_add("Arista", "vEOS 4.30.1F", "veos-4.30.1F.tgz",
     f"{_LH}/Arista/veos-4.30.1F.tgz", "veos", 2048)
_add("Arista", "vEOS 4.29.1F", "veos-4.29.1F.tgz",
     f"{_LH}/Arista/veos-4.29.1F.tgz", "veos", 2048)
_add("Aruba", "Aruba CX 10.10", "arubacx-10.10.tgz",
     f"{_LH}/Aruba%20CX/arubacx-10.10.tgz", "arubacx", 4096)
_add("Aruba", "Aruba CX 10.09", "arubacx-10.09.tgz",
     f"{_LH}/Aruba%20CX/arubacx-10.09.tgz", "arubacx", 4096)
_add("Aruba", "ClearPass 6.11", "clearpass-6.11.0.tgz",
     f"{_LH}/Aruba%20ClearPass/clearpass-6.11.0.tgz", "clearpass", 8192)
_add("F5", "BIGIP 17.1.0", "bigip-17.1.0-0.0.3.tgz",
     f"{_LH}/F5%20BIGIP/bigip-17.1.0-0.0.3.tgz", "bigip", 8192)
_add("F5", "BIGIP 16.1.3", "bigip-16.1.3-0.0.28.tgz",
     f"{_LH}/F5%20BIGIP/bigip-16.1.3-0.0.28.tgz", "bigip", 8192)
_add("Juniper", "vSRX 21.4R1.12", "vsrxng-21.4R1.12.tgz",
     f"{_LH}/Juniper/vsrxng-21.4R1.12.tgz", "vsrxng", 4096)
_add("Juniper", "vSRX 22.4R2.8", "vsrxng-22.4R2.8.tgz",
     f"{_LH}/Juniper/vsrxng-22.4R2.8.tgz", "vsrxng", 4096)
_add("Juniper", "vMX 21.2R3.11", "vmx-21.2R3.11.tgz",
     f"{_LH}/Juniper/vmx-21.2R3.11.tgz", "vmx", 4096)
_add("Juniper", "vMX 22.3R2.9", "vmx-22.3R2.9.tgz",
     f"{_LH}/Juniper/vmx-22.3R2.9.tgz", "vmx", 4096)

VENDORS = ["All vendors"] + sorted({e["vendor"] for e in CATALOG})


def direct_download(url: str, dest_path: str, progress_cb=None, timeout: float = 30.0):
    """
    Plain HTTP/HTTPS direct download with streaming progress.
    progress_cb(percent:int, message:str) is called while streaming.
    """
    import requests

    resp = requests.get(url, stream=True, timeout=timeout)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0) or 0)
    done = 0
    with open(dest_path, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=1024 * 256):
            if not chunk:
                continue
            fh.write(chunk)
            done += len(chunk)
            if progress_cb:
                pct = int(done / total * 100) if total else 0
                mb = done // (1024 * 1024)
                msg = f"{mb} MB" + (f" / {total // (1024*1024)} MB" if total else "")
                progress_cb(pct if total else min(done // (1024 * 1024), 99),
                            f"downloading {msg}")
    return dest_path


def google_drive_download(file_id: str, dest_path: str, progress_cb=None, timeout: float = 30.0):
    """
    Downloads a file from Google Drive, handling the large-file
    'virus scan' confirmation page automatically.
    progress_cb(percent:int, message:str) is called while streaming.
    """
    import requests

    session = requests.Session()
    url = "https://drive.google.com/uc?export=download"
    resp = session.get(url, params={"id": file_id}, stream=True, timeout=timeout)

    if "text/html" in resp.headers.get("content-type", ""):
        # Large-file confirmation page — extract token and re-request.
        html = resp.text
        params = {"id": file_id, "export": "download", "confirm": "t"}
        uuid_m = re.search(r'name="uuid"\s+value="([^"]+)"', html)
        if uuid_m:
            params["uuid"] = uuid_m.group(1)
        resp.close()
        resp = session.get("https://drive.usercontent.google.com/download",
                           params=params, stream=True, timeout=timeout)

    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0) or 0)
    done = 0
    with open(dest_path, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=1024 * 256):
            if not chunk:
                continue
            fh.write(chunk)
            done += len(chunk)
            if progress_cb:
                pct = int(done / total * 100) if total else 0
                mb = done // (1024 * 1024)
                msg = f"{mb} MB" + (f" / {total // (1024*1024)} MB" if total else "")
                progress_cb(pct if total else min(done // (1024 * 1024), 99),
                            f"downloading {msg}")
    return dest_path
