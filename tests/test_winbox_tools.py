"""
Unit tests for Winbox Tools and System Menu features.
Validates functionality across Mock client, Security Manager, and Hermes Agent.
"""

from __future__ import annotations

import unittest
from config.settings import DeviceConfig, settings
from core.agent import hermes_agent
from core.confirmation import confirmation_manager
from core.security import security_manager
from mikrotik.mock_client import MockMikrotikClient
from mikrotik.tools import (
    TOOL_REGISTRY,
    add_netwatch,
    create_system_user,
    delete_system_user,
    get_clock_sntp,
    get_cpu_profile,
    get_identity,
    get_netwatch,
    get_packages,
    get_packet_sniffer,
    get_resource,
    get_routerboard,
    get_system_users,
    get_traffic_monitor,
    send_router_email,
    set_clock_timezone,
    set_identity,
    sniff_packets,
    system_reboot,
    system_shutdown,
    tool_bandwidth_test,
    tool_ip_scan,
    tool_ping,
    tool_torch,
    tool_traceroute,
)


class TestWinboxTools(unittest.TestCase):
    def setUp(self):
        self.device = "mock_demo"
        self.mock_client = MockMikrotikClient()
        self.mock_dev = DeviceConfig({"id": "mock_demo", "name": "mock_demo", "host": "127.0.0.1", "protocol": "mock"})
        if not any(d.name == "mock_demo" for d in settings.devices):
            settings.devices.append(self.mock_dev)
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
        hermes_agent.google_api_key = self._orig_google_key
        hermes_agent.openai_api_key = self._orig_openai_key
        if hasattr(self, "mock_dev") and self.mock_dev in settings.devices:
            settings.devices.remove(self.mock_dev)

    # =========================================================================
    # TOOLS MENU TESTS
    # =========================================================================
    def test_tool_ping(self):
        res = tool_ping(device=self.device, target="8.8.8.8", count=4)
        self.assertTrue(res.get("success"))
        self.assertIn("packet_loss_percent", res.get("data", {}))

    def test_tool_traceroute(self):
        res = tool_traceroute(device=self.device, target="8.8.8.8", count=4)
        self.assertTrue(res.get("success"))
        hops = res.get("data", {}).get("hops", [])
        self.assertGreater(len(hops), 0)
        self.assertEqual(hops[-1].get("address"), "8.8.8.8")

    def test_tool_torch(self):
        res = tool_torch(device=self.device, interface="ether1-WAN", duration=3)
        self.assertTrue(res.get("success"))
        streams = res.get("data", {}).get("active_streams", [])
        self.assertGreater(len(streams), 0)

    def test_tool_bandwidth_test(self):
        res = tool_bandwidth_test(device=self.device, target="10.20.33.1")
        self.assertTrue(res.get("success"))
        self.assertGreater(res.get("data", {}).get("rx_throughput_mbps", 0), 0)

    def test_netwatch_flow(self):
        # 1. Get netwatch
        res_get = get_netwatch(device=self.device)
        self.assertTrue(res_get.get("success"))
        initial_count = len(res_get.get("data", []))

        # 2. Add netwatch
        res_add = add_netwatch(device=self.device, host="1.1.1.1", interval="1m", timeout="1000ms")
        self.assertTrue(res_add.get("success"))

        # 3. Verify added
        res_get2 = get_netwatch(device=self.device)
        self.assertEqual(len(res_get2.get("data", [])), initial_count + 1)

    def test_tool_ip_scan(self):
        res = tool_ip_scan(device=self.device, interface="ether1-WAN")
        self.assertTrue(res.get("success"))
        self.assertGreater(len(res.get("data", {}).get("discovered", [])), 0)

    def test_get_cpu_profile(self):
        res = get_cpu_profile(device=self.device, duration=3)
        self.assertTrue(res.get("success"))
        self.assertIn("cpu_usage", res.get("data", {}))

    def test_send_router_email(self):
        res = send_router_email(device=self.device, to="noc@pti.ac.id", subject="Test", body="Alert body")
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("data", {}).get("status"), "SENT")

    def test_packet_sniffer(self):
        res_status = get_packet_sniffer(device=self.device)
        self.assertTrue(res_status.get("success"))

        res_sniff = sniff_packets(device=self.device, interface="ether1-WAN", count=5)
        self.assertTrue(res_sniff.get("success"))
        self.assertGreater(len(res_sniff.get("data", {}).get("packets", [])), 0)

    def test_get_traffic_monitor(self):
        res = get_traffic_monitor(device=self.device)
        self.assertTrue(res.get("success"))
        self.assertGreater(len(res.get("data", [])), 0)

    # =========================================================================
    # SYSTEM MENU TESTS
    # =========================================================================
    def test_get_resource_enhanced(self):
        res = get_resource(device=self.device)
        self.assertTrue(res.get("success"))
        data = res.get("data", {})
        self.assertIn("cpu_load", data)
        self.assertIn("free_hdd_space_mb", data)

    def test_identity_get_and_set(self):
        res_get = get_identity(device=self.device)
        self.assertTrue(res_get.get("success"))

        res_set = set_identity(device=self.device, name="Router-PTI-Utama")
        self.assertTrue(res_set.get("success"))

        res_get_new = get_identity(device=self.device)
        self.assertEqual((res_get_new.get("data") or {}).get("name"), "Router-PTI-Utama")

    def test_system_users_flow(self):
        res_get = get_system_users(device=self.device)
        self.assertTrue(res_get.get("success"))
        initial_count = len(res_get.get("data", []))

        # Create user
        res_create = create_system_user(device=self.device, name="noc_user", group="read", password="secretpassword")
        self.assertTrue(res_create.get("success"))

        # Verify exists
        res_get2 = get_system_users(device=self.device)
        self.assertEqual(len(res_get2.get("data", [])), initial_count + 1)

        # Delete user
        res_del = delete_system_user(device=self.device, name="noc_user")
        self.assertTrue(res_del.get("success"))

        # Verify deleted
        res_get3 = get_system_users(device=self.device)
        self.assertEqual(len(res_get3.get("data", [])), initial_count)

    def test_packages_and_routerboard(self):
        res_pkg = get_packages(device=self.device)
        self.assertTrue(res_pkg.get("success"))
        self.assertGreater(len(res_pkg.get("data", [])), 0)

        res_rb = get_routerboard(device=self.device)
        self.assertTrue(res_rb.get("success"))
        self.assertIn("serial_number", res_rb.get("data", {}))

    def test_clock_and_sntp(self):
        res_clk = get_clock_sntp(device=self.device)
        self.assertTrue(res_clk.get("success"))
        self.assertIn("clock", res_clk.get("data", {}))

        res_tz = set_clock_timezone(device=self.device, time_zone="Asia/Makassar")
        self.assertTrue(res_tz.get("success"))

    def test_reboot_and_shutdown(self):
        res_reb = system_reboot(device=self.device)
        self.assertTrue(res_reb.get("success"))
        self.assertIn("REBOOT", res_reb.get("message", "").upper())

        res_shut = system_shutdown(device=self.device)
        self.assertTrue(res_shut.get("success"))
        self.assertIn("SHUTDOWN", res_shut.get("message", "").upper())

    # =========================================================================
    # SECURITY & CONFIRMATION TESTS
    # =========================================================================
    def test_factory_reset_remains_blocked(self):
        is_dang, warning = security_manager.is_dangerous("tolong reset configuration router bawaan pabrik")
        self.assertTrue(is_dang)
        self.assertIn("OPERASI BERISIKO TINGGI DITOLAK", warning)

        res = hermes_agent.process_message(self.admin_id, "admin", "reset-configuration router mock_demo sekarang")
        self.assertIn("DITOLAK", res.get("reply", ""))
        self.assertFalse(res.get("action_required", False))

    def test_reboot_requires_admin_confirmation(self):
        # Viewer attempting reboot -> rejected by security manager or RBAC
        res_viewer = hermes_agent.process_message(self.viewer_id, "viewer", "reboot router mock_demo")
        self.assertTrue(
            "Viewer" in res_viewer.get("reply", "") or "DITOLAK" in res_viewer.get("reply", "")
        )

        # Admin attempting reboot -> asks confirmation
        res_admin = hermes_agent.process_message(self.admin_id, "admin", "reboot router mock_demo sekarang")
        self.assertTrue(res_admin.get("action_required"))
        self.assertIsNotNone(res_admin.get("pending_action"))
        token = res_admin.get("pending_action").token

        # Confirm reboot
        res_confirm = confirmation_manager.execute_action(token)
        self.assertTrue(res_confirm.success)
        self.assertIn("REBOOT", res_confirm.message)


if __name__ == "__main__":
    unittest.main()
