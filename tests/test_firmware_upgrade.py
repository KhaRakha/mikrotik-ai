"""
Unit and Integration Tests for MikroTik Firmware and RouterOS Upgrade.
Tests Mock client, Tools, Security RBAC, Hermes AI Agent heuristics, and Telegram handlers.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock
from config.settings import DeviceConfig, settings
from core.agent import hermes_agent
from core.confirmation import confirmation_manager
from core.security import security_manager
from mikrotik.mock_client import MockMikrotikClient
from mikrotik.tools import (
    TOOL_REGISTRY,
    TOOL_SCHEMAS,
    check_router_update,
    get_firmware_status,
    install_router_update,
    upgrade_routerboard_firmware,
)
from bot.handlers import firmware_command, handle_callback_query, reboot_command, upgrade_command
from bot.formatters import format_firmware_card, make_firmware_keyboard


class TestFirmwareUpgrade(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.device = "mock_demo"
        from mikrotik.manager import device_manager
        device_manager._clients.clear()
        device_manager._status_cache.clear()
        device_manager.mock_client = MockMikrotikClient()
        self.mock_client = MockMikrotikClient()
        self.mock_dev = DeviceConfig({
            "id": "mock_demo",
            "name": "mock_demo",
            "host": "127.0.0.1",
            "protocol": "mock",
        })
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
    # 1. MOCK CLIENT TESTS
    # =========================================================================
    def test_mock_client_check_router_update(self):
        res = self.mock_client.check_router_update(channel="stable")
        self.assertTrue(res.success)
        self.assertIn("update_available", res.data)
        self.assertTrue(res.data["update_available"])
        self.assertEqual(res.data["installed_version"], "7.15.2")
        self.assertEqual(res.data["latest_version"], "7.16.1")

    def test_mock_client_install_router_update(self):
        res = self.mock_client.install_router_update(channel="stable")
        self.assertTrue(res.success)
        self.assertIn("REBOOT", res.message)
        self.assertEqual(self.mock_client._package_update["installed_version"], "7.16.1")
        self.assertFalse(self.mock_client._package_update["update_available"])

        # Check subsequent check shows already up to date
        check_after = self.mock_client.check_router_update()
        self.assertFalse(check_after.data["update_available"])

    def test_mock_client_upgrade_routerboard_firmware(self):
        res = self.mock_client.upgrade_routerboard_firmware()
        self.assertTrue(res.success)
        self.assertIn("RouterBOARD", res.message)
        self.assertEqual(
            self.mock_client._routerboard["current_firmware"],
            self.mock_client._routerboard["upgrade_firmware"],
        )

    def test_mock_client_get_firmware_status(self):
        res = self.mock_client.get_firmware_status()
        self.assertTrue(res.success)
        self.assertIn("routerboard", res.data)
        self.assertIn("package_update", res.data)
        self.assertIn("has_os_update", res.data)

    # =========================================================================
    # 2. TOOL LAYER TESTS
    # =========================================================================
    def test_tool_registry_and_schemas(self):
        self.assertIn("check_router_update", TOOL_REGISTRY)
        self.assertIn("install_router_update", TOOL_REGISTRY)
        self.assertIn("upgrade_routerboard_firmware", TOOL_REGISTRY)
        self.assertIn("get_firmware_status", TOOL_REGISTRY)

        schema_names = [s["function"]["name"] for s in TOOL_SCHEMAS]
        self.assertIn("check_router_update", schema_names)
        self.assertIn("install_router_update", schema_names)
        self.assertIn("upgrade_routerboard_firmware", schema_names)
        self.assertIn("get_firmware_status", schema_names)

    def test_tool_functions(self):
        status = get_firmware_status(device=self.device)
        self.assertTrue(status.get("success"))

        update_chk = check_router_update(device=self.device)
        self.assertTrue(update_chk.get("success"))

        upg_boot = upgrade_routerboard_firmware(device=self.device)
        self.assertTrue(upg_boot.get("success"))

        upg_os = install_router_update(device=self.device)
        self.assertTrue(upg_os.get("success"))

    # =========================================================================
    # 3. SECURITY AND RBAC TESTS
    # =========================================================================
    def test_security_rbac_classification(self):
        self.assertEqual(security_manager.classify_permission("check_router_update"), "READ")
        self.assertEqual(security_manager.classify_permission("get_firmware_status"), "READ")
        self.assertEqual(security_manager.classify_permission("install_router_update"), "WRITE")
        self.assertEqual(security_manager.classify_permission("upgrade_routerboard_firmware"), "WRITE")

    def test_viewer_blocked_from_upgrade(self):
        # Imperative upgrade from viewer must be rejected
        res = hermes_agent.process_message(self.viewer_id, "viewer", "upgrade firmware router mock_demo sekarang")
        self.assertFalse(res.get("action_required", False))
        self.assertIn("Viewer", res.get("reply", ""))

    def test_viewer_allowed_to_check_firmware(self):
        # Informational check from viewer is permitted
        res = hermes_agent.process_message(self.viewer_id, "viewer", "cek update firmware router mock_demo")
        self.assertFalse(res.get("action_required", False))
        self.assertIn("Status Firmware", res.get("reply", ""))
        self.assertNotIn("Ditolak", res.get("reply", ""))

    # =========================================================================
    # 4. HERMES AGENT NATURAL LANGUAGE TESTS
    # =========================================================================
    def test_agent_check_firmware_status(self):
        queries = [
            "cek firmware router mock_demo",
            "cek update routeros mock_demo",
            "apakah ada update firmware untuk mock_demo?",
            "status firmware mock_demo",
        ]
        for q in queries:
            res = hermes_agent.process_message(self.admin_id, "admin", q)
            reply = res.get("reply", "")
            self.assertIn("Status Firmware & Pembaruan Sistem", reply, f"Failed for {q}")
            self.assertIn("RouterOS Aktif", reply, f"Failed for {q}")
            self.assertIn("Hardware & Bootloader BIOS", reply, f"Failed for {q}")

    def test_agent_upgrade_firmware_flow(self):
        # 1. Admin triggers upgrade
        res = hermes_agent.process_message(self.admin_id, "admin", "upgrade firmware router mock_demo")
        self.assertTrue(res.get("action_required"))
        self.assertIsNotNone(res.get("pending_action"))
        token = res["pending_action"].token

        # Check safety warning in reply
        self.assertIn("Konfirmasi Diperlukan", res["reply"])
        self.assertIn("PERINGATAN KESELAMATAN JARINGAN", res["reply"])
        self.assertIn("REBOOT", res["reply"])

        # 2. Confirm upgrade
        confirm_res = hermes_agent.process_message(self.admin_id, "admin", "Ya")
        self.assertFalse(confirm_res.get("action_required", False))
        self.assertIn("Upgrade RouterOS Berhasil", confirm_res.get("reply", ""))

    def test_agent_upgrade_bootloader_flow(self):
        res = hermes_agent.process_message(self.admin_id, "admin", "upgrade bootloader router mock_demo")
        self.assertTrue(res.get("action_required"))
        self.assertIsNotNone(res.get("pending_action"))
        token = res["pending_action"].token

        self.assertIn("BOOTLOADER", res["reply"])
        exec_res = confirmation_manager.execute_action(token)
        self.assertTrue(exec_res.success)
        self.assertIn("RouterBOARD", exec_res.message)

    # =========================================================================
    # 5. FORMATTER & KEYBOARD TESTS
    # =========================================================================
    def test_format_firmware_card(self):
        data = {
            "has_os_update": True,
            "has_rb_update": True,
            "package_update": {"installed_version": "7.15.2", "latest_version": "7.16.1", "channel": "stable", "status": "New version is available"},
            "routerboard": {"model": "RB750Gr3", "board_name": "hEX", "serial_number": "123456", "current_firmware": "7.15.2", "upgrade_firmware": "7.16.1"},
        }
        card = format_firmware_card(data, "Kantor_Pusat")
        self.assertIn("Kantor_Pusat", card)
        self.assertIn("UPDATE TERSEDIA", card)
        self.assertIn("v7.15.2", card)
        self.assertIn("v7.16.1", card)

    def test_make_firmware_keyboard(self):
        kb = make_firmware_keyboard("Kantor_Pusat", has_os_update=True, has_rb_update=True)
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertIn("fw_os_upg:Kantor_Pusat", callbacks)
        self.assertIn("fw_rb_upg:Kantor_Pusat", callbacks)
        self.assertIn("fw_check:Kantor_Pusat", callbacks)

    # =========================================================================
    # 6. TELEGRAM COMMAND HANDLER TESTS
    # =========================================================================
    async def test_telegram_firmware_command(self):
        update = MagicMock()
        update.effective_user.id = self.admin_id
        update.effective_user.first_name = "Admin"
        update.effective_user.username = "admin_user"
        msg = AsyncMock()
        update.message = msg
        msg.reply_text = AsyncMock(return_value=msg)
        msg.edit_message_text = AsyncMock()

        context = MagicMock()
        context.args = ["mock_demo"]

        await firmware_command(update, context)
        self.assertTrue(msg.reply_text.called or msg.edit_message_text.called)

    async def test_telegram_upgrade_command_viewer_blocked(self):
        update = MagicMock()
        update.effective_user.id = self.viewer_id
        update.effective_user.first_name = "Viewer"
        update.effective_user.username = "viewer_user"
        msg = AsyncMock()
        update.message = msg
        msg.reply_text = AsyncMock()

        context = MagicMock()
        context.args = ["mock_demo"]

        await upgrade_command(update, context)
        self.assertTrue(msg.reply_text.called)
        sent_text = msg.reply_text.call_args[0][0]
        self.assertIn("Viewer", sent_text)

    async def test_telegram_upgrade_command_admin_success(self):
        update = MagicMock()
        update.effective_user.id = self.admin_id
        update.effective_user.first_name = "Admin"
        update.effective_user.username = "admin_user"
        msg = AsyncMock()
        update.message = msg
        msg.reply_text = AsyncMock(return_value=msg)
        msg.edit_message_text = AsyncMock()

        context = MagicMock()
        context.args = ["mock_demo", "stable"]

        await upgrade_command(update, context)
        # Should ask for confirmation
        self.assertTrue(msg.edit_message_text.called)
        edit_args = msg.edit_message_text.call_args
        self.assertIn("Konfirmasi Diperlukan", edit_args[0][0])
        self.assertIsNotNone(edit_args[1].get("reply_markup"))

    async def test_telegram_reboot_command_viewer_blocked(self):
        update = MagicMock()
        update.effective_user.id = self.viewer_id
        update.effective_user.first_name = "Viewer"
        msg = AsyncMock()
        update.message = msg
        msg.reply_text = AsyncMock()

        context = MagicMock()
        context.args = ["mock_demo"]

        await reboot_command(update, context)
        self.assertTrue(msg.reply_text.called)
        sent_text = msg.reply_text.call_args[0][0]
        self.assertIn("Viewer", sent_text)

    async def test_telegram_reboot_command_admin_success(self):
        update = MagicMock()
        update.effective_user.id = self.admin_id
        update.effective_user.first_name = "Admin"
        msg = AsyncMock()
        update.message = msg
        msg.reply_text = AsyncMock(return_value=msg)

        context = MagicMock()
        context.args = ["mock_demo"]

        await reboot_command(update, context)
        self.assertTrue(msg.reply_text.called)
        call_args = msg.reply_text.call_args
        self.assertIn("REBOOT ROUTER", call_args[0][0])
        self.assertIsNotNone(call_args[1].get("reply_markup"))

    async def test_telegram_fw_reboot_callback(self):
        update = MagicMock()
        query = AsyncMock()
        update.callback_query = query
        update.effective_user.id = self.admin_id
        update.effective_user.first_name = "Admin"
        query.data = "fw_reboot:mock_demo"
        query.edit_message_text = AsyncMock()

        context = MagicMock()
        await handle_callback_query(update, context)
        self.assertTrue(query.edit_message_text.called)
        call_args = query.edit_message_text.call_args
        self.assertIn("REBOOT ROUTER", call_args[0][0])

    def test_agent_typos_in_firmware_upgrade(self):
        # Typo 'frimware' or 'perbarui' should properly initiate write confirmation
        typos = [
            "update frimware router mock_demo",
            "upgrade frimware mock_demo",
            "perbarui firmware router mock_demo",
        ]
        for q in typos:
            res = hermes_agent.process_message(self.admin_id, "admin", q)
            self.assertTrue(res.get("action_required"), f"Failed to require action for: {q}")
            self.assertIsNotNone(res.get("pending_action"))
            self.assertIn("Konfirmasi Diperlukan", res.get("reply", ""))

    def test_hardware_hyphenated_keys_in_firmware_card(self):
        raw_hw_data = {
            "has_os_update": False,
            "has_rb_update": True,
            "package_update": {
                "channel": "stable",
                "installed_version": "7.22.2",
                "latest_version": "",
                "status": "System is up to date",
                "update_available": False,
            },
            "routerboard": {
                "routerboard": "true",
                "model": "RB2011UiAS",
                "serial-number": "763107FA581B",
                "current-firmware": "3.33",
                "upgrade-firmware": "7.22.2",
            },
        }
        card = format_firmware_card(raw_hw_data, "Kantor Utama")
        self.assertIn("RB2011UiAS", card)
        self.assertIn("763107FA581B", card)
        self.assertIn("v3.33", card)
        self.assertIn("v7.22.2", card)
        self.assertNotIn("Bootloader Aktif  : `v-`", card)
        self.assertNotIn("Bootloader Upgrade: `v-`", card)


if __name__ == "__main__":
    unittest.main()
