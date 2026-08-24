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
     "https://drive.google.com/uc?export=download&id=1SVCqx7KOfRUkVwedtq7wFSWSEjVBQd32", "vios", 1024)
_add("Cisco vIOS", "vIOS 15.9(3)M6", "vios-adventerprisek9-m.SPA.159-3.M6.tgz",
     "https://drive.google.com/uc?export=download&id=10SMwVfnrbpj4OtJo9QPIsOYUh1W6UDAn", "vios", 1024)
_add("Cisco vIOS", "vIOS 15.9(3)M4", "vios-adventerprisek9-m.SPA.159-3.M4.tgz",
     "https://drive.google.com/uc?export=download&id=1SN-_V9atlCGBGpxO3NJjlMeCm0VmKjaP", "vios", 1024)
_add("Cisco vIOS-L2", "vIOS-L2 high-iron 2020", "viosl2-adventerprisek9-m.ssa.high_iron_20200929.tgz",
     "https://drive.google.com/uc?export=download&id=1lgdL0muj12c0zr4p6ZAQXRq9OZh49sPc", "viosl2", 1024)
_add("Cisco vIOS-L2", "vIOS-L2 high-iron 2018", "viosl2-adventerprisek9-m.SSA.high_iron_20180619.tgz",
     "https://drive.google.com/uc?export=download&id=1bD9Yvwfo5P9UgwxC9u3xlPft7GIjcKNu", "viosl2", 1024)
_add("Cisco ASAv", "ASAv 9.17.1", "asav-9-17-1-10.tgz",
     "https://drive.google.com/uc?export=download&id=1OMGD_Hl-07Ygs58Q-qRZpP-0RDJammbT", "asav", 2048)
_add("Cisco ASAv", "ASAv 9.18.1", "asav-9-18-1.tgz",
     "https://drive.google.com/uc?export=download&id=18HXNz5mJwgTyskxFzEEFOiBl-8YMasDG", "asav", 2048)
_add("Cisco ASAv", "ASAv 9.16.1-28", "asav-916-1-28.tgz",
     "https://drive.google.com/uc?export=download&id=1ISYEeMk9An--hdoOO4oUTZid7StZj05B", "asav", 2048)
_add("Cisco ASAv", "ASAv 9.10.1-100", "asav-9101-100.tar.gz",
     "https://drive.google.com/uc?export=download&id=1Sso1Ef5TOi4aHmC8bHlMNRAVyqfUfjwP", "asav", 2048)
_add("Cisco CSR1000v", "CSR1000v 17.03.05", "csr1000vng-universalk9.17.03.05-serial.tgz",
     "https://drive.google.com/uc?export=download&id=1sa32PPR1N5eoCloRVL9rWtvn-NO94OMl", "csr1000vng", 4096)
_add("Cisco CSR1000v", "CSR1000v 17.03.03", "csr1000vng-universalk9.17.03.03-serial.tgz",
     "https://drive.google.com/uc?export=download&id=1vCmc4BsF0Wg-1EkAII9m_LURfB08cVJv", "csr1000vng", 4096)
_add("Cisco CSR1000v", "CSR1000v 16.12.05", "csr1000vng-universalk9.16.12.05-serial.tgz",
     "https://drive.google.com/uc?export=download&id=1NcneLlGxy2I_dxKe9juV-VFFogQBV1-5", "csr1000vng", 4096)
_add("Cisco Cat8000v", "Catalyst 8000v 17.06.03", "c8000v-17.06.03.tgz",
     "https://drive.google.com/uc?export=download&id=1aXteE3NwFhtYDfvQrreXpLWr9q8LcL3J", "c8000v", 4096)
_add("Cisco Cat8000v", "Catalyst 8000v 17.04.01", "catalyst8000v-17.04.01.tgz",
     "https://drive.google.com/uc?export=download&id=1CbndphsEJVVX0wdZvbXOF4cIrWuFmvF9", "c8000v", 4096)
_add("Cisco Cat9000v", "Catalyst 9000v 17.10.01", "cat9kv-17.10.01-prd7.tgz",
     "https://drive.google.com/uc?export=download&id=1kjG_a9xkqaH7iIRwp2BT6bimQNB884jK", "cat9kv", 6144)
