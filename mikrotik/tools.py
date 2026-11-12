"""
MikroTik Tool Layer (PRD Section 9 & 13).
Exposes structured Python functions and OpenAPI/JSON schemas for Hermes AI Agent tool calling.
"""

from __future__ import annotations

from pathlib import Path
import socket
import time
from typing import Any, Dict, List, Optional
from mikrotik.discovery import device_discovery
from mikrotik.manager import device_manager


def connect_mikrotik(device: str = "") -> Dict[str, Any]:
    """Cek koneksi dan status router MikroTik target."""
    client = device_manager.get_client(device)
    return client.test_connection().to_dict()


def get_resource(device: str = "") -> Dict[str, Any]:
    """Ambil informasi resource sistem MikroTik (CPU load, memory, uptime, version, board, arch)."""
    client = device_manager.get_client(device)
    return client.get_resource().to_dict()


def get_interface(device: str = "") -> Dict[str, Any]:
    """Ambil daftar seluruh interface jaringan, status aktif/down, dan statistik traffic rx/tx bytes."""
    client = device_manager.get_client(device)
    return client.get_interfaces().to_dict()


def get_ip(device: str = "") -> Dict[str, Any]:
    """Ambil daftar alamat IP address yang terkonfigurasi di MikroTik."""
    client = device_manager.get_client(device)
    return client.get_ip_addresses().to_dict()


def get_route(device: str = "") -> Dict[str, Any]:
    """Ambil tabel routing IP (destination address, gateway, status active)."""
    client = device_manager.get_client(device)
    return client.get_ip_routes().to_dict()


def get_arp(device: str = "") -> Dict[str, Any]:
    """Ambil tabel ARP MikroTik (pemetaan IP address ke MAC address perangkat client)."""
    client = device_manager.get_client(device)
    return client.get_arp_table().to_dict()


def get_dhcp(device: str = "") -> Dict[str, Any]:
    """Ambil daftar lease DHCP server yang sedang aktif atau terikat ke client."""
    client = device_manager.get_client(device)
    return client.get_dhcp_leases().to_dict()


def get_hotspot(device: str = "", query_type: str = "all") -> Dict[str, Any]:
    """
    Ambil informasi hotspot MikroTik.
    query_type: 'users' (daftar user), 'active' (user yang sedang login), 'profiles' (profil bandwidth), atau 'all'.
    """
    client = device_manager.get_client(device)
    if query_type == "users":
        return client.get_hotspot_users().to_dict()
    elif query_type == "active":
        return client.get_hotspot_active().to_dict()
    elif query_type == "profiles":
        return client.get_hotspot_profiles().to_dict()
    else:
        users = client.get_hotspot_users().to_dict()
        active = client.get_hotspot_active().to_dict()
        profiles = client.get_hotspot_profiles().to_dict()
        return {
            "success": True,
            "data": {
                "users": users.get("data", []),
                "active_sessions": active.get("data", []),
                "profiles": profiles.get("data", []),
            },
            "device": client.device_name,
        }


def get_firewall(device: str = "") -> Dict[str, Any]:
    """Ambil daftar aturan filter firewall MikroTik."""
    client = device_manager.get_client(device)
    return client.get_firewall_rules().to_dict()


def get_logs(device: str = "", limit: int = 20) -> Dict[str, Any]:
    """Ambil baris log sistem MikroTik terbaru (info, warning, error)."""
    client = device_manager.get_client(device)
    return client.get_system_logs(limit=limit).to_dict()


def ping(device: str = "", target: str = "8.8.8.8", count: int = 4) -> Dict[str, Any]:
    """Lakukan pengujian konektivitas ping dari MikroTik ke alamat IP / host tujuan."""
    client = device_manager.get_client(device)
    return client.ping(target=target, count=count).to_dict()


def create_hotspot_user(
    device: str = "",
    name: str = "",
    password: str = "",
    profile: str = "default",
    limit_uptime: str = "",
) -> Dict[str, Any]:
    """
    [WRITE / CONFIG] Membuat user hotspot baru di MikroTik.
    Membutuhkan konfirmasi pengguna sebelum dieksekusi.
    """
    client = device_manager.get_client(device)
    return client.create_hotspot_user(
        name=name,
        password=password,
        profile=profile,
        limit_uptime=limit_uptime,
    ).to_dict()


def delete_hotspot_user(device: str = "", name: str = "") -> Dict[str, Any]:
    """
    [WRITE / CONFIG] Menghapus user hotspot dari MikroTik.
    Membutuhkan konfirmasi pengguna sebelum dieksekusi.
    """
    client = device_manager.get_client(device)
    return client.delete_hotspot_user(name=name).to_dict()


def set_interface_state(device: str = "", interface_name: str = "", enabled: bool = True) -> Dict[str, Any]:
    """
    [WRITE / CONFIG] Mengaktifkan atau menonaktifkan interface jaringan di MikroTik.
    Membutuhkan konfirmasi pengguna sebelum dieksekusi.
    """
    client = device_manager.get_client(device)
    return client.set_interface_state(interface_name=interface_name, enabled=enabled).to_dict()


def add_ip_address(device: str = "", address: str = "", interface: str = "", comment: str = "") -> Dict[str, Any]:
    """
    [WRITE / CONFIG] Menambahkan IP address baru pada antarmuka router MikroTik.
    Membutuhkan konfirmasi pengguna sebelum dieksekusi.
    """
    if not address or not interface:
        return {"success": False, "message": "Alamat IP dan antarmuka (interface) wajib diisi."}
    client = device_manager.get_client(device)
    return client.add_ip_address(address=address, interface=interface, comment=comment).to_dict()


