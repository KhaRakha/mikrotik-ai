"""
Unit tests for IP address management (add, remove, edit IP).
"""

from __future__ import annotations

import pytest
from config.settings import settings
from core.agent import hermes_agent
from core.confirmation import confirmation_manager
from mikrotik.mock_client import MockMikrotikClient
from mikrotik.tools import add_ip_address, remove_ip_address, set_ip_address


def test_mock_client_ip_lifecycle():
    client = MockMikrotikClient()
    test_ip = "172.16.10.1/24"
    iface = "ether2-LAN-Kantor"

    # 1. Add IP
    res_add = client.add_ip_address(address=test_ip, interface=iface, comment="Subnet Server")
    assert res_add.success is True
    assert "berhasil ditambahkan" in res_add.message

    # Duplicate check
    dup = client.add_ip_address(address=test_ip, interface=iface)
    assert dup.success is False

    # 2. Edit IP
    new_ip = "172.16.20.1/24"
    res_edit = client.set_ip_address(current_address=test_ip, new_address=new_ip, new_interface="ether3-Hotspot")
    assert res_edit.success is True
    assert "berhasil diubah" in res_edit.message

    # Verify updated
    res_ips = client.get_ip_addresses()
    addrs = [item["address"] for item in res_ips.data]
    assert new_ip in addrs
    assert test_ip not in addrs

    # 3. Remove IP
    res_del = client.remove_ip_address(address=new_ip)
    assert res_del.success is True
    assert "berhasil dihapus" in res_del.message

    # Verify deleted
    res_ips_after = client.get_ip_addresses()
    addrs_after = [item["address"] for item in res_ips_after.data]
    assert new_ip not in addrs_after


def test_natural_language_add_ip_with_confirmation():
    user_id = 888123
    if user_id not in settings.admin_telegram_ids:
        settings.admin_telegram_ids.append(user_id)
        settings.allowed_telegram_ids.append(user_id)

    from mikrotik.tools import remove_ip_address
    remove_ip_address(device="Kantor Utama", address="192.168.77.1/24")
    remove_ip_address(device="Kantor Utama", address="192.168.77.1")

    prompt = "Tambahkan IP 192.168.77.1/24 di interface ether2"
    result = hermes_agent.process_message(user_id=user_id, username="NetAdmin", text=prompt)

    assert result["pending_action"] is not None
    assert result["pending_action"].action_name == "add_ip_address"
    assert result["pending_action"].arguments["address"] == "192.168.77.1/24"
    assert "Konfirmasi Penambahan IP Address" in result["reply"]

    # Execute confirmation
    token = result["pending_action"].token
    exec_res = confirmation_manager.execute_action(token)
    assert exec_res.success is True


def test_natural_language_edit_ip_with_confirmation(monkeypatch):
    monkeypatch.setattr(hermes_agent, "google_api_key", "")
    monkeypatch.setattr(hermes_agent, "openai_api_key", "")
    user_id = 888123
    if user_id not in settings.admin_telegram_ids:
        settings.admin_telegram_ids.append(user_id)
        settings.allowed_telegram_ids.append(user_id)

    prompt = "Ubah IP 192.168.77.1 menjadi 192.168.88.1/24"
    result = hermes_agent.process_message(user_id=user_id, username="NetAdmin", text=prompt)

    assert result["pending_action"] is not None
    assert result["pending_action"].action_name == "set_ip_address"
    assert result["pending_action"].arguments["current_address"] == "192.168.77.1"
    assert "Konfirmasi Pengubahan IP Address" in result["reply"]


def test_natural_language_remove_ip_with_confirmation(monkeypatch):
    monkeypatch.setattr(hermes_agent, "google_api_key", "")
    monkeypatch.setattr(hermes_agent, "openai_api_key", "")
    user_id = 888123
    if user_id not in settings.admin_telegram_ids:
        settings.admin_telegram_ids.append(user_id)
        settings.allowed_telegram_ids.append(user_id)

    prompt = "Hapus IP 192.168.88.1"
    result = hermes_agent.process_message(user_id=user_id, username="NetAdmin", text=prompt)

    assert result["pending_action"] is not None
    assert result["pending_action"].action_name == "remove_ip_address"
    assert result["pending_action"].arguments["address"] == "192.168.88.1"
    assert "Konfirmasi Penghapusan IP Address" in result["reply"]
