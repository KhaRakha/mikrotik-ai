"""
Unit and Integration Tests for MikroTik Network Topology Discovery and Mapping.
Tests Models, InterfaceMapper, Graph, Visualizer, SQLite Database, Tools, Agent, and Bot Handlers.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from config.settings import DeviceConfig, settings
from core.agent import hermes_agent
from core.security import security_manager
from core.topology import (
    InterfaceMapper,
    NetworkTopologyGraph,
    TopologyDatabase,
    TopologyLink,
    TopologyNode,
    TopologyScanner,
    TopologySnapshot,
    TopologyVisualizer,
)
from mikrotik.mock_client import MockMikrotikClient
from mikrotik.tools import (
    TOOL_REGISTRY,
    compare_topology_snapshots,
    generate_topology_diagram,
    get_connected_interfaces,
    get_network_topology,
    get_router_neighbors,
    scan_network_topology,
)
from bot.handlers import topology_command


class TestTopologyModule(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_topology.db"
        self.test_db = TopologyDatabase(self.db_path)

        # Configure mock devices in settings
        from mikrotik.manager import device_manager
        device_manager._clients.clear()
        device_manager._status_cache.clear()
        device_manager.mock_client = MockMikrotikClient()

        self.dev_r1 = DeviceConfig({
            "id": "R1_Utama",
            "name": "Kantor Utama",
            "host": "10.20.33.240",
            "protocol": "mock",
            "aliases": ["r1", "utama", "kantor utama"],
        })
        self.dev_r2 = DeviceConfig({
            "id": "R2_Cabang",
            "name": "Kantor Cabang",
            "host": "192.168.88.1",
            "protocol": "mock",
            "aliases": ["r2", "cabang", "kantor cabang"],
        })

        self._orig_devices = list(settings.devices)
        settings.devices.clear()
        settings.devices.extend([self.dev_r1, self.dev_r2])

        self.admin_id = settings.admin_telegram_ids[0] if settings.admin_telegram_ids else 5605485301
        self.viewer_id = 999123
        if self.viewer_id not in settings.viewer_telegram_ids:
            settings.viewer_telegram_ids.append(self.viewer_id)
        if self.viewer_id not in settings.allowed_telegram_ids:
            settings.allowed_telegram_ids.append(self.viewer_id)
        if self.viewer_id in settings.admin_telegram_ids:
            settings.admin_telegram_ids.remove(self.viewer_id)

        self._orig_google_key = hermes_agent.google_api_key
        self._orig_openai_key = hermes_agent.openai_api_key
        hermes_agent.google_api_key = ""
        hermes_agent.openai_api_key = ""

    def tearDown(self):
        settings.devices.clear()
        settings.devices.extend(self._orig_devices)
        hermes_agent.google_api_key = self._orig_google_key
        hermes_agent.openai_api_key = self._orig_openai_key
        self.temp_dir.cleanup()

    # =========================================================================
    # 1. MODELS TEST
    # =========================================================================
    def test_topology_node_and_link_serialization(self):
        node = TopologyNode(
            node_id="R1",
            identity="Router-1",
            host="192.168.1.1",
            mac_address="00:11:22:33:44:55",
            version="7.15",
            board="hEX",
            status="ONLINE",
            interfaces=[{"name": "ether1", "mac": "00:11:22:33:44:55"}],
            is_isolated=False,
        )
        d = node.to_dict()
        self.assertEqual(d["node_id"], "R1")
        self.assertEqual(d["identity"], "Router-1")
        self.assertEqual(d["status"], "ONLINE")

        restored_node = TopologyNode.from_dict(d)
        self.assertEqual(restored_node.node_id, "R1")
        self.assertEqual(restored_node.mac_address, "00:11:22:33:44:55")

        link = TopologyLink(
            source="R1",
            source_interface="ether2",
            target="R2",
            target_interface="ether1",
            protocol="mndp",
            verification_status="VERIFIED",
            is_redundant=False,
        )
        self.assertEqual(link.link_id, "R1:ether2<->R2:ether1")
        link_dict = link.to_dict()
        self.assertEqual(link_dict["source"], "R1")
        self.assertEqual(link_dict["verification_status"], "VERIFIED")

        restored_link = TopologyLink.from_dict(link_dict)
        self.assertEqual(restored_link.link_id, link.link_id)

    def test_topology_snapshot_properties(self):
        n1 = TopologyNode(node_id="R1", identity="R1", host="10.0.0.1", status="ONLINE")
        n2 = TopologyNode(node_id="R2", identity="R2", host="10.0.0.2", status="ONLINE")
        n3 = TopologyNode(node_id="R3", identity="R3", host="10.0.0.3", status="OFFLINE", is_isolated=True)

        l1 = TopologyLink(source="R1", source_interface="ether1", target="R2", target_interface="ether1", verification_status="VERIFIED")
        l2 = TopologyLink(source="R1", source_interface="ether2", target="R2", target_interface="ether2", verification_status="VERIFIED", is_redundant=True)
        l3 = TopologyLink(source="R1", source_interface="ether3", target="ISP_Modem", target_interface="LAN1", verification_status="UNVERIFIED")

        snapshot = TopologySnapshot(
            snapshot_id=1,
            timestamp="2026-11-12 12:00:00",
            nodes={"R1": n1, "R2": n2, "R3": n3},
            links=[l1, l2, l3],
        )

        self.assertEqual(snapshot.total_routers, 3)
        self.assertEqual(snapshot.online_routers, 2)
        self.assertEqual(snapshot.offline_routers, 1)
        self.assertEqual(snapshot.total_links, 3)
        self.assertEqual(snapshot.verified_links, 2)
        self.assertEqual(snapshot.redundant_links, 1)
        self.assertEqual(len(snapshot.inter_router_links), 2)
        self.assertEqual(len(snapshot.external_links), 1)
        self.assertIn("R3", snapshot.isolated_routers)

        snap_dict = snapshot.to_dict()
        restored_snap = TopologySnapshot.from_dict(snap_dict)
        self.assertEqual(restored_snap.total_routers, 3)
        self.assertEqual(restored_snap.online_routers, 2)

    # =========================================================================
    # 2. INTERFACE MAPPER & CORRELATION TEST
    # =========================================================================
    def test_interface_mapper_bidirectional_and_redundant(self):
        # Router A sees Router B on ether2 -> ether1
        node_a = TopologyNode(
            node_id="RA",
            identity="Router-A",
            host="192.168.1.1",
            mac_address="AA:AA:AA:AA:AA:AA",
            interfaces=[
                {"name": "ether1", "mac": "AA:AA:AA:AA:AA:01"},
                {"name": "ether2", "mac": "AA:AA:AA:AA:AA:02"},
                {"name": "ether3", "mac": "AA:AA:AA:AA:AA:03"},
            ],
            neighbors_raw=[
                {
                    "interface": "ether2",
                    "address": "192.168.1.2",
                    "mac_address": "BB:BB:BB:BB:BB:01",
                    "identity": "Router-B",
                    "remote_interface": "ether1",
                    "protocol": "mndp",
                },
                {
                    "interface": "ether3",
                    "address": "192.168.1.2",
                    "mac_address": "BB:BB:BB:BB:BB:02",
                    "identity": "Router-B",
                    "remote_interface": "ether2",
                    "protocol": "mndp",
                },
                {
                    "interface": "ether1",
                    "address": "10.0.0.1",
                    "mac_address": "CC:CC:CC:CC:CC:CC",
                    "identity": "Indihome_ONT",
                    "remote_interface": "LAN1",
                    "protocol": "lldp",
                },
            ],
            status="ONLINE",
        )

        # Router B sees Router A on ether1 -> ether2
        node_b = TopologyNode(
            node_id="RB",
            identity="Router-B",
            host="192.168.1.2",
            mac_address="BB:BB:BB:BB:BB:BB",
            interfaces=[
                {"name": "ether1", "mac": "BB:BB:BB:BB:BB:01"},
                {"name": "ether2", "mac": "BB:BB:BB:BB:BB:02"},
            ],
            neighbors_raw=[
                {
                    "interface": "ether1",
                    "address": "192.168.1.1",
                    "mac_address": "AA:AA:AA:AA:AA:02",
                    "identity": "Router-A",
                    "remote_interface": "ether2",
                    "protocol": "mndp",
                },
            ],
            status="ONLINE",
        )

        mapper = InterfaceMapper({"RA": node_a, "RB": node_b})
        links = mapper.build_links()

        # Check links
        inter_links = [l for l in links if l.verification_status != "UNVERIFIED"]
        self.assertEqual(len(inter_links), 2)  # 2 cables between RA and RB

        # One should be verified, one is redundant
        has_verified = any(l.verification_status == "VERIFIED" for l in inter_links)
        has_redundant = any(l.is_redundant for l in inter_links)
        self.assertTrue(has_verified)
        self.assertTrue(has_redundant)

        # External ONT link check
        ext_links = [l for l in links if l.verification_status == "UNVERIFIED"]
        self.assertEqual(len(ext_links), 1)
        self.assertEqual(ext_links[0].target, "Indihome_ONT")

    # =========================================================================
    # 3. GRAPH MODEL (NETWORKX) TEST
    # =========================================================================
    def test_network_topology_graph(self):
        n1 = TopologyNode(node_id="R1", identity="Kantor Utama", host="10.20.33.240", status="ONLINE")
        n2 = TopologyNode(node_id="R2", identity="Kantor Cabang", host="192.168.88.1", status="ONLINE")
        n3 = TopologyNode(node_id="R3", identity="Lab", host="192.168.10.1", status="ONLINE")

        l1 = TopologyLink(source="R1", source_interface="ether2", target="R2", target_interface="ether1", protocol="mndp", verification_status="VERIFIED")
        l2 = TopologyLink(source="R2", source_interface="ether3", target="R3", target_interface="ether1", protocol="mndp", verification_status="VERIFIED")

        snapshot = TopologySnapshot(
            snapshot_id=1,
            timestamp="2026-11-12 12:00:00",
            nodes={"R1": n1, "R2": n2, "R3": n3},
            links=[l1, l2],
        )

        graph = NetworkTopologyGraph(snapshot)
        r2_neighbors = graph.get_neighbors_for("Kantor Cabang")
        self.assertEqual(len(r2_neighbors), 2)
        neighbor_names = [n["neighbor_identity"] for n in r2_neighbors]
        self.assertIn("Kantor Utama", neighbor_names)
        self.assertIn("Lab", neighbor_names)

        # Path finding from R1 to R3 through R2
        path = graph.find_path("R1", "R3")
        self.assertEqual(path, ["R1", "R2", "R3"])

    # =========================================================================
    # 4. VISUALIZER (TEXT & IMAGE & JSON) TEST
    # =========================================================================
    def test_topology_visualizer_text_and_image(self):
        n1 = TopologyNode(node_id="Kantor Utama", identity="Kantor Utama", host="10.20.33.240", version="7.15.2", status="ONLINE")
        n2 = TopologyNode(node_id="Kantor Cabang", identity="Kantor Cabang", host="192.168.88.1", version="7.15.2", status="ONLINE")
        l1 = TopologyLink(source="Kantor Utama", source_interface="ether2", target="Kantor Cabang", target_interface="ether1", verification_status="VERIFIED")

        snapshot = TopologySnapshot(
            snapshot_id=1,
            timestamp="2026-11-12 12:00:00",
            nodes={"Kantor Utama": n1, "Kantor Cabang": n2},
            links=[l1],
        )

        vis = TopologyVisualizer(snapshot)
        text = vis.render_text()
        self.assertIn("PETA TOPOLOGI JARINGAN MIKROTIK", text)
        self.assertIn("Kantor Utama", text)
        self.assertIn("Kantor Cabang", text)
        self.assertIn("ether2", text)

        out_img = Path(self.temp_dir.name) / "test_topology.png"
        img_path = vis.render_image(str(out_img))
        self.assertTrue(os.path.exists(img_path))
        self.assertGreater(os.path.getsize(img_path), 1000)

        json_dict = vis.render_json()
        self.assertEqual(json_dict["snapshot_id"], 1)

    # =========================================================================
    # 5. SQLITE DATABASE & CHANGE DETECTION TEST
    # =========================================================================
    def test_database_snapshots_and_compare_diff(self):
        # Snap 1
        n1 = TopologyNode(node_id="R1", identity="R1", host="10.0.0.1", status="ONLINE")
        n2 = TopologyNode(node_id="R2", identity="R2", host="10.0.0.2", status="ONLINE")
        l1 = TopologyLink(source="R1", source_interface="ether1", target="R2", target_interface="ether1", verification_status="VERIFIED")

        snap1 = TopologySnapshot(snapshot_id=1, timestamp="2026-11-12 10:00:00", nodes={"R1": n1, "R2": n2}, links=[l1])
        id1 = self.test_db.save_snapshot(snap1)

        # Snap 2: R2 went OFFLINE, R3 added, link R1-R2 broken, link R1-R3 added
        n1_v2 = TopologyNode(node_id="R1", identity="R1", host="10.0.0.1", status="ONLINE")
        n2_v2 = TopologyNode(node_id="R2", identity="R2", host="10.0.0.2", status="OFFLINE")
        n3 = TopologyNode(node_id="R3", identity="R3", host="10.0.0.3", status="ONLINE")
        l2 = TopologyLink(source="R1", source_interface="ether2", target="R3", target_interface="ether1", verification_status="VERIFIED")

        snap2 = TopologySnapshot(snapshot_id=2, timestamp="2026-11-12 11:00:00", nodes={"R1": n1_v2, "R2": n2_v2, "R3": n3}, links=[l2])
        id2 = self.test_db.save_snapshot(snap2)

        # Test latest retrieval
        latest = self.test_db.get_latest_snapshot()
        self.assertIsNotNone(latest)
        self.assertEqual(latest.total_routers, 3)

        # Test diff comparison
        diff = self.test_db.compare_snapshots(old_id=id1, new_id=id2)
        self.assertTrue(diff["has_changes"])
        changes = diff["changes"]

        # R3 was added
        self.assertEqual(len(changes["added_routers"]), 1)
        self.assertEqual(changes["added_routers"][0]["id"], "R3")

        # R2 changed to OFFLINE
        self.assertEqual(len(changes["status_changes"]), 1)
        self.assertEqual(changes["status_changes"][0]["id"], "R2")
        self.assertEqual(changes["status_changes"][0]["new_status"], "OFFLINE")

        # Link R1-R2 broken, Link R1-R3 added
        self.assertEqual(len(changes["broken_links"]), 1)
        self.assertEqual(len(changes["added_links"]), 1)

        self.assertIn("Router Baru Terdeteksi", diff["summary_text"])
        self.assertIn("Perubahan Status Router", diff["summary_text"])

    # =========================================================================
    # 6. MIKROTIK TOOLS API TEST
    # =========================================================================
    def test_tools_topology_functions(self):
        # 1. Scan topology
        scan_res = scan_network_topology(force_refresh=True)
        self.assertTrue(scan_res["success"])
        self.assertGreaterEqual(scan_res["summary"]["total_routers"], 2)

        # 2. Get network topology (summary format)
        topo_summary = get_network_topology(format="summary")
        self.assertTrue(topo_summary["success"])
        self.assertIn("PETA TOPOLOGI JARINGAN", topo_summary["text"])

        # 3. Get network topology (json format)
        topo_json = get_network_topology(format="json")
        self.assertTrue(topo_json["success"])
        self.assertIn("nodes", topo_json["data"])

        # 4. Get router neighbors
        nbr_res = get_router_neighbors(device="Kantor Utama")
        self.assertTrue(nbr_res["success"])
        self.assertIn("neighbors", nbr_res)

        # 5. Connected interfaces
        conn_res = get_connected_interfaces(device="Kantor Utama", interface="ether2")
        self.assertTrue(conn_res["success"])

        # 6. Compare snapshots
        comp_res = compare_topology_snapshots()
        self.assertTrue(comp_res["success"])

        # 7. Generate diagram image
        diag_res = generate_topology_diagram(filename="test_out_diagram.png")
        self.assertTrue(diag_res["success"])
        self.assertTrue(os.path.exists(diag_res["image_path"]))

    # =========================================================================
    # 7. HERMES AGENT HEURISTICS TEST
    # =========================================================================
    def test_agent_topology_natural_queries(self):
        # Full topology map
        res1 = hermes_agent.process_message(user_id=self.admin_id, username="Admin", text="Coba cek topologi seluruh jaringan")
        self.assertIn("PETA TOPOLOGI JARINGAN", res1["reply"])

        # Visual diagram
        res2 = hermes_agent.process_message(user_id=self.admin_id, username="Admin", text="Tolong buatkan diagram topologi jaringan")
        self.assertIn("Topologi", res2["reply"])
        self.assertIsNotNone(res2.get("image_path"))
        if res2.get("image_path"):
            self.assertTrue(os.path.exists(res2["image_path"]))

        # Router neighbors
        res3 = hermes_agent.process_message(user_id=self.admin_id, username="Admin", text="Siapa tetangga router kantor utama")
        self.assertIn("Daftar Tetangga", res3["reply"])

        # Interface connection query
        res4 = hermes_agent.process_message(user_id=self.admin_id, username="Admin", text="Interface ether2 kantor utama nyambung kemana")
        self.assertTrue(len(res4["reply"]) > 10)

        # Topology comparison
        res5 = hermes_agent.process_message(user_id=self.admin_id, username="Admin", text="Bandingkan topologi sekarang dengan kemarin, ada link putus?")
        self.assertIn("HASIL PERBANDINGAN", res5["reply"])

    # =========================================================================
    # 8. TELEGRAM BOT TOPOLOGY COMMAND TEST
    # =========================================================================
    async def test_bot_topology_command(self):
        update = MagicMock()
        update.effective_user.id = self.admin_id
        update.message.reply_text = AsyncMock()
        update.message.reply_photo = AsyncMock()
        update.message.chat.send_action = AsyncMock()

        # 1. /topology (summary)
        context = MagicMock()
        context.args = []
        await topology_command(update, context)
        update.message.reply_text.assert_called()

        # 2. /topology image
        context.args = ["image"]
        await topology_command(update, context)
        # Should attempt reply_photo
        update.message.reply_photo.assert_called()

        # 3. /topology diff
        context.args = ["diff"]
        await topology_command(update, context)
        update.message.reply_text.assert_called()

        # 4. Unauthorized user test
        unauth_update = MagicMock()
        unauth_update.effective_user.id = 111222333  # Not in allowed IDs
        unauth_update.message.reply_text = AsyncMock()
        await topology_command(unauth_update, context)
        self.assertIn("Akses Ditolak", unauth_update.message.reply_text.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
