"""
EVE-NG Image Upload & Deployment Manager
-----------------------------------------
Implements image installation the way EVE-NG's own documentation describes it
(https://www.eve-ng.net/index.php/documentation/howtos/ and
https://www.eve-ng.net/index.php/documentation/qemu-image-namings/):

  QEMU images   -> /opt/unetlab/addons/qemu/<prefix-name>/<diskname>.qcow2
                   Folder name MUST start with the vendor's required prefix
                   (e.g. "asav-", "vios-", "csr1000vng-"). Disk file name
                   depends on vendor (virtioa.qcow2, hda.qcow2, sataa.qcow2...).
                   If the downloaded image isn't already qcow2 (vmdk/raw/img/
                   vhd/ova-extracted disk), it must be converted with
                   `qemu-img convert` on the EVE-NG host before use.

  IOL images    -> /opt/unetlab/addons/iol/bin/<image>.bin, chmod +x.
                   Some newer IOL XE downloads are missing the .bin extension
                   and must have it appended, or EVE-NG won't recognize them.
                   An iourc license file is required for IOL/IOU nodes to run.

  Dynamips imgs -> /opt/unetlab/addons/dynamips/<image>.image
                   The downloaded .bin is a *compressed* IOS image and must be
                   decompressed with `unzip -p file.bin > file.image` on the
                   EVE-NG host — simply renaming/uploading it as-is will not
                   produce a working image.

  ISO-install   -> Some QEMU platforms (CSR1000v, XRv9000, some Firepower
  images           builds) ship as an install ISO rather than a ready qcow2.
                   These require booting the ISO against a blank qcow2 with
                   qemu-system-x86_64 and completing an interactive installer,
                   then moving the resulting disk into the final image folder.
                   This module prepares everything scriptable (blank disk,
                   ISO upload, exact install command) and exposes a finalize
                   step; the interactive install itself is done by the user
                   in a real console, since safely automating install-wizard
                   keypresses across many different vendor ISOs isn't reliable.

Note: This uses the EVE-NG host's root SSH account (port 22), which is
separate from the API admin/eve login used by EveNGClient in eve_api.py.
"""

import os
import posixpath

try:
    import paramiko
except ImportError:  # pragma: no cover - surfaced as a friendly runtime error
    paramiko = None

# Standard EVE-NG addon directories (Community/PRO default layout)
REMOTE_BASE_PATHS = {
    "qemu": "/opt/unetlab/addons/qemu",
    "iol": "/opt/unetlab/addons/iol/bin",
    "dynamips": "/opt/unetlab/addons/dynamips",
}

FIXPERMISSIONS_CMD = "/opt/unetlab/wrappers/unl_wrapper -a fixpermissions"

# Disk image extensions that are NOT already qcow2 and need conversion on the
# EVE-NG host via `qemu-img convert` before they'll work as a QEMU node disk.
CONVERTIBLE_DISK_EXTENSIONS = {".vmdk", ".raw", ".img", ".vhd", ".vhdx", ".ova"}