_add("Cisco ISRv", "ISRv 17.01.01", "isrv-17.01.01.tgz",
     "https://drive.google.com/uc?export=download&id=1IV_cYG8ysxQ_7EtwvOehaIeZnMbWHJ7L", "isrv", 4096)
_add("Cisco Nexus", "NX-OSv Titanium 7.3.0", "titanium-final.7.3.0.D1.1.tgz",
     "https://drive.google.com/uc?export=download&id=1Xo-9UkJ7XanFkTaHTBW2hI4mzS3VAnsF", "titanium", 4096)
_add("Cisco vWLC", "vWLC 8.7.102", "vwlc-8.7.102.tar.gz",
     "https://drive.google.com/uc?export=download&id=1a18vFHz_WRsDEnCb_iNjlLAT11iQOYnv", "vwlc", 2048)
_add("Cisco ISE", "ISE 3.1.0.518", "ise-3.1.0.518.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20ISE/ise-3.1.0.518.tgz", "ise", 16384)
_add("Cisco ESA", "ESA 14.2.1-020", "phoebe-14-2-1-020-C100V.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20ESA/phoebe-14-2-1-020-C100V.tgz", "phoebe", 4096)
_add("Cisco WSA", "WSA 15.2.0-116", "coeus-15-2-0-116-S100V.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Cisco%20WSA/coeus-15-2-0-116-S100V.tgz", "coeus", 4096)
_add("Cisco Viptela", "vBond 20.7.1", "vtbond-20.7.1.tgz",
     "https://drive.google.com/uc?export=download&id=1aYAagitlfk0v8AxyIEmy_xYjnDY04vwA", "vtbond", 4096)
_add("Cisco Viptela", "vEdge 20.7.1", "vtedge-20.7.1.tgz",
     "https://drive.google.com/uc?export=download&id=1O330mPeime1X_ZuQ6HS5L4wvY7Kqq2sI", "vtedge", 4096)
_add("Cisco Viptela", "vManage 20.7.1", "vtmgmt-20.7.1-002.tgz",
     "https://drive.google.com/uc?export=download&id=1WfEI3xa94SRk8GK6Nze__ihgIYc230Am", "vtmgmt", 16384)
_add("Cisco Viptela", "vSmart 20.7.1", "vtsmart-20.7.1.tgz",
     "https://drive.google.com/uc?export=download&id=1kXBJmGPAfVe9fqlAqp_HEr5K_jpdji_n", "vtsmart", 4096)

# ---------------- Firewalls ----------------
_add("Fortinet", "FortiGate 7.2.0", "fortinet-FGT-v7.2.0-build1157.tgz",
     "https://drive.google.com/uc?export=download&id=1G4RgntQrZ-qxjRO-5SoYG-7QNZ_wYizY", "fortinet", 2048)
_add("Fortinet", "FortiManager 7.2.2", "fortinet-FMG-v7.2.2-build1334.tgz",
     "https://drive.google.com/uc?export=download&id=1_OwGDUG7ARpY-IXq_Pu2Kn7H5gllRfw_", "fortinet", 4096)
_add("Palo Alto", "PAN-OS 10.2.5 (eval)", "paloalto-10.2.5-Pre-Licensed-Eval.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Palo%20Alto/paloalto-10.2.5-Pre-Licensed-Eval.tgz", "paloalto", 4096)
_add("Palo Alto", "Panorama 9.1.2", "panorama-9.1.2.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Palo%20Alto/panorama-9.1.2.tgz", "panorama", 4096)
_add("Check Point", "R81.20 (install ISO)", "Check_Point_R81.20_T634.iso",
     "https://drive.google.com/uc?export=download&id=1jYMPsISHoMl71D46G6Dhxou7Q2rBEOcz", "cpsg", 4096, "iso")
_add("Barracuda", "Barracuda FW 8.0.3", "barracuda-fw8.0.3.0137-20200426.tgz",
     "https://drive.google.com/uc?export=download&id=1ceePAkcqU3OmRtFZE1Z8hs9ZgxrrYj1R", "barracuda", 2048)