def remove_ip_address(device: str = "", address: str = "") -> Dict[str, Any]:
    """
    [WRITE / CONFIG] Menghapus IP address dari router MikroTik.
    Membutuhkan konfirmasi pengguna sebelum dieksekusi.
    """
    if not address:
        return {"success": False, "message": "Alamat IP yang akan dihapus wajib diisi."}
    client = device_manager.get_client(device)
    return client.remove_ip_address(address=address).to_dict()


def set_ip_address(
    device: str = "",
    current_address: str = "",
    new_address: str = "",
    new_interface: str = "",
    comment: str = "",
) -> Dict[str, Any]:
    """
    [WRITE / CONFIG] Mengubah (edit) konfigurasi IP address atau antarmuka pada router MikroTik.
    Membutuhkan konfirmasi pengguna sebelum dieksekusi.
    """
    if not current_address:
        return {"success": False, "message": "Alamat IP saat ini (current_address) wajib diisi."}
    client = device_manager.get_client(device)
    return client.set_ip_address(
        current_address=current_address,
        new_address=new_address or None,
        new_interface=new_interface or None,
        comment=comment if comment else None,
    ).to_dict()


def discover_devices(subnet: str = "10.20.33.0/24") -> Dict[str, Any]:
    """Memindai subnet jaringan lokal untuk menemukan router MikroTik yang aktif."""
    results = device_discovery.scan_subnet(subnet_cidr=subnet)
    return {
        "success": True,
        "message": f"Ditemukan {len(results)} perangkat aktif pada subnet {subnet}.",
        "data": results,
    }


def register_device(
    name: str = "",
    host: str = "",
    protocol: str = "api",
    port: int = 0,
    username: str = "admin",
    password: str = "",
    description: str = "",
    device: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """[WRITE / INVENTORY] Mendaftarkan router MikroTik baru ke inventaris perangkat sistem."""
    if not name or not host:
        return {"success": False, "message": "Parameter nama router dan host/IP wajib diisi."}
    return device_discovery.register_device(
        name=name,
        host=host,
        protocol=protocol,
        port=port,
        username=username,
        password=password,
        description=description,
    )


def remove_device(name: str = "", device: str = "", **kwargs: Any) -> Dict[str, Any]:
    """[WRITE / INVENTORY] Menghapus router MikroTik dari inventaris perangkat sistem."""
    target = name or device
    if not target:
        return {"success": False, "message": "Parameter nama atau ID router wajib diisi."}
    return device_discovery.remove_device(name_or_id=target)


def check_server_port(host: str, port: int, timeout: float = 3.0) -> Dict[str, Any]:
    """Menguji ketersediaan server/service pada port tertentu (misal port 80/443 Web, 3306 Database, 22 SSH)."""
    start = time.time()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, int(port)))
        sock.close()
        latency_ms = (time.time() - start) * 1000
        if result == 0:
            return {
                "success": True,
                "message": f"Port {port} pada host {host} TERBUKA (ONLINE)",
                "data": {
                    "host": host,
                    "port": int(port),
                    "status": "OPEN",
                    "latency_ms": round(latency_ms, 2),
                },
            }
        else:
            return {
                "success": False,
                "message": f"Port {port} pada host {host} TERTUTUP atau tidak dapat dijangkau",
                "data": {
                    "host": host,
                    "port": int(port),
                    "status": "CLOSED_OR_FILTERED",
                    "latency_ms": round(latency_ms, 2),
                },
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Gagal memeriksa port {port} pada {host}: {e}",
            "error": str(e),
        }


def ping_host(host: str, count: int = 4) -> Dict[str, Any]:
    """Lakukan pengujian ping / konektivitas ke host atau server mana pun di jaringan."""
    client = device_manager.get_client()
    return client.ping(target=host, count=count).to_dict()


# =============================================================================
# WINBOX TOOLS MENU FUNCTIONS
# =============================================================================
def tool_ping(device: str = "", target: str = "8.8.8.8", count: int = 4) -> Dict[str, Any]:
    """Pengujian konektivitas IP (Ping) dari router MikroTik."""
    client = device_manager.get_client(device)
    return client.ping(target=target, count=count).to_dict()


def tool_traceroute(device: str = "", target: str = "8.8.8.8", count: int = 4) -> Dict[str, Any]:
    """Melacak jalur lompatan (hop) paket data menuju IP tujuan dari router MikroTik."""
    client = device_manager.get_client(device)
    return client.traceroute(target=target, count=count).to_dict()


def tool_torch(device: str = "", interface: str = "ether1-WAN", duration: int = 3) -> Dict[str, Any]:
    """Memantau lalu lintas trafik data secara real-time (Torch) berdasarkan antarmuka, IP asal/tujuan, dan port."""
    client = device_manager.get_client(device)
    return client.torch(interface=interface, duration=duration).to_dict()


def tool_bandwidth_test(device: str = "", target: str = "127.0.0.1", direction: str = "both", duration: int = 5, protocol: str = "udp") -> Dict[str, Any]:
    """Menguji kapasitas throughput jaringan (Bandwidth Test) antar router MikroTik."""
    client = device_manager.get_client(device)
    return client.bandwidth_test(target=target, direction=direction, duration=duration, protocol=protocol).to_dict()


def get_netwatch(device: str = "") -> Dict[str, Any]:
    """Memantau status koneksi host/antarmuka (Netwatch) pada router MikroTik."""
    client = device_manager.get_client(device)
    return client.get_netwatch().to_dict()