# QEMU folder-name prefix -> (vendor label, [disk basenames without extension])
# Sourced from https://www.eve-ng.net/index.php/documentation/qemu-image-namings/
# Where a vendor supports multiple disks (e.g. F5 BIGIP), the first entry is
# the primary/first disk used for single-disk uploads via this tool.
QEMU_IMAGE_NAMING = [
    ("a10-", "A10 vThunder", ["hda"]),
    ("acs-", "Cisco ACS", ["hda"]),
    ("asa-", "Cisco ASA (ported)", ["hda"]),
    ("asav-", "Cisco ASAv", ["virtioa"]),
    ("ampcloud-", "Ampcloud Private", ["hda", "hdb", "hdc"]),
    ("alteon-", "Radware Alteon", ["virtioa"]),
    ("barracuda-", "Barracuda FW", ["hda"]),
    ("bigip-", "F5 BIG-IP", ["virtioa", "virtiob"]),
    ("brocadevadx-", "Brocade vADX", ["virtioa"]),
    ("cda-", "Cisco CDA", ["hda"]),
    ("cips-", "Cisco IPS", ["hda", "hdb"]),
    ("clearpass-", "Aruba ClearPass", ["hda", "hdb"]),
    ("aruba-", "Aruba Virtual Mobility Controller", ["hda", "hdb"]),
    ("arubacx-", "Aruba CX Switch", ["virtioa"]),
    ("coeus-", "Cisco WSA (coeus)", ["virtioa"]),
    ("phoebe-", "Cisco ESA", ["virtioa"]),
    ("cpsg-", "Checkpoint", ["hda"]),
    ("c8000v-", "Cisco Catalyst 8000v Router", ["virtioa"]),
    ("cat9kv-", "Cisco Catalyst 9000v", ["virtioa"]),
    ("cat9kvq200-", "Cisco Catalyst 9000v Q200", ["virtioa"]),
    ("cat9kvuadp-", "Cisco Catalyst 9000v UADP", ["virtioa"]),
    ("csr1000v-", "Cisco CSR1000v 3.x", ["virtioa"]),
    ("csr1000vng-", "Cisco CSR1000v 16.x/17.x (incl. SD-WAN)", ["virtioa"]),
    ("catc1k-", "Catalyst 1000v SD-WAN Edge", ["virtioa"]),
    ("catc8k-", "Catalyst 8000v SD-WAN Edge", ["virtioa"]),
    ("catcontrol-", "Catalyst Controller SD-WAN", ["virtioa"]),
    ("catvalid-", "Catalyst Validator SD-WAN", ["virtioa"]),
    ("catmanager-", "Catalyst Manager SD-WAN", ["virtioa", "virtiob"]),
    ("catvedge-", "Catalyst vEdge SD-WAN", ["virtioa"]),
    ("prime-", "Cisco Prime Infrastructure", ["virtioa"]),
    ("cucm-", "Cisco CUCM", ["virtioa"]),
    ("cumulus-", "Cumulus VX", ["virtioa"]),
    ("extremexos-", "Extreme EXOS", ["sataa"]),
    ("extremevoss-", "Extreme VOSS", ["hda"]),
    ("esxi-", "VMware ESXi", ["hda", "hdb", "hdc"]),
    ("firepower-", "Cisco Firepower 5.4 NGIPS", ["scsia"]),
    ("firepower6-", "Cisco Firepower 6.x (NGIPS/FMC/FTD)", ["virtioa"]),
    ("ftd7-", "Cisco Firepower 7 FTD", ["virtioa"]),
    ("fmc7-", "Cisco Firepower 7 FMC", ["virtioa"]),
    ("fortinet-", "Fortinet FortiGate/FortiManager/FortiMail", ["virtioa"]),
    ("fpfw-", "Forcepoint NGFW", ["hda"]),
    ("fpsmc-", "Forcepoint Security Manager", ["hda"]),
    ("hpvsr-", "HP Virtual Router (VSR1000)", ["hda"]),
    ("huaweiar1k-", "Huawei AR1000v", ["virtioa"]),
    ("huaweiusg6kv-", "Huawei USG6000v", ["hda"]),
    ("ise-", "Cisco ISE", ["virtioa"]),
    ("jspace-", "Junos Space", ["virtioa"]),
    ("infoblox-", "Infoblox DDI", ["virtioa"]),
    ("junipervrr-", "Juniper vRR", ["virtioa"]),
    ("kerio-", "Kerio Control FW", ["sataa"]),
    ("linux-", "Generic Linux", ["virtioa"]),
    ("mikrotik-", "Mikrotik Cloud Router", ["hda"]),
    ("nsvpx-", "Citrix Netscaler", ["virtioa"]),
    ("nsx-", "VMware NSX", ["hda"]),
    ("nxosv9k-", "Cisco Nexus 9000v (NX-OS)", ["sataa"]),
    ("olive-", "Juniper Olive", ["hda"]),
    ("ostinato-", "Ostinato Traffic Generator", ["hda"]),
    ("paloalto-", "Palo Alto FW", ["virtioa"]),
    ("panorama-", "Palo Alto Panorama", ["virtioa", "virtiob"]),
    ("pfsense-", "pfSense / OPNsense FW", ["virtioa"]),
    ("pulse-", "Pulse Secure Connect", ["virtioa"]),
    ("riverbed-", "Riverbed SteelHead", ["virtioa", "virtiob"]),
    ("scrutinizer-", "Plixer Scrutinizer Netflow", ["virtioa"]),
    ("silveredge-", "Silver Peak Edge", ["hda"]),
    ("silverorch-", "Silver Peak Orchestrator", ["hda"]),
    ("sonicwall-", "SonicWALL FW", ["sataa"]),
    ("sourcefire-", "Sourcefire NGIPS", ["scsia"]),
    ("sterra-", "S-Terra VPN/Gate", ["hda"]),
    ("stealth-", "Cisco StealthWatch", ["hda"]),
    ("timos-", "Alcatel-Lucent/Nokia TiMOS", ["hda"]),
    ("timoscpm-", "Nokia TiMOS 19 CPM", ["virtidea"]),
    ("timosiom-", "Nokia TiMOS 19 IOM", ["virtidea"]),
    ("titanium-", "Cisco NX-OS Titanium", ["virtioa"]),
    ("vcenter-", "VMware vCenter", ["sataa"]),
    ("veos-", "Arista vEOS", ["hda"]),
    ("veloedge-", "VeloCloud Edge", ["virtioa"]),
    ("velogw-", "VeloCloud Gateway", ["virtioa"]),
    ("veloorch-", "VeloCloud Orchestrator", ["virtioa", "virtiob", "virtioc"]),
    ("versaana-", "Versa Networks Analyzer", ["virtioa"]),
    ("versadir-", "Versa Networks Director", ["virtioa"]),
    ("versavnf-", "Versa Networks FlexVNF Edge", ["virtioa"]),
    ("vios-", "Cisco vIOS (L3 Router)", ["virtioa"]),
    ("viosl2-", "Cisco vIOS L2 (Switch)", ["virtioa"]),
    ("vjunosswitch-", "Juniper vJunos EX Switch", ["virtioa"]),
    ("vjunosrouter-", "Juniper vJunos Router", ["virtioa"]),
    ("vjunosevo-", "Juniper vJunos EVO Router", ["virtioa"]),
    ("vtbond-", "Cisco Viptela vBond", ["virtioa"]),
    ("vtedge-", "Cisco Viptela vEdge", ["virtioa"]),
    ("vtsmart-", "Cisco Viptela vSmart", ["virtioa"]),
    ("vtmgmt-", "Cisco Viptela vManage", ["virtioa", "virtiob"]),
    ("vmx-", "Juniper vMX Router", ["hda"]),
    ("vmxvcp-", "Juniper vMX-VCP", ["virtioa", "virtiob", "virtioc"]),
    ("vmxvfp-", "Juniper vMX-VFP", ["virtioa"]),
    ("vnam-", "Cisco VNAM", ["hda"]),
    ("vqfxpfe-", "Juniper vQFX-PFE", ["hda"]),
    ("vqfxre-", "Juniper vQFX-RE", ["hda"]),
    ("vsrx-", "Juniper vSRX 12.1", ["virtioa"]),
    ("vsrxng-", "Juniper vSRX 15.x+", ["virtioa"]),
    ("vwaas-", "Cisco WAAS", ["virtioa", "virtiob", "virtioc"]),
    ("vwlc-", "Cisco vWLC", ["megasasa"]),
    ("vyos-", "VyOS", ["virtioa"]),
    ("win-", "Windows Workstation (non-server)", ["hda"]),
    ("winserver-", "Windows Server", ["hda"]),
    ("xrv-", "Cisco XRv", ["hda"]),
    ("xrv9k-", "Cisco XRv 9000", ["virtioa"]),
    ("zabbix-", "Zabbix Monitoring", ["virtioa"]),
]


