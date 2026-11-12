"""
Mock MikroTik Client for offline simulation, unit testing, and demonstration.
Maintains state in memory to allow full testing of read and write workflows.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from mikrotik.base import BaseMikrotikClient, OperationResult


class MockMikrotikClient(BaseMikrotikClient):
    def __init__(self, host: str = "127.0.0.1", port: int = 0, username: str = "admin", password: str = "", **kwargs):
        super().__init__(host, port, username, password)
        self.device_name = "Simulasi Router"
        self._connected = True

        # In-memory virtual router state
        self._resources = {
            "cpu_load": 14,
            "free_memory_mb": 158.4,
            "total_memory_mb": 256.0,
            "memory_usage_percent": 38.1,
            "uptime": "12d 08:44:21",
            "version": "7.15.2 (stable)",
            "board_name": "RB750Gr3",
            "architecture_name": "mmips",
            "cpu_count": 4,
            "free_hdd_space_mb": 11.2,
            "total_hdd_space_mb": 16.0,
            "cpu_frequency_mhz": 880,
            "bad_blocks_percent": 0.0,
        }

        self._identity = "MikroTik-Router-PTI"
        self._netwatch = [
            {"host": "8.8.8.8", "status": "up", "since": "sep/14 10:15:30", "interval": "1m", "timeout": "1000ms", "comment": "Internet Gateway Monitor"},
            {"host": "10.20.33.1", "status": "up", "since": "sep/14 10:15:30", "interval": "30s", "timeout": "500ms", "comment": "Core Switch"},
            {"host": "192.168.10.50", "status": "down", "since": "sep/15 08:20:11", "interval": "2m", "timeout": "1000ms", "comment": "Printer Server"},
        ]
        self._system_users = [
            {"name": "admin", "group": "full", "address": "", "last_logged_in": "sep/16 11:20:05", "comment": "Super Admin"},
            {"name": "teknisi", "group": "write", "address": "", "last_logged_in": "sep/15 14:10:00", "comment": "Teknisi Jaringan"},
            {"name": "monitoring", "group": "read", "address": "", "last_logged_in": "sep/16 12:00:00", "comment": "NOC Readonly"},
        ]
        self._packages = [
            {"name": "routeros", "version": "7.15.2", "bundle": "system", "disabled": False},
            {"name": "wireless", "version": "7.15.2", "bundle": "system", "disabled": False},
            {"name": "security", "version": "7.15.2", "bundle": "system", "disabled": False},
            {"name": "routing", "version": "7.15.2", "bundle": "system", "disabled": False},
        ]
        self._routerboard = {
            "routerboard": True,
            "model": "RB750Gr3",
            "serial_number": "HD808ABCDEF12",
            "current_firmware": "7.15.2",
            "upgrade_firmware": "7.16.1",
            "factory_firmware": "6.48.6",
            "board_name": "hEX",
        }
        self._package_update = {
            "channel": "stable",
            "installed_version": "7.15.2",
            "latest_version": "7.16.1",
            "status": "New version is available",
            "changelog": "RouterOS v7.16.1: Menambahkan optimasi performa routing, perbaikan stabilitas REST API & Winbox v4, serta patch keamanan kernel.",
        }
        self._clock = {
            "time": "13:55:00",
            "date": "sep/16/2026",
            "time_zone_name": "Asia/Jakarta",
            "gmt_offset": "+07:00",
            "dst_active": False,
        }
        self._sntp = {
            "enabled": True,
            "mode": "unicast",
            "primary_server": "pool.ntp.org",
            "secondary_server": "id.pool.ntp.org",
            "status": "synchronized",
        }
        self._traffic_monitors = [
            {"name": "wan-high-traffic", "interface": "ether1-WAN", "threshold": 50000000, "trigger": "above", "on_event": ":log warning 'WAN traffic spike'", "status": "active"},
            {"name": "lan-low-traffic", "interface": "ether2-LAN-Kantor", "threshold": 100000, "trigger": "below", "on_event": ":log info 'LAN traffic idle'", "status": "active"},
        ]

        self._interfaces = [
            {"name": "ether1-WAN", "type": "ether", "running": True, "disabled": False, "mac": "CC:2D:E0:1A:2B:01", "comment": "ISP Uplink", "rx_byte": 4523190200, "tx_byte": 1289401200, "rx_rate_kbps": 3420, "tx_rate_kbps": 1150},
            {"name": "ether2-LAN-Kantor", "type": "ether", "running": True, "disabled": False, "mac": "CC:2D:E0:1A:2B:02", "comment": "LAN Utama", "rx_byte": 1204910200, "tx_byte": 3819201920, "rx_rate_kbps": 1200, "tx_rate_kbps": 3100},
            {"name": "ether3-Hotspot", "type": "ether", "running": True, "disabled": False, "mac": "CC:2D:E0:1A:2B:03", "comment": "Hotspot Tamu & Mahasiswa", "rx_byte": 890412300, "tx_byte": 2109401200, "rx_rate_kbps": 850, "tx_rate_kbps": 1950},
            {"name": "ether4-Server", "type": "ether", "running": True, "disabled": False, "mac": "CC:2D:E0:1A:2B:04", "comment": "Lokal Server", "rx_byte": 341029100, "tx_byte": 412091000, "rx_rate_kbps": 120, "tx_rate_kbps": 180},
            {"name": "ether5", "type": "ether", "running": False, "disabled": True, "mac": "CC:2D:E0:1A:2B:05", "comment": "Cadangan", "rx_byte": 0, "tx_byte": 0, "rx_rate_kbps": 0, "tx_rate_kbps": 0},
            {"name": "wlan1", "type": "wlan", "running": True, "disabled": False, "mac": "CC:2D:E0:1A:2B:06", "comment": "AP Internal", "rx_byte": 612091200, "tx_byte": 1120912000, "rx_rate_kbps": 540, "tx_rate_kbps": 890},
        ]

        self._ip_addresses = [
            {"address": "10.20.33.240/24", "network": "10.20.33.0", "interface": "ether1-WAN", "comment": "WAN IP"},
            {"address": "192.168.10.1/24", "network": "192.168.10.0", "interface": "ether2-LAN-Kantor", "comment": "Gateway LAN"},
            {"address": "192.168.20.1/24", "network": "192.168.20.0", "interface": "ether3-Hotspot", "comment": "Gateway Hotspot"},
        ]

        self._ip_routes = [
            {"dst_address": "0.0.0.0/0", "gateway": "10.20.33.1", "active": True, "distance": 1, "comment": "Default Route Internet"},
            {"dst_address": "10.20.33.0/24", "gateway": "ether1-WAN", "active": True, "distance": 0, "comment": "Direct WAN"},
            {"dst_address": "192.168.10.0/24", "gateway": "ether2-LAN-Kantor", "active": True, "distance": 0, "comment": "Direct LAN"},
            {"dst_address": "192.168.20.0/24", "gateway": "ether3-Hotspot", "active": True, "distance": 0, "comment": "Direct Hotspot"},
        ]

        self._arp_table = [
            {"address": "10.20.33.1", "mac_address": "00:15:5D:01:02:AA", "interface": "ether1-WAN", "status": "reachable"},
            {"address": "192.168.10.15", "mac_address": "E4:5F:01:3C:99:A1", "interface": "ether2-LAN-Kantor", "status": "reachable"},
            {"address": "192.168.20.45", "mac_address": "80:D2:1D:55:12:03", "interface": "ether3-Hotspot", "status": "reachable"},
        ]

        self._dhcp_leases = [
            {"address": "192.168.10.15", "mac_address": "E4:5F:01:3C:99:A1", "host_name": "PC-Admin-01", "status": "bound", "expires_after": "2d 04:12:00"},
            {"address": "192.168.10.22", "mac_address": "F0:2F:74:11:88:B2", "host_name": "Laptop-Dosen-PTI", "status": "bound", "expires_after": "1d 22:45:00"},
            {"address": "192.168.20.45", "mac_address": "80:D2:1D:55:12:03", "host_name": "Smartphone-Tamu", "status": "bound", "expires_after": "05:12:30"},
        ]

        self._hotspot_users = [
            {"name": "admin_pti", "profile": "default", "uptime": "4h 12m", "bytes_in": 12049100, "bytes_out": 45192000, "limit_uptime": "unlimited"},
            {"name": "dosen01", "profile": "staff", "uptime": "2h 30m", "bytes_in": 8192000, "bytes_out": 22109000, "limit_uptime": "unlimited"},
            {"name": "mahasiswa1", "profile": "student", "uptime": "45m", "bytes_in": 2100400, "bytes_out": 8901200, "limit_uptime": "2h"},
        ]

        self._hotspot_active = [
            {"user": "admin_pti", "address": "192.168.20.10", "mac_address": "CC:2D:E0:99:88:77", "uptime": "4h 12m", "bytes_in": 12049100, "bytes_out": 45192000},
            {"user": "mahasiswa1", "address": "192.168.20.45", "mac_address": "80:D2:1D:55:12:03", "uptime": "45m", "bytes_in": 2100400, "bytes_out": 8901200},
        ]

        self._hotspot_profiles = [
            {"name": "default", "rate_limit": "10M/10M", "shared_users": 1},
            {"name": "staff", "rate_limit": "20M/20M", "shared_users": 2},
            {"name": "student", "rate_limit": "5M/5M", "shared_users": 1},
        ]

        self._firewall_rules = [
            {"chain": "input", "action": "accept", "connection_state": "established,related", "comment": "Allow established"},
            {"chain": "input", "action": "drop", "connection_state": "invalid", "comment": "Drop invalid"},
            {"chain": "input", "action": "accept", "protocol": "icmp", "comment": "Allow ping"},
            {"chain": "forward", "action": "accept", "connection_state": "established,related", "comment": "Fasttrack established"},
        ]

        self._system_logs = [
            {"time": "sep/14 10:15:02", "topics": "system,info", "message": "router rebooted"},
            {"time": "sep/14 11:30:12", "topics": "dhcp,info", "message": "dhcp1 assigned 192.168.10.15 to E4:5F:01:3C:99:A1"},
            {"time": "sep/14 12:05:44", "topics": "hotspot,info,debug", "message": "admin_pti logged in from 192.168.20.10"},
            {"time": "sep/14 12:45:10", "topics": "system,warning", "message": "WAN interface traffic spike detected: 35 Mbps"},
        ]

        self.custom_neighbors: Optional[List[Dict[str, Any]]] = None
        self._default_neighbors = [
            {
                "interface": "ether2-LAN-Kantor",
                "address": "192.168.88.1",
                "mac_address": "48:8F:5A:22:33:44",
                "identity": "Kantor Cabang",
                "platform": "MikroTik",
                "version": "7.15.2",
                "remote_interface": "ether1-Uplink",
                "board": "RB750Gr3",
                "protocol": "mndp",
                "age": "15s",
                "uptime": "12d 08:44:21",
            },
            {
                "interface": "ether3-Hotspot",
                "address": "192.168.10.1",
                "mac_address": "48:8F:5A:55:66:77",
                "identity": "Lab PTI",
                "platform": "MikroTik",
                "version": "7.14.3",
                "remote_interface": "ether1-WAN",
                "board": "hEX S",
                "protocol": "lldp",
                "age": "20s",
                "uptime": "5d 02:11:00",
            },
        ]

    def test_connection(self) -> OperationResult:
        return OperationResult(
            success=True,
            message="Koneksi simulasi MikroTik berhasil (Online).",
            data={"status": "online", "mode": "mock", "latency_ms": 1.2},
            device=self.device_name,
            latency_ms=1.2,
        )

    def get_resource(self) -> OperationResult:
        return OperationResult(
            success=True,
            message="Berhasil mengambil resource sistem.",
            data=self._resources,
            device=self.device_name,
            latency_ms=2.1,
        )

    def get_interfaces(self) -> OperationResult:
        return OperationResult(
            success=True,
            message=f"Berhasil mengambil {len(self._interfaces)} interface.",
            data=self._interfaces,
            device=self.device_name,
            latency_ms=3.4,
        )

    def set_mock_neighbors(self, neighbors: List[Dict[str, Any]]) -> None:
        """Allow injecting specific neighbor data for testing topologies."""
        self.custom_neighbors = neighbors

    def get_neighbors(self) -> OperationResult:
        if self.custom_neighbors is not None:
            return OperationResult(
                success=True,
                message=f"Berhasil mengambil {len(self.custom_neighbors)} neighbor.",
                data=self.custom_neighbors,
                device=self.device_name,
                latency_ms=1.5,
            )

        name_lower = self.device_name.lower()
        if "cabang 2" in name_lower:
            data = [
                {
                    "interface": "ether2",
                    "address": "192.168.88.1",
                    "mac_address": "48:8F:5A:22:33:55",
                    "identity": "Kantor Cabang",
                    "platform": "MikroTik",
                    "version": "7.15.2",
                    "remote_interface": "ether4",
                    "board": "RB750Gr3",
                    "protocol": "mndp",
                    "age": "10s",
                    "uptime": "4d 06:12:00",
                }
            ]
        elif "cabang" in name_lower:
            data = [
                {
                    "interface": "ether1-Uplink",
                    "address": "10.20.33.240",
                    "mac_address": "CC:2D:E0:1A:2B:02",
                    "identity": "Kantor Utama",
                    "platform": "MikroTik",
                    "version": "7.15.2",
                    "remote_interface": "ether2-LAN-Kantor",
                    "board": "RB750Gr3",
                    "protocol": "mndp",
                    "age": "15s",
                    "uptime": "12d 08:44:21",
                },
                {
                    "interface": "ether4",
                    "address": "10.20.188.6",
                    "mac_address": "48:8F:5A:88:99:AA",
                    "identity": "Kantor Cabang 2",
                    "platform": "MikroTik",
                    "version": "7.12.1",
                    "remote_interface": "ether2",
                    "board": "RB951Ui-2HnD",
                    "protocol": "mndp",
                    "age": "10s",
                    "uptime": "4d 06:12:00",
                },
            ]
        elif "lab" in name_lower:
            data = [
                {
                    "interface": "ether1-WAN",
                    "address": "10.20.33.240",
                    "mac_address": "CC:2D:E0:1A:2B:03",
                    "identity": "Kantor Utama",
                    "platform": "MikroTik",
                    "version": "7.15.2",
                    "remote_interface": "ether3-Hotspot",
                    "board": "RB750Gr3",
                    "protocol": "lldp",
                    "age": "20s",
                    "uptime": "12d 08:44:21",
                }
            ]
        else:
            data = self._default_neighbors

        return OperationResult(
            success=True,
            message=f"Berhasil mengambil {len(data)} neighbor.",
            data=data,
            device=self.device_name,
            latency_ms=1.8,
        )

    def get_ip_addresses(self) -> OperationResult:
        return OperationResult(
            success=True,
            message=f"Berhasil mengambil {len(self._ip_addresses)} IP address.",
            data=self._ip_addresses,
            device=self.device_name,
            latency_ms=2.0,
        )

    def get_ip_routes(self) -> OperationResult:
        return OperationResult(
            success=True,
            message=f"Berhasil mengambil {len(self._ip_routes)} route.",
            data=self._ip_routes,
            device=self.device_name,
            latency_ms=2.5,
        )

    def get_arp_table(self) -> OperationResult:
        return OperationResult(
            success=True,
            message=f"Berhasil mengambil {len(self._arp_table)} entri ARP.",
            data=self._arp_table,
            device=self.device_name,
            latency_ms=2.2,
        )

    def get_dhcp_leases(self) -> OperationResult:
        return OperationResult(
            success=True,
            message=f"Berhasil mengambil {len(self._dhcp_leases)} DHCP lease.",
            data=self._dhcp_leases,
            device=self.device_name,
            latency_ms=3.0,
        )

    def get_hotspot_users(self) -> OperationResult:
        return OperationResult(
            success=True,
            message=f"Berhasil mengambil {len(self._hotspot_users)} user hotspot.",
            data=self._hotspot_users,
            device=self.device_name,
            latency_ms=2.8,
        )

    def get_hotspot_active(self) -> OperationResult:
        return OperationResult(
            success=True,
            message=f"Berhasil mengambil {len(self._hotspot_active)} user hotspot aktif.",
            data=self._hotspot_active,
            device=self.device_name,
            latency_ms=2.6,
        )

    def get_hotspot_profiles(self) -> OperationResult:
        return OperationResult(
            success=True,
            message=f"Berhasil mengambil {len(self._hotspot_profiles)} profil hotspot.",
            data=self._hotspot_profiles,
            device=self.device_name,
            latency_ms=1.9,
        )

    def get_firewall_rules(self) -> OperationResult:
        return OperationResult(
            success=True,
            message=f"Berhasil mengambil {len(self._firewall_rules)} aturan firewall.",
            data=self._firewall_rules,
            device=self.device_name,
            latency_ms=3.1,
        )

    def get_system_logs(self, limit: int = 30) -> OperationResult:
        logs = self._system_logs[-limit:]
        return OperationResult(
            success=True,
            message=f"Berhasil mengambil {len(logs)} baris log sistem.",
            data=logs,
            device=self.device_name,
            latency_ms=2.4,
        )

    def ping(self, target: str, count: int = 4) -> OperationResult:
        # Realistic latency calculation
        avg_rtt = 14.5 if "8.8.8.8" in target or "1.1.1.1" in target else 2.1
        ping_data = {
            "host": target,
            "sent": count,
            "received": count,
            "packet_loss_percent": 0.0,
            "avg_rtt_ms": avg_rtt,
            "min_rtt_ms": avg_rtt - 2.0,
            "max_rtt_ms": avg_rtt + 3.5,
            "status": "Reachable / OK",
        }
        return OperationResult(
            success=True,
            message=f"Ping ke {target}: 0% packet loss, avg rtt {avg_rtt}ms.",
            data=ping_data,
            device=self.device_name,
            latency_ms=avg_rtt,
        )

    def create_hotspot_user(self, name: str, password: str = "", profile: str = "default", limit_uptime: str = "") -> OperationResult:
        # Check if already exists
        for user in self._hotspot_users:
            if user["name"].lower() == name.lower():
                return OperationResult(
                    success=False,
                    message=f"User hotspot '{name}' sudah ada.",
                    error=f"User '{name}' already exists",
                    device=self.device_name,
                )

        new_user = {
            "name": name,
            "password": password or "123456",
            "profile": profile or "default",
            "uptime": "0s",
            "bytes_in": 0,
            "bytes_out": 0,
            "limit_uptime": limit_uptime or "1d",
        }
        self._hotspot_users.append(new_user)
        self._system_logs.append({
            "time": time.strftime("%b/%d %H:%M:%S").lower(),
            "topics": "hotspot,info,account",
            "message": f"user {name} added by AI agent",
        })
        return OperationResult(
            success=True,
            message=f"✅ User hotspot '{name}' berhasil dibuat dengan profil '{profile}' dan masa aktif '{limit_uptime or '1d'}'.",
            data=new_user,
            device=self.device_name,
            latency_ms=12.0,
        )

    def delete_hotspot_user(self, name: str) -> OperationResult:
        for idx, user in enumerate(self._hotspot_users):
            if user["name"].lower() == name.lower():
                removed = self._hotspot_users.pop(idx)
                # Also remove from active sessions if logged in
                self._hotspot_active = [u for u in self._hotspot_active if u["user"].lower() != name.lower()]
                self._system_logs.append({
                    "time": time.strftime("%b/%d %H:%M:%S").lower(),
                    "topics": "hotspot,info,account",
                    "message": f"user {name} removed by AI agent",
                })
                return OperationResult(
                    success=True,
                    message=f"✅ User hotspot '{name}' berhasil dihapus.",
                    data=removed,
                    device=self.device_name,
                    latency_ms=10.5,
                )
        return OperationResult(
            success=False,
            message=f"User hotspot '{name}' tidak ditemukan.",
            error="User not found",
            device=self.device_name,
        )

    def set_interface_state(self, interface_name: str, enabled: bool) -> OperationResult:
        for iface in self._interfaces:
            if iface["name"].lower() == interface_name.lower():
                iface["disabled"] = not enabled
                iface["running"] = enabled
                state_str = "diaktifkan (enabled)" if enabled else "dinonaktifkan (disabled)"
                self._system_logs.append({
                    "time": time.strftime("%b/%d %H:%M:%S").lower(),
                    "topics": "interface,info",
                    "message": f"interface {interface_name} {state_str} by AI agent",
                })
                return OperationResult(
                    success=True,
                    message=f"✅ Interface '{interface_name}' berhasil {state_str}.",
                    data=iface,
                    device=self.device_name,
                    latency_ms=15.2,
                )
        return OperationResult(
            success=False,
            message=f"Interface '{interface_name}' tidak ditemukan.",
            error="Interface not found",
            device=self.device_name,
        )

    def add_ip_address(self, address: str, interface: str, comment: str = "") -> OperationResult:
        clean_addr = address.strip()
        if "/" not in clean_addr:
            clean_addr = f"{clean_addr}/24"

        for ip_ent in self._ip_addresses:
            if ip_ent.get("address", "").split("/")[0] == clean_addr.split("/")[0]:
                return OperationResult(
                    success=False,
                    message=f"IP address {clean_addr} sudah terkonfigurasi pada interface {ip_ent.get('interface')}.",
                    device=self.device_name,
                )

        new_entry = {
            "address": clean_addr,
            "network": clean_addr.split("/")[0].rsplit(".", 1)[0] + ".0",
            "interface": interface,
            "comment": comment or "Dibuat via MikroTik AI Bot",
        }
        self._ip_addresses.append(new_entry)
        self._system_logs.append({
            "time": time.strftime("%b/%d %H:%M:%S").lower(),
            "topics": "ip,address,info",
            "message": f"ip address {clean_addr} added on {interface} by AI agent",
        })
        return OperationResult(
            success=True,
            message=f"✅ IP address '{clean_addr}' berhasil ditambahkan ke interface '{interface}'.",
            data=new_entry,
            device=self.device_name,
            latency_ms=10.0,
        )

    def remove_ip_address(self, address: str) -> OperationResult:
        clean_target = address.strip()
        matched = None
        for ip_ent in self._ip_addresses:
            curr_addr = ip_ent.get("address", "")
            if curr_addr == clean_target or curr_addr.split("/")[0] == clean_target.split("/")[0]:
                matched = ip_ent
                break

        if not matched:
            return OperationResult(
                success=False,
                message=f"IP address '{address}' tidak ditemukan pada router.",
                device=self.device_name,
            )

        self._ip_addresses.remove(matched)
        self._system_logs.append({
            "time": time.strftime("%b/%d %H:%M:%S").lower(),
            "topics": "ip,address,info",
            "message": f"ip address {matched['address']} removed by AI agent",
        })
        return OperationResult(
            success=True,
            message=f"✅ IP address '{matched['address']}' ({matched.get('interface')}) berhasil dihapus.",
            data=matched,
            device=self.device_name,
            latency_ms=8.0,
        )

    def set_ip_address(
        self,
        current_address: str,
        new_address: Optional[str] = None,
        new_interface: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> OperationResult:
        clean_target = current_address.strip()
        matched = None
        for ip_ent in self._ip_addresses:
            curr_addr = ip_ent.get("address", "")
            if curr_addr == clean_target or curr_addr.split("/")[0] == clean_target.split("/")[0]:
                matched = ip_ent
                break

        if not matched:
            return OperationResult(
                success=False,
                message=f"IP address '{current_address}' tidak ditemukan untuk diubah.",
                device=self.device_name,
            )

        if new_address:
            clean_new = new_address.strip()
            if "/" not in clean_new:
                clean_new = f"{clean_new}/24"
            matched["address"] = clean_new
            matched["network"] = clean_new.split("/")[0].rsplit(".", 1)[0] + ".0"
        if new_interface:
            matched["interface"] = new_interface
        if comment is not None:
            matched["comment"] = comment

        self._system_logs.append({
            "time": time.strftime("%b/%d %H:%M:%S").lower(),
            "topics": "ip,address,info",
            "message": f"ip address updated to {matched['address']} by AI agent",
        })
        return OperationResult(
            success=True,
            message=f"✅ IP address berhasil diubah menjadi '{matched['address']}' pada interface '{matched.get('interface')}'.",
            data=matched,
            device=self.device_name,
            latency_ms=12.0,
        )

    def execute_raw_command(self, path: str, command: str, params: Optional[Dict[str, Any]] = None) -> OperationResult:
        return OperationResult(
            success=True,
            message=f"Operasi {path} '{command}' selesai (mock mode).",
            data={"path": path, "command": command, "params": params or {}},
            device=self.device_name,
            latency_ms=5.0,
        )

    # =========================================================================
    # WINBOX TOOLS MENU (MOCK IMPLEMENTATIONS)
    # =========================================================================
    def traceroute(self, target: str, count: int = 4) -> OperationResult:
        hops = [
            {"hop": 1, "address": "10.20.33.1", "rtt_ms": 1.2, "status": "OK"},
            {"hop": 2, "address": "180.252.16.1", "rtt_ms": 8.4, "status": "OK"},
            {"hop": 3, "address": "202.152.0.22", "rtt_ms": 16.5, "status": "OK"},
            {"hop": 4, "address": target, "rtt_ms": 22.1, "status": "Reached Target"},
        ]
        return OperationResult(
            success=True,
            message=f"Traceroute ke {target} selesai ({len(hops)} hops).",
            data={"target": target, "hops": hops, "total_hops": len(hops)},
            device=self.device_name,
            latency_ms=22.1,
        )

    def torch(self, interface: str, duration: int = 3) -> OperationResult:
        streams = [
            {"src_address": "192.168.10.15", "dst_address": "142.250.190.46", "protocol": "tcp", "port": 443, "rx_rate_kbps": 2400, "tx_rate_kbps": 120},
            {"src_address": "192.168.20.45", "dst_address": "157.240.22.35", "protocol": "tcp", "port": 443, "rx_rate_kbps": 850, "tx_rate_kbps": 45},
            {"src_address": "10.20.33.240", "dst_address": "8.8.8.8", "protocol": "udp", "port": 53, "rx_rate_kbps": 12, "tx_rate_kbps": 12},
        ]
        return OperationResult(
            success=True,
            message=f"Pemantauan traffic (Torch) pada interface '{interface}' selama {duration}s selesai.",
            data={"interface": interface, "active_streams": streams, "duration_sec": duration},
            device=self.device_name,
            latency_ms=10.0,
        )

    def bandwidth_test(self, target: str, direction: str = "both", duration: int = 5, protocol: str = "udp") -> OperationResult:
        return OperationResult(
            success=True,
            message=f"Bandwidth test ke {target} ({protocol.upper()}, {direction}) selesai.",
            data={
                "target": target,
                "protocol": protocol.upper(),
                "direction": direction,
                "duration_sec": duration,
                "rx_throughput_mbps": 94.8,
                "tx_throughput_mbps": 48.2,
                "lost_packets": 2,
                "jitter_ms": 1.4,
                "status": "Completed",
            },
            device=self.device_name,
            latency_ms=15.0,
        )

    def get_netwatch(self) -> OperationResult:
        return OperationResult(
            success=True,
            message=f"Berhasil mengambil {len(self._netwatch)} host Netwatch.",
            data=self._netwatch,
            device=self.device_name,
            latency_ms=2.5,
        )

    def add_netwatch(self, host: str, interval: str = "1m", timeout: str = "1000ms", comment: str = "") -> OperationResult:
        entry = {
            "host": host,
            "status": "up",
            "since": time.strftime("%b/%d %H:%M:%S").lower(),
            "interval": interval,
            "timeout": timeout,
            "comment": comment or "Netwatch created via AI Agent",
        }
        self._netwatch.append(entry)
        return OperationResult(
            success=True,
            message=f"✅ Host Netwatch '{host}' berhasil ditambahkan (Interval: {interval}, Timeout: {timeout}).",
            data=entry,
            device=self.device_name,
            latency_ms=5.0,
        )

    def ip_scan(self, interface: str, address_range: str = "", duration: int = 5) -> OperationResult:
        scanned_hosts = [
            {"ip": "192.168.10.1", "mac_address": "CC:2D:E0:1A:2B:02", "dns_name": "router.local", "status": "active"},
            {"ip": "192.168.10.15", "mac_address": "E4:5F:01:3C:99:A1", "dns_name": "PC-Admin-01", "status": "active"},
            {"ip": "192.168.10.22", "mac_address": "F0:2F:74:11:88:B2", "dns_name": "Laptop-Dosen", "status": "active"},
            {"ip": "192.168.10.50", "mac_address": "70:85:C2:10:44:A9", "dns_name": "Printer-Server", "status": "active"},
        ]
        return OperationResult(
            success=True,
            message=f"IP Scan pada interface '{interface}' ({address_range or 'subnet default'}) menemukan {len(scanned_hosts)} host aktif.",
            data={"interface": interface, "range": address_range, "discovered": scanned_hosts},
            device=self.device_name,
            latency_ms=12.0,
        )

    def get_profile(self, duration: int = 3) -> OperationResult:
        breakdown = [
            {"process": "firewall", "cpu_percent": 3.5},
            {"process": "ethernet", "cpu_percent": 2.8},
            {"process": "networking", "cpu_percent": 2.1},
            {"process": "management", "cpu_percent": 1.4},
            {"process": "queuing", "cpu_percent": 0.8},
            {"process": "idle", "cpu_percent": 89.4},
        ]
        return OperationResult(
            success=True,
            message=f"Profile beban CPU MikroTik selama {duration}s berhasil diambil.",
            data={"duration_sec": duration, "cpu_usage": breakdown, "total_busy_percent": 10.6},
            device=self.device_name,
            latency_ms=5.0,
        )

    def send_email(self, to: str, subject: str, body: str) -> OperationResult:
        self._system_logs.append({
            "time": time.strftime("%b/%d %H:%M:%S").lower(),
            "topics": "system,info",
            "message": f"email sent to {to} with subject '{subject}'",
        })
        return OperationResult(
            success=True,
            message=f"✅ Notifikasi email berhasil dikirim ke '{to}'.",
            data={"to": to, "subject": subject, "body": body, "status": "SENT"},
            device=self.device_name,
            latency_ms=120.0,
        )

    def get_packet_sniffer(self) -> OperationResult:
        return OperationResult(
            success=True,
            message="Status Packet Sniffer berhasil diambil.",
            data={
                "running": False,
                "interface": "all",
                "file_name": "",
                "memory_limit_kb": 100,
                "filter_stream": True,
            },
            device=self.device_name,
            latency_ms=3.0,
        )

    def sniff_packets(self, interface: str = "", count: int = 10) -> OperationResult:
        packets = [
            {"num": 1, "time": "0.001", "interface": interface or "ether1-WAN", "src": "10.20.33.240:443", "dst": "142.250.190.46:53210", "proto": "TCP", "size": 1420},
            {"num": 2, "time": "0.003", "interface": interface or "ether1-WAN", "src": "192.168.10.15:53", "dst": "8.8.8.8:53", "proto": "UDP", "size": 78},
            {"num": 3, "time": "0.005", "interface": interface or "ether2-LAN-Kantor", "src": "192.168.10.22", "dst": "192.168.10.1", "proto": "ICMP", "size": 64},
        ]
        return OperationResult(
            success=True,
            message=f"Berhasil menangkap {len(packets)} paket data dari sniffer.",
            data={"interface": interface or "all", "packets": packets},
            device=self.device_name,
            latency_ms=8.0,
        )

    def get_traffic_monitor(self) -> OperationResult:
        return OperationResult(
            success=True,
            message=f"Berhasil mengambil {len(self._traffic_monitors)} traffic monitor.",
            data=self._traffic_monitors,
            device=self.device_name,
            latency_ms=2.0,
        )

    def add_traffic_monitor(self, name: str, interface: str, threshold: str, trigger: str = "above", on_event: str = "") -> OperationResult:
        entry = {
            "name": name,
            "interface": interface,
            "threshold": int(threshold) if str(threshold).isdigit() else 50000000,
            "trigger": trigger,
            "on_event": on_event or ":log info 'Traffic threshold exceeded'",
            "status": "active",
        }
        self._traffic_monitors.append(entry)
        return OperationResult(success=True, message=f"✅ Aturan Traffic Monitor '{name}' berhasil ditambahkan.", data=entry, device=self.device_name, latency_ms=5.0)

    # =========================================================================
    # WINBOX SYSTEM MENU (MOCK IMPLEMENTATIONS)
    # =========================================================================
    def get_identity(self) -> OperationResult:
        ident = self._identity
        if self.device_name and self.device_name not in ("127.0.0.1", "Unknown", "Simulasi Router", "mock_demo"):
            clean_name = self.device_name.replace(" [Simulasi Offline]", "").strip()
            if clean_name:
                ident = clean_name
        return OperationResult(
            success=True,
            message=f"Identitas router: '{ident}'",
            data={"name": ident},
            device=self.device_name,
            latency_ms=1.5,
        )

    def set_identity(self, name: str) -> OperationResult:
        old_name = self._identity
        self._identity = name
        self.device_name = name
        self._system_logs.append({
            "time": time.strftime("%b/%d %H:%M:%S").lower(),
            "topics": "system,info",
            "message": f"system identity changed from '{old_name}' to '{name}'",
        })
        return OperationResult(
            success=True,
            message=f"✅ Identitas router berhasil diubah menjadi '{name}'.",
            data={"old_name": old_name, "new_name": name},
            device=self.device_name,
            latency_ms=4.0,
        )

    def get_system_users(self) -> OperationResult:
        return OperationResult(
            success=True,
            message=f"Berhasil mengambil {len(self._system_users)} user sistem MikroTik.",
            data=self._system_users,
            device=self.device_name,
            latency_ms=2.0,
        )

    def create_system_user(self, name: str, group: str = "read", password: str = "") -> OperationResult:
        for u in self._system_users:
            if u["name"].lower() == name.lower():
                return OperationResult(
                    success=False,
                    message=f"User '{name}' sudah terdaftar di sistem.",
                    error="User already exists",
                    device=self.device_name,
                )
        new_u = {
            "name": name,
            "group": group,
            "address": "",
            "last_logged_in": "never",
            "comment": "Created via Hermes AI Telegram Bot",
        }
        self._system_users.append(new_u)
        self._system_logs.append({
            "time": time.strftime("%b/%d %H:%M:%S").lower(),
            "topics": "system,info,account",
            "message": f"user {name} added to group {group}",
        })
        return OperationResult(
            success=True,
            message=f"✅ User sistem '{name}' berhasil dibuat dengan grup akses '{group}'.",
            data=new_u,
            device=self.device_name,
            latency_ms=6.0,
        )

    def delete_system_user(self, name: str) -> OperationResult:
        if name.lower() == "admin":
            return OperationResult(
                success=False,
                message="User default 'admin' tidak dapat dihapus demi keamanan akses router.",
                error="Cannot delete default admin",
                device=self.device_name,
            )
        for i, u in enumerate(self._system_users):
            if u["name"].lower() == name.lower():
                del self._system_users[i]
                self._system_logs.append({
                    "time": time.strftime("%b/%d %H:%M:%S").lower(),
                    "topics": "system,info,account",
                    "message": f"user {name} removed",
                })
                return OperationResult(
                    success=True,
                    message=f"✅ User sistem '{name}' berhasil dihapus.",
                    device=self.device_name,
                    latency_ms=5.0,
                )
        return OperationResult(
            success=False,
            message=f"User sistem '{name}' tidak ditemukan.",
            error="User not found",
            device=self.device_name,
        )

    def get_packages(self) -> OperationResult:
        return OperationResult(
            success=True,
            message=f"Berhasil mengambil {len(self._packages)} paket RouterOS.",
            data=self._packages,
            device=self.device_name,
            latency_ms=2.0,
        )

    def get_routerboard(self) -> OperationResult:
        return OperationResult(
            success=True,
            message="Informasi RouterBOARD hardware dan firmware berhasil diambil.",
            data=self._routerboard,
            device=self.device_name,
            latency_ms=2.5,
        )

    def get_clock_sntp(self) -> OperationResult:
        combined = {
            "clock": self._clock,
            "sntp": self._sntp,
        }
        return OperationResult(
            success=True,
            message="Informasi Clock dan SNTP Client berhasil diambil.",
            data=combined,
            device=self.device_name,
            latency_ms=2.0,
        )

    def set_clock_timezone(self, time_zone: str) -> OperationResult:
        self._clock["time_zone_name"] = time_zone
        return OperationResult(
            success=True,
            message=f"✅ Zona waktu router berhasil diatur ke '{time_zone}'.",
            data=self._clock,
            device=self.device_name,
            latency_ms=5.0,
        )

    def reboot(self) -> OperationResult:
        self._system_logs.append({
            "time": time.strftime("%b/%d %H:%M:%S").lower(),
            "topics": "system,info",
            "message": "system reboot triggered by admin via Telegram Bot",
        })
        return OperationResult(
            success=True,
            message=f"🔄 Router '{self.device_name}' sedang melakukan proses REBOOT...\nSistem akan offline sementara selama 30-60 detik dan otomatis kembali aktif.",
            data={"status": "REBOOTING", "device": self.device_name},
            device=self.device_name,
            latency_ms=10.0,
        )

    def shutdown(self) -> OperationResult:
        self._system_logs.append({
            "time": time.strftime("%b/%d %H:%M:%S").lower(),
            "topics": "system,info",
            "message": "system shutdown triggered by admin via Telegram Bot",
        })
        return OperationResult(
            success=True,
            message=f"🔌 Router '{self.device_name}' sedang melakukan proses SHUTDOWN secara aman.\nPerangkat akan mati dan perlu dinyalakan kembali secara manual.",
            data={"status": "SHUTTING_DOWN", "device": self.device_name},
            device=self.device_name,
            latency_ms=10.0,
        )

    def check_router_update(self, channel: str = "stable") -> OperationResult:
        if channel:
            self._package_update["channel"] = channel
        has_update = self._package_update["installed_version"] != self._package_update["latest_version"]
        self._package_update["update_available"] = has_update
        msg = (
            f"Update tersedia: v{self._package_update['installed_version']} ➔ v{self._package_update['latest_version']} (Channel: {self._package_update['channel']})."
            if has_update
            else f"Sistem sudah menggunakan versi terbaru (v{self._package_update['installed_version']})."
        )
        return OperationResult(
            success=True,
            message=msg,
            data=dict(self._package_update),
            device=self.device_name,
            latency_ms=3.0,
        )

    def install_router_update(self, channel: str = "stable") -> OperationResult:
        if channel:
            self._package_update["channel"] = channel
        old_ver = self._package_update["installed_version"]
        new_ver = self._package_update["latest_version"]

        # Apply upgrade
        self._package_update["installed_version"] = new_ver
        self._package_update["status"] = "System is already up to date"
        self._package_update["update_available"] = False

        # Update packages list
        for pkg in self._packages:
            pkg["version"] = new_ver

        # Update system resource version
        self._resources["version"] = f"{new_ver} (stable)"

        # RouterBOARD upgrade firmware is now available to match new OS
        self._routerboard["upgrade_firmware"] = new_ver

        self._system_logs.append({
            "time": time.strftime("%b/%d %H:%M:%S").lower(),
            "topics": "system,info",
            "message": f"system package upgraded from {old_ver} to {new_ver} and rebooted",
        })

        return OperationResult(
            success=True,
            message=(
                f"🚀 **Upgrade RouterOS Berhasil Dimulai!**\n\n"
                f"• Target Router : **{self.device_name}**\n"
                f"• Versi Lama    : `v{old_ver}`\n"
                f"• Versi Baru    : `v{new_ver}` (Channel: `{self._package_update['channel']}`)\n"
                f"• Status        : Paket telah diunduh dan sistem sedang melakukan REBOOT otomatis.\n"
                f"⏳ Router akan offline sementara selama 1-3 menit untuk proses flash writing dan reboot."
            ),
            data={
                "status": "UPGRADE_INSTALLED_REBOOTING",
                "old_version": old_ver,
                "new_version": new_ver,
                "device": self.device_name,
            },
            device=self.device_name,
            latency_ms=15.0,
        )

    def upgrade_routerboard_firmware(self) -> OperationResult:
        curr = self._routerboard.get("current_firmware", "7.15.2")
        upg = self._routerboard.get("upgrade_firmware", "7.16.1")

        self._routerboard["current_firmware"] = upg
        self._system_logs.append({
            "time": time.strftime("%b/%d %H:%M:%S").lower(),
            "topics": "system,info",
            "message": f"routerboard firmware upgraded from {curr} to {upg}",
        })

        return OperationResult(
            success=True,
            message=(
                f"⚡ **Upgrade Firmware RouterBOARD Berhasil!**\n\n"
                f"• Target Router    : **{self.device_name}**\n"
                f"• Model Hardware   : `{self._routerboard.get('model', 'RB750Gr3')}`\n"
                f"• Serial Number    : `{self._routerboard.get('serial_number', '-')}`\n"
                f"• Firmware Bootloader : `{curr}` ➔ `v{upg}`\n\n"
                f"⚠️ *Catatan: Firmware bootloader telah ditulis ke flash BIOS. Lakukan reboot router (`/system reboot`) agar firmware baru aktif sepenuhnya.*"
            ),
            data={
                "status": "FIRMWARE_UPGRADED",
                "current_firmware": upg,
                "previous_firmware": curr,
                "model": self._routerboard.get("model"),
                "device": self.device_name,
            },
            device=self.device_name,
            latency_ms=8.0,
        )

    def get_firmware_status(self, channel: str = "stable") -> OperationResult:
        if channel:
            self._package_update["channel"] = channel
        has_os_update = self._package_update["installed_version"] != self._package_update["latest_version"]
        has_rb_update = self._routerboard.get("current_firmware") != self._routerboard.get("upgrade_firmware")

        rb_data = dict(self._routerboard)
        # Mirror both hyphen and underscore formats for hardware parity
        for k, v in list(rb_data.items()):
            if "_" in k:
                rb_data[k.replace("_", "-")] = v
            elif "-" in k:
                rb_data[k.replace("-", "_")] = v

        combined = {
            "routerboard": rb_data,
            "package_update": dict(self._package_update),
            "has_os_update": has_os_update,
            "has_rb_update": has_rb_update,
        }
        return OperationResult(
            success=True,
            message="Informasi status firmware dan update RouterOS berhasil diambil.",
            data=combined,
            device=self.device_name,
            latency_ms=3.0,
        )
