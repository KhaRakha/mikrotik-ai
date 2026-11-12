"""
Base class and data structures for MikroTik communication.
Defines unified interface implemented by REST, RouterOS API, SSH, and Mock clients.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class OperationResult:
    success: bool
    message: str = ""
    data: Any = None
    error: Optional[str] = None
    device: str = ""
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "data": self.data,
            "error": self.error,
            "device": self.device,
            "latency_ms": round(self.latency_ms, 2),
        }


@dataclass
class ResourceInfo:
    cpu_load: int = 0
    free_memory_mb: float = 0.0
    total_memory_mb: float = 0.0
    memory_usage_percent: float = 0.0
    uptime: str = "0s"
    version: str = "Unknown"
    board_name: str = "RouterBOARD"
    architecture_name: str = "unknown"
    cpu_count: int = 1
    free_hdd_space_mb: float = 0.0
    total_hdd_space_mb: float = 0.0


@dataclass
class InterfaceInfo:
    name: str
    type: str = "ether"
    running: bool = True
    disabled: bool = False
    mac_address: str = ""
    comment: str = ""
    rx_byte: int = 0
    tx_byte: int = 0
    rx_packet: int = 0
    tx_packet: int = 0
    link_downs: int = 0


@dataclass
class IpAddressInfo:
    address: str
    network: str = ""
    interface: str = ""
    disabled: bool = False
    dynamic: bool = False


@dataclass
class PingResult:
    host: str
    sent: int = 4
    received: int = 4
    packet_loss_percent: float = 0.0
    avg_rtt_ms: float = 0.0
    min_rtt_ms: float = 0.0
    max_rtt_ms: float = 0.0
    status: str = "OK"


@dataclass
class NeighborInfo:
    interface: str
    address: str = ""
    mac_address: str = ""
    identity: str = ""
    platform: str = "MikroTik"
    version: str = ""
    remote_interface: str = ""
    board: str = ""
    protocol: str = "mndp"
    age: str = ""
    uptime: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interface": self.interface,
            "address": self.address,
            "mac_address": self.mac_address,
            "identity": self.identity,
            "platform": self.platform,
            "version": self.version,
            "remote_interface": self.remote_interface,
            "board": self.board,
            "protocol": self.protocol,
            "age": self.age,
            "uptime": self.uptime,
        }


class BaseMikrotikClient(ABC):
    """Abstract base client for communicating with MikroTik RouterOS."""

    def __init__(self, host: str, port: int, username: str = "admin", password: str = "", use_ssl: bool = False, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.timeout = timeout
        self.device_name: str = host

    @abstractmethod
    def test_connection(self) -> OperationResult:
        """Test if router is reachable and credentials are valid."""
        pass

    @abstractmethod
    def get_resource(self) -> OperationResult:
        """Retrieve system resources (CPU, Memory, Uptime, Version, Board)."""
        pass

    @abstractmethod
    def get_interfaces(self) -> OperationResult:
        """Retrieve list of network interfaces and traffic counters."""
        pass

    @abstractmethod
    def get_neighbors(self) -> OperationResult:
        """Retrieve discovered network neighbors via MNDP/LLDP (/ip/neighbor/print)."""
        pass

    @abstractmethod
    def get_ip_addresses(self) -> OperationResult:
        """Retrieve configured IP addresses."""
        pass

    @abstractmethod
    def get_ip_routes(self) -> OperationResult:
        """Retrieve IP routing table."""
        pass

    @abstractmethod
    def get_arp_table(self) -> OperationResult:
        """Retrieve ARP cache."""
        pass

    @abstractmethod
    def get_dhcp_leases(self) -> OperationResult:
        """Retrieve active DHCP server leases."""
        pass

    @abstractmethod
    def get_hotspot_users(self) -> OperationResult:
        """Retrieve configured hotspot users."""
        pass

    @abstractmethod
    def get_hotspot_active(self) -> OperationResult:
        """Retrieve currently active hotspot sessions."""
        pass

    @abstractmethod
    def get_hotspot_profiles(self) -> OperationResult:
        """Retrieve hotspot user profiles."""
        pass

    @abstractmethod
    def get_firewall_rules(self) -> OperationResult:
        """Retrieve firewall filter rules."""
        pass

    @abstractmethod
    def get_system_logs(self, limit: int = 30) -> OperationResult:
        """Retrieve recent system logs."""
        pass

    @abstractmethod
    def ping(self, target: str, count: int = 4) -> OperationResult:
        """Perform ping to destination."""
        pass

    @abstractmethod
    def create_hotspot_user(self, name: str, password: str = "", profile: str = "default", limit_uptime: str = "") -> OperationResult:
        """Create a new hotspot user. Requires confirmation."""
        pass

    @abstractmethod
    def delete_hotspot_user(self, name: str) -> OperationResult:
        """Delete an existing hotspot user. Requires confirmation."""
        pass

    @abstractmethod
    def set_interface_state(self, interface_name: str, enabled: bool) -> OperationResult:
        """Enable or disable a network interface. Requires confirmation."""
        pass

    def add_ip_address(self, address: str, interface: str, comment: str = "") -> OperationResult:
        """Add a new IP address to an interface. Requires confirmation."""
        return OperationResult(success=False, message="add_ip_address belum diimplementasikan untuk driver ini.")

    def remove_ip_address(self, address: str) -> OperationResult:
        """Remove an IP address from the router. Requires confirmation."""
        return OperationResult(success=False, message="remove_ip_address belum diimplementasikan untuk driver ini.")

    def set_ip_address(
        self,
        current_address: str,
        new_address: Optional[str] = None,
        new_interface: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> OperationResult:
        """Edit an existing IP address on the router. Requires confirmation."""
        return OperationResult(success=False, message="set_ip_address belum diimplementasikan untuk driver ini.")

    @abstractmethod
    def execute_raw_command(self, path: str, command: str, params: Optional[Dict[str, Any]] = None) -> OperationResult:
        """Execute a raw operation on RouterOS (subject to dangerous command filter)."""
        pass

    # =========================================================================
    # WINBOX TOOLS MENU
    # =========================================================================
    def traceroute(self, target: str, count: int = 4) -> OperationResult:
        """Trace route to destination."""
        return self.execute_raw_command("tool", f"traceroute address={target} count={count}")

    def torch(self, interface: str, duration: int = 3) -> OperationResult:
        """Monitor real-time interface traffic (Torch)."""
        return self.execute_raw_command("tool", f"torch {interface}")

    def bandwidth_test(self, target: str, direction: str = "both", duration: int = 5, protocol: str = "udp") -> OperationResult:
        """Test throughput between routers."""
        return self.execute_raw_command("tool", f"bandwidth-test address={target} direction={direction} duration={duration}s protocol={protocol}")

    def get_netwatch(self) -> OperationResult:
        """Retrieve configured Netwatch host entries."""
        return self.execute_raw_command("tool/netwatch", "print")

    def add_netwatch(self, host: str, interval: str = "1m", timeout: str = "1000ms", comment: str = "") -> OperationResult:
        """Add Netwatch monitoring target."""
        return self.execute_raw_command("tool/netwatch", f"add host={host} interval={interval} timeout={timeout} comment=\"{comment}\"")

    def ip_scan(self, interface: str, address_range: str = "", duration: int = 5) -> OperationResult:
        """Scan active IP addresses on subnet/interface."""
        return self.execute_raw_command("tool", f"ip-scan interface={interface} duration={duration}s")

    def get_profile(self, duration: int = 3) -> OperationResult:
        """Retrieve CPU usage profile breakdown per process."""
        return self.execute_raw_command("tool", f"profile duration={duration}s")

    def send_email(self, to: str, subject: str, body: str) -> OperationResult:
        """Send notification email via router SMTP."""
        return self.execute_raw_command("tool/e-mail", f"send to=\"{to}\" subject=\"{subject}\" body=\"{body}\"")

    def get_packet_sniffer(self) -> OperationResult:
        """Retrieve packet sniffer status."""
        return self.execute_raw_command("tool/sniffer", "print")

    def sniff_packets(self, interface: str = "", count: int = 10) -> OperationResult:
        """Capture packet header samples from sniffer."""
        return self.execute_raw_command("tool/sniffer/packet", f"print count={count}")

    def get_traffic_monitor(self) -> OperationResult:
        """Retrieve traffic monitor rules."""
        return self.execute_raw_command("tool/traffic-monitor", "print")

    # =========================================================================
    # WINBOX SYSTEM MENU
    # =========================================================================
    def get_identity(self) -> OperationResult:
        """Retrieve router identity."""
        return self.execute_raw_command("system/identity", "print")

    def set_identity(self, name: str) -> OperationResult:
        """Set router identity."""
        return self.execute_raw_command("system/identity", f"set name=\"{name}\"")

    def get_system_users(self) -> OperationResult:
        """Retrieve RouterOS users."""
        return self.execute_raw_command("user", "print")

    def create_system_user(self, name: str, group: str = "read", password: str = "") -> OperationResult:
        """Create RouterOS user."""
        return self.execute_raw_command("user", f"add name=\"{name}\" group=\"{group}\" password=\"{password}\"")

    def delete_system_user(self, name: str) -> OperationResult:
        """Delete RouterOS user."""
        return self.execute_raw_command("user", f"remove [find name=\"{name}\"]")

    def get_packages(self) -> OperationResult:
        """Retrieve installed RouterOS packages."""
        return self.execute_raw_command("system/package", "print")

    def get_routerboard(self) -> OperationResult:
        """Retrieve RouterBOARD hardware and firmware info."""
        return self.execute_raw_command("system/routerboard", "print")

    def get_clock_sntp(self) -> OperationResult:
        """Retrieve clock and SNTP client configuration."""
        return self.execute_raw_command("system/clock", "print")

    def set_clock_timezone(self, time_zone: str) -> OperationResult:
        """Set router time zone."""
        return self.execute_raw_command("system/clock", f"set time-zone-name=\"{time_zone}\"")

    def reboot(self) -> OperationResult:
        """Reboot router."""
        return self.execute_raw_command("system", "reboot")

    def shutdown(self) -> OperationResult:
        """Shutdown router."""
        return self.execute_raw_command("system", "shutdown")

    def check_router_update(self, channel: str = "stable") -> OperationResult:
        """Check for RouterOS software updates from MikroTik servers."""
        return self.execute_raw_command("system/package/update", f"check-for-updates once")

    def install_router_update(self, channel: str = "stable") -> OperationResult:
        """Download and install RouterOS update packages, initiating an automatic reboot."""
        return self.execute_raw_command("system/package/update", "install")

    def upgrade_routerboard_firmware(self) -> OperationResult:
        """Upgrade RouterBOARD bootloader (BIOS) firmware to match RouterOS version."""
        return self.execute_raw_command("system/routerboard", "upgrade")

    def get_firmware_status(self, channel: str = "stable") -> OperationResult:
        """Retrieve combined RouterOS update status and RouterBOARD hardware firmware information."""
        return OperationResult(
            success=False,
            message="get_firmware_status belum didukung secara bawaan untuk protokol ini.",
            device=self.device_name,
        )