def find_qemu_naming(prefix_or_foldername: str):
    """
    Looks up the required disk-name pattern for a QEMU folder-name prefix
    (e.g. 'asav-' or a full folder name like 'asav-984-10'). Returns
    (prefix, vendor_label, [disk_basenames]) or None if no known prefix matches.
    """
    name = prefix_or_foldername.strip().lower()
    matches = [entry for entry in QEMU_IMAGE_NAMING if name.startswith(entry[0])]
    if not matches:
        return None
    # Prefer the longest matching prefix (most specific) in case of overlaps.
    return max(matches, key=lambda e: len(e[0]))


class EveImageUploader:
    """
    Manages an SSH + SFTP session to an EVE-NG host for uploading and
    installing node images (QEMU folders, IOL .bin files, Dynamips .image
    files) following EVE-NG's documented installation procedures.
    """

    def __init__(self, host: str, username: str = "root", password: str = "", port: int = 22):
        if paramiko is None:
            raise RuntimeError("paramiko is required for image upload. Install it with: pip install paramiko")
        self.host = host.strip()
        self.username = username
        self.password = password
        self.port = port
        self.ssh = None
        self.sftp = None

    def connect(self):
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(
            self.host, port=self.port, username=self.username,
            password=self.password, timeout=10, banner_timeout=15,
        )
        self.sftp = self.ssh.open_sftp()

    def close(self):
        try:
            if self.sftp:
                self.sftp.close()
            if self.ssh:
                self.ssh.close()
        except Exception:
            pass

    # ---------- Helpers ----------
    def _remote_mkdir_p(self, remote_dir: str):
        """Recursively create remote directories, similar to `mkdir -p`."""
        parts = remote_dir.strip("/").split("/")
        path = ""
        for part in parts:
            path += "/" + part
            try:
                self.sftp.stat(path)
            except IOError:
                self.sftp.mkdir(path)

    def run_command(self, command: str, timeout: float = 90.0) -> str:
        """Execute a command over SSH and return combined stdout+stderr."""
        _stdin, stdout, stderr = self.ssh.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="ignore")
        err = stderr.read().decode("utf-8", errors="ignore")
        return (out + err).strip()

    def fix_permissions(self) -> str:
        """Run EVE-NG's official fixpermissions wrapper on the server."""
        return self.run_command(FIXPERMISSIONS_CMD)

    def list_images(self, image_type: str):
        """List images/folders already present on the server for a given type."""
        base = REMOTE_BASE_PATHS.get(image_type)
        if not base:
            return []
        try:
            return sorted(self.sftp.listdir(base))
        except IOError:
            return []

    def _put_with_progress(self, local_file, remote_file, file_idx, total_files, progress_cb):
        file_size = os.path.getsize(local_file)

        def _cb(transferred, total):
            if progress_cb:
                pct = int((transferred / total) * 100) if total else 100
                progress_cb(file_idx, total_files, os.path.basename(local_file), pct)

        self.sftp.put(local_file, remote_file, callback=_cb if file_size > 0 else None)

    # ---------- QEMU: standard "drop-in" images (ASAv, vIOS, PaloAlto, etc.) ----------
    def upload_qemu_image(self, local_path: str, remote_folder_name: str, progress_cb=None,
                           convert_to_qcow2: bool = None) -> str:
        """
        Upload a QEMU image following EVE-NG's documented procedure:
        mkdir /opt/unetlab/addons/qemu/<folder> -> upload -> rename to the
        vendor-correct disk filename -> (if needed) convert to qcow2 on the
        host -> caller should then run fix_permissions().

        `local_path` may be a folder (its contents are uploaded and the first
        file is treated as the primary disk) or a single disk/image file.
        `remote_folder_name` must follow EVE-NG's naming convention, e.g.
        'asav-984-10' (see QEMU_IMAGE_NAMING / find_qemu_naming()).

        `convert_to_qcow2`: if None (default), auto-detects based on the
        uploaded file's extension (vmdk/raw/img/vhd/vhdx/ova -> convert).
        """
        remote_folder_name = remote_folder_name.strip().strip("/")
        remote_dir = posixpath.join(REMOTE_BASE_PATHS["qemu"], remote_folder_name)
        self._remote_mkdir_p(remote_dir)

        naming = find_qemu_naming(remote_folder_name)
        target_disk_base = naming[2][0] if naming else "virtioa"

        if os.path.isdir(local_path):
            files = sorted(
                os.path.join(local_path, f) for f in os.listdir(local_path)
                if os.path.isfile(os.path.join(local_path, f))
            )
            if not files:
                raise RuntimeError(f"No files found in folder: {local_path}")
            primary_local_file = files[0]
        else:
            primary_local_file = local_path

        _, ext = os.path.splitext(primary_local_file)
        ext = ext.lower()
        should_convert = convert_to_qcow2 if convert_to_qcow2 is not None else (ext in CONVERTIBLE_DISK_EXTENSIONS)

        if should_convert:
            # Upload as-is under its original extension, convert remotely, then remove the original.
            uploaded_name = f"{target_disk_base}_original{ext}"
            remote_uploaded_path = posixpath.join(remote_dir, uploaded_name)
            self._put_with_progress(primary_local_file, remote_uploaded_path, 1, 1, progress_cb)

            remote_final_path = posixpath.join(remote_dir, f"{target_disk_base}.qcow2")
            if progress_cb:
                progress_cb(1, 1, "Converting to qcow2 on server...", 100)
            self.convert_to_qcow2(remote_uploaded_path, remote_final_path)
            try:
                self.sftp.remove(remote_uploaded_path)
            except Exception:
                pass
            return remote_dir
        else:
            remote_final_path = posixpath.join(remote_dir, f"{target_disk_base}.qcow2")
            self._put_with_progress(primary_local_file, remote_final_path, 1, 1, progress_cb)
            return remote_dir

    def convert_to_qcow2(self, remote_src_path: str, remote_dst_path: str, timeout: float = 600.0) -> str:
        """
        Runs `qemu-img convert` on the EVE-NG host to produce a qcow2 disk
        from a vmdk/raw/img/vhd/ova-extracted source — required because
        EVE-NG QEMU nodes only accept qcow2 disks.
        """
        qemu_img_bin = self._find_qemu_img_binary()
        cmd = f'{qemu_img_bin} convert -O qcow2 "{remote_src_path}" "{remote_dst_path}"'
        output = self.run_command(cmd, timeout=timeout)
        try:
            self.sftp.stat(remote_dst_path)
        except IOError:
            raise RuntimeError(f"qemu-img convert did not produce the expected output file. Output: {output}")
        return output

    def _find_qemu_img_binary(self) -> str:
        for candidate in ("/opt/qemu/bin/qemu-img", "/usr/bin/qemu-img", "qemu-img"):
            check = self.run_command(f'test -x "{candidate}" && echo FOUND || which {candidate} 2>/dev/null')
            if check.strip():
                return candidate
        return "qemu-img"  # fall back and let the shell resolve it

    # ---------- QEMU: ISO-install images (CSR1000v, XRv9000, etc.) ----------
    def prepare_iso_install(self, local_iso_path: str, work_dir: str, disk_filename: str,
                             disk_size_gb: int = 8, progress_cb=None) -> str:
        """
        Prepares an interactive ISO installation: creates a temp working
        directory on the EVE-NG host, uploads the install ISO, and creates a
        blank qcow2 disk of the requested size — mirroring the manual steps
        in EVE-NG's CSR1000v/XRv9000-style howtos, up to (but not including)
        the actual interactive install.
        """
        self._remote_mkdir_p(work_dir)
        remote_iso_path = posixpath.join(work_dir, os.path.basename(local_iso_path))
        self._put_with_progress(local_iso_path, remote_iso_path, 1, 1, progress_cb)

        qemu_img_bin = self._find_qemu_img_binary()
        remote_disk_path = posixpath.join(work_dir, disk_filename)
        create_cmd = f'{qemu_img_bin} create -f qcow2 "{remote_disk_path}" {disk_size_gb}G'
        self.run_command(create_cmd)
        try:
            self.sftp.stat(remote_disk_path)
        except IOError:
            raise RuntimeError("Failed to create the blank install disk on the EVE-NG host.")

        return remote_iso_path

    @staticmethod
    def build_install_qemu_command(work_dir: str, iso_filename: str, disk_filename: str,
                                    ram_mb: int = 4096, machine_type: str = "pc-1.0",
                                    qemu_bin: str = "/opt/qemu-2.2.0/bin/qemu-system-x86_64") -> str:
        """
        Builds the exact interactive qemu-system-x86_64 install command as
        documented in EVE-NG's ISO-install howtos. Run this in a real SSH
        terminal (not scripted) since the installer requires watching the
        console and pressing keys (e.g. selecting the serial-console boot
        entry, and 'ctrl+a then c' then 'quit' to exit qemu when done).
        """
        return (
            f'cd "{work_dir}" && {qemu_bin} -nographic '
            f'-drive file={disk_filename},if=virtio,bus=0,unit=0,cache=none '
            f'-machine type={machine_type},accel=kvm -serial mon:stdio -nographic '
            f'-nodefconfig -nodefaults -rtc base=utc -cdrom {iso_filename} -boot order=dc -m {ram_mb}'
        )

    def finalize_iso_install(self, work_dir: str, disk_filename: str, remote_folder_name: str) -> str:
        """
        After the interactive install is complete and qemu has been quit,
        moves the resulting disk into its final EVE-NG image folder (renamed
        to the vendor-correct disk filename) and cleans up the temp work dir.
        """
        remote_folder_name = remote_folder_name.strip().strip("/")
        final_dir = posixpath.join(REMOTE_BASE_PATHS["qemu"], remote_folder_name)
        self._remote_mkdir_p(final_dir)

        naming = find_qemu_naming(remote_folder_name)
        target_disk_base = naming[2][0] if naming else "virtioa"
        src_path = posixpath.join(work_dir, disk_filename)
        dst_path = posixpath.join(final_dir, f"{target_disk_base}.qcow2")

        self.run_command(f'mv "{src_path}" "{dst_path}"')
        try:
            self.sftp.stat(dst_path)
        except IOError:
            raise RuntimeError(f"Move failed — expected disk at {dst_path} but it wasn't found. "
                                f"Did the install finish and was qemu quit cleanly?")

        self.run_command(f'rm -rf "{work_dir}"')
        return final_dir

    # ---------- Community .tgz image packs (Online Store) ----------
    def upload_tgz_image(self, local_tgz: str, remote_folder: str, progress_cb=None) -> str:
        """
        EVE-NG community image packs ship as .tgz archives containing
        virtioa.qcow2 (+ optional extra disks). Standard install: upload the
        archive into the image folder, extract it there, remove the archive,
        then the caller runs fixpermissions. Returns the remote folder path.
        """
        remote_folder = remote_folder.strip().strip("/")
        remote_dir = posixpath.join(REMOTE_BASE_PATHS["qemu"], remote_folder)
        self._remote_mkdir_p(remote_dir)

        base = os.path.basename(local_tgz)
        remote_tgz = posixpath.join(remote_dir, base)
        self._put_with_progress(local_tgz, remote_tgz, 1, 1, progress_cb)

        out = self.run_command(f'cd "{remote_dir}" && tar zxf "{base}" && rm -f "{base}"',
                               timeout=600)
        # verify a disk appeared
        listing = self.run_command(f'ls "{remote_dir}"', timeout=15)
        if "qcow2" not in listing and "iso" not in listing.lower():
            raise RuntimeError(f"Extraction produced no disk image in {remote_dir}. "
                               f"tar output: {out[:200]}")
        return remote_dir

    # ---------- IOL ----------
    def upload_iol_image(self, local_path: str, progress_cb=None) -> str:
        """
        Upload a single IOL/IOU .bin image and mark it executable. Per
        EVE-NG's docs, some newer IOL XE downloads are missing the .bin
        extension — this appends it automatically if needed.
        """
        base = REMOTE_BASE_PATHS["iol"]
        self._remote_mkdir_p(base)
        filename = os.path.basename(local_path)
        if not filename.lower().endswith(".bin"):
            filename += ".bin"
        remote_file = posixpath.join(base, filename)
        self._put_with_progress(local_path, remote_file, 1, 1, progress_cb)
        try:
            self.sftp.chmod(remote_file, 0o755)
        except Exception:
            pass
        return remote_file

    def write_iol_license(self, iourc_content: str) -> str:
        """
        Writes an iourc license file to /opt/unetlab/addons/iol/bin/iourc,
        required for IOL/IOU nodes to start (per EVE-NG's IOL howto).
        """
        base = REMOTE_BASE_PATHS["iol"]
        self._remote_mkdir_p(base)
        remote_path = posixpath.join(base, "iourc")
        with self.sftp.open(remote_path, "w") as f:
            f.write(iourc_content)
        try:
            self.sftp.chmod(remote_path, 0o644)
        except Exception:
            pass
        return remote_path

    # ---------- Dynamips ----------
    def upload_dynamips_image(self, local_path: str, progress_cb=None) -> str:
        """
        Upload a Dynamips IOS image following EVE-NG's documented procedure:
        the downloaded .bin is a *compressed* image and must be decompressed
        with `unzip -p file.bin > file.image` on the host before it will
        work — this method does that automatically. If the local file is
        already a .image (already decompressed), it's uploaded as-is.
        """
        work_dir = "/opt/unetlab/tmp/img_upload_tmp"
        self._remote_mkdir_p(work_dir)

        filename = os.path.basename(local_path)
        remote_upload_path = posixpath.join(work_dir, filename)
        self._put_with_progress(local_path, remote_upload_path, 1, 1, progress_cb)

        base = REMOTE_BASE_PATHS["dynamips"]
        self._remote_mkdir_p(base)

        if filename.lower().endswith(".image"):
            # Already decompressed — just move it into place.
            final_path = posixpath.join(base, filename)
            self.run_command(f'mv "{remote_upload_path}" "{final_path}"')
        else:
            image_filename = os.path.splitext(filename)[0] + ".image"
            remote_image_path = posixpath.join(work_dir, image_filename)
            if progress_cb:
                progress_cb(1, 1, "Decompressing IOS image on server...", 100)
            self.run_command(f'unzip -p "{remote_upload_path}" > "{remote_image_path}"')
            try:
                self.sftp.stat(remote_image_path)
            except IOError:
                raise RuntimeError(
                    "Decompression failed — the uploaded file may not be a valid compressed "
                    "Dynamips IOS image, or 'unzip' isn't available on the EVE-NG host."
                )
            final_path = posixpath.join(base, image_filename)
            self.run_command(f'mv "{remote_image_path}" "{final_path}"')

        self.run_command(f'rm -rf "{work_dir}"')
        return final_path

    @staticmethod
    def build_idlepc_calc_command(image_path: str, platform: str = "3725") -> str:
        """
        Builds the interactive `dynamips` command used to calculate a
        suggested Idle-PC value for a Dynamips image, per EVE-NG's docs.
        Run this in a real terminal — it requires watching the console and
        pressing 'ctrl+]' then 'i' to trigger the calculation, and 'ctrl+]'
        then 'q' to quit.
        """
        platform_flags = {
            "1710": "-P 1700 -t 1710",
            "3725": "-P 3725",
            "7200": "-P 7200",
        }
        flags = platform_flags.get(platform, f"-P {platform}")
        return f'dynamips {flags} "{image_path}"'

