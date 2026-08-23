"""
EVE-NG REST API Client for Python PyQt6 Automation Suite
Handles Session Authentication, Lab details, Nodes Management, Topology, and Control.
"""

import time
import requests
import json
import urllib.parse
from typing import Dict, Any, List, Optional

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

class EveNGClient:
    def __init__(self, host: str = "", username: str = "", password: str = ""):
        self.host = host.strip().rstrip("/")
        self.scheme = "http"
        self.base_url = f"http://{self.host}/api" if self.host else ""
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        self.is_logged_in = False
        # Human-readable reason for the most recent failed login, shown in the UI.
        self.last_error = ""

    def _attempt_login(self, base_url: str):
        """
        POSTs credentials to {base_url}/auth/login.
        Returns (ok, server_reachable) — 'reachable' tells the caller whether
        the scheme answered at all (so it shouldn't bother trying the other one).
        """
        url = f"{base_url}/auth/login"
        payload = {"username": self.username, "password": self.password}
        verify = not base_url.startswith("https://")  # EVE-NG HTTPS is often self-signed
        try:
            resp = self.session.post(url, json=payload, timeout=8, verify=verify)
        except requests.exceptions.Timeout:
            self.last_error = f"{self.host} did not answer within 8s (host offline, wrong IP, or firewall)."
            return False, False
        except requests.exceptions.ConnectionError as e:
            self.last_error = f"Couldn't reach {self.host} ({e.__class__.__name__}). Check the IP/cable/VPN."
            return False, False
        except Exception as e:
            self.last_error = f"{self.host}: {e.__class__.__name__}: {e}"
            return False, False

        if resp.status_code == 200:
            try:
                data = resp.json()
            except ValueError:
                data = {}
            if data.get("code") == 200 or data.get("status") == "success":
                return True, True
            self.last_error = f"Unexpected login response: {resp.text[:150]}"
            return False, True
        if resp.status_code in (401, 403):
            self.last_error = "Server reached, but the username/password was rejected."
        else:
            self.last_error = f"Server responded HTTP {resp.status_code}: {resp.text[:150]}"
        return False, True

    def login(self) -> bool:
        """
        Tries HTTP first, then HTTPS automatically (some EVE-NG installs serve
        only HTTPS with a self-signed certificate). Sets last_error on failure.
        """
        errors = []
        for scheme in ("http", "https"):
            base = f"{scheme}://{self.host}/api"
            ok, reachable = self._attempt_login(base)
            if ok:
                self.scheme = scheme
                self.base_url = base
                self.is_logged_in = True
                return True
            errors.append(f"[{scheme}] {self.last_error}")
            if reachable:
                # The server answered over this scheme — trying the other one
                # would just produce a second connection error.
                break
        self.is_logged_in = False
        self.last_error = "  ".join(errors)
        return False


    # ------------------------------------------------------------------
    # Hardened request helpers: one automatic retry on transient network
    # failures and on expired sessions (401 -> re-login once). EVE-NG
    # servers under load sometimes answer slowly or drop a connection;
    # without this, a single hiccup made start/stop look like it failed.
    # ------------------------------------------------------------------
    def _api(self, method: str, path: str, timeout: float = 15.0,
             json_body=None, retry: bool = True):
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.request(method, url, json=json_body, timeout=timeout)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if retry:
                time.sleep(1.0)
                return self._api(method, path, timeout, json_body, retry=False)
            self.last_error = f"{self.host} timed out / dropped the connection."
            raise

        if resp.status_code == 401 and retry:
            if self.login():
                return self._api(method, path, timeout, json_body, retry=False)
            self.last_error = "Session expired and re-login failed - reconnect from the top bar."
        return resp

    @staticmethod
    def _json_ok(resp) -> bool:
        """True when EVE-NG reports success in the JSON body (code 200 /
        status success), not just at the HTTP level."""
        try:
            data = resp.json()
        except ValueError:
            return resp.status_code == 200
        return resp.status_code in (200, 201) and (
            data.get("code") == 200 or data.get("status") == "success"
        )

    def _node_action(self, lab_name: str, node_id: int, action: str) -> bool:
        """start/stop/wipe a node with the hardened helper."""
        lab_path = urllib.parse.quote(lab_name.lstrip('/'))
        try:
            resp = self._api("GET", f"/labs/{lab_path}/nodes/{node_id}/{action}")
        except Exception as e:
            self.last_error = f"Node {action} {node_id}: {e.__class__.__name__}"
            print(f"Error {action}ing node {node_id}: {e}")
            return False
        if self._json_ok(resp):
            return True
        try:
            msg = resp.json().get("message", "")
        except ValueError:
            msg = resp.text[:120]
        self.last_error = f"Node {action} failed (HTTP {resp.status_code}): {msg}"
        print(f"Node {action} {node_id}: HTTP {resp.status_code} {msg}")
        return False

    def get_labs(self, path: str = "/") -> List[Dict[str, Any]]:
        """Fetch all lab files available in EVE-NG server."""
        url = f"{self.base_url}/folders{path}"
        labs_found = []
        try:
            resp = self.session.get(url, timeout=12)
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                labs_found.extend(data.get("labs", []))
                
                # Recursively check subfolders if any
                for folder in data.get("folders", []):
                    folder_path = folder.get("path")
                    if folder_path:
                        sub_labs = self.get_labs(path=folder_path)
                        labs_found.extend(sub_labs)
        except Exception as e:
            print(f"Error fetching labs: {e}")
        return labs_found

    def get_server_status(self) -> Dict[str, Any]:
        """Fetch system resource usage (CPU %, RAM %, Disk %, node counts) from EVE-NG."""
        url = f"{self.base_url}/status"
        try:
            resp = self.session.get(url, timeout=12)
            if resp.status_code == 200:
                return resp.json().get("data", {})
        except Exception as e:
            print(f"Error fetching system status: {e}")
        return {}

    def get_lab_nodes(self, lab_name: str) -> Dict[str, Any]:
        """Fetch all nodes for a specific lab (e.g. Basic-CCNA-Router-on-Stick.unl)."""
        lab_path = urllib.parse.quote(lab_name.lstrip('/'))
        url = f"{self.base_url}/labs/{lab_path}/nodes"
        try:
            resp = self.session.get(url, timeout=12)
            if resp.status_code == 200:
                return resp.json().get("data", {})
        except Exception as e:
            print(f"Error getting lab nodes: {e}")
        return {}

    def get_lab_topology(self, lab_name: str) -> List[Dict[str, Any]]:
        """Fetch link connections / topology for a lab."""
        lab_path = urllib.parse.quote(lab_name.lstrip('/'))
        url = f"{self.base_url}/labs/{lab_path}/topology"
        try:
            resp = self.session.get(url, timeout=12)
            if resp.status_code == 200:
                return resp.json().get("data", [])
        except Exception as e:
            print(f"Error getting topology: {e}")
        return []

    def start_node(self, lab_name: str, node_id: int) -> bool:
        """Start a specific node by ID (auto-retries transient failures)."""
        return self._node_action(lab_name, node_id, "start")


    # ------------------ LAB MANAGEMENT ------------------
    def create_lab(self, name: str, version: str = '1.0',
                   author: str = '', description: str = ''):
        """Creates a new empty lab. Returns (ok, server_message)."""
        payload = {
            'name': name.strip(), 'version': (version or '1').strip(),
            'author': author or '', 'description': description or '',
            'body': '', 'path': '',
        }
        try:
            resp = self._api('POST', '/labs', json_body=payload)
        except Exception as e:
            return False, f"{e.__class__.__name__}: {e}"
        ok = self._json_ok(resp)
        try:
            msg = resp.json().get('message', '')
        except ValueError:
            msg = resp.text[:120]
        if not ok:
            self.last_error = msg
        return ok, msg

    def delete_lab(self, lab_name: str):
        """Deletes a lab by its file name (must end with .unl).
        Returns (ok, server_message)."""
        target = lab_name.strip().rstrip('/')
        if not target.endswith('.unl'):
            target += '.unl'
        try:
            resp = self._api('DELETE', f'/labs/{urllib.parse.quote(target)}')
        except Exception as e:
            return False, f"{e.__class__.__name__}: {e}"
        ok = self._json_ok(resp)
        try:
            msg = resp.json().get('message', '')
        except ValueError:
            msg = resp.text[:120]
        if not ok:
            self.last_error = msg
        return ok, msg

    def get_templates(self) -> Dict[str, str]:
        """Fetch all available node templates (e.g. iol, qemu, vios)."""
        url = f"{self.base_url}/list/templates/"
        try:
            resp = self.session.get(url, timeout=12)
            if resp.status_code == 200:
                # EVE-NG returns a dict where key is template name, value is description
                return resp.json().get("data", {})
        except Exception as e:
            print(f"Error fetching templates: {e}")
        return {}

    def get_template_details(self, template_name: str) -> Dict[str, Any]:
        """Fetch default options and available images for a specific template."""
        url = f"{self.base_url}/list/templates/{template_name}"
        try:
            resp = self.session.get(url, timeout=12)
            if resp.status_code == 200:
                return resp.json().get("data", {})
        except Exception as e:
            print(f"Error fetching template details for {template_name}: {e}")
        return {}

    def add_node(self, lab_name: str, node_data: Dict[str, Any]) -> bool:
        """
        Add one or more nodes to the lab.
        node_data keys: template, type, count, image, name, icon, ram, cpu, ethernet, nvram, left, top, etc.
        """
        lab_path = urllib.parse.quote(lab_name.lstrip('/'))
        url = f"{self.base_url}/labs/{lab_path}/nodes"
        try:
            resp = self.session.post(url, json=node_data, timeout=10)
            return resp.status_code == 201 or resp.status_code == 200
        except Exception as e:
            print(f"Error adding node to {lab_name}: {e}")
            return False

    def update_node(self, lab_name: str, node_id: int, node_data: Dict[str, Any]) -> bool:
        """
        Update properties of an existing node (e.g. ram, nvram, cpu, ethernet).
        Only include the keys you want to change in node_data — EVE-NG merges
        the PUT payload with the node's existing configuration.
        The lab should be stopped/nodes stopped for changes like RAM/NVRAM to
        take effect on next start; EVE-NG will reject some changes on running nodes.
        """
        lab_path = urllib.parse.quote(lab_name.lstrip('/'))
        url = f"{self.base_url}/labs/{lab_path}/nodes/{node_id}"
        try:
            resp = self.session.put(url, json=node_data, timeout=10)
            return resp.status_code == 200
        except Exception as e:
            print(f"Error updating node {node_id}: {e}")
            return False

    def stop_node(self, lab_name: str, node_id: int) -> bool:
        """Stop a specific node by ID (auto-retries transient failures)."""
        return self._node_action(lab_name, node_id, "stop")

    def wipe_node(self, lab_name: str, node_id: int) -> bool:
        """Wipe startup config / NVRAM for a specific node."""
        return self._node_action(lab_name, node_id, "wipe")

    def start_all_nodes(self, lab_name: str) -> bool:
        """Start all nodes in the lab simultaneously."""
        lab_path = urllib.parse.quote(lab_name.lstrip('/'))
        url = f"{self.base_url}/labs/{lab_path}/nodes/start"
        try:
            resp = self.session.get(url, timeout=15)
            return resp.status_code == 200
        except Exception as e:
            print(f"Error starting all nodes: {e}")
            return False

    def stop_all_nodes(self, lab_name: str) -> bool:
        """Stop all nodes in the lab simultaneously."""
        lab_path = urllib.parse.quote(lab_name.lstrip('/'))
        url = f"{self.base_url}/labs/{lab_path}/nodes/stop"
        try:
            resp = self.session.get(url, timeout=15)
            return resp.status_code == 200
        except Exception as e:
            print(f"Error stopping all nodes: {e}")
            return False