def add_netwatch(device: str = "", host: str = "", interval: str = "1m", timeout: str = "1000ms", comment: str = "") -> Dict[str, Any]:
    """[WRITE] Menambahkan target pemantauan host baru pada Netwatch MikroTik."""
    client = device_manager.get_client(device)
    return client.add_netwatch(host=host, interval=interval, timeout=timeout, comment=comment).to_dict()


def tool_ip_scan(device: str = "", interface: str = "ether1-WAN", address_range: str = "", duration: int = 5) -> Dict[str, Any]:
    """Memindai IP Address aktif (IP Scan) dalam satu rentang jaringan atau antarmuka."""
    client = device_manager.get_client(device)
    return client.ip_scan(interface=interface, address_range=address_range, duration=duration).to_dict()


def get_cpu_profile(device: str = "", duration: int = 3) -> Dict[str, Any]:
    """Memantau penggunaan beban CPU berdasarkan rincian proses sistem yang sedang berjalan (Profile)."""
    client = device_manager.get_client(device)
    return client.get_profile(duration=duration).to_dict()


def send_router_email(device: str = "", to: str = "", subject: str = "", body: str = "") -> Dict[str, Any]:
    """[WRITE] Mengirimkan pesan notifikasi atau berkas dari router via SMTP Email MikroTik."""
    client = device_manager.get_client(device)
    return client.send_email(to=to, subject=subject, body=body).to_dict()


def get_packet_sniffer(device: str = "") -> Dict[str, Any]:
    """Mengambil status konfigurasi Packet Sniffer MikroTik."""
    client = device_manager.get_client(device)
    return client.get_packet_sniffer().to_dict()


def sniff_packets(device: str = "", interface: str = "", count: int = 10) -> Dict[str, Any]:
    """Menangkap sampel paket data yang melintas pada antarmuka router (Packet Sniffer)."""
    client = device_manager.get_client(device)
    return client.sniff_packets(interface=interface, count=count).to_dict()


def get_traffic_monitor(device: str = "") -> Dict[str, Any]:
    """Melihat daftar aturan pemantau batas ambang bandwidth (Traffic Monitor)."""
    client = device_manager.get_client(device)
    return client.get_traffic_monitor().to_dict()


def add_traffic_monitor(device: str = "", name: str = "", interface: str = "ether1-WAN", threshold: str = "50M", trigger: str = "above", on_event: str = "") -> Dict[str, Any]:
    """[WRITE] Menambahkan aturan pemantau batas ambang bandwidth (Traffic Monitor)."""
    client = device_manager.get_client(device)
    return client.add_traffic_monitor(name=name, interface=interface, threshold=threshold, trigger=trigger, on_event=on_event).to_dict()


# =============================================================================
# WINBOX SYSTEM MENU FUNCTIONS
# =============================================================================
def get_identity(device: str = "") -> Dict[str, Any]:
    """Mengambil nama identitas sistem router MikroTik."""
    client = device_manager.get_client(device)
    return client.get_identity().to_dict()


def set_identity(device: str = "", name: str = "") -> Dict[str, Any]:
    """[WRITE] Mengubah nama identitas router MikroTik."""
    client = device_manager.get_client(device)
    return client.set_identity(name=name).to_dict()


def get_system_users(device: str = "") -> Dict[str, Any]:
    """Melihat daftar pengguna sistem router MikroTik dan grup hak aksesnya."""
    client = device_manager.get_client(device)
    return client.get_system_users().to_dict()


def create_system_user(device: str = "", name: str = "", group: str = "read", password: str = "") -> Dict[str, Any]:
    """[WRITE] Menambahkan pengguna sistem router MikroTik baru."""
    client = device_manager.get_client(device)
    return client.create_system_user(name=name, group=group, password=password).to_dict()


def delete_system_user(device: str = "", name: str = "") -> Dict[str, Any]:
    """[WRITE] Menghapus pengguna sistem router MikroTik."""
    client = device_manager.get_client(device)
    return client.delete_system_user(name=name).to_dict()


def get_packages(device: str = "") -> Dict[str, Any]:
    """Melihat daftar modul paket fitur RouterOS yang terpasang."""
    client = device_manager.get_client(device)
    return client.get_packages().to_dict()


def get_routerboard(device: str = "") -> Dict[str, Any]:
    """Mengambil informasi perangkat keras RouterBOARD, nomor seri (serial number), dan firmware BIOS."""
    client = device_manager.get_client(device)
    return client.get_routerboard().to_dict()


def get_clock_sntp(device: str = "") -> Dict[str, Any]:
    """Melihat pengaturan jam sistem, zona waktu, dan status sinkronisasi SNTP Client."""
    client = device_manager.get_client(device)
    return client.get_clock_sntp().to_dict()


def set_clock_timezone(device: str = "", time_zone: str = "Asia/Jakarta") -> Dict[str, Any]:
    """[WRITE] Mengatur zona waktu pada jam sistem router MikroTik."""
    client = device_manager.get_client(device)
    return client.set_clock_timezone(time_zone=time_zone).to_dict()


def system_reboot(device: str = "") -> Dict[str, Any]:
    """[WRITE / ADMIN ONLY] Memulai ulang (reboot) sistem perangkat MikroTik secara aman."""
    client = device_manager.get_client(device)
    return client.reboot().to_dict()


