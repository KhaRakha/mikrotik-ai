"""
MikroTik RouterOS binary API Protocol Client (port 8728 / 8729).
Pure Python implementation of the RouterOS API sentence/word protocol.
"""

from __future__ import annotations

import binascii
import hashlib
import re
import socket
import ssl
import time
from typing import Any, Dict, List, Optional, Tuple
from mikrotik.base import BaseMikrotikClient, OperationResult


class MikrotikRosApiClient(BaseMikrotikClient):
    def __init__(
        self,
        host: str,
        port: int = 8728,
        username: str = "admin",
        password: str = "",
        use_ssl: bool = False,
        timeout: float = 5.0,
    ):
        super().__init__(host, port, username, password, use_ssl, timeout)
        self.sock: Optional[socket.socket] = None

    def _connect(self) -> socket.socket:
        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.settimeout(self.timeout)
        if self.use_ssl:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            sock = context.wrap_socket(raw_sock, server_hostname=self.host)
        else:
            sock = raw_sock
        sock.connect((self.host, self.port))
        return sock

    def _encode_length(self, length: int) -> bytes:
        if length < 0x80:
            return bytes([length])
        elif length < 0x4000:
            length |= 0x8000
            return bytes([(length >> 8) & 0xFF, length & 0xFF])
        elif length < 0x200000:
            length |= 0xC00000
            return bytes([(length >> 16) & 0xFF, (length >> 8) & 0xFF, length & 0xFF])
        elif length < 0x10000000:
            length |= 0xE0000000
            return bytes([(length >> 24) & 0xFF, (length >> 16) & 0xFF, (length >> 8) & 0xFF, length & 0xFF])
        else:
            return bytes([0xF0, (length >> 24) & 0xFF, (length >> 16) & 0xFF, (length >> 8) & 0xFF, length & 0xFF])

    def _decode_length(self, sock: socket.socket) -> int:
        b = sock.recv(1)
        if not b:
            raise ConnectionError("Koneksi terputus saat membaca panjang kata.")
        first = b[0]
        if (first & 0x80) == 0x00:
            return first
        elif (first & 0xC0) == 0x80:
            second = sock.recv(1)[0]
            return ((first & 0x3F) << 8) | second
        elif (first & 0xE0) == 0xC0:
            rest = sock.recv(2)
            return ((first & 0x1F) << 16) | (rest[0] << 8) | rest[1]
        elif (first & 0xF0) == 0xE0:
            rest = sock.recv(3)
            return ((first & 0x0F) << 24) | (rest[0] << 16) | (rest[1] << 8) | rest[2]
        elif first == 0xF0:
            rest = sock.recv(4)
            return (rest[0] << 24) | (rest[1] << 16) | (rest[2] << 8) | rest[3]
        return 0

    def _write_word(self, sock: socket.socket, word: str) -> None:
        data = word.encode("utf-8")
        sock.sendall(self._encode_length(len(data)) + data)

    def _read_word(self, sock: socket.socket) -> str:
        length = self._decode_length(sock)
        if length == 0:
            return ""
        buf = bytearray()
        while len(buf) < length:
            chunk = sock.recv(min(length - len(buf), 4096))
            if not chunk:
                break
            buf.extend(chunk)
        return buf.decode("utf-8", errors="replace")

    def _write_sentence(self, sock: socket.socket, words: List[str]) -> None:
        for w in words:
            self._write_word(sock, w)
        self._write_word(sock, "")

    def _read_sentence(self, sock: socket.socket) -> List[str]:
        sentence = []
        while True:
            word = self._read_word(sock)
            if word == "":
                break
            sentence.append(word)
        return sentence

    def _execute(self, command: str, params: Optional[Dict[str, str]] = None) -> List[Dict[str, str]]:
        sock = self._connect()
        try:
            # 1. Try modern RouterOS plain login first (RouterOS 6.43+ and v7)
            self._write_sentence(sock, ["/login", f"=name={self.username}", f"=password={self.password}"])
            reply = self._read_sentence(sock)
            if not reply:
                raise ConnectionError("Tidak ada respon dari MikroTik saat login.")

            if "!done" not in reply:
                # 2. Fallback to Challenge Response login (legacy RouterOS)
                self._write_sentence(sock, ["/login"])
                c_reply = self._read_sentence(sock)
                chal = ""
                for w in c_reply:
                    if w.startswith("=ret="):
                        chal = w.split("=", 2)[2]
                if chal:
                    md = hashlib.md5()
                    md.update(b"\x00")
                    md.update(self.password.encode("utf-8"))
                    md.update(binascii.unhexlify(chal))
                    response_hash = "00" + md.hexdigest()
                    self._write_sentence(sock, ["/login", f"=name={self.username}", f"=response={response_hash}"])
                    auth_reply = self._read_sentence(sock)
                    if "!done" not in auth_reply:
                        err = ", ".join([w.split("=", 1)[-1] for w in auth_reply if w.startswith("=message=")])
                        raise PermissionError(f"Autentikasi gagal: {err or 'invalid username/password'}")
                else:
                    err = ", ".join([w.split("=", 1)[-1] for w in reply if w.startswith("=message=")])
                    raise PermissionError(f"Autentikasi gagal: {err or 'invalid username/password'}")

            # Now execute command
            words = [command]
            if params:
                for k, v in params.items():
                    words.append(f"={k}={v}")
            self._write_sentence(sock, words)

            results: List[Dict[str, str]] = []
            while True:
                sentence = self._read_sentence(sock)
                if not sentence:
                    break
                reply_type = sentence[0]
                if reply_type == "!re":
                    item = {}
                    for w in sentence[1:]:
                        if w.startswith("="):
                            parts = w[1:].split("=", 1)
                            if len(parts) == 2:
                                item[parts[0]] = parts[1]
                    results.append(item)
                elif reply_type == "!done":
                    break
                elif reply_type == "!trap":
                    err_msg = "Error dari RouterOS: " + ", ".join(sentence[1:])
                    raise RuntimeError(err_msg)
                elif reply_type == "!fatal":
                    raise ConnectionError("Koneksi fatal dari RouterOS.")

            return results
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def test_connection(self) -> OperationResult:
        start = time.time()
        try:
            res = self._execute("/system/resource/print")
            latency = (time.time() - start) * 1000
            if res:
                return OperationResult(
                    success=True,
                    message=f"Koneksi RouterOS API ke {self.host}:{self.port} berhasil.",
                    data={"status": "online", "version": res[0].get("version"), "board": res[0].get("board-name")},
                    device=self.device_name,
                    latency_ms=latency,
                )
            return OperationResult(success=True, message="Koneksi terhubung.", device=self.device_name, latency_ms=latency)
        except Exception as e:
            latency = (time.time() - start) * 1000
            return OperationResult(
                success=False,
                message=f"Gagal terhubung ke RouterOS API pada {self.host}:{self.port}.",
                error=str(e),
                device=self.device_name,
                latency_ms=latency,
            )

    def get_resource(self) -> OperationResult:
        start = time.time()
        try:
            res = self._execute("/system/resource/print")
            latency = (time.time() - start) * 1000
            if res:
                raw = res[0]
                free_mem = int(raw.get("free-memory", 0)) / (1024 * 1024)
                total_mem = int(raw.get("total-memory", 1)) / (1024 * 1024)
                usage_pct = round(((total_mem - free_mem) / total_mem) * 100, 1) if total_mem > 0 else 0.0
                data = {
                    "cpu_load": int(raw.get("cpu-load", 0)),
                    "free_memory_mb": round(free_mem, 1),
                    "total_memory_mb": round(total_mem, 1),
                    "memory_usage_percent": usage_pct,
                    "uptime": raw.get("uptime", "0s"),
                    "version": raw.get("version", "unknown"),
                    "board_name": raw.get("board-name", "RouterBOARD"),
                    "architecture_name": raw.get("architecture-name", "unknown"),
                    "cpu_count": int(raw.get("cpu-count", 1)),
                }
                return OperationResult(success=True, data=data, device=self.device_name, latency_ms=latency)
            return OperationResult(success=False, message="Tidak ada data resource.", device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_interfaces(self) -> OperationResult:
        try:
            res = self._execute("/interface/print")
            normalized = []
            for item in res:
                normalized.append({
                    "name": item.get("name"),
                    "type": item.get("type"),
                    "running": item.get("running") == "true",
                    "disabled": item.get("disabled") == "true",
                    "mac": item.get("mac-address", ""),
                    "comment": item.get("comment", ""),
                    "rx_byte": int(item.get("rx-byte", 0)),
                    "tx_byte": int(item.get("tx-byte", 0)),
                })
            return OperationResult(success=True, data=normalized, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_neighbors(self) -> OperationResult:
        try:
            res = self._execute("/ip/neighbor/print")
            normalized = []
            for item in res:
                local_if = item.get("interface", "")
                remote_ip = item.get("address", "") or item.get("address4", "")
                mac_addr = (item.get("mac-address", "") or item.get("mac", "")).upper()
                identity = item.get("identity", "")
                platform = item.get("platform", "MikroTik")
                version = item.get("version", "")
                remote_if = item.get("interface-name", "") or item.get("remote-interface", "")
                board = item.get("board", "")
                proto = (item.get("discovered-by", "") or item.get("discovery-protocol", "mndp")).lower()
                age = item.get("age", "")
                uptime = item.get("uptime", "")
                normalized.append({
                    "interface": local_if,
                    "address": remote_ip,
                    "mac_address": mac_addr,
                    "identity": identity,
                    "platform": platform,
                    "version": version,
                    "remote_interface": remote_if,
                    "board": board,
                    "protocol": proto,
                    "age": age,
                    "uptime": uptime,
                })
            return OperationResult(
                success=True,
                message=f"Berhasil mengambil {len(normalized)} neighbor.",
                data=normalized,
                device=self.device_name,
            )
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_ip_addresses(self) -> OperationResult:
        try:
            res = self._execute("/ip/address/print")
            return OperationResult(success=True, data=res, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_ip_routes(self) -> OperationResult:
        try:
            res = self._execute("/ip/route/print")
            return OperationResult(success=True, data=res, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_arp_table(self) -> OperationResult:
        try:
            res = self._execute("/ip/arp/print")
            return OperationResult(success=True, data=res, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_dhcp_leases(self) -> OperationResult:
        try:
            res = self._execute("/ip/dhcp-server/lease/print")
            return OperationResult(success=True, data=res, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_hotspot_users(self) -> OperationResult:
        try:
            res = self._execute("/ip/hotspot/user/print")
            return OperationResult(success=True, data=res, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_hotspot_active(self) -> OperationResult:
        try:
            res = self._execute("/ip/hotspot/active/print")
            return OperationResult(success=True, data=res, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_hotspot_profiles(self) -> OperationResult:
        try:
            res = self._execute("/ip/hotspot/user/profile/print")
            return OperationResult(success=True, data=res, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_firewall_rules(self) -> OperationResult:
        try:
            res = self._execute("/ip/firewall/filter/print")
            return OperationResult(success=True, data=res, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_system_logs(self, limit: int = 30) -> OperationResult:
        try:
            res = self._execute("/log/print")
            return OperationResult(success=True, data=res[-limit:], device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def ping(self, target: str, count: int = 4) -> OperationResult:
        try:
            import re
            res = self._execute("/ping", {"address": target, "count": str(count)})
            sent = len(res)
            received = len([p for p in res if p.get("packet-loss") in ("0", 0, None) and ("time" in p or "avg-rtt" in p)])
            loss_pct = round(((sent - received) / sent) * 100, 1) if sent > 0 else 0.0

            times = []
            for p in res:
                t_str = p.get("time") or p.get("avg-rtt") or ""
                ms_match = re.search(r'([0-9\.]+)\s*ms', t_str)
                if ms_match:
                    times.append(float(ms_match.group(1)))

            avg_rtt = round(sum(times) / len(times), 1) if times else 20.0
            data = {
                "host": target,
                "sent": sent,
                "received": received,
                "packet_loss_percent": loss_pct,
                "avg_rtt_ms": avg_rtt,
                "status": "Reachable" if loss_pct < 100 else "Unreachable",
                "raw": res,
            }
            return OperationResult(success=True, data=data, device=self.device_name, latency_ms=avg_rtt)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def create_hotspot_user(self, name: str, password: str = "", profile: str = "default", limit_uptime: str = "") -> OperationResult:
        try:
            # Check if user already exists; if so, remove first for idempotent creation
            all_users = self._execute("/ip/hotspot/user/print")
            existing = [u for u in all_users if u.get("name") == name]
            if existing:
                uid = existing[0].get(".id")
                if uid:
                    self._execute("/ip/hotspot/user/remove", {".id": uid})

            params = {"name": name, "profile": profile or "default"}
            if password:
                params["password"] = password
            if limit_uptime:
                params["limit-uptime"] = limit_uptime

            self._execute("/ip/hotspot/user/add", params)
            return OperationResult(
                success=True,
                message=f"✅ User hotspot '{name}' berhasil dibuat via RouterOS API.",
                device=self.device_name,
            )
        except Exception as e:
            return OperationResult(success=False, message=f"Gagal membuat user hotspot: {e}", error=str(e), device=self.device_name)

    def delete_hotspot_user(self, name: str) -> OperationResult:
        try:
            all_users = self._execute("/ip/hotspot/user/print")
            users = [u for u in all_users if u.get("name") == name]
            if not users:
                return OperationResult(success=False, message=f"User hotspot '{name}' tidak ditemukan.", device=self.device_name)
            user_id = users[0].get(".id")
            self._execute("/ip/hotspot/user/remove", {".id": user_id})
            return OperationResult(success=True, message=f"✅ User hotspot '{name}' berhasil dihapus.", device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, message=f"Gagal menghapus user hotspot: {e}", error=str(e), device=self.device_name)

    def set_interface_state(self, interface_name: str, enabled: bool) -> OperationResult:
        try:
            real_interface = self.resolve_interface_name(interface_name)
            cmd = "/interface/enable" if enabled else "/interface/disable"
            self._execute(cmd, {"numbers": real_interface})
            state_str = "diaktifkan" if enabled else "dinonaktifkan"
            return OperationResult(success=True, message=f"✅ Interface '{real_interface}' berhasil {state_str}.", device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, message=f"Gagal mengubah status interface: {e}", error=str(e), device=self.device_name)

    def add_ip_address(self, address: str, interface: str, comment: str = "") -> OperationResult:
        try:
            real_interface = self.resolve_interface_name(interface)
            params = {"address": address.strip(), "interface": real_interface}
            if comment:
                params["comment"] = comment
            self._execute("/ip/address/add", params)
            return OperationResult(
                success=True,
                message=f"✅ IP address '{address}' berhasil ditambahkan ke interface '{real_interface}'.",
                device=self.device_name,
            )
        except Exception as e:
            return OperationResult(success=False, message=f"Gagal menambahkan IP address: {e}", error=str(e), device=self.device_name)

    def remove_ip_address(self, address: str) -> OperationResult:
        try:
            clean_target = address.strip()
            all_ips = self._execute("/ip/address/print")
            target_entry = None
            for item in all_ips:
                addr = item.get("address", "")
                if addr == clean_target or addr.split("/")[0] == clean_target.split("/")[0]:
                    target_entry = item
                    break
            if not target_entry:
                return OperationResult(success=False, message=f"IP address '{address}' tidak ditemukan.", device=self.device_name)
            uid = target_entry.get(".id")
            self._execute("/ip/address/remove", {".id": uid})
            return OperationResult(success=True, message=f"✅ IP address '{target_entry.get('address')}' berhasil dihapus.", device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, message=f"Gagal menghapus IP address: {e}", error=str(e), device=self.device_name)

    def set_ip_address(
        self,
        current_address: str,
        new_address: Optional[str] = None,
        new_interface: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> OperationResult:
        try:
            clean_target = current_address.strip()
            all_ips = self._execute("/ip/address/print")
            target_entry = None
            for item in all_ips:
                addr = item.get("address", "")
                if addr == clean_target or addr.split("/")[0] == clean_target.split("/")[0]:
                    target_entry = item
                    break
            if not target_entry:
                return OperationResult(success=False, message=f"IP address '{current_address}' tidak ditemukan.", device=self.device_name)
            uid = target_entry.get(".id")
            params = {".id": uid}
            if new_address:
                params["address"] = new_address.strip()
            if new_interface:
                params["interface"] = self.resolve_interface_name(new_interface)
            if comment is not None:
                params["comment"] = comment
            self._execute("/ip/address/set", params)
            return OperationResult(success=True, message=f"✅ IP address '{current_address}' berhasil diperbarui.", device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, message=f"Gagal mengubah IP address: {e}", error=str(e), device=self.device_name)

    def execute_raw_command(self, path: str, command: str, params: Optional[Dict[str, Any]] = None) -> OperationResult:
        try:
            res = self._execute(f"/{path.strip('/')}/{command.strip('/')}", {k: str(v) for k, v in (params or {}).items()})
            return OperationResult(success=True, data=res, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    # =========================================================================
    # WINBOX TOOLS MENU (ROUTEROS API)
    # =========================================================================
    def traceroute(self, target: str, count: int = 1) -> OperationResult:
        try:
            target_clean = target.strip()
            target_ips = {target_clean}
            try:
                target_ips.add(socket.gethostbyname(target_clean))
            except Exception:
                pass

            res = self._execute("/tool/traceroute", {"address": target_clean, "count": str(count)})
            # RouterOS API returns streaming probe updates across multiple sections (.section='0', '1', etc.)
            # The final/highest section contains the complete consolidated hop list.
            if res:
                sections = {}
                for r in res:
                    sec = r.get(".section", "0")
                    sections.setdefault(sec, []).append(r)
                highest_sec = max(sections.keys(), key=lambda s: int(s) if s.isdigit() else 0)
                raw_hops = sections[highest_sec]
            else:
                raw_hops = []

            # Truncate immediately once the target IP/domain is reached
            final_hops = []
            for h in raw_hops:
                final_hops.append(h)
                addr = str(h.get("address") or h.get("ip") or "").strip()
                if addr and addr in target_ips:
                    break

            return OperationResult(success=True, message=f"Traceroute ke {target_clean} selesai ({len(final_hops)} hops).", data=final_hops, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def resolve_interface_name(self, requested_name: str) -> str:
        """Resolve interface names fuzzy/intelligently to actual RouterOS interface."""
        if not requested_name:
            return "ether1"
        try:
            ifaces_res = self.get_interfaces()
            if not ifaces_res.success or not ifaces_res.data:
                return requested_name
            req_clean = requested_name.strip().lower()
            avail = [i.get("name") for i in ifaces_res.data if i.get("name")]
            for name in avail:
                if name.lower() == req_clean:
                    return name
            m = re.search(r'(ether\d+|wlan\d+|sfp\d+|bridge\d*|vlan\d*)', req_clean)
            if m:
                p = m.group(1)
                for name in avail:
                    if re.search(r'\b' + p + r'(?:\D|$)', name.lower()):
                        return name
            if any(w in req_clean for w in ("wan", "internet", "uplink")):
                for name in avail:
                    if any(w in name.lower() for w in ("wan", "internet", "uplink", "sw")):
                        return name
                for i in ifaces_res.data:
                    if i.get("running"):
                        return i.get("name")
            elif any(w in req_clean for w in ("lan", "local", "wifi", "hotspot")):
                for name in avail:
                    if any(w in name.lower() for w in ("lan", "wifi", "asus", "local", "hotspot")):
                        return name
            for name in avail:
                if req_clean in name.lower() or name.lower() in req_clean:
                    return name
        except Exception:
            pass
        return requested_name

    def torch(self, interface: str, duration: int = 3) -> OperationResult:
        real_interface = self.resolve_interface_name(interface)
        sock = self._connect()
        try:
            # Modern RouterOS plain login
            self._write_sentence(sock, ["/login", f"=name={self.username}", f"=password={self.password}"])
            reply = self._read_sentence(sock)
            if "!done" not in reply:
                self._write_sentence(sock, ["/login"])
                c_reply = self._read_sentence(sock)
                chal = ""
                for w in c_reply:
                    if w.startswith("=ret="):
                        chal = w.split("=", 2)[2]
                if chal:
                    md = hashlib.md5()
                    md.update(b"\x00")
                    md.update(self.password.encode("utf-8"))
                    md.update(binascii.unhexlify(chal))
                    response_hash = "00" + md.hexdigest()
                    self._write_sentence(sock, ["/login", f"=name={self.username}", f"=response={response_hash}"])
                    auth_reply = self._read_sentence(sock)
                    if "!done" not in auth_reply:
                        err = ", ".join([w.split("=", 1)[-1] for w in auth_reply if w.startswith("=message=")])
                        raise PermissionError(f"Autentikasi gagal: {err or 'invalid username/password'}")

            tag = "t" + str(int(time.time() * 1000) % 100000)
            words = ["/tool/torch", f"=interface={real_interface}", f".tag={tag}"]
            self._write_sentence(sock, words)

            start_t = time.time()
            sock.settimeout(0.5)
            results = []
            seen = set()
            while time.time() - start_t < duration:
                try:
                    sentence = self._read_sentence(sock)
                    if not sentence:
                        break
                    if sentence[0] == "!re":
                        item = {}
                        for w in sentence[1:]:
                            if w.startswith("="):
                                parts = w[1:].split("=", 1)
                                if len(parts) == 2:
                                    item[parts[0]] = parts[1]
                        if item:
                            key = (item.get("src-address"), item.get("dst-address"), item.get("dst-port"))
                            if key not in seen:
                                seen.add(key)
                                results.append(item)
                    elif sentence[0] == "!trap":
                        err_msg = "Error dari RouterOS: " + ", ".join(sentence[1:])
                        return OperationResult(success=False, error=err_msg, device=self.device_name)
                except socket.timeout:
                    continue

            try:
                self._write_sentence(sock, ["/cancel", f"=tag={tag}"])
            except Exception:
                pass

            return OperationResult(success=True, message=f"Torch pada interface '{real_interface}' selesai ({len(results)} aliran terdeteksi).", data=results, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def bandwidth_test(self, target: str, direction: str = "both", duration: int = 5, protocol: str = "udp") -> OperationResult:
        try:
            params = {"address": target, "direction": direction, "duration": f"{duration}s", "protocol": protocol}
            if self.username:
                params["user"] = self.username
            if self.password:
                params["password"] = self.password
            res = self._execute("/tool/bandwidth-test", params)
            item = res[-1] if isinstance(res, list) and res else (res if isinstance(res, dict) else {})
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
                "raw": res,
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
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_netwatch(self) -> OperationResult:
        try:
            res = self._execute("/tool/netwatch/print")
            return OperationResult(success=True, message=f"Berhasil mengambil {len(res)} host Netwatch.", data=res, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def add_netwatch(self, host: str, interval: str = "1m", timeout: str = "1000ms", comment: str = "") -> OperationResult:
        try:
            params = {"host": host, "interval": interval, "timeout": timeout}
            if comment:
                params["comment"] = comment
            res = self._execute("/tool/netwatch/add", params)
            return OperationResult(success=True, message=f"✅ Host Netwatch '{host}' berhasil ditambahkan.", data=res, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def ip_scan(self, interface: str, address_range: str = "", duration: int = 5) -> OperationResult:
        try:
            real_interface = self.resolve_interface_name(interface)
            params = {"interface": real_interface, "duration": f"{duration}s"}
            if address_range:
                params["address-range"] = address_range
            res = self._execute("/tool/ip-scan", params)
            return OperationResult(success=True, message=f"IP Scan pada interface '{real_interface}' selesai.", data=res, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_profile(self, duration: int = 3) -> OperationResult:
        try:
            res = self._execute("/tool/profile", {"duration": f"{duration}s"})
            process_usages: Dict[str, float] = {}
            total_busy = 0.0
            for item in (res or []):
                name = item.get("name", "unknown")
                try:
                    usage = float(item.get("usage", 0))
                except (ValueError, TypeError):
                    usage = 0.0
                if name == "total":
                    total_busy = max(total_busy, usage)
                else:
                    process_usages[name] = max(process_usages.get(name, 0.0), usage)

            breakdown = [{"process": k, "cpu_percent": v} for k, v in process_usages.items()]
            breakdown.sort(key=lambda x: x["cpu_percent"], reverse=True)
            if not total_busy and breakdown:
                total_busy = sum(x["cpu_percent"] for x in breakdown)

            data = {
                "duration_sec": duration,
                "cpu_usage": breakdown,
                "total_busy_percent": round(total_busy, 1),
            }
            return OperationResult(
                success=True,
                message=f"Profile beban CPU MikroTik selama {duration}s berhasil diambil.",
                data=data,
                device=self.device_name,
            )
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def send_email(self, to: str, subject: str, body: str) -> OperationResult:
        try:
            self._execute("/tool/e-mail/send", {"to": to, "subject": subject, "body": body})
            return OperationResult(success=True, message=f"✅ Notifikasi email berhasil dikirim ke '{to}'.", device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_packet_sniffer(self) -> OperationResult:
        try:
            res = self._execute("/tool/sniffer/print")
            return OperationResult(success=True, message="Status Packet Sniffer berhasil diambil.", data=res, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def sniff_packets(self, interface: str = "", count: int = 10) -> OperationResult:
        try:
            params = {}
            if interface:
                params["interface"] = self.resolve_interface_name(interface)
            res = self._execute("/tool/sniffer/packet/print", params)
            return OperationResult(success=True, message=f"Berhasil mengambil {len(res)} sampel paket data.", data=res[:count], device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_traffic_monitor(self) -> OperationResult:
        try:
            res = self._execute("/tool/traffic-monitor/print")
            return OperationResult(success=True, message=f"Berhasil mengambil {len(res)} traffic monitor.", data=res, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def add_traffic_monitor(self, name: str, interface: str, threshold: str, trigger: str = "above", on_event: str = "") -> OperationResult:
        try:
            real_interface = self.resolve_interface_name(interface)
            params = {
                "name": name,
                "interface": real_interface,
                "threshold": str(threshold),
                "trigger": trigger,
            }
            if on_event:
                params["on-event"] = on_event
            res = self._execute("/tool/traffic-monitor/add", params)
            return OperationResult(success=True, message=f"✅ Aturan Traffic Monitor '{name}' pada interface '{real_interface}' berhasil ditambahkan.", data=res, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    # =========================================================================
    # WINBOX SYSTEM MENU (ROUTEROS API)
    # =========================================================================
    def get_identity(self) -> OperationResult:
        try:
            res = self._execute("/system/identity/print")
            name = res[0].get("name", "Unknown") if res else "Unknown"
            return OperationResult(success=True, message=f"Identitas router: '{name}'", data={"name": name, "raw": res}, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def set_identity(self, name: str) -> OperationResult:
        try:
            self._execute("/system/identity/set", {"name": name})
            return OperationResult(success=True, message=f"✅ Identitas router berhasil diubah menjadi '{name}'.", data={"name": name}, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_system_users(self) -> OperationResult:
        try:
            res = self._execute("/user/print")
            return OperationResult(success=True, message=f"Berhasil mengambil {len(res)} user sistem MikroTik.", data=res, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def create_system_user(self, name: str, group: str = "read", password: str = "") -> OperationResult:
        try:
            params = {"name": name, "group": group}
            if password:
                params["password"] = password
            self._execute("/user/add", params)
            return OperationResult(success=True, message=f"✅ User sistem '{name}' ({group}) berhasil dibuat via RouterOS API.", device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def delete_system_user(self, name: str) -> OperationResult:
        try:
            all_users = self._execute("/user/print")
            matched = [u for u in all_users if u.get("name") == name]
            if not matched:
                return OperationResult(success=False, message=f"User sistem '{name}' tidak ditemukan.", device=self.device_name)
            uid = matched[0].get(".id")
            self._execute("/user/remove", {".id": uid})
            return OperationResult(success=True, message=f"✅ User sistem '{name}' berhasil dihapus via RouterOS API.", device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_packages(self) -> OperationResult:
        try:
            res = self._execute("/system/package/print")
            return OperationResult(success=True, message=f"Berhasil mengambil {len(res)} paket RouterOS.", data=res, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_routerboard(self) -> OperationResult:
        try:
            res = self._execute("/system/routerboard/print")
            raw_data = res[0] if res else {}
            data = dict(raw_data)
            for k, v in raw_data.items():
                if "-" in k:
                    data[k.replace("-", "_")] = v
            return OperationResult(success=True, message="Informasi RouterBOARD berhasil diambil.", data=data, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def get_clock_sntp(self) -> OperationResult:
        try:
            clk = self._execute("/system/clock/print")
            sntp = self._execute("/system/ntp/client/print")
            combined = {
                "clock": clk[0] if clk else {},
                "sntp": sntp[0] if sntp else {},
            }
            return OperationResult(success=True, message="Informasi Clock dan SNTP berhasil diambil.", data=combined, device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def set_clock_timezone(self, time_zone: str) -> OperationResult:
        try:
            self._execute("/system/clock/set", {"time-zone-name": time_zone})
            return OperationResult(success=True, message=f"✅ Zona waktu berhasil diatur ke '{time_zone}'.", device=self.device_name)
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def reboot(self) -> OperationResult:
        try:
            self._execute("/system/reboot")
        except Exception as e:
            err_lower = str(e).lower()
            disconnect_terms = (
                "terputus", "broken pipe", "connection reset", "closed",
                "timed out", "timeout", "koneksi fatal", "fatal", "eof",
                "connection error", "connection refused", "aborted", "peer",
            )
            if not any(term in err_lower for term in disconnect_terms):
                return OperationResult(success=False, error=str(e), device=self.device_name)
        return OperationResult(
            success=True,
            message=f"🔄 Router '{self.device_name}' sedang melakukan proses REBOOT...\nSistem akan offline sementara dan otomatis kembali aktif.",
            device=self.device_name,
        )

    def shutdown(self) -> OperationResult:
        try:
            self._execute("/system/shutdown")
            return OperationResult(
                success=True,
                message=f"🔌 Router '{self.device_name}' sedang melakukan proses SHUTDOWN secara aman.",
                device=self.device_name,
            )
        except Exception as e:
            return OperationResult(success=False, error=str(e), device=self.device_name)

    def check_router_update(self, channel: str = "stable") -> OperationResult:
        try:
            if channel:
                try:
                    self._execute("/system/package/update/set", {"channel": channel})
                except Exception:
                    pass
            try:
                self._execute("/system/package/update/check-for-updates")
            except Exception:
                pass
            res = self._execute("/system/package/update/print")
            data = res[0] if res else {}
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
            if channel:
                try:
                    self._execute("/system/package/update/set", {"channel": channel})
                except Exception:
                    pass
            try:
                self._execute("/system/package/update/install")
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
            self._execute("/system/routerboard/upgrade")
            rb = self.get_routerboard()
            rb_data = rb.data if rb.success and isinstance(rb.data, dict) else {}
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
