"""
MikroTik SSH Client for executing RouterOS CLI commands.
Uses paramiko or Windows native OpenSSH client.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from typing import Any, Dict, List, Optional
from mikrotik.base import BaseMikrotikClient, OperationResult


class MikrotikSshClient(BaseMikrotikClient):
    def __init__(
        self,
        host: str,
        port: int = 22,
        username: str = "admin",
        password: str = "",
        timeout: float = 5.0,
        **kwargs,
    ):
        super().__init__(host, port, username, password, timeout=timeout)

    def _exec_command(self, cmd: str) -> str:
        # Construct SSH command line using Windows built-in ssh.exe
        ssh_cmd = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=no",
            "-o", f"ConnectTimeout={int(self.timeout)}",
            "-p", str(self.port),
            f"{self.username}@{self.host}",
            cmd,
        ]
        proc = subprocess.run(ssh_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=self.timeout + 3)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout)
        return proc.stdout

    def test_connection(self) -> OperationResult:
        start = time.time()
        try:
            out = self._exec_command("/system identity print")
            latency = (time.time() - start) * 1000
            return OperationResult(
                success=True,
                message=f"Koneksi SSH ke MikroTik {self.host}:{self.port} berhasil.",
                data={"output": out.strip()},
                device=self.device_name,
                latency_ms=latency,
            )
        except Exception as e:
            latency = (time.time() - start) * 1000
            return OperationResult(
                success=False,
                message=f"Gagal koneksi SSH ke {self.host}:{self.port}.",
                error=str(e),
                device=self.device_name,
                latency_ms=latency,
            )

    def get_resource(self) -> OperationResult:
        try:
            out = self._exec_command("/system resource print")
            data: Dict[str, Any] = {}
            for line in out.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip().replace(" ", "_").lower()
                    v = v.strip()
                    data[k] = v
            return OperationResult(success=True, data=data, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_interfaces(self) -> OperationResult:
        try:
            out = self._exec_command("/interface print detail without-paging")
            return OperationResult(success=True, data={"raw": out}, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_neighbors(self) -> OperationResult:
        try:
            out = self._exec_command("/ip neighbor print detail without-paging")
            records: List[Dict[str, Any]] = []
            current: Dict[str, str] = {}
            for line in out.splitlines():
                line = line.strip()
                if not line:
                    continue
                if re.match(r"^\d+\s+", line):
                    if current:
                        records.append(current)
                        current = {}
                    line = re.sub(r"^\d+\s+", "", line)

                matches = re.findall(r'([\w-]+)=(?:"([^"]*)"|([^\s]+))', line)
                for k, v_quoted, v_unquoted in matches:
                    val = v_quoted if v_quoted != "" else v_unquoted
                    current[k] = val

            if current:
                records.append(current)

            normalized = []
            for item in records:
                normalized.append({
                    "interface": item.get("interface", ""),
                    "address": item.get("address", "") or item.get("address4", ""),
                    "mac_address": (item.get("mac-address", "") or item.get("mac", "")).upper(),
                    "identity": item.get("identity", ""),
                    "platform": item.get("platform", "MikroTik"),
                    "version": item.get("version", ""),
                    "remote_interface": item.get("interface-name", "") or item.get("remote-interface", ""),
                    "board": item.get("board", ""),
                    "protocol": (item.get("discovered-by", "") or item.get("discovery-protocol", "mndp")).lower(),
                    "age": item.get("age", ""),
                    "uptime": item.get("uptime", ""),
                })
            return OperationResult(
                success=True,
                message=f"Berhasil mengambil {len(normalized)} neighbor via SSH.",
                data=normalized,
                device=self.device_name,
            )
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_ip_addresses(self) -> OperationResult:
        try:
            out = self._exec_command("/ip address print detail without-paging")
            return OperationResult(success=True, data={"raw": out}, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_ip_routes(self) -> OperationResult:
        try:
            out = self._exec_command("/ip route print detail without-paging")
            return OperationResult(success=True, data={"raw": out}, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_arp_table(self) -> OperationResult:
        try:
            out = self._exec_command("/ip arp print without-paging")
            return OperationResult(success=True, data={"raw": out}, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_dhcp_leases(self) -> OperationResult:
        try:
            out = self._exec_command("/ip dhcp-server lease print detail without-paging")
            return OperationResult(success=True, data={"raw": out}, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_hotspot_users(self) -> OperationResult:
        try:
            out = self._exec_command("/ip hotspot user print detail without-paging")
            return OperationResult(success=True, data={"raw": out}, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_hotspot_active(self) -> OperationResult:
        try:
            out = self._exec_command("/ip hotspot active print detail without-paging")
            return OperationResult(success=True, data={"raw": out}, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_hotspot_profiles(self) -> OperationResult:
        try:
            out = self._exec_command("/ip hotspot user profile print detail without-paging")
            return OperationResult(success=True, data={"raw": out}, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_firewall_rules(self) -> OperationResult:
        try:
            out = self._exec_command("/ip firewall filter print without-paging")
            return OperationResult(success=True, data={"raw": out}, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_system_logs(self, limit: int = 30) -> OperationResult:
        try:
            out = self._exec_command(f"/log print without-paging")
            lines = out.splitlines()[-limit:]
            return OperationResult(success=True, data=lines, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def ping(self, target: str, count: int = 4) -> OperationResult:
        try:
            out = self._exec_command(f"/ping address={target} count={count}")
            return OperationResult(success=True, data={"raw": out}, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def create_hotspot_user(self, name: str, password: str = "", profile: str = "default", limit_uptime: str = "") -> OperationResult:
        try:
            cmd = f'/ip hotspot user add name="{name}" profile="{profile or "default"}"'
            if password:
                cmd += f' password="{password}"'
            if limit_uptime:
                cmd += f' limit-uptime="{limit_uptime}"'
            out = self._exec_command(cmd)
            return OperationResult(success=True, message=f"✅ User hotspot '{name}' dibuat via SSH.", data=out, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def delete_hotspot_user(self, name: str) -> OperationResult:
        try:
            cmd = f'/ip hotspot user remove [find name="{name}"]'
            out = self._exec_command(cmd)
            return OperationResult(success=True, message=f"✅ User hotspot '{name}' dihapus via SSH.", data=out, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def set_interface_state(self, interface_name: str, enabled: bool) -> OperationResult:
        try:
            action = "enable" if enabled else "disable"
            cmd = f'/interface {action} [find name="{interface_name}"]'
            out = self._exec_command(cmd)
            state_str = "diaktifkan" if enabled else "dinonaktifkan"
            return OperationResult(success=True, message=f"✅ Interface '{interface_name}' berhasil {state_str} via SSH.", data=out, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def add_ip_address(self, address: str, interface: str, comment: str = "") -> OperationResult:
        try:
            cmd = f'/ip address add address="{address.strip()}" interface="{interface.strip()}"'
            if comment:
                cmd += f' comment="{comment}"'
            out = self._exec_command(cmd)
            return OperationResult(success=True, message=f"✅ IP address '{address}' ditambahkan via SSH.", data=out, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def remove_ip_address(self, address: str) -> OperationResult:
        try:
            cmd = f'/ip address remove [find address~"{address.strip()}"]'
            out = self._exec_command(cmd)
            return OperationResult(success=True, message=f"✅ IP address '{address}' dihapus via SSH.", data=out, device=self.device_name)
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
            params = []
            if new_address:
                params.append(f'address="{new_address.strip()}"')
            if new_interface:
                params.append(f'interface="{new_interface.strip()}"')
            if comment is not None:
                params.append(f'comment="{comment}"')
            cmd = f'/ip address set [find address~"{current_address.strip()}"] {" ".join(params)}'
            out = self._exec_command(cmd)
            return OperationResult(success=True, message=f"✅ IP address '{current_address}' diperbarui via SSH.", data=out, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def execute_raw_command(self, path: str, command: str, params: Optional[Dict[str, Any]] = None) -> OperationResult:
        try:
            full_cmd = f"/{path.strip('/')} {command.strip('/')}"
            out = self._exec_command(full_cmd)
            return OperationResult(success=True, data=out, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_routerboard(self) -> OperationResult:
        try:
            out = self._exec_command("/system routerboard print")
            data: Dict[str, Any] = {}
            for line in out.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip()
                    v = v.strip()
                    if k:
                        data[k] = v
                        if "-" in k:
                            data[k.replace("-", "_")] = v
            return OperationResult(success=True, message="Informasi RouterBOARD berhasil diambil via SSH.", data=data, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def check_router_update(self, channel: str = "stable") -> OperationResult:
        try:
            if channel:
                self._exec_command(f"/system package update set channel={channel}")
            self._exec_command("/system package update check-for-updates")
            out = self._exec_command("/system package update print")
            installed = ""
            latest = ""
            status_text = ""
            for line in out.splitlines():
                if "installed-version:" in line:
                    installed = line.split("installed-version:", 1)[1].strip()
                elif "latest-version:" in line:
                    latest = line.split("latest-version:", 1)[1].strip()
                elif "status:" in line:
                    status_text = line.split("status:", 1)[1].strip()
                elif "channel:" in line:
                    channel = line.split("channel:", 1)[1].strip()
            if not latest and ("up to date" in status_text.lower() or not (latest and latest != installed)):
                latest = installed
            has_update = bool(latest and installed and latest != installed)
            norm = {
                "channel": channel,
                "installed_version": installed,
                "installed-version": installed,
                "latest_version": latest,
                "latest-version": latest,
                "status": status_text or ("New version is available" if has_update else "System is up to date"),
                "update_available": has_update,
                "raw": out,
            }
            msg = f"Update RouterOS tersedia: v{installed} ➔ v{latest} (Channel: {channel})." if has_update else f"RouterOS sudah versi terbaru (v{installed})."
            return OperationResult(success=True, message=msg, data=norm, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def install_router_update(self, channel: str = "stable") -> OperationResult:
        try:
            if channel:
                self._exec_command(f"/system package update set channel={channel}")
            try:
                self._exec_command("/system package update install")
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
            out = self._exec_command("/system routerboard upgrade\ny")
            return OperationResult(
                success=True,
                message=(
                    f"⚡ **Upgrade Firmware RouterBOARD Berhasil!**\n\n"
                    f"• Target Router    : **{self.device_name}**\n\n"
                    f"⚠️ *Catatan: Perintah upgrade firmware bootloader telah dikirimkan ke router. Lakukan REBOOT router agar firmware baru mulai digunakan.*"
                ),
                data={"status": "UPGRADED_PENDING_REBOOT", "output": out, "device": self.device_name},
                device=self.device_name,
            )
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_firmware_status(self, channel: str = "stable") -> OperationResult:
        try:
            rb_res = self.get_routerboard()
            update_res = self.check_router_update(channel=channel)
            rb_data = rb_res.data if rb_res.success and isinstance(rb_res.data, dict) else {}
            curr_fw = rb_data.get("current_firmware") or rb_data.get("current-firmware", "")
            upg_fw = rb_data.get("upgrade_firmware") or rb_data.get("upgrade-firmware", "")
            has_rb_update = bool(curr_fw and upg_fw and curr_fw != upg_fw)
            combined = {
                "routerboard": rb_data,
                "package_update": update_res.data if update_res.success else {},
                "has_os_update": update_res.data.get("update_available", False) if update_res.success and isinstance(update_res.data, dict) else False,
                "has_rb_update": has_rb_update,
            }
            return OperationResult(
                success=True,
                message="Informasi status firmware dan update RouterOS berhasil diambil via SSH.",
                data=combined,
                device=self.device_name,
            )
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)