def system_shutdown(device: str = "") -> Dict[str, Any]:
    """[WRITE / ADMIN ONLY] Mematikan (shutdown) sistem perangkat MikroTik secara aman."""
    client = device_manager.get_client(device)
    return client.shutdown().to_dict()


def check_router_update(device: str = "", channel: str = "stable") -> Dict[str, Any]:
    """Mengecek ketersediaan pembaruan RouterOS dan membandingkan versi yang terpasang dengan versi terbaru."""
    client = device_manager.get_client(device)
    return client.check_router_update(channel=channel).to_dict()


def install_router_update(device: str = "", channel: str = "stable") -> Dict[str, Any]:
    """[WRITE / ADMIN ONLY] Mengunduh dan menginstal pembaruan paket RouterOS (otomatis reboot perangkat)."""
    client = device_manager.get_client(device)
    return client.install_router_update(channel=channel).to_dict()


def upgrade_routerboard_firmware(device: str = "") -> Dict[str, Any]:
    """[WRITE / ADMIN ONLY] Meng-upgrade firmware bootloader BIOS RouterBOARD ke versi terbaru yang didukung."""
    client = device_manager.get_client(device)
    return client.upgrade_routerboard_firmware().to_dict()


def get_firmware_status(device: str = "", channel: str = "stable") -> Dict[str, Any]:
    """Melihat status lengkap firmware RouterBOARD dan ketersediaan update paket RouterOS."""
    client = device_manager.get_client(device)
    return client.get_firmware_status(channel=channel).to_dict()


# =============================================================================
# NETWORK TOPOLOGY DISCOVERY & MAPPING TOOLS
# =============================================================================

def scan_network_topology(subnet: str = "", force_refresh: bool = False, **kwargs: Any) -> Dict[str, Any]:
    """
    [READ-ONLY] Memindai seluruh router MikroTik di jaringan, mengumpulkan tabel MNDP/LLDP,
    membangun peta topologi inter-router, dan menyimpan snapshot ke database.
    """
    from core.topology import topology_scanner, TopologyVisualizer
    snapshot = topology_scanner.scan_topology(subnet_cidr=subnet or None)
    visualizer = TopologyVisualizer(snapshot)
    text_summary = visualizer.render_text()
    img_path = visualizer.render_image()

    return {
        "success": True,
        "message": f"Pemindaian topologi berhasil diselesaikan ({snapshot.total_routers} router, {snapshot.total_links} link).",
        "snapshot_id": snapshot.snapshot_id,
        "summary": {
            "total_routers": snapshot.total_routers,
            "online_routers": snapshot.online_routers,
            "offline_routers": snapshot.offline_routers,
            "total_links": snapshot.total_links,
            "verified_links": snapshot.verified_links,
            "redundant_links": snapshot.redundant_links,
            "isolated_routers": snapshot.isolated_routers,
        },
        "text_summary": text_summary,
        "image_path": img_path,
        "links": [l.to_dict() for l in snapshot.inter_router_links],
    }


def get_network_topology(format: str = "summary", **kwargs: Any) -> Dict[str, Any]:
    """
    [READ-ONLY] Mengambil peta topologi jaringan MikroTik saat ini beserta status hubungan antar-router.
    format: 'summary' (ringkasan teks), 'json' (data struktur lengkap), atau 'image' (file gambar diagram).
    """
    from core.topology import topology_scanner, snapshot_db, TopologyVisualizer
    snapshot = snapshot_db.get_latest_snapshot()
    if not snapshot:
        snapshot = topology_scanner.scan_topology()

    visualizer = TopologyVisualizer(snapshot)
    fmt = format.lower().strip()

    if fmt == "json":
        return {
            "success": True,
            "format": "json",
            "data": snapshot.to_dict(),
        }
    elif fmt == "image":
        img_path = visualizer.render_image()
        return {
            "success": True,
            "format": "image",
            "image_path": img_path,
            "caption": f"Bagan Topologi Jaringan MikroTik ({snapshot.total_routers} Router, {snapshot.verified_links} Verified Links)",
        }
    else:
        text_summary = visualizer.render_text()
        return {
            "success": True,
            "format": "summary",
            "text": text_summary,
            "summary": {
                "total_routers": snapshot.total_routers,
                "online_routers": snapshot.online_routers,
                "offline_routers": snapshot.offline_routers,
                "total_links": snapshot.total_links,
                "verified_links": snapshot.verified_links,
                "redundant_links": snapshot.redundant_links,
                "isolated_routers": snapshot.isolated_routers,
            },
            "inter_router_links": [l.to_dict() for l in snapshot.inter_router_links],
        }


def get_router_neighbors(device: str = "") -> Dict[str, Any]:
    """
    [READ-ONLY] Mengambil daftar tetangga perangkat (MNDP / LLDP) yang terdeteksi oleh router target.
    """
    from core.topology import snapshot_db, NetworkTopologyGraph
    client = device_manager.get_client(device)
    raw_res = client.get_neighbors()

    # Correlate with graph model if snapshot exists
    correlated_neighbors = []
    snapshot = snapshot_db.get_latest_snapshot()
    if snapshot:
        graph = NetworkTopologyGraph(snapshot)
        correlated_neighbors = graph.get_neighbors_for(client.device_name)

    return {
        "success": raw_res.success,
        "device": client.device_name,
        "message": f"Ditemukan {len(raw_res.data or [])} tetangga melalui discovery MNDP/LLDP.",
        "neighbors": raw_res.data or [],
        "verified_connections": correlated_neighbors,
    }


