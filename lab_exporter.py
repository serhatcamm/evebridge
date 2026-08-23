"""
Lab Export
------------
Downloads an EVE-NG lab straight off the server and packages it as a local
.zip. A lab "file" (e.g. BGP.unl) is actually a directory under
/opt/unetlab/labs/ containing the .unl topology JSON plus a configs/ folder
with saved node startup-configs — so exporting that directory captures
everything needed to back the lab up or move it to another EVE-NG host.

Uses the EVE-NG host's root SSH account (the same credentials as the Image
Manager), not the API login.
"""

import os
import posixpath
import zipfile

try:
    import paramiko
except ImportError:  # pragma: no cover - surfaced as a friendly runtime error
    paramiko = None

LAB_BASE = "/opt/unetlab/labs"


class LabExporter:
    """Read-only SSH/SFTP walker for one lab directory on the EVE-NG host."""

    def __init__(self, host: str, username: str = "root", password: str = "", port: int = 22):
        if paramiko is None:
            raise RuntimeError("paramiko is required for lab export. Install it with: pip install paramiko")
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

    # ------------------------------------------------------------------
    def list_lab_contents(self, lab_file_name: str, include_configs: bool = True):
        """
        Returns [(remote_path, relative_path, size)] for everything belonging
        to the lab. Two server layouts are supported:

          - File-based (EVE-NG Community 6.x+): <name>.unl is a single XML
            file containing the whole topology -> one entry.
          - Directory-based (older Community / Pro): <name>.unl/ is a folder
            with the topology JSON plus configs/ -> walked recursively,
            skipping 'backups/' (EVE-NG's internal history) and, when
            include_configs is False, 'configs/' too.
        """
        import stat as statmod
        base = posixpath.join(LAB_BASE, lab_file_name.strip("/"))
        try:
            st = self.sftp.stat(base)
        except IOError:
            raise RuntimeError(
                f"Lab not found on the server: {base}. "
                f"Pick a lab that exists (its name should end with .unl)."
            )

        if not statmod.S_ISDIR(st.st_mode):
            # Single-file lab layout.
            return [(base, lab_file_name.strip("/"), st.st_size)]

        entries = []

        def walk(dir_path: str, rel_prefix: str):
            for item in sorted(self.sftp.listdir_attr(dir_path), key=lambda a: a.filename):
                remote = posixpath.join(dir_path, item.filename)
                rel = posixpath.join(rel_prefix, item.filename) if rel_prefix else item.filename
                if statmod.S_ISDIR(item.st_mode):
                    top = rel.split("/", 1)[0] if "/" in rel else rel
                    if rel == "backups" or top == "backups":
                        continue  # EVE-NG's internal backup history - skip
                    if not include_configs and (rel == "configs" or top == "configs"):
                        continue
                    walk(remote, rel)
                else:
                    entries.append((remote, rel, item.st_size))

        walk(base, "")
        return entries

    def read_file(self, remote_path: str) -> bytes:
        with self.sftp.open(remote_path, "rb") as fh:
            return fh.read()


def export_lab_zip(host: str, ssh_user: str, ssh_pass: str, ssh_port: int,
                   lab_file_name: str, dest_zip_path: str,
                   include_configs: bool = True, progress_cb=None) -> str:
    """
    Exports the lab into dest_zip_path (a local .zip). Entries are stored
    under <lab-stem>/ so unzipping produces a ready-to-copy lab folder.
    progress_cb(done, total, current_name) is called while packaging.
    Returns the destination path.
    """
    lab_file_name = lab_file_name.strip()
    if not lab_file_name.endswith(".unl"):
        raise RuntimeError("Pick a lab file (should end with .unl).")

    exporter = LabExporter(host, ssh_user, ssh_pass, ssh_port)
    try:
        exporter.connect()
        entries = exporter.list_lab_contents(lab_file_name, include_configs=include_configs)
        if not entries:
            raise RuntimeError("The lab folder on the server is empty - nothing to export.")

        stem = lab_file_name[:-len(".unl")]
        os.makedirs(os.path.dirname(os.path.abspath(dest_zip_path)) or ".", exist_ok=True)

        total = len(entries)
        with zipfile.ZipFile(dest_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, (remote, rel, _size) in enumerate(entries, start=1):
                data = exporter.read_file(remote)
                zf.writestr(f"{stem}/{rel}", data)
                if progress_cb:
                    progress_cb(idx, total, rel)

        if progress_cb:
            progress_cb(total, total, "done")
        return dest_zip_path
    finally:
        exporter.close()
