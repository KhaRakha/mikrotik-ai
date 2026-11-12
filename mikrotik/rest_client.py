"""
MikroTik RouterOS v7 REST API Client.
Communicates with MikroTik via native HTTP/HTTPS REST endpoints.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
import httpx
from mikrotik.base import BaseMikrotikClient, OperationResult


class MikrotikRestClient(BaseMikrotikClient):
    def __init__(
        self,
        host: str,
        port: int = 80,
        username: str = "admin",
        password: str = "",
        use_ssl: bool = False,
        timeout: float = 5.0,
        verify_ssl: bool = False,
    ):
        super().__init__(host, port, username, password, use_ssl, timeout)
        protocol = "https" if use_ssl else "http"
        self.base_url = f"{protocol}://{self.host}:{self.port}/rest"
        self.auth = (self.username, self.password)
        self.verify_ssl = verify_ssl

    def _client(self) -> httpx.Client:
        return httpx.Client(
            auth=self.auth,
            verify=self.verify_ssl,
            timeout=self.timeout,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )

    def test_connection(self) -> OperationResult:
        start = time.time()
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/system/resource")
                latency = (time.time() - start) * 1000
                if res.status_code == 200:
                    data = res.json()
                    return OperationResult(
                        success=True,
                        message=f"Koneksi ke MikroTik {self.host} berhasil (RouterOS {data.get('version', 'v7')}).",
                        data={"status": "online", "version": data.get("version"), "board": data.get("board-name")},
                        device=self.device_name,
                        latency_ms=latency,
                    )
                elif res.status_code in (401, 403):
                    return OperationResult(
                        success=False,
                        message=f"Autentikasi gagal untuk user '{self.username}' pada MikroTik {self.host}.",
                        error=f"HTTP {res.status_code} Unauthorized",
                        device=self.device_name,
                        latency_ms=latency,
                    )
                else:
                    return OperationResult(
                        success=False,
                        message=f"Respon error dari MikroTik: HTTP {res.status_code}.",
                        error=res.text,
                        device=self.device_name,
                        latency_ms=latency,
                    )
        except Exception as e:
            latency = (time.time() - start) * 1000
            return OperationResult(
                success=False,
                message=f"Gagal menghubungi MikroTik pada {self.host}:{self.port}.",
                error=str(e),
                device=self.device_name,
                latency_ms=latency,
            )

    def get_resource(self) -> OperationResult:
        start = time.time()
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/system/resource")
                latency = (time.time() - start) * 1000
                if res.status_code == 200:
                    raw = res.json()
                    free_mem = int(raw.get("free-memory", 0)) / (1024 * 1024)
                    total_mem = int(raw.get("total-memory", 1)) / (1024 * 1024)
                    usage_pct = round(((total_mem - free_mem) / total_mem) * 100, 1) if total_mem > 0 else 0.0

                    normalized = {
                        "cpu_load": int(raw.get("cpu-load", 0)),
                        "free_memory_mb": round(free_mem, 1),
                        "total_memory_mb": round(total_mem, 1),
                        "memory_usage_percent": usage_pct,
                        "uptime": raw.get("uptime", "0s"),
                        "version": raw.get("version", "v7"),
                        "board_name": raw.get("board-name", "RouterBOARD"),
                        "architecture_name": raw.get("architecture-name", "unknown"),
                        "cpu_count": int(raw.get("cpu-count", 1)),
                        "free_hdd_space_mb": round(int(raw.get("free-hdd-space", 0)) / (1024 * 1024), 1),
                        "total_hdd_space_mb": round(int(raw.get("total-hdd-space", 1)) / (1024 * 1024), 1),
                    }
                    return OperationResult(
                        success=True,
                        message="Resource sistem berhasil diambil.",
                        data=normalized,
                        device=self.device_name,
                        latency_ms=latency,
                    )
                return OperationResult(success=False, message=f"HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, message=f"Koneksi gagal ke {self.host}", error=str(e), device=self.device_name)

    def get_interfaces(self) -> OperationResult:
        start = time.time()
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/interface")
                latency = (time.time() - start) * 1000
                if res.status_code == 200:
                    data = res.json()
                    normalized = []
                    for item in data:
                        normalized.append({
                            "name": item.get("name"),
                            "type": item.get("type"),
                            "running": item.get("running") in ("true", True),
                            "disabled": item.get("disabled") in ("true", True),
                            "mac": item.get("mac-address", ""),
                            "comment": item.get("comment", ""),
                            "rx_byte": int(item.get("rx-byte", 0)),
                            "tx_byte": int(item.get("tx-byte", 0)),
                        })
                    return OperationResult(
                        success=True,
                        message=f"Berhasil mengambil {len(normalized)} interface.",
                        data=normalized,
                        device=self.device_name,
                        latency_ms=latency,
                    )
                return OperationResult(success=False, message=f"HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, message=f"Koneksi gagal ke {self.host}", error=str(e), device=self.device_name)

    def get_ip_addresses(self) -> OperationResult:
        start = time.time()
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/ip/address")
                latency = (time.time() - start) * 1000
                if res.status_code == 200:
                    data = res.json()
                    return OperationResult(
                        success=True,
                        message=f"Berhasil mengambil {len(data)} IP address.",
                        data=data,
                        device=self.device_name,
                        latency_ms=latency,
                    )
                return OperationResult(success=False, message=f"HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, message=f"Koneksi gagal ke {self.host}", error=str(e), device=self.device_name)

    def get_ip_routes(self) -> OperationResult:
        start = time.time()
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/ip/route")
                latency = (time.time() - start) * 1000
                if res.status_code == 200:
                    return OperationResult(success=True, data=res.json(), device=self.device_name, latency_ms=latency)
                return OperationResult(success=False, message=f"HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_arp_table(self) -> OperationResult:
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/ip/arp")
                if res.status_code == 200:
                    return OperationResult(success=True, data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_dhcp_leases(self) -> OperationResult:
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/ip/dhcp-server/lease")
                if res.status_code == 200:
                    return OperationResult(success=True, data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_hotspot_users(self) -> OperationResult:
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/ip/hotspot/user")
                if res.status_code == 200:
                    return OperationResult(success=True, data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_hotspot_active(self) -> OperationResult:
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/ip/hotspot/active")
                if res.status_code == 200:
                    return OperationResult(success=True, data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_hotspot_profiles(self) -> OperationResult:
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/ip/hotspot/user/profile")
                if res.status_code == 200:
                    return OperationResult(success=True, data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_firewall_rules(self) -> OperationResult:
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/ip/firewall/filter")
                if res.status_code == 200:
                    return OperationResult(success=True, data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_system_logs(self, limit: int = 30) -> OperationResult:
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/log")
                if res.status_code == 200:
                    logs = res.json()
                    return OperationResult(success=True, data=logs[-limit:], device=self.device_name)
                return OperationResult(success=False, message=f"HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def ping(self, target: str, count: int = 4) -> OperationResult:
        try:
            with self._client() as client:
                payload = {"address": target, "count": count}
                res = client.post(f"{self.base_url}/ping", json=payload)
                if res.status_code == 200:
                    return OperationResult(success=True, message=f"Ping ke {target} selesai.", data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def create_hotspot_user(self, name: str, password: str = "", profile: str = "default", limit_uptime: str = "") -> OperationResult:
        try:
            with self._client() as client:
                payload: Dict[str, Any] = {"name": name, "profile": profile or "default"}
                if password:
                    payload["password"] = password
                if limit_uptime:
                    payload["limit-uptime"] = limit_uptime

                res = client.put(f"{self.base_url}/ip/hotspot/user", json=payload)
                if res.status_code in (200, 201):
                    return OperationResult(
                        success=True,
                        message=f"✅ User hotspot '{name}' berhasil dibuat di MikroTik {self.host}.",
                        data=res.json(),
                        device=self.device_name,
                    )
                return OperationResult(success=False, message=f"Gagal membuat user hotspot: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def delete_hotspot_user(self, name: str) -> OperationResult:
        try:
            with self._client() as client:
                # First find user id
                res_find = client.get(f"{self.base_url}/ip/hotspot/user?.proplist=.id,name")
                if res_find.status_code != 200:
                    return OperationResult(success=False, message="Gagal mencari daftar user hotspot", error=res_find.text, device=self.device_name)

                user_id = None
                for u in res_find.json():
                    if u.get("name", "").lower() == name.lower():
                        user_id = u.get(".id")
                        break

                if not user_id:
                    return OperationResult(success=False, message=f"User hotspot '{name}' tidak ditemukan.", device=self.device_name)

                res_del = client.delete(f"{self.base_url}/ip/hotspot/user/{user_id}")
                if res_del.status_code in (200, 204):
                    return OperationResult(success=True, message=f"✅ User hotspot '{name}' berhasil dihapus.", device=self.device_name)
                return OperationResult(success=False, message=f"Gagal menghapus user: HTTP {res_del.status_code}", error=res_del.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def set_interface_state(self, interface_name: str, enabled: bool) -> OperationResult:
        try:
            with self._client() as client:
                res_find = client.get(f"{self.base_url}/interface?.proplist=.id,name")
                if res_find.status_code != 200:
                    return OperationResult(success=False, message="Gagal mencari daftar interface", error=res_find.text, device=self.device_name)

                iface_id = None
                for iface in res_find.json():
                    if iface.get("name", "").lower() == interface_name.lower():
                        iface_id = iface.get(".id")
                        break

                if not iface_id:
                    return OperationResult(success=False, message=f"Interface '{interface_name}' tidak ditemukan.", device=self.device_name)

                disabled_val = "false" if enabled else "true"
                res_patch = client.patch(f"{self.base_url}/interface/{iface_id}", json={"disabled": disabled_val})
                state_str = "diaktifkan" if enabled else "dinonaktifkan"
                if res_patch.status_code in (200, 204):
                    return OperationResult(success=True, message=f"✅ Interface '{interface_name}' berhasil {state_str}.", device=self.device_name)
                return OperationResult(success=False, message=f"Gagal mengubah status interface: HTTP {res_patch.status_code}", error=res_patch.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def add_ip_address(self, address: str, interface: str, comment: str = "") -> OperationResult:
        try:
            with self._client() as client:
                payload = {"address": address.strip(), "interface": interface}
                if comment:
                    payload["comment"] = comment
                res = client.put(f"{self.base_url}/ip/address", json=payload)
                if res.status_code in (200, 201):
                    return OperationResult(
                        success=True,
                        message=f"✅ IP address '{address}' berhasil ditambahkan ke interface '{interface}'.",
                        data=res.json(),
                        device=self.device_name,
                    )
                return OperationResult(success=False, message=f"Gagal menambahkan IP address: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def remove_ip_address(self, address: str) -> OperationResult:
        try:
            with self._client() as client:
                clean_target = address.strip()
                res_find = client.get(f"{self.base_url}/ip/address")
                if res_find.status_code != 200:
                    return OperationResult(success=False, message="Gagal mengambil daftar IP address", error=res_find.text, device=self.device_name)

                target_id = None
                for item in res_find.json():
                    addr = item.get("address", "")
                    if addr == clean_target or addr.split("/")[0] == clean_target.split("/")[0]:
                        target_id = item.get(".id")
                        break

                if not target_id:
                    return OperationResult(success=False, message=f"IP address '{address}' tidak ditemukan.", device=self.device_name)

                res_del = client.delete(f"{self.base_url}/ip/address/{target_id}")
                if res_del.status_code in (200, 204):
                    return OperationResult(success=True, message=f"✅ IP address '{address}' berhasil dihapus.", device=self.device_name)
                return OperationResult(success=False, message=f"Gagal menghapus IP address: HTTP {res_del.status_code}", error=res_del.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def set_ip_address(
        self,
        current_address: str,
        new_address: Optional[str] = None,
        new_interface: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> OperationResult:
        try:
            with self._client() as client:
                clean_target = current_address.strip()
                res_find = client.get(f"{self.base_url}/ip/address")
                if res_find.status_code != 200:
                    return OperationResult(success=False, message="Gagal mengambil daftar IP address", error=res_find.text, device=self.device_name)

                target_id = None
                for item in res_find.json():
                    addr = item.get("address", "")
                    if addr == clean_target or addr.split("/")[0] == clean_target.split("/")[0]:
                        target_id = item.get(".id")
                        break

                if not target_id:
                    return OperationResult(success=False, message=f"IP address '{current_address}' tidak ditemukan.", device=self.device_name)

                payload: Dict[str, Any] = {}
                if new_address:
                    payload["address"] = new_address.strip()
                if new_interface:
                    payload["interface"] = new_interface
                if comment is not None:
                    payload["comment"] = comment

                res_patch = client.patch(f"{self.base_url}/ip/address/{target_id}", json=payload)
                if res_patch.status_code in (200, 204):
                    return OperationResult(success=True, message=f"✅ IP address '{current_address}' berhasil diperbarui.", device=self.device_name)
                return OperationResult(success=False, message=f"Gagal mengubah IP address: HTTP {res_patch.status_code}", error=res_patch.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def execute_raw_command(self, path: str, command: str, params: Optional[Dict[str, Any]] = None) -> OperationResult:
        try:
            with self._client() as client:
                clean_path = path.strip("/")
                url = f"{self.base_url}/{clean_path}"
                cmd_upper = command.strip().upper()
                if cmd_upper in ("GET", "PRINT", "SHOW"):
                    res = client.get(url, params=params)
                elif cmd_upper in ("POST", "ADD", "CREATE"):
                    res = client.post(url, json=params)
                elif cmd_upper in ("PUT",):
                    res = client.put(url, json=params)
                elif cmd_upper in ("PATCH", "SET"):
                    res = client.patch(url, json=params)
                elif cmd_upper in ("DELETE", "REMOVE"):
                    res = client.delete(url)
                else:
                    return OperationResult(success=False, message=f"HTTP method '{command}' tidak didukung.", device=self.device_name)

                return OperationResult(
                    success=res.status_code in (200, 201, 204),
                    message=f"Operasi REST {command} {clean_path} selesai (HTTP {res.status_code}).",
                    data=res.json() if res.content else None,
                    device=self.device_name,
                )
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    # =========================================================================
    # WINBOX TOOLS MENU (REST API)
    # =========================================================================
    def traceroute(self, target: str, count: int = 4) -> OperationResult:
        try:
            with self._client() as client:
                payload = {"address": target, "count": count}
                res = client.post(f"{self.base_url}/tool/traceroute", json=payload, timeout=self.timeout + 15.0)
                if res.status_code == 200:
                    return OperationResult(success=True, message=f"Traceroute ke {target} selesai.", data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"Traceroute gagal: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def torch(self, interface: str, duration: int = 3) -> OperationResult:
        try:
            with self._client() as client:
                res = client.post(f"{self.base_url}/tool/torch", json={"interface": interface}, timeout=self.timeout + duration)
                if res.status_code == 200:
                    return OperationResult(success=True, message=f"Torch pada interface '{interface}' selesai.", data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"Torch gagal: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def bandwidth_test(self, target: str, direction: str = "both", duration: int = 5, protocol: str = "udp") -> OperationResult:
        try:
            with self._client() as client:
                payload = {"address": target, "direction": direction, "duration": f"{duration}s", "protocol": protocol}
                if self.username:
                    payload["user"] = self.username
                if self.password:
                    payload["password"] = self.password
                res = client.post(f"{self.base_url}/tool/bandwidth-test", json=payload, timeout=self.timeout + duration + 5)
                if res.status_code == 200:
                    raw_json = res.json()
                    item = raw_json[-1] if isinstance(raw_json, list) and raw_json else (raw_json if isinstance(raw_json, dict) else {})
                    status = str(item.get("status", "completed")).lower()
                    rx_bps = float(item.get("rx-total-average") or item.get("rx-current") or 0)
                    tx_bps = float(item.get("tx-total-average") or item.get("tx-current") or 0)
                    rx_mbps = round(rx_bps / 1_000_000, 2)
                    tx_mbps = round(tx_bps / 1_000_000, 2)
                    lost = int(item.get("lost-packets", 0))
                    data_dict = {
                        "target": target,
                        "direction": direction,
                        "protocol": protocol,
                        "duration_s": duration,
                        "status": status,
                        "rx_throughput_mbps": rx_mbps,
                        "tx_throughput_mbps": tx_mbps,
                        "lost_packets": lost,
                        "jitter_ms": 0.0,
                        "raw": raw_json,
                    }
                    if any(err_kw in status for err_kw in ("can not connect", "connection refused", "failed", "authentication failed", "error")):
                        return OperationResult(
                            success=False,
                            message=f"Bandwidth test ke {target} gagal: {status}.",
                            data=data_dict,
                            error=f"Target {target} menolak atau tidak merespons Bandwidth Test Server ({status}).",
                            device=self.device_name,
                        )
                    return OperationResult(success=True, message=f"Bandwidth test ke {target} selesai.", data=data_dict, device=self.device_name)
                return OperationResult(success=False, message=f"Bandwidth test gagal: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_netwatch(self) -> OperationResult:
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/tool/netwatch")
                if res.status_code == 200:
                    return OperationResult(success=True, message="Data Netwatch berhasil diambil.", data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"Gagal mengambil Netwatch: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def add_netwatch(self, host: str, interval: str = "1m", timeout: str = "1000ms", comment: str = "") -> OperationResult:
        try:
            with self._client() as client:
                payload = {"host": host, "interval": interval, "timeout": timeout}
                if comment:
                    payload["comment"] = comment
                res = client.put(f"{self.base_url}/tool/netwatch", json=payload)
                if res.status_code in (200, 201):
                    return OperationResult(success=True, message=f"✅ Host Netwatch '{host}' berhasil ditambahkan.", data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"Gagal menambahkan Netwatch: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def ip_scan(self, interface: str, address_range: str = "", duration: int = 5) -> OperationResult:
        try:
            with self._client() as client:
                payload = {"interface": interface, "duration": f"{duration}s"}
                if address_range:
                    payload["address-range"] = address_range
                res = client.post(f"{self.base_url}/tool/ip-scan", json=payload, timeout=self.timeout + duration + 5)
                if res.status_code == 200:
                    return OperationResult(success=True, message=f"IP Scan pada interface '{interface}' selesai.", data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"IP Scan gagal: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_profile(self, duration: int = 3) -> OperationResult:
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/tool/profile")
                if res.status_code == 200:
                    return OperationResult(success=True, message="Profile CPU berhasil diambil.", data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"Profile CPU gagal: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def send_email(self, to: str, subject: str, body: str) -> OperationResult:
        try:
            with self._client() as client:
                payload = {"to": to, "subject": subject, "body": body}
                res = client.post(f"{self.base_url}/tool/e-mail/send", json=payload)
                if res.status_code in (200, 201):
                    return OperationResult(success=True, message=f"✅ Notifikasi email berhasil dikirim ke '{to}'.", device=self.device_name)
                return OperationResult(success=False, message=f"Gagal mengirim email: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_packet_sniffer(self) -> OperationResult:
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/tool/sniffer")
                if res.status_code == 200:
                    return OperationResult(success=True, message="Status Sniffer berhasil diambil.", data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"Gagal mengambil sniffer: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def sniff_packets(self, interface: str = "", count: int = 10) -> OperationResult:
        try:
            with self._client() as client:
                url = f"{self.base_url}/tool/sniffer/packet"
                params = {"count": count}
                if interface:
                    params["interface"] = interface
                res = client.get(url, params=params)
                if res.status_code == 200:
                    return OperationResult(success=True, message="Daftar paket berhasil diambil.", data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"Gagal mengambil paket sniffer: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_traffic_monitor(self) -> OperationResult:
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/tool/traffic-monitor")
                if res.status_code == 200:
                    return OperationResult(success=True, message="Daftar Traffic Monitor berhasil diambil.", data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"Gagal mengambil traffic monitor: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def add_traffic_monitor(self, name: str, interface: str, threshold: str, trigger: str = "above", on_event: str = "") -> OperationResult:
        try:
            with self._client() as client:
                payload = {
                    "name": name,
                    "interface": interface,
                    "threshold": str(threshold),
                    "trigger": trigger,
                }
                if on_event:
                    payload["on-event"] = on_event
                res = client.put(f"{self.base_url}/tool/traffic-monitor", json=payload)
                if res.status_code in (200, 201):
                    return OperationResult(success=True, message=f"✅ Aturan Traffic Monitor '{name}' pada interface '{interface}' berhasil ditambahkan.", data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"Gagal menambahkan traffic monitor: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    # =========================================================================
    # WINBOX SYSTEM MENU (REST API)
    # =========================================================================
    def get_identity(self) -> OperationResult:
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/system/identity")
                if res.status_code == 200:
                    data = res.json()
                    name = data.get("name", "Unknown") if isinstance(data, dict) else str(data)
                    return OperationResult(success=True, message=f"Identitas router: '{name}'", data=data, device=self.device_name)
                return OperationResult(success=False, message=f"Gagal mengambil identitas: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def set_identity(self, name: str) -> OperationResult:
        try:
            with self._client() as client:
                res = client.patch(f"{self.base_url}/system/identity", json={"name": name})
                if res.status_code in (200, 204):
                    return OperationResult(success=True, message=f"✅ Identitas router berhasil diubah menjadi '{name}'.", data={"name": name}, device=self.device_name)
                return OperationResult(success=False, message=f"Gagal mengubah identitas: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_system_users(self) -> OperationResult:
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/user")
                if res.status_code == 200:
                    return OperationResult(success=True, message="Daftar user sistem MikroTik berhasil diambil.", data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"Gagal mengambil user sistem: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def create_system_user(self, name: str, group: str = "read", password: str = "") -> OperationResult:
        try:
            with self._client() as client:
                payload = {"name": name, "group": group}
                if password:
                    payload["password"] = password
                res = client.put(f"{self.base_url}/user", json=payload)
                if res.status_code in (200, 201):
                    return OperationResult(success=True, message=f"✅ User sistem '{name}' ({group}) berhasil dibuat.", data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"Gagal membuat user sistem: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def delete_system_user(self, name: str) -> OperationResult:
        try:
            with self._client() as client:
                # Find user ID
                res_find = client.get(f"{self.base_url}/user?.proplist=.id,name")
                if res_find.status_code != 200:
                    return OperationResult(success=False, message="Gagal mencari daftar user", error=res_find.text, device=self.device_name)

                user_id = None
                for u in res_find.json():
                    if u.get("name", "").lower() == name.lower():
                        user_id = u.get(".id")
                        break

                if not user_id:
                    return OperationResult(success=False, message=f"User sistem '{name}' tidak ditemukan.", device=self.device_name)

                res_del = client.delete(f"{self.base_url}/user/{user_id}")
                if res_del.status_code in (200, 204):
                    return OperationResult(success=True, message=f"✅ User sistem '{name}' berhasil dihapus.", device=self.device_name)
                return OperationResult(success=False, message=f"Gagal menghapus user: HTTP {res_del.status_code}", error=res_del.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_packages(self) -> OperationResult:
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/system/package")
                if res.status_code == 200:
                    return OperationResult(success=True, message="Daftar paket RouterOS berhasil diambil.", data=res.json(), device=self.device_name)
                return OperationResult(success=False, message=f"Gagal mengambil paket: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_routerboard(self) -> OperationResult:
        try:
            with self._client() as client:
                res = client.get(f"{self.base_url}/system/routerboard")
                if res.status_code == 200:
                    raw_data = res.json()
                    if isinstance(raw_data, list) and raw_data:
                        raw_data = raw_data[0]
                    data = dict(raw_data) if isinstance(raw_data, dict) else {}
                    for k, v in list(data.items()):
                        if "-" in k:
                            data[k.replace("-", "_")] = v
                    return OperationResult(success=True, message="Informasi RouterBOARD berhasil diambil.", data=data, device=self.device_name)
                return OperationResult(success=False, message=f"Gagal mengambil data RouterBOARD: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_clock_sntp(self) -> OperationResult:
        try:
            with self._client() as client:
                res_clock = client.get(f"{self.base_url}/system/clock")
                res_ntp = client.get(f"{self.base_url}/system/ntp/client")
                combined = {
                    "clock": res_clock.json() if res_clock.status_code == 200 else {},
                    "sntp": res_ntp.json() if res_ntp.status_code == 200 else {},
                }
                return OperationResult(success=True, message="Informasi Clock dan SNTP berhasil diambil.", data=combined, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def set_clock_timezone(self, time_zone: str) -> OperationResult:
        try:
            with self._client() as client:
                res = client.patch(f"{self.base_url}/system/clock", json={"time-zone-name": time_zone})
                if res.status_code in (200, 204):
                    return OperationResult(success=True, message=f"✅ Zona waktu berhasil diatur ke '{time_zone}'.", device=self.device_name)
                return OperationResult(success=False, message=f"Gagal mengatur zona waktu: HTTP {res.status_code}", error=res.text, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def reboot(self) -> OperationResult:
        try:
            with self._client() as client:
                res = client.post(f"{self.base_url}/system/reboot")
                return OperationResult(
                    success=True,
                    message=f"🔄 Router '{self.device_name}' sedang melakukan proses REBOOT...\nSistem akan offline sementara dan otomatis kembali aktif.",
                    device=self.device_name,
                )
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def shutdown(self) -> OperationResult:
        try:
            with self._client() as client:
                res = client.post(f"{self.base_url}/system/shutdown")
                return OperationResult(
                    success=True,
                    message=f"🔌 Router '{self.device_name}' sedang melakukan proses SHUTDOWN secara aman.",
                    device=self.device_name,
                )
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def check_router_update(self, channel: str = "stable") -> OperationResult:
        try:
            with self._client() as client:
                if channel:
                    try:
                        client.patch(f"{self.base_url}/system/package/update", json={"channel": channel})
                    except Exception:
                        pass
                try:
                    client.post(f"{self.base_url}/system/package/update/check-for-updates")
                except Exception:
                    pass
                res = client.get(f"{self.base_url}/system/package/update")
                data = res.json() if res.status_code == 200 else {}
                if isinstance(data, list) and data:
                    data = data[0]

                installed = data.get("installed-version") or data.get("installed_version") or ""
                latest = data.get("latest-version") or data.get("latest_version") or ""
                status_text = data.get("status") or ("New version is available" if latest and latest != installed else "System is up to date")
                if not latest and ("up to date" in str(status_text).lower() or not (latest and latest != installed)):
                    latest = installed
                has_update = bool(latest and installed and latest != installed)
                norm = {
                    "channel": data.get("channel", channel),
                    "installed_version": installed,
                    "installed-version": installed,
                    "latest_version": latest,
                    "latest-version": latest,
                    "status": status_text,
                    "update_available": has_update,
                }
                msg = f"Update RouterOS tersedia: v{installed} ➔ v{latest} (Channel: {norm['channel']})." if has_update else f"RouterOS sudah versi terbaru (v{installed})."
                return OperationResult(success=True, message=msg, data=norm, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def install_router_update(self, channel: str = "stable") -> OperationResult:
        try:
            with self._client() as client:
                if channel:
                    try:
                        client.patch(f"{self.base_url}/system/package/update", json={"channel": channel})
                    except Exception:
                        pass
                try:
                    client.post(f"{self.base_url}/system/package/update/install")
                except Exception as e:
                    err_lower = str(e).lower()
                    disconnect_terms = (
                        "terputus", "broken pipe", "connection reset", "closed",
                        "timed out", "timeout", "koneksi fatal", "fatal", "eof",
                        "connection error", "connection refused", "aborted", "peer",
                    )
                    if not any(term in err_lower for term in disconnect_terms):
                        raise
            return OperationResult(
                success=True,
                message=(
                    f"🚀 **Proses Upgrade RouterOS Berhasil Dimulai!**\n\n"
                    f"• Target Router : **{self.device_name}**\n"
                    f"• Channel       : `{channel}`\n"
                    f"• Status        : Router sedang mengunduh paket update dan akan melakukan REBOOT otomatis.\n"
                    f"⏳ Router akan offline sementara selama 1-3 menit. Pemantauan otomatis akan memberi kabar saat router kembali online."
                ),
                data={"status": "INSTALLING_AND_REBOOTING", "device": self.device_name},
                device=self.device_name,
            )
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def upgrade_routerboard_firmware(self) -> OperationResult:
        try:
            with self._client() as client:
                client.post(f"{self.base_url}/system/routerboard/upgrade")
                rb_res = client.get(f"{self.base_url}/system/routerboard")
                rb_data = rb_res.json() if rb_res.status_code == 200 else {}
                if isinstance(rb_data, list) and rb_data:
                    rb_data = rb_data[0]
                curr = rb_data.get("current-firmware") or rb_data.get("current_firmware", "")
                upg = rb_data.get("upgrade-firmware") or rb_data.get("upgrade_firmware", "")
                return OperationResult(
                    success=True,
                    message=(
                        f"⚡ **Upgrade Firmware RouterBOARD Berhasil!**\n\n"
                        f"• Target Router    : **{self.device_name}**\n"
                        f"• Firmware Versi   : `{curr}` ➔ `v{upg}`\n\n"
                        f"⚠️ *Catatan: Firmware bootloader telah ditulis ke chip BIOS router. Lakukan REBOOT router agar firmware baru mulai digunakan.*"
                    ),
                    data={"status": "UPGRADED_PENDING_REBOOT", "current_firmware": curr, "upgrade_firmware": upg, "device": self.device_name},
                    device=self.device_name,
                )
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_firmware_status(self, channel: str = "stable") -> OperationResult:
        try:
            rb_res = self.get_routerboard()
            update_res = self.check_router_update(channel=channel)
            rb_data = rb_res.data if rb_res.success and isinstance(rb_res.data, dict) else {}
            upd_data = update_res.data if update_res.success and isinstance(update_res.data, dict) else {}

            curr_fw = rb_data.get("current-firmware") or rb_data.get("current_firmware", "")
            upg_fw = rb_data.get("upgrade-firmware") or rb_data.get("upgrade_firmware", "")
            has_rb_update = bool(curr_fw and upg_fw and curr_fw != upg_fw)

            combined = {
                "routerboard": rb_data,
                "package_update": upd_data,
                "has_os_update": upd_data.get("update_available", False),
                "has_rb_update": has_rb_update,
            }
            return OperationResult(
                success=True,
                message="Informasi status firmware dan update RouterOS berhasil diambil.",
                data=combined,
                device=self.device_name,
            )
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)