def get_connected_interfaces(device: str = "", interface: str = "") -> Dict[str, Any]:
    """
    [READ-ONLY] Memeriksa interface mana yang saling terhubung antara router target dengan router lainnya.
    """
    from core.topology import snapshot_db, topology_scanner
    snapshot = snapshot_db.get_latest_snapshot()
    if not snapshot:
        snapshot = topology_scanner.scan_topology()

    dev_clean = device.lower().strip()
    if_clean = interface.lower().strip()

    matches = []
    for link in snapshot.links:
        src_match = (dev_clean in link.source.lower()) if dev_clean else True
        tgt_match = (dev_clean in link.target.lower()) if dev_clean else True

        if src_match and (not if_clean or if_clean in link.source_interface.lower()):
            matches.append({
                "local_router": link.source,
                "local_interface": link.source_interface,
                "remote_router": link.target_identity or link.target,
                "remote_interface": link.target_interface,
                "protocol": link.protocol,
                "status": link.verification_status,
                "is_redundant": link.is_redundant,
            })
        elif tgt_match and (not if_clean or if_clean in link.target_interface.lower()):
            matches.append({
                "local_router": link.target,
                "local_interface": link.target_interface,
                "remote_router": link.source,
                "remote_interface": link.source_interface,
                "protocol": link.protocol,
                "status": link.verification_status,
                "is_redundant": link.is_redundant,
            })

    return {
        "success": True,
        "device_queried": device,
        "interface_queried": interface,
        "found_connections_count": len(matches),
        "connections": matches,
    }


def compare_topology_snapshots(snapshot_id_a: Optional[int] = None, snapshot_id_b: Optional[int] = None, **kwargs: Any) -> Dict[str, Any]:
    """
    [READ-ONLY] Membandingkan dua snapshot topologi jaringan untuk mendeteksi perubahan router,
    link baru, link putus, atau pergeseran interface.
    """
    from core.topology import snapshot_db
    diff = snapshot_db.compare_snapshots(old_id=snapshot_id_a, new_id=snapshot_id_b)
    return {
        "success": True,
        "has_changes": diff.get("has_changes", False),
        "old_snapshot_time": diff.get("old_timestamp"),
        "new_snapshot_time": diff.get("new_timestamp"),
        "changes": diff.get("changes", {}),
        "summary_text": diff.get("summary_text", ""),
    }


def generate_topology_diagram(filename: str = "topology.png", **kwargs: Any) -> Dict[str, Any]:
    """
    [READ-ONLY] Menghasilkan file gambar visual diagram topologi jaringan MikroTik (.PNG)
    menggunakan NetworkX dan Matplotlib untuk dikirimkan melalui Telegram.
    """
    from core.topology import topology_scanner, snapshot_db, TopologyVisualizer
    snapshot = snapshot_db.get_latest_snapshot()
    if not snapshot:
        snapshot = topology_scanner.scan_topology()

    visualizer = TopologyVisualizer(snapshot)
    out_path = Path("data") / filename
    img_path = visualizer.render_image(str(out_path))

    return {
        "success": True,
        "image_path": str(img_path),
        "total_routers": snapshot.total_routers,
        "total_links": snapshot.total_links,
        "verified_links": snapshot.verified_links,
        "timestamp": snapshot.timestamp,
        "caption": (
            f"🌐 **Bagan Topologi Jaringan MikroTik**\n"
            f"📊 {snapshot.total_routers} Router ({snapshot.online_routers} Online) | "
            f"{snapshot.total_links} Link ({snapshot.verified_links} Terverifikasi)\n"
            f"📅 _Waktu: {snapshot.timestamp}_"
        ),
    }


# Map function names to Python callables
TOOL_REGISTRY: Dict[str, Any] = {
    "connect_mikrotik": connect_mikrotik,
    "get_resource": get_resource,
    "get_interface": get_interface,
    "get_ip": get_ip,
    "get_route": get_route,
    "get_arp": get_arp,
    "get_dhcp": get_dhcp,
    "get_hotspot": get_hotspot,
    "get_firewall": get_firewall,
    "get_logs": get_logs,
    "ping": ping,
    "create_hotspot_user": create_hotspot_user,
    "delete_hotspot_user": delete_hotspot_user,
    "set_interface_state": set_interface_state,
    "add_ip_address": add_ip_address,
    "remove_ip_address": remove_ip_address,
    "set_ip_address": set_ip_address,
    "discover_devices": discover_devices,
    "register_device": register_device,
    "remove_device": remove_device,
    "check_server_port": check_server_port,
    "ping_host": ping_host,
    # Tools Menu
    "tool_ping": tool_ping,
    "tool_traceroute": tool_traceroute,
    "tool_torch": tool_torch,
    "tool_bandwidth_test": tool_bandwidth_test,
    "get_netwatch": get_netwatch,
    "add_netwatch": add_netwatch,
    "tool_ip_scan": tool_ip_scan,
    "get_cpu_profile": get_cpu_profile,
    "send_router_email": send_router_email,
    "get_packet_sniffer": get_packet_sniffer,
    "sniff_packets": sniff_packets,
    "get_traffic_monitor": get_traffic_monitor,
    "add_traffic_monitor": add_traffic_monitor,
    # System Menu
    "get_identity": get_identity,
    "set_identity": set_identity,
    "get_system_users": get_system_users,
    "create_system_user": create_system_user,
    "delete_system_user": delete_system_user,
    "get_packages": get_packages,
    "get_routerboard": get_routerboard,
    "get_clock_sntp": get_clock_sntp,
    "set_clock_timezone": set_clock_timezone,
    "system_reboot": system_reboot,
    "system_shutdown": system_shutdown,
    # Firmware & Update Menu
    "check_router_update": check_router_update,
    "install_router_update": install_router_update,
    "upgrade_routerboard_firmware": upgrade_routerboard_firmware,
    "get_firmware_status": get_firmware_status,
    # Network Topology & Mapping Menu
    "scan_network_topology": scan_network_topology,
    "get_network_topology": get_network_topology,
    "get_router_neighbors": get_router_neighbors,
    "get_connected_interfaces": get_connected_interfaces,
    "compare_topology_snapshots": compare_topology_snapshots,
    "generate_topology_diagram": generate_topology_diagram,
}

