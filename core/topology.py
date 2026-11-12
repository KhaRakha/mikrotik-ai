"""
Network Topology Discovery and Automatic Network Mapping Module.
Provides multi-router discovery, MNDP/LLDP neighbor aggregation,
interface correlation, graph analysis (NetworkX), visualization (text/image/JSON),
and SQLite snapshot change detection.
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime
import ipaddress
import json
import logging
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import matplotlib
    matplotlib.use("Agg")  # Non-interactive backend safe for servers and CLI
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    matplotlib = None
    plt = None
    HAS_MATPLOTLIB = False

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    nx = None
    HAS_NETWORKX = False

from config.settings import DeviceConfig, settings
from mikrotik.base import BaseMikrotikClient, OperationResult
from mikrotik.discovery import device_discovery
from mikrotik.manager import device_manager

logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

class TopologyNode:
    """Represents a network device (router or switch) in the topology."""

    def __init__(
        self,
        node_id: str,
        identity: str,
        host: str,
        mac_address: str = "",
        version: str = "Unknown",
        board: str = "RouterBOARD",
        status: str = "ONLINE",
        interfaces: Optional[List[Dict[str, Any]]] = None,
        neighbors_raw: Optional[List[Dict[str, Any]]] = None,
        is_isolated: bool = False,
        neighbor_discovery_enabled: bool = True,
        is_managed: bool = True,
    ):
        self.node_id = node_id.strip()
        self.identity = identity.strip() or self.node_id
        self.host = host.strip()
        self.mac_address = (mac_address or "").upper().strip()
        self.version = version or "Unknown"
        self.board = board or "RouterBOARD"
        self.status = status.upper()  # ONLINE, OFFLINE, SIMULATED, EXTERNAL
        self.interfaces = interfaces or []
        self.neighbors_raw = neighbors_raw or []
        self.is_isolated = is_isolated
        self.neighbor_discovery_enabled = neighbor_discovery_enabled
        self.is_managed = is_managed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "identity": self.identity,
            "host": self.host,
            "mac_address": self.mac_address,
            "version": self.version,
            "board": self.board,
            "status": self.status,
            "interfaces_count": len(self.interfaces),
            "interfaces": self.interfaces,
            "neighbors_raw": self.neighbors_raw,
            "is_isolated": self.is_isolated,
            "neighbor_discovery_enabled": self.neighbor_discovery_enabled,
            "is_managed": self.is_managed,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TopologyNode:
        return cls(
            node_id=data.get("node_id", ""),
            identity=data.get("identity", ""),
            host=data.get("host", ""),
            mac_address=data.get("mac_address", ""),
            version=data.get("version", "Unknown"),
            board=data.get("board", "RouterBOARD"),
            status=data.get("status", "ONLINE"),
            interfaces=data.get("interfaces", []),
            neighbors_raw=data.get("neighbors_raw", []),
            is_isolated=data.get("is_isolated", False),
            neighbor_discovery_enabled=data.get("neighbor_discovery_enabled", True),
            is_managed=data.get("is_managed", True),
        )


class TopologyLink:
    """Represents a physical/logical connection between two router interfaces."""

    def __init__(
        self,
        source: str,
        source_interface: str,
        target: str,
        target_interface: str,
        target_identity: str = "",
        target_ip: str = "",
        target_mac: str = "",
        protocol: str = "mndp",
        verification_status: str = "VERIFIED",
        is_redundant: bool = False,
    ):
        self.source = source
        self.source_interface = source_interface
        self.target = target
        self.target_interface = target_interface
        self.target_identity = target_identity or target
        self.target_ip = target_ip
        self.target_mac = (target_mac or "").upper()
        self.protocol = protocol.lower()  # mndp, lldp, cdp, correlated
        # VERIFIED (bidirectional match), ESTIMATED_ONE_WAY (unidirectional), UNVERIFIED (external)
        self.verification_status = verification_status.upper()
        self.is_redundant = is_redundant

    @property
    def link_id(self) -> str:
        """Normalized unique identifier for the undirected link."""
        endpoints = sorted([
            f"{self.source}:{self.source_interface}",
            f"{self.target}:{self.target_interface}",
        ])
        return f"{endpoints[0]}<->{endpoints[1]}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "source_interface": self.source_interface,
            "target": self.target,
            "target_interface": self.target_interface,
            "target_identity": self.target_identity,
            "target_ip": self.target_ip,
            "target_mac": self.target_mac,
            "protocol": self.protocol,
            "verification_status": self.verification_status,
            "is_redundant": self.is_redundant,
            "link_id": self.link_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TopologyLink:
        return cls(
            source=data.get("source", ""),
            source_interface=data.get("source_interface", ""),
            target=data.get("target", ""),
            target_interface=data.get("target_interface", ""),
            target_identity=data.get("target_identity", ""),
            target_ip=data.get("target_ip", ""),
            target_mac=data.get("target_mac", ""),
            protocol=data.get("protocol", "mndp"),
            verification_status=data.get("verification_status", "VERIFIED"),
            is_redundant=data.get("is_redundant", False),
        )


class TopologySnapshot:
    """A full point-in-time snapshot of the network topology."""

    def __init__(
        self,
        snapshot_id: int,
        timestamp: str,
        nodes: Dict[str, TopologyNode],
        links: List[TopologyLink],
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.snapshot_id = snapshot_id
        self.timestamp = timestamp
        self.nodes = nodes
        self.links = links
        self.metadata = metadata or {}

    @property
    def inter_router_links(self) -> List[TopologyLink]:
        return [l for l in self.links if l.verification_status in ("VERIFIED", "ESTIMATED_ONE_WAY")]

    @property
    def external_links(self) -> List[TopologyLink]:
        return [l for l in self.links if l.verification_status == "UNVERIFIED"]

    @property
    def total_routers(self) -> int:
        return len(self.nodes)

    @property
    def online_routers(self) -> int:
        return sum(1 for n in self.nodes.values() if n.status in ("ONLINE", "SIMULATED"))

    @property
    def offline_routers(self) -> int:
        return sum(1 for n in self.nodes.values() if n.status == "OFFLINE")

    @property
    def total_links(self) -> int:
        return len(self.links)

    @property
    def verified_links(self) -> int:
        return sum(1 for l in self.links if l.verification_status == "VERIFIED")

    @property
    def redundant_links(self) -> int:
        return sum(1 for l in self.links if l.is_redundant)

    @property
    def isolated_routers(self) -> List[str]:
        return [n.identity for n in self.nodes.values() if n.is_isolated]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "summary": {
                "total_routers": self.total_routers,
                "online_routers": self.online_routers,
                "offline_routers": self.offline_routers,
                "total_links": self.total_links,
                "verified_links": self.verified_links,
                "redundant_links": self.redundant_links,
                "isolated_routers": self.isolated_routers,
            },
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "links": [l.to_dict() for l in self.links],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TopologySnapshot:
        nodes = {k: TopologyNode.from_dict(v) for k, v in data.get("nodes", {}).items()}
        links = [TopologyLink.from_dict(l) for l in data.get("links", [])]
        return cls(
            snapshot_id=data.get("snapshot_id", 0),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            nodes=nodes,
            links=links,
            metadata=data.get("metadata", {}),
        )


# =============================================================================
# TOPOLOGY SCANNER & INTERFACE MAPPER
# =============================================================================

class TopologyScanner:
    """Discovers router nodes, aggregates MNDP/LLDP neighbors, and maps links."""

    def __init__(self, timeout: float = 3.0, max_workers: int = 10):
        self.timeout = timeout
        self.max_workers = max_workers

    def scan_single_device(self, dev: DeviceConfig) -> TopologyNode:
        """Polls a single router to retrieve its identity, resources, interfaces, and neighbors."""
        node_id = dev.name
        identity = dev.name
        host = dev.host
        client = device_manager.get_client(dev.name)

        is_simulated = getattr(client, "is_fallback_mock", False) or dev.protocol.lower() == "mock"

        # 1. Connection check
        conn_res = client.test_connection()
        if not conn_res.success and not is_simulated:
            logger.warning("Router '%s' (%s) unreachable during topology scan.", dev.name, dev.host)
            return TopologyNode(
                node_id=node_id,
                identity=identity,
                host=host,
                status="OFFLINE",
                is_managed=True,
                is_isolated=True,
            )

        # 2. Retrieve identity
        id_res = client.get_identity()
        if id_res.success and id_res.data:
            if isinstance(id_res.data, list) and id_res.data:
                identity = id_res.data[0].get("name", identity)
            elif isinstance(id_res.data, dict):
                identity = id_res.data.get("name", identity)

        # 3. Retrieve system resources (RouterOS version, board)
        res_res = client.get_resource()
        version = "Unknown"
        board = "RouterBOARD"
        if res_res.success and isinstance(res_res.data, dict):
            version = res_res.data.get("version", "Unknown")
            board = res_res.data.get("board_name") or res_res.data.get("board", "RouterBOARD")

        # 4. Retrieve interfaces
        if_res = client.get_interfaces()
        interfaces = if_res.data if (if_res.success and isinstance(if_res.data, list)) else []

        # Find primary router MAC
        primary_mac = ""
        for iface in interfaces:
            mac = iface.get("mac") or iface.get("mac_address") or iface.get("mac-address")
            if mac:
                primary_mac = mac.upper()
                break

        # 5. Retrieve neighbors (MNDP / LLDP)
        nbr_res = client.get_neighbors()
        neighbors = nbr_res.data if (nbr_res.success and isinstance(nbr_res.data, list)) else []

        status = "SIMULATED" if is_simulated else "ONLINE"
        neighbor_discovery_enabled = len(neighbors) > 0 or len(interfaces) > 0

        return TopologyNode(
            node_id=node_id,
            identity=identity,
            host=host,
            mac_address=primary_mac,
            version=version,
            board=board,
            status=status,
            interfaces=interfaces,
            neighbors_raw=neighbors,
            is_isolated=False,  # Evaluated later in mapping
            neighbor_discovery_enabled=neighbor_discovery_enabled,
            is_managed=True,
        )

    def scan_topology(self, subnet_cidr: Optional[str] = None) -> TopologySnapshot:
        """
        Scans all configured routers concurrently, collects neighbor tables,
        and constructs the complete interconnected topology graph.
        """
        start_time = time.time()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. Concurrently poll all managed devices
        devices = list(settings.devices)
        nodes: Dict[str, TopologyNode] = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(devices) or 1, self.max_workers)) as executor:
            future_to_dev = {executor.submit(self.scan_single_device, dev): dev for dev in devices}
            for future in concurrent.futures.as_completed(future_to_dev):
                try:
                    node = future.result()
                    nodes[node.node_id] = node
                except Exception as e:
                    dev = future_to_dev[future]
                    logger.error("Error scanning device %s: %s", dev.name, e)
                    nodes[dev.name] = TopologyNode(
                        node_id=dev.name,
                        identity=dev.name,
                        host=dev.host,
                        status="OFFLINE",
                        is_managed=True,
                        is_isolated=True,
                    )

        # 2. Subnet Discovery for unconfigured routers (RFC 1918 safe)
        discovered_subnet_hosts: List[str] = []
        if subnet_cidr:
            clean_cidr = subnet_cidr.strip()
            try:
                net = ipaddress.ip_network(clean_cidr, strict=False)
                if net.is_private:
                    logger.info("Scanning subnet %s for additional active MikroTik routers...", clean_cidr)
                    raw_discovered = device_discovery.scan_subnet(clean_cidr, max_hosts=32)
                    for disc in raw_discovered:
                        ip_found = disc["ip"]
                        # Check if already in nodes
                        if not any(n.host == ip_found for n in nodes.values()):
                            discovered_subnet_hosts.append(ip_found)
                else:
                    logger.warning("Subnet %s is not private; skipping discovery scan for security.", clean_cidr)
            except Exception as e:
                logger.error("Invalid subnet CIDR %s: %s", subnet_cidr, e)

        # 3. Correlate and build links
        mapper = InterfaceMapper(nodes)
        links = mapper.build_links()

        # Update node isolation status
        connected_node_ids = set()
        for link in links:
            connected_node_ids.add(link.source)
            connected_node_ids.add(link.target)

        for nid, node in nodes.items():
            if node.status in ("ONLINE", "SIMULATED"):
                node.is_isolated = (nid not in connected_node_ids)
            else:
                node.is_isolated = True

        elapsed = round(time.time() - start_time, 2)
        metadata = {
            "scan_duration_sec": elapsed,
            "scanned_subnet": subnet_cidr or "",
            "unmanaged_subnet_hosts_found": discovered_subnet_hosts,
        }

        snapshot = TopologySnapshot(
            snapshot_id=int(time.time()),
            timestamp=timestamp,
            nodes=nodes,
            links=links,
            metadata=metadata,
        )

        # Save to database
        try:
            snapshot_db.save_snapshot(snapshot)
        except Exception as e:
            logger.error("Failed to save topology snapshot to database: %s", e)

        return snapshot


class InterfaceMapper:
    """Matches router neighbors, validates bidirectional links, and detects redundant connections."""

    def __init__(self, nodes: Dict[str, TopologyNode]):
        self.nodes = nodes
        # Index MAC addresses to router_id & interface
        self.mac_to_router: Dict[str, Tuple[str, str]] = {}
        self.ip_to_router: Dict[str, str] = {}
        self.identity_to_router: Dict[str, str] = {}

        self._build_indexes()

    def _build_indexes(self) -> None:
        for node_id, node in self.nodes.items():
            # Identity index
            self.identity_to_router[node.identity.lower()] = node_id
            self.identity_to_router[node_id.lower()] = node_id

            # Host IP index
            if node.host:
                self.ip_to_router[node.host] = node_id

            # MAC and IP index from interfaces
            for iface in node.interfaces:
                if_name = iface.get("name", "")
                mac = (iface.get("mac") or iface.get("mac_address") or iface.get("mac-address") or "").upper().strip()
                if mac:
                    self.mac_to_router[mac] = (node_id, if_name)

        # Index aliases and hosts from configured devices
        for dev in settings.devices:
            for alias in dev.aliases:
                self.identity_to_router[alias.lower()] = dev.name
            if dev.host:
                self.ip_to_router[dev.host] = dev.name

    def _find_target_router(self, neighbor: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """
        Attempts to resolve which managed router matches a neighbor entry.
        Returns (target_node_id, target_interface_name).
        """
        nbr_mac = (neighbor.get("mac_address") or neighbor.get("mac") or "").upper().strip()
        nbr_ip = neighbor.get("address") or neighbor.get("ip") or ""
        nbr_ident = neighbor.get("identity") or ""
        remote_if = neighbor.get("remote_interface") or neighbor.get("interface_name") or ""

        # 1. Exact MAC match on a known interface
        if nbr_mac and nbr_mac in self.mac_to_router:
            target_id, if_name = self.mac_to_router[nbr_mac]
            return target_id, (remote_if or if_name)

        # 2. Host IP match
        if nbr_ip and nbr_ip in self.ip_to_router:
            target_id = self.ip_to_router[nbr_ip]
            return target_id, remote_if

        # 3. Identity match
        if nbr_ident and nbr_ident.lower() in self.identity_to_router:
            target_id = self.identity_to_router[nbr_ident.lower()]
            return target_id, remote_if

        # 4. Partial identity alias check against configured device aliases
        if nbr_ident:
            for dev in settings.devices:
                for alias in dev.aliases:
                    if alias.lower() == nbr_ident.lower() or dev.name.lower() == nbr_ident.lower():
                        if dev.name in self.nodes:
                            return dev.name, remote_if

        return None, None

    def build_links(self) -> List[TopologyLink]:
        """Processes neighbor tables from all nodes to produce clean, validated links."""
        processed_pairs: Set[str] = set()
        raw_links: List[TopologyLink] = []
        links_between_pairs: Dict[Tuple[str, str], int] = {}

        for source_id, source_node in self.nodes.items():
            if source_node.status not in ("ONLINE", "SIMULATED"):
                continue

            for nbr in source_node.neighbors_raw:
                source_if = nbr.get("interface", "")
                proto = nbr.get("protocol") or "mndp"
                target_mac = (nbr.get("mac_address") or "").upper().strip()
                target_ip = nbr.get("address") or ""
                target_ident = nbr.get("identity") or ""

                target_id, target_if = self._find_target_router(nbr)

                if target_id and target_id != source_id:
                    # Known managed router
                    target_node = self.nodes.get(target_id)
                    target_display_if = target_if or "unknown_if"

                    # Check bidirectional confirmation: does target_node see source_node?
                    has_reverse = False
                    if target_node and target_node.status in ("ONLINE", "SIMULATED"):
                        for rev_nbr in target_node.neighbors_raw:
                            rev_mac = (rev_nbr.get("mac_address") or "").upper().strip()
                            rev_ip = rev_nbr.get("address") or ""
                            rev_ident = (rev_nbr.get("identity") or "").lower()

                            # Match source node by MAC, IP, or identity
                            if (
                                (source_node.mac_address and rev_mac == source_node.mac_address)
                                or (source_node.host and rev_ip == source_node.host)
                                or (rev_ident == source_node.identity.lower())
                            ):
                                has_reverse = True
                                if not target_if and rev_nbr.get("interface"):
                                    target_display_if = rev_nbr.get("interface")
                                break

                    # Canonical pair representation to prevent duplicate opposite link
                    pair_key = tuple(sorted([f"{source_id}:{source_if}", f"{target_id}:{target_display_if}"]))
                    if str(pair_key) in processed_pairs:
                        continue
                    processed_pairs.add(str(pair_key))

                    router_pair = tuple(sorted([source_id, target_id]))
                    links_between_pairs[router_pair] = links_between_pairs.get(router_pair, 0) + 1
                    is_redundant = links_between_pairs[router_pair] > 1

                    status = "VERIFIED" if has_reverse else "ESTIMATED_ONE_WAY"
                    link = TopologyLink(
                        source=source_id,
                        source_interface=source_if,
                        target=target_id,
                        target_interface=target_display_if,
                        target_identity=target_node.identity if target_node else target_ident,
                        target_ip=target_ip,
                        target_mac=target_mac,
                        protocol=proto,
                        verification_status=status,
                        is_redundant=is_redundant,
                    )
                    raw_links.append(link)

                elif target_ident or target_mac:
                    # External / unmanaged device (e.g. ISP router, switch, AP)
                    external_id = target_ident or f"Device-{target_mac[:8]}"
                    pair_key = (f"{source_id}:{source_if}", f"EXT:{external_id}")
                    if str(pair_key) in processed_pairs:
                        continue
                    processed_pairs.add(str(pair_key))

                    link = TopologyLink(
                        source=source_id,
                        source_interface=source_if,
                        target=external_id,
                        target_interface=nbr.get("remote_interface") or "port",
                        target_identity=external_id,
                        target_ip=target_ip,
                        target_mac=target_mac,
                        protocol=proto,
                        verification_status="UNVERIFIED",
                        is_redundant=False,
                    )
                    raw_links.append(link)

        return raw_links


# =============================================================================
# NETWORK GRAPH ANALYSIS (NETWORKX)
# =============================================================================

class NetworkTopologyGraph:
    """Graph model of the network using NetworkX."""

    def __init__(self, snapshot: TopologySnapshot):
        self.snapshot = snapshot
        self.graph = nx.MultiGraph() if nx else None
        if self.graph is not None:
            self._build_graph()

    def _build_graph(self) -> None:
        if self.graph is None:
            return
        # Add nodes
        for nid, node in self.snapshot.nodes.items():
            self.graph.add_node(
                nid,
                identity=node.identity,
                host=node.host,
                status=node.status,
                version=node.version,
                board=node.board,
                is_isolated=node.is_isolated,
                is_managed=node.is_managed,
            )

        # Add edges
        for link in self.snapshot.links:
            # Ensure target exists in graph even if external
            if not self.graph.has_node(link.target):
                self.graph.add_node(
                    link.target,
                    identity=link.target_identity or link.target,
                    host=link.target_ip,
                    status="EXTERNAL",
                    version="",
                    board="",
                    is_isolated=False,
                    is_managed=False,
                )

            self.graph.add_edge(
                link.source,
                link.target,
                key=link.link_id,
                source_interface=link.source_interface,
                target_interface=link.target_interface,
                protocol=link.protocol,
                status=link.verification_status,
                is_redundant=link.is_redundant,
            )

    def get_neighbors_for(self, router_id: str) -> List[Dict[str, Any]]:
        """Finds all connected adjacent routers and link details for a given router."""
        if self.graph is None:
            return []
        clean_id = router_id.lower().strip()
        matched_node = None
        for n, data in self.graph.nodes(data=True):
            if n.lower() == clean_id or data.get("identity", "").lower() == clean_id:
                matched_node = n
                break

        if not matched_node or not self.graph.has_node(matched_node):
            return []

        results = []
        for neighbor in self.graph.neighbors(matched_node):
            edge_dict = self.graph.get_edge_data(matched_node, neighbor)
            for _, attrs in edge_dict.items():
                results.append({
                    "neighbor_id": neighbor,
                    "neighbor_identity": self.graph.nodes[neighbor].get("identity", neighbor),
                    "neighbor_host": self.graph.nodes[neighbor].get("host", ""),
                    "neighbor_status": self.graph.nodes[neighbor].get("status", "UNKNOWN"),
                    "local_interface": attrs.get("source_interface") if attrs.get("source") == matched_node else attrs.get("target_interface", ""),
                    "remote_interface": attrs.get("target_interface") if attrs.get("source") == matched_node else attrs.get("source_interface", ""),
                    "protocol": attrs.get("protocol", "mndp"),
                    "verification_status": attrs.get("status", "UNVERIFIED"),
                    "is_redundant": attrs.get("is_redundant", False),
                })
        return results

    def find_path(self, source_id: str, target_id: str) -> Optional[List[str]]:
        """Finds shortest route hop path between two routers in topology."""
        if self.graph is None or not nx:
            return None
        try:
            return nx.shortest_path(self.graph, source=source_id, target=target_id)
        except Exception:
            return None


# =============================================================================
# TOPOLOGY VISUALIZER (TEXT, IMAGE, JSON)
# =============================================================================

class TopologyVisualizer:
    """Generates human-readable Telegram Markdown, graph diagrams (PNG), and JSON."""

    def __init__(self, snapshot: TopologySnapshot):
        self.snapshot = snapshot
        self.graph_model = NetworkTopologyGraph(snapshot)

    def render_text(self) -> str:
        """Generates a structured, handsome Telegram Markdown message."""
        s = self.snapshot
        lines = [
            "🌐 **PETA TOPOLOGI JARINGAN MIKROTIK**",
            f"📅 _Waktu Pemindaian: {s.timestamp}_",
            "═" * 32,
            f"📊 **Ringkasan Jaringan:**",
            f"• Total Router  : **{s.total_routers}** (🟢 {s.online_routers} Online | 🔴 {s.offline_routers} Offline)",
            f"• Hubungan Link : **{s.total_links}** (✅ {s.verified_links} Terverifikasi | ⚠️ {s.redundant_links} Redundan)",
        ]

        if s.isolated_routers:
            lines.append(f"• Router Terisolasi: `{', '.join(s.isolated_routers)}`")

        lines.append("")
        lines.append("📡 **KONEKSI ANTAR-ROUTER (INTER-ROUTER LINK):**")

        inter_links = s.inter_router_links
        if not inter_links:
            lines.append("_(Belum ada koneksi antar-router terkelola yang terverifikasi)_")
        else:
            for idx, link in enumerate(inter_links, 1):
                proto_badge = f"`[{link.protocol.upper()}]`"
                if link.verification_status == "VERIFIED":
                    status_badge = "✅"
                else:
                    status_badge = "🟡 (1-Arah)"

                redundant_str = " ⚠️ [REDUNDAN]" if link.is_redundant else ""
                src_name = self.snapshot.nodes[link.source].identity if link.source in self.snapshot.nodes else link.source
                tgt_name = self.snapshot.nodes[link.target].identity if link.target in self.snapshot.nodes else link.target_identity or link.target

                lines.append(
                    f"{idx}. {status_badge} **[{src_name}]** `{link.source_interface}` ──{proto_badge}── "
                    f"`{link.target_interface}` **[{tgt_name}]**{redundant_str}"
                )

        ext_links = s.external_links
        if ext_links:
            lines.append("")
            lines.append(f"🌐 **PERANGKAT EKSTERNAL / TETANGGA DETEKSI ({len(ext_links)}):**")
            if len(ext_links) <= 8:
                for el in ext_links:
                    src_name = self.snapshot.nodes[el.source].identity if el.source in self.snapshot.nodes else el.source
                    lines.append(f"• ⚪ **[{src_name}]** `{el.source_interface}` ──► `{el.target_identity or el.target}`")
            else:
                for el in ext_links[:5]:
                    src_name = self.snapshot.nodes[el.source].identity if el.source in self.snapshot.nodes else el.source
                    lines.append(f"• ⚪ **[{src_name}]** `{el.source_interface}` ──► `{el.target_identity or el.target}`")
                lines.append(f"• _...dan {len(ext_links) - 5} tetangga uplink/eksternal lainnya._")

        lines.append("")
        lines.append("🏢 **STATUS PERANGKAT ROUTER:**")
        for node in s.nodes.values():
            if node.status in ("ONLINE", "SIMULATED"):
                status_icon = "🟢" if node.status == "ONLINE" else "🟡 (Simulasi)"
                board_str = f" `{node.board}`" if node.board else ""
                lines.append(f"• {status_icon} **{node.identity}** (`{node.host}`){board_str} - RouterOS v{node.version}")
            else:
                lines.append(f"• 🔴 **{node.identity}** (`{node.host}`) - _OFFLINE / Tidak Terjangkau_")

        return "\n".join(lines)

    def render_image(self, output_path: Optional[str] = None) -> str:
        """
        Renders a high-quality network graph diagram using Matplotlib & NetworkX.
        Returns the absolute path of the generated image.
        """
        out_file = Path(output_path) if output_path else settings.database_path.parent / "topology.png"
        out_file.parent.mkdir(parents=True, exist_ok=True)

        if not HAS_MATPLOTLIB or not HAS_NETWORKX:
            logger.warning("matplotlib atau networkx belum terpasang; tidak dapat merender diagram gambar.")
            return str(out_file.resolve())

        # Build optimized sub-graph for visualization (managed nodes + top external neighbors)
        draw_g = nx.MultiGraph()
        for nid, n in self.snapshot.nodes.items():
            draw_g.add_node(
                nid,
                identity=n.identity,
                host=n.host,
                status=n.status,
                is_managed=True,
            )

        # Add inter-router links
        for link in self.snapshot.inter_router_links:
            draw_g.add_edge(
                link.source,
                link.target,
                key=link.link_id,
                source_interface=link.source_interface,
                target_interface=link.target_interface,
                status=link.verification_status,
                is_redundant=link.is_redundant,
            )

        # Include prominent external links (up to 4 to avoid cluttering)
        ext_links = self.snapshot.external_links
        if ext_links:
            for el in ext_links[:4]:
                ext_name = el.target_identity or el.target
                if not draw_g.has_node(ext_name):
                    draw_g.add_node(ext_name, identity=ext_name, host=el.target_ip, status="EXTERNAL", is_managed=False)
                draw_g.add_edge(
                    el.source,
                    ext_name,
                    key=el.link_id,
                    source_interface=el.source_interface,
                    target_interface=el.target_interface,
                    status="UNVERIFIED",
                    is_redundant=False,
                )
            if len(ext_links) > 4:
                agg_name = f"+{len(ext_links) - 4} Eksternal"
                draw_g.add_node(agg_name, identity=agg_name, host="", status="EXTERNAL", is_managed=False)
                first_src = ext_links[0].source
                draw_g.add_edge(first_src, agg_name, key="agg_ext", source_interface="uplink", target_interface="cloud", status="UNVERIFIED", is_redundant=False)

        fig, ax = plt.subplots(figsize=(10, 7), dpi=180)
        ax.set_facecolor("#1e222b")
        fig.patch.set_facecolor("#15181f")

        if len(draw_g.nodes) == 0:
            ax.text(0.5, 0.5, "Tidak ada data topologi jaringan", ha="center", va="center", color="white", fontsize=14)
            plt.savefig(str(out_file), bbox_inches="tight", facecolor=fig.get_facecolor())
            plt.close(fig)
            return str(out_file.resolve())

        # Layout without requiring scipy
        if len(draw_g.nodes) <= 4:
            pos = nx.spring_layout(draw_g, seed=42, k=2.0)
        else:
            pos = nx.spring_layout(draw_g, seed=42, k=1.3, iterations=60)

        # Color mapping for nodes
        node_colors = []
        for n, d in draw_g.nodes(data=True):
            status = d.get("status", "UNKNOWN")
            if status == "ONLINE":
                node_colors.append("#2ecc71")  # Green
            elif status == "SIMULATED":
                node_colors.append("#f1c40f")  # Yellow
            elif status == "OFFLINE":
                node_colors.append("#e74c3c")  # Red
            else:
                node_colors.append("#95a5a6")  # Gray (External)

        # Draw nodes
        nx.draw_networkx_nodes(
            draw_g,
            pos,
            ax=ax,
            node_color=node_colors,
            node_size=2400,
            edgecolors="#ffffff",
            linewidths=2.0,
        )

        # Node labels (Identity + IP)
        labels = {}
        for n, d in draw_g.nodes(data=True):
            ident = d.get("identity") or n
            host = d.get("host") or ""
            # Wrap long identities
            if len(ident) > 16:
                ident = ident[:14] + ".."
            labels[n] = f"{ident}\n{host}" if host else ident

        nx.draw_networkx_labels(
            draw_g,
            pos,
            labels=labels,
            ax=ax,
            font_size=8.5,
            font_color="#ffffff",
            font_weight="bold",
        )

        # Draw edges by category
        verified_edges = []
        one_way_edges = []
        redundant_edges = []
        ext_edges = []
        edge_labels = {}

        for u, v, k, d in draw_g.edges(data=True, keys=True):
            src_if = d.get("source_interface", "")
            tgt_if = d.get("target_interface", "")
            edge_labels[(u, v)] = f"{src_if} ↔ {tgt_if}"

            if d.get("is_redundant"):
                redundant_edges.append((u, v))
            elif d.get("status") == "VERIFIED":
                verified_edges.append((u, v))
            elif d.get("status") == "ESTIMATED_ONE_WAY":
                one_way_edges.append((u, v))
            else:
                ext_edges.append((u, v))

        if verified_edges:
            nx.draw_networkx_edges(draw_g, pos, edgelist=verified_edges, ax=ax, edge_color="#00d2d3", width=2.5, style="solid", alpha=0.9)
        if one_way_edges:
            nx.draw_networkx_edges(draw_g, pos, edgelist=one_way_edges, ax=ax, edge_color="#ff9f43", width=2.0, style="dashed", alpha=0.8)
        if redundant_edges:
            nx.draw_networkx_edges(draw_g, pos, edgelist=redundant_edges, ax=ax, edge_color="#ff5252", width=2.0, style="dotted", alpha=0.85)
        if ext_edges:
            nx.draw_networkx_edges(draw_g, pos, edgelist=ext_edges, ax=ax, edge_color="#636e72", width=1.5, style="dotted", alpha=0.7)

        # Draw edge labels
        nx.draw_networkx_edge_labels(
            draw_g,
            pos,
            edge_labels=edge_labels,
            ax=ax,
            font_size=7,
            font_color="#dfe6e9",
            bbox=dict(boxstyle="round,pad=0.2", fc="#2d3436", ec="none", alpha=0.8),
        )

        s = self.snapshot
        ax.set_title(
            f"MIKROTIK NETWORK TOPOLOGY MAP\n"
            f"{s.total_routers} Routers ({s.online_routers} Online) | {s.total_links} Links ({s.verified_links} Verified) | {s.timestamp}",
            fontsize=11,
            color="#ffffff",
            fontweight="bold",
            pad=15,
        )

        ax.axis("off")
        plt.tight_layout()
        plt.savefig(str(out_file), bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=180)
        plt.close(fig)

        return str(out_file.resolve())

    def render_json(self) -> Dict[str, Any]:
        """Returns complete JSON dictionary representation."""
        return self.snapshot.to_dict()


# =============================================================================
# SQLITE SNAPSHOT DATABASE & TOPOLOGY CHANGE DETECTION
# =============================================================================

class TopologyDatabase:
    """Stores topology history and detects changes between snapshots."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.database_path
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS topology_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    total_routers INTEGER DEFAULT 0,
                    online_routers INTEGER DEFAULT 0,
                    total_links INTEGER DEFAULT 0,
                    verified_links INTEGER DEFAULT 0,
                    raw_json TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_topo_time ON topology_snapshots(timestamp)")
            conn.commit()

    def save_snapshot(self, snapshot: TopologySnapshot) -> int:
        """Persists snapshot into SQLite database."""
        raw_json_str = json.dumps(snapshot.to_dict(), default=str)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO topology_snapshots (
                    timestamp, total_routers, online_routers, total_links, verified_links, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                snapshot.timestamp,
                snapshot.total_routers,
                snapshot.online_routers,
                snapshot.total_links,
                snapshot.verified_links,
                raw_json_str,
            ))
            conn.commit()
            snapshot.snapshot_id = cursor.lastrowid
            return cursor.lastrowid

    def get_latest_snapshot(self) -> Optional[TopologySnapshot]:
        """Retrieves the most recent topology snapshot from database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, timestamp, raw_json FROM topology_snapshots
                ORDER BY id DESC LIMIT 1
            """)
            row = cursor.fetchone()
            if row:
                data = json.loads(row[2])
                data["snapshot_id"] = row[0]
                return TopologySnapshot.from_dict(data)
        return None

    def get_snapshot_by_id(self, snapshot_id: int) -> Optional[TopologySnapshot]:
        """Retrieves a specific topology snapshot by ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, timestamp, raw_json FROM topology_snapshots WHERE id = ?
            """, (snapshot_id,))
            row = cursor.fetchone()
            if row:
                data = json.loads(row[2])
                data["snapshot_id"] = row[0]
                return TopologySnapshot.from_dict(data)
        return None

    def list_snapshots(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Returns historical snapshots summary."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, timestamp, total_routers, online_routers, total_links, verified_links
                FROM topology_snapshots ORDER BY id DESC LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "timestamp": r[1],
                    "total_routers": r[2],
                    "online_routers": r[3],
                    "total_links": r[4],
                    "verified_links": r[5],
                }
                for r in rows
            ]

    def compare_snapshots(
        self,
        old_id: Optional[int] = None,
        new_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Compares two snapshots to detect additions, removals, link breaks,
        interface movements, and offline routers.
        """
        if new_id and old_id:
            snap_new = self.get_snapshot_by_id(new_id)
            snap_old = self.get_snapshot_by_id(old_id)
        else:
            # Default to the two most recent snapshots
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM topology_snapshots ORDER BY id DESC LIMIT 2")
                rows = cursor.fetchall()
                if len(rows) < 2:
                    return {
                        "has_changes": False,
                        "message": "Belum ada riwayat snapshot sebelumnya untuk dibandingkan. Lakukan minimal 2 kali scan.",
                        "changes": {},
                    }
                snap_new = self.get_snapshot_by_id(rows[0][0])
                snap_old = self.get_snapshot_by_id(rows[1][0])

        if not snap_new or not snap_old:
            return {
                "has_changes": False,
                "message": "Snapshot yang dipilih tidak ditemukan dalam database.",
                "changes": {},
            }

        old_nodes = snap_old.nodes
        new_nodes = snap_new.nodes

        old_links = {l.link_id: l for l in snap_old.links}
        new_links = {l.link_id: l for l in snap_new.links}

        # 1. Router Additions and Removals
        added_routers = [
            {"id": nid, "identity": node.identity, "host": node.host}
            for nid, node in new_nodes.items() if nid not in old_nodes
        ]
        removed_routers = [
            {"id": nid, "identity": node.identity, "host": node.host}
            for nid, node in old_nodes.items() if nid not in new_nodes
        ]

        # 2. Router Status Changes (Online <-> Offline)
        status_changes = []
        for nid, new_node in new_nodes.items():
            if nid in old_nodes:
                old_node = old_nodes[nid]
                if old_node.status != new_node.status:
                    status_changes.append({
                        "id": nid,
                        "identity": new_node.identity,
                        "old_status": old_node.status,
                        "new_status": new_node.status,
                    })

        # 3. New and Broken Links
        added_links = [
            l.to_dict() for lid, l in new_links.items() if lid not in old_links
        ]
        broken_links = [
            l.to_dict() for lid, l in old_links.items() if lid not in new_links
        ]

        # 4. Interface Changes (Same pair, different interface)
        interface_changes = []
        old_router_pairs: Dict[Tuple[str, str], TopologyLink] = {
            tuple(sorted([l.source, l.target])): l for l in snap_old.links
        }
        for l in snap_new.links:
            pair = tuple(sorted([l.source, l.target]))
            if pair in old_router_pairs:
                old_l = old_router_pairs[pair]
                if (
                    old_l.source_interface != l.source_interface
                    or old_l.target_interface != l.target_interface
                ):
                    interface_changes.append({
                        "router_a": l.source,
                        "router_b": l.target,
                        "old_source_if": old_l.source_interface,
                        "new_source_if": l.source_interface,
                        "old_target_if": old_l.target_interface,
                        "new_target_if": l.target_interface,
                    })

        has_changes = bool(
            added_routers or removed_routers or status_changes or added_links or broken_links or interface_changes
        )

        # Build natural language summary
        summary_lines = [
            "🔄 **HASIL PERBANDINGAN PERUBAHAN TOPOLOGI JARINGAN**",
            f"📅 Snapshot Lama: `{snap_old.timestamp}`",
            f"📅 Snapshot Baru: `{snap_new.timestamp}`",
            "═" * 32,
        ]

        if not has_changes:
            summary_lines.append("✅ **Tidak ada perubahan topologi:** Seluruh router dan link koneksi stabil.")
        else:
            if added_routers:
                summary_lines.append(f"🟢 **Router Baru Terdeteksi ({len(added_routers)}):**")
                for r in added_routers:
                    summary_lines.append(f"  • `{r['identity']}` ({r['host']})")

            if removed_routers:
                summary_lines.append(f"🔴 **Router Tidak Ditemukan Lagi ({len(removed_routers)}):**")
                for r in removed_routers:
                    summary_lines.append(f"  • `{r['identity']}` ({r['host']})")

            if status_changes:
                summary_lines.append(f"⚠️ **Perubahan Status Router ({len(status_changes)}):**")
                for sc in status_changes:
                    summary_lines.append(f"  • `{sc['identity']}`: `{sc['old_status']}` ➔ **{sc['new_status']}**")

            if added_links:
                summary_lines.append(f"🔗 **Link Baru Terhubung ({len(added_links)}):**")
                for al in added_links:
                    summary_lines.append(f"  • `{al['source']}` ({al['source_interface']}) ➔ `{al['target']}` ({al['target_interface']})")

            if broken_links:
                summary_lines.append(f"❌ **Link Terputus ({len(broken_links)}):**")
                for bl in broken_links:
                    summary_lines.append(f"  • `{bl['source']}` ({bl['source_interface']}) ⇹ `{bl['target']}` ({bl['target_interface']})")

            if interface_changes:
                summary_lines.append(f"🔀 **Perubahan Port Interface ({len(interface_changes)}):**")
                for ic in interface_changes:
                    summary_lines.append(
                        f"  • `{ic['router_a']}` ↔ `{ic['router_b']}` berpindah dari "
                        f"({ic['old_source_if']} ↔ {ic['old_target_if']}) ke "
                        f"({ic['new_source_if']} ↔ {ic['new_target_if']})"
                    )

        return {
            "has_changes": has_changes,
            "old_snapshot_id": snap_old.snapshot_id,
            "new_snapshot_id": snap_new.snapshot_id,
            "old_timestamp": snap_old.timestamp,
            "new_timestamp": snap_new.timestamp,
            "changes": {
                "added_routers": added_routers,
                "removed_routers": removed_routers,
                "status_changes": status_changes,
                "added_links": added_links,
                "broken_links": broken_links,
                "interface_changes": interface_changes,
            },
            "summary_text": "\n".join(summary_lines),
        }


# Singleton instances
topology_scanner = TopologyScanner()
snapshot_db = TopologyDatabase()