_add("Sophos", "Sophos UTM 9.704-3", "sophosutm-UTM-9.704-3.1.tgz",
     "https://drive.google.com/uc?export=download&id=18ILOAGbQjS5FnkKIsPO3d0k58cBogMvj", "sophosutm", 1024)
_add("F5", "BIGIP 17.0.0", "bigip-17.0.0-0.0.22.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/F5%20BIGIP/bigip-17.0.0-0.0.22.tgz", "bigip", 8192)

# ---------------- Routers / switches / others ----------------
_add("Arista", "vEOS 4.28.0F", "veos-4.28.0F.tgz",
     "https://drive.google.com/uc?export=download&id=1aoJDbkCUaqhpJYb3GcEtNaIRSMwYV17a", "veos", 2048)
_add("Aruba", "Aruba CX 10.07", "arubacx-10.07.tgz",
     "https://drive.google.com/uc?export=download&id=1AFj_65JrzkF-hQklXwkrRmp_kISKKDmP", "arubacx", 4096)
_add("Aruba", "ClearPass 6.8.0", "clearpass-6.8.0.tgz",
     "https://drive.google.com/uc?export=download&id=1vKJhrNVwJuCybfN7Fp128giB7h8slTuq", "clearpass", 8192)
_add("MikroTik", "RouterOS 7.5", "mikrotik-7.5.tgz",
     "https://drive.google.com/uc?export=download&id=1BN-n0kn7L9Pek8M6GdUra31b2hZPlel7", "mikrotik", 512)
_add("Citrix", "Netscaler 14.1-12.30", "nsvpx-14.1-12.30.tgz",
     "https://drive.google.com/uc?export=download&id=1gOOGhbP2zOb8OuCznLaydHg4GXy4ysA-", "nsvpx", 4096)
_add("Versa", "FlexVNF 21.1.2", "versafvnf-21.1.2.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Versa%20Networks%20SD-WAN/versafvnf-21.1.2.tgz", "versafvnf", 4096)
_add("Alienvault", "OSSIM 5.8.5", "alienvault-ossim-5.8.5.tgz",
     "https://drive.google.com/uc?export=download&id=1nRDRd3PRLVxIfxEn2xnfcrN6qBSjLCvj", "alienvault", 8192)

# ---------------- Linux ----------------
_add("Linux", "Ubuntu Server 20.04", "linux-ubuntu-server-20.04.tgz",
     "https://drive.google.com/uc?export=download&id=10n65xQo_d929qJg1rV3I6uxWM5Ax1GLB", "linux", 1024)
_add("Linux", "Ubuntu Server 18.04.4", "linux-ubuntu-server-18.04.4.tgz",
     "https://drive.google.com/uc?export=download&id=111f5GpWXnAOEjgR6lGu8tHDP4wWivJ-x", "linux", 1024)
_add("Linux", "Debian 10.3", "linux-debian-10.3.0.tgz",
     "https://drive.google.com/uc?export=download&id=1dPXwEqcpPfAaYRQLGUGJHgQuyhVOgcoy", "linux", 1024)
_add("Linux", "Kali 2019.3 (large)", "linux-kali-large-2019.3.tgz",
     "https://drive.google.com/uc?export=download&id=1Nud7nHICZyo1ptkxYNUUOOqrxU3Z_wKI", "linux", 2048)
_add("Linux", "CentOS 8", "linux-centos-8.tgz",
     "https://drive.google.com/uc?export=download&id=1yZuuhkPUOsEK-wMMvbJkRfAETQOdFaP_", "linux", 1024)
_add("Linux", "RHEL 8.4", "linux-rhel-8.4.tgz",
     "https://drive.google.com/uc?export=download&id=1gmcDHJmfI9SJlCJKKVf99LumOMQ4lyrY", "linux", 1024)

# ---------------- Windows ----------------
_add("Windows", "Server 2019 R2 x64", "winserver-S2019-R2-x64-rev3.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Windows/winserver-S2019-R2-x64-rev3.tgz", "winserver", 4096)
_add("Windows", "Windows 10 x64 21H1", "win-10-x64-21H1v1.tgz",
     "https://legacy.labhub.eu.org/1:/addons/qemu/Windows/win-10-x64-21H1v1.tgz", "win", 4096)

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