# OpenAI / Gemini tool function definitions schema
TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "connect_mikrotik",
            "description": "Cek koneksi dan status router MikroTik target",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama atau alias router (misal: 'Kantor Utama', 'Lab')"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_resource",
            "description": "Ambil data resource router dan info perangkat (tipe/model router, board name, versi RouterOS, arsitektur CPU, RAM, Uptime)",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router (misal: 'Kantor Utama')"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_interface",
            "description": "Ambil daftar interface, link status UP/DOWN, dan traffic RX/TX byte",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ip",
            "description": "Ambil daftar seluruh alamat IP address yang terpasang pada interface MikroTik (bukan tabel routing)",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_route",
            "description": "Ambil tabel routing IP (destination prefix, gateway, distance, status active). Gunakan untuk rute, routing table, dan mencari default route WAN",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_arp",
            "description": "Ambil tabel ARP (IP ke MAC address client)",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dhcp",
            "description": "Ambil daftar client DHCP lease yang terhubung",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_hotspot",
            "description": "Ambil informasi user hotspot, user yang sedang aktif online, atau profil",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "query_type": {
                        "type": "string",
                        "enum": ["all", "users", "active", "profiles"],
                        "description": "Tipe data hotspot yang diminta",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_firewall",
            "description": "Ambil aturan filter firewall",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_logs",
            "description": "Ambil baris log sistem MikroTik (warning, info, error)",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "limit": {"type": "integer", "description": "Jumlah baris log maksimal"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ping",
            "description": "Lakukan ping dari MikroTik ke alamat tujuan (misal 8.8.8.8)",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "target": {"type": "string", "description": "IP atau domain target ping"},
                    "count": {"type": "integer", "description": "Jumlah paket ping"}
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_hotspot_user",
            "description": "[WRITE] Membuat user hotspot baru. Memerlukan konfirmasi dari user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "name": {"type": "string", "description": "Username hotspot baru"},
                    "password": {"type": "string", "description": "Password hotspot"},
                    "profile": {"type": "string", "description": "Nama profil (default, staff, student)"},
                    "limit_uptime": {"type": "string", "description": "Batas waktu aktif (misal '1d', '3h', '30m')"}
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_hotspot_user",
            "description": "[WRITE] Menghapus user hotspot. Memerlukan konfirmasi dari user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "name": {"type": "string", "description": "Username hotspot yang akan dihapus"}
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_interface_state",
            "description": "[WRITE] Mengaktifkan atau menonaktifkan interface. Memerlukan konfirmasi dari user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "interface_name": {"type": "string", "description": "Nama interface (misal 'ether1-WAN', 'wlan1')"},
                    "enabled": {"type": "boolean", "description": "True untuk aktifkan, False untuk nonaktifkan"}
                },
                "required": ["interface_name", "enabled"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_ip_address",
            "description": "[WRITE] Menambahkan IP address baru pada antarmuka router MikroTik. Memerlukan konfirmasi.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "address": {"type": "string", "description": "Alamat IP dan subnet prefix (misal '192.168.10.1/24')"},
                    "interface": {"type": "string", "description": "Nama antarmuka/interface (misal 'ether2', 'ether2-LAN')"},
                    "comment": {"type": "string", "description": "Catatan atau keterangan IP address"},
                },
                "required": ["address", "interface"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_ip_address",
            "description": "[WRITE] Menghapus konfigurasi IP address dari router MikroTik. Memerlukan konfirmasi.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "address": {"type": "string", "description": "Alamat IP yang akan dihapus (misal '192.168.10.1/24' atau '192.168.10.1')"},
                },
                "required": ["address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_ip_address",
            "description": "[WRITE] Mengubah (edit) konfigurasi IP address atau antarmuka router MikroTik. Memerlukan konfirmasi.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "current_address": {"type": "string", "description": "Alamat IP saat ini yang akan diubah"},
                    "new_address": {"type": "string", "description": "Alamat IP baru pengganti"},
                    "new_interface": {"type": "string", "description": "Nama antarmuka baru jika dipindahkan"},
                    "comment": {"type": "string", "description": "Keterangan/catatan baru"},
                },
                "required": ["current_address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discover_devices",
            "description": "Memindai subnet untuk mencari perangkat router MikroTik baru",
            "parameters": {
                "type": "object",
                "properties": {
                    "subnet": {"type": "string", "description": "Subnet CIDR (misal: '10.20.33.0/24')"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "register_device",
            "description": "[WRITE] Mendaftarkan router MikroTik baru ke sistem dan background monitor",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nama router (misal 'Kantor Cabang', 'Lab PTI')"},
                    "host": {"type": "string", "description": "Alamat IP host router (misal '192.168.88.1')"},
                    "protocol": {"type": "string", "description": "Protokol: 'api' (port 8728), 'rest' (port 80), 'ssh' (port 22)"},
                    "port": {"type": "integer", "description": "Nomor port koneksi (default: 8728 untuk API, 80 untuk REST)"},
                    "username": {"type": "string", "description": "Username admin router (default 'admin')"},
                    "password": {"type": "string", "description": "Password admin router"},
                    "description": {"type": "string", "description": "Keterangan singkat tentang router"},
                },
                "required": ["name", "host"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_device",
            "description": "[WRITE] Menghapus router MikroTik dari inventaris dan background monitor",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nama atau ID router yang ingin dihapus"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_server_port",
            "description": "Menguji status keterjangkauan port service pada server atau host (misal port 80/443 HTTP/S, 3306 MySQL, 22 SSH)",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Alamat IP atau hostname server yang dituju (misal '10.20.33.10' atau 'example.com')"},
                    "port": {"type": "integer", "description": "Nomor port TCP (misal 80, 443, 22, 3306)"},
                    "timeout": {"type": "number", "description": "Batas waktu koneksi dalam detik (default: 3.0)"}
                },
                "required": ["host", "port"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ping_host",
            "description": "Lakukan pengujian ping / konektivitas ke host atau server mana pun di jaringan",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Alamat IP atau domain target yang ingin diping"},
                    "count": {"type": "integer", "description": "Jumlah paket ICMP (default: 4)"}
                },
                "required": ["host"],
            },
        },
    },
    # =========================================================================
    # WINBOX TOOLS MENU SCHEMAS
    # =========================================================================
    {
        "type": "function",
        "function": {
            "name": "tool_traceroute",
            "description": "Melacak rute lompatan hop (traceroute/tracert) menuju IP atau domain tujuan dari router MikroTik",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "target": {"type": "string", "description": "Alamat IP atau domain tujuan (misal '8.8.8.8')"},
                    "count": {"type": "integer", "description": "Jumlah hitungan probe (default: 4)"},
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_torch",
            "description": "Memantau lalu lintas trafik data real-time (Torch) pada antarmuka router",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "interface": {"type": "string", "description": "Nama antarmuka jaringan (misal 'ether1-WAN')"},
                    "duration": {"type": "integer", "description": "Durasi pemantauan dalam detik (default: 3)"},
                },
                "required": ["interface"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_bandwidth_test",
            "description": "Menguji kapasitas bandwidth throughput antar router MikroTik",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "target": {"type": "string", "description": "IP router lawan yang menjalankan btest server"},
                    "direction": {"type": "string", "description": "'both', 'receive', atau 'transmit' (default: 'both')"},
                    "duration": {"type": "integer", "description": "Durasi tes dalam detik (default: 5)"},
                    "protocol": {"type": "string", "description": "'udp' atau 'tcp' (default: 'udp')"},
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_netwatch",
            "description": "Melihat daftar target pemantauan Netwatch pada router",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_netwatch",
            "description": "[WRITE] Menambahkan host baru untuk dipantau statusnya oleh Netwatch",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "host": {"type": "string", "description": "Alamat IP host yang ingin dipantau"},
                    "interval": {"type": "string", "description": "Interval waktu ping (misal '1m', '30s')"},
                    "timeout": {"type": "string", "description": "Timeout ping (misal '1000ms')"},
                    "comment": {"type": "string", "description": "Komentar / keterangan"},
                },
                "required": ["host"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_ip_scan",
            "description": "Memindai IP Address aktif dalam suatu antarmuka atau rentang IP",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "interface": {"type": "string", "description": "Nama interface jaringan"},
                    "address_range": {"type": "string", "description": "Rentang subnet IP (misal '192.168.10.0/24')"},
                    "duration": {"type": "integer", "description": "Durasi pemindaian dalam detik (default: 5)"},
                },
                "required": ["interface"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cpu_profile",
            "description": "Mengambil rincian pemakaian CPU berdasarkan proses sistem (Profile)",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "duration": {"type": "integer", "description": "Durasi sampling dalam detik (default: 3)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_router_email",
            "description": "[WRITE] Mengirimkan notifikasi email via SMTP router MikroTik",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "to": {"type": "string", "description": "Alamat email penerima"},
                    "subject": {"type": "string", "description": "Judul subjek email"},
                    "body": {"type": "string", "description": "Isi pesan email"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_packet_sniffer",
            "description": "Melihat status konfigurasi packet sniffer MikroTik",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sniff_packets",
            "description": "Menangkap sampel paket data jaringan dari sniffer MikroTik",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "interface": {"type": "string", "description": "Nama interface (kosongkan untuk semua)"},
                    "count": {"type": "integer", "description": "Jumlah sampel paket (default: 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_traffic_monitor",
            "description": "Melihat daftar aturan pemantauan batas traffic monitor",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_traffic_monitor",
            "description": "[WRITE] Menambahkan aturan baru untuk memantau batas ambang trafik (Traffic Monitor)",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "name": {"type": "string", "description": "Nama aturan traffic monitor"},
                    "interface": {"type": "string", "description": "Nama interface yang dipantau (misal: ether1-WAN)"},
                    "threshold": {"type": "string", "description": "Ambang batas trafik (misal: 10M, 50M, 10000000)"},
                    "trigger": {"type": "string", "enum": ["above", "below"], "description": "Kondisi pemicu: 'above' jika melebihi, 'below' jika di bawah ambang"},
                    "on_event": {"type": "string", "description": "Script atau perintah yang dijalankan saat trigger terjadi"}
                },
                "required": ["name", "interface", "threshold"]
            },
        },
    },
    # =========================================================================
    # WINBOX SYSTEM MENU SCHEMAS
    # =========================================================================
    {
        "type": "function",
        "function": {
            "name": "get_identity",
            "description": "Melihat nama identitas router MikroTik",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_identity",
            "description": "[WRITE] Mengubah nama identitas router MikroTik",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "name": {"type": "string", "description": "Nama identitas baru untuk router"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_users",
            "description": "Melihat daftar akun user administrator sistem MikroTik dan privilege grupnya",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_system_user",
            "description": "[WRITE] Menambahkan akun user baru pada sistem router MikroTik",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "name": {"type": "string", "description": "Nama username baru"},
                    "group": {"type": "string", "description": "Grup privilege ('read', 'write', 'full')"},
                    "password": {"type": "string", "description": "Password user"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_system_user",
            "description": "[WRITE] Menghapus akun user sistem MikroTik",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "name": {"type": "string", "description": "Nama username yang ingin dihapus"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_packages",
            "description": "Melihat daftar paket modul sistem RouterOS yang terpasang",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_routerboard",
            "description": "Melihat rincian hardware RouterBOARD, nomor seri (serial number), dan firmware BIOS",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_clock_sntp",
            "description": "Melihat pengaturan jam sistem, kalender, zona waktu, dan status SNTP client",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_clock_timezone",
            "description": "[WRITE] Mengatur zona waktu (timezone) jam router MikroTik",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"},
                    "time_zone": {"type": "string", "description": "Nama timezone (misal 'Asia/Jakarta', 'Asia/Makassar')"},
                },
                "required": ["time_zone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_reboot",
            "description": "[WRITE / ADMIN ONLY] Memulai ulang (reboot) router MikroTik secara aman",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_shutdown",
            "description": "[WRITE / ADMIN ONLY] Mematikan (shutdown) router MikroTik secara aman",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router"}
                },
            },
        },
    },
    # =========================================================================
    # FIRMWARE & UPGRADE SCHEMAS
    # =========================================================================
    {
        "type": "function",
        "function": {
            "name": "check_router_update",
            "description": "Mengecek ketersediaan update RouterOS dari server MikroTik untuk melihat apakah ada versi baru",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router target"},
                    "channel": {"type": "string", "description": "Channel rilis RouterOS ('stable', 'long-term', 'testing')", "default": "stable"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "install_router_update",
            "description": "[WRITE / ADMIN ONLY] Mengunduh dan menginstal update RouterOS dan memulai proses reboot otomatis",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router target"},
                    "channel": {"type": "string", "description": "Channel rilis RouterOS ('stable', 'long-term', 'testing')", "default": "stable"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upgrade_routerboard_firmware",
            "description": "[WRITE / ADMIN ONLY] Meng-upgrade firmware bootloader (BIOS) RouterBOARD router MikroTik",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router target"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_firmware_status",
            "description": "Melihat status komprehensif versi RouterOS saat ini, update terbaru, serta versi firmware bootloader RouterBOARD",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router target"},
                    "channel": {"type": "string", "description": "Kanal rilis pembaruan (misal: 'stable', 'long-term', 'testing')", "default": "stable"}
                },
            },
        },
    },
    # =========================================================================
    # TOPOLOGY & NETWORK MAPPING SCHEMAS
    # =========================================================================
    {
        "type": "function",
        "function": {
            "name": "scan_network_topology",
            "description": "Memindai seluruh router MikroTik secara otomatis, mengumpulkan neighbor MNDP/LLDP, dan memetakan topologi jaringan terbaru",
            "parameters": {
                "type": "object",
                "properties": {
                    "subnet": {"type": "string", "description": "Subnet CIDR opsional (misal: '10.20.33.0/24') untuk mencari router tambahan yang belum terdaftar"},
                    "force_refresh": {"type": "boolean", "description": "Paksa refresh scan jaringan secara langsung", "default": True}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_network_topology",
            "description": "Melihat peta topologi jaringan MikroTik saat ini, daftar koneksi antar-router, dan status online/offline setiap router",
            "parameters": {
                "type": "object",
                "properties": {
                    "format": {"type": "string", "description": "Format output: 'summary' (ringkasan teks), 'json' (data terstruktur), atau 'image' (diagram gambar)", "default": "summary"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_router_neighbors",
            "description": "Melihat daftar perangkat tetangga (neighbors) MNDP/LLDP yang terhubung langsung ke router target beserta interface-nya",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router yang ingin diperiksa tetangganya (misal: 'Kantor Utama')"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_connected_interfaces",
            "description": "Mengetahui hubungan antar-interface spesifik router (misal: interface ether2 pada R1 terhubung ke router mana dan interface apa)",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Nama router (misal: 'Kantor Utama', 'R1')"},
                    "interface": {"type": "string", "description": "Nama interface lokal yang ingin diperiksa (misal: 'ether2', 'ether1-WAN')"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_topology_snapshots",
            "description": "Membandingkan kondisi topologi jaringan sekarang dengan sebelumnya untuk mendeteksi router baru, router mati, link terputus, atau perubahan port",
            "parameters": {
                "type": "object",
                "properties": {
                    "snapshot_id_a": {"type": "integer", "description": "ID snapshot lama (opsional)"},
                    "snapshot_id_b": {"type": "integer", "description": "ID snapshot baru (opsional)"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_topology_diagram",
            "description": "Menghasilkan gambar visual diagram topologi jaringan MikroTik (.PNG) untuk dikirimkan ke Telegram",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Nama file gambar keluaran", "default": "topology.png"}
                },
            },
        },
    },
]
