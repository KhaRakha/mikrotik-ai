"""
Formatting utilities for Telegram messages, cards, buttons, and reports.
"""

from __future__ import annotations

from typing import Any, Dict, List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def make_confirmation_keyboard(token: str) -> InlineKeyboardMarkup:
    """Create Telegram inline keyboard for confirmation."""
    keyboard = [
        [
            InlineKeyboardButton("✅ YA (Setuju)", callback_data=f"conf_yes:{token}"),
            InlineKeyboardButton("❌ BATAL (Tolak)", callback_data=f"conf_no:{token}"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def format_device_list(devices: List[Dict[str, Any]]) -> str:
    """Format configured devices list into an attractive Telegram card."""
    lines = ["📋 **Daftar Perangkat MikroTik Terdaftar**\n"]
    for dev in devices:
        icon = "🟢" if dev.get("online") else "🔴"
        default_tag = " `[Default]`" if dev.get("is_default") else ""
        lines.append(
            f"{icon} **{dev.get('name')}**{default_tag}\n"
            f"   • Host/IP : `{dev.get('host')}:{dev.get('port')}`\n"
            f"   • Protokol: `{dev.get('protocol').upper()}`\n"
            f"   • Status  : {dev.get('status_message', 'OK')}\n"
        )
    lines.append("💡 *Gunakan nama perangkat dalam pertanyaan Anda (misal: 'cek resource kantor cabang').*")
    return "\n".join(lines)


def format_audit_logs(logs: List[Dict[str, Any]]) -> str:
    """Format audit trail logs for Telegram view."""
    if not logs:
        return "📜 Belum ada catatan aktivitas audit."

    lines = ["📜 **Catatan Audit Trail Aktivitas Terakhir**\n"]
    for log in logs:
        res_icon = "✅" if log.get("result_status") == "SUCCESS" else ("⚠️" if log.get("result_status") == "BLOCKED" else "❌")
        lines.append(
            f"{res_icon} `[{log.get('timestamp')}]`\n"
            f"• User   : `{log.get('telegram_user_name')}` (`{log.get('telegram_user_id')}`)\n"
            f"• Target : **{log.get('target_device')}**\n"
            f"• Aksi   : `{log.get('action_name')}` ({log.get('action_category')})\n"
            f"• Status : **{log.get('result_status')}** (Konfirmasi: `{log.get('confirmation_status')}`)\n"
            f"• Prompt : *\"{log.get('user_prompt')}\"*\n"
        )
    return "\n".join(lines)


def make_firmware_keyboard(
    device_name: str,
    has_os_update: bool = False,
    has_rb_update: bool = False,
    can_write: bool = True,
) -> InlineKeyboardMarkup:
    """Create Telegram inline keyboard for firmware actions."""
    buttons = []
    if has_os_update and can_write:
        buttons.append([InlineKeyboardButton("🚀 Upgrade RouterOS Sekarang", callback_data=f"fw_os_upg:{device_name}")])
    if has_rb_update and can_write:
        buttons.append([InlineKeyboardButton("⚡ Upgrade Bootloader Firmware", callback_data=f"fw_rb_upg:{device_name}")])

    # Bottom control row: Refresh update check and safe reboot
    control_row = [InlineKeyboardButton("🔄 Refresh / Cek Update", callback_data=f"fw_check:{device_name}")]
    if can_write:
        control_row.append(InlineKeyboardButton("🔁 Reboot Router", callback_data=f"fw_reboot:{device_name}"))
    buttons.append(control_row)
    return InlineKeyboardMarkup(buttons)


def format_firmware_card(data: Dict[str, Any], device_name: str) -> str:
    """Format firmware and update status into a rich Telegram card."""
    rb = data.get("routerboard") or {}
    pkg = data.get("package_update") or {}

    curr_fw = rb.get("current_firmware") or rb.get("current-firmware") or "-"
    upg_fw = rb.get("upgrade_firmware") or rb.get("upgrade-firmware") or "-"
    installed = pkg.get("installed_version") or pkg.get("installed-version") or curr_fw
    has_os_update = data.get("has_os_update", False)
    has_rb_update = data.get("has_rb_update", False)
    latest = pkg.get("latest_version") or pkg.get("latest-version") or (installed if not has_os_update else "-")
    channel = pkg.get("channel", "stable")
    status_text = pkg.get("status", "-")

    status_badge = "🚀 **UPDATE TERSEDIA!**" if has_os_update else "✅ **Sistem Up to Date (Terbaru)**"

    model = rb.get("model") or "-"
    board_name = rb.get("board_name") or rb.get("board-name") or ""
    model_str = f"**{model}** ({board_name})" if board_name else f"**{model}**"
    serial = rb.get("serial_number") or rb.get("serial-number") or "-"

    is_hardware = rb.get("routerboard") not in ("no", False, "false")

    lines = [
        f"🛰️ **Status Firmware & Pembaruan Sistem ({device_name})**\n",
        f"• Status Rilis      : {status_badge}",
        f"• Channel Update    : `{channel}`",
        f"• RouterOS Aktif    : `v{installed}`",
        f"• Versi Terbaru     : `v{latest}`",
        f"• Keterangan Server : _{status_text}_\n",
    ]

    if is_hardware and model != "-":
        lines.extend([
            f"🔧 **Hardware & Bootloader BIOS:**",
            f"• Model Board       : {model_str}",
            f"• Serial Number     : `{serial}`",
            f"• Bootloader Aktif  : `v{curr_fw}`",
            f"• Bootloader Upgrade: `v{upg_fw}`\n",
        ])
    else:
        lines.extend([
            f"🔧 **Hardware & Bootloader BIOS:**",
            f"• Tipe Sistem       : _Virtual / Cloud Hosted Router (CHR / x86)_\n",
        ])

    if has_os_update:
        lines.append(
            "💡 **Tindakan yang Disarankan:**\n"
            f"Klik tombol [ 🚀 Upgrade RouterOS Sekarang ] di bawah atau ketik `/upgrade {device_name}` "
            "untuk mengunduh dan menginstal pembaruan ke versi terbaru."
        )
    elif has_rb_update:
        lines.append(
            "💡 **Tindakan yang Disarankan:**\n"
            f"Firmware bootloader BIOS baru (`v{upg_fw}`) tersedia untuk perangkat ini.\n"
            "Klik tombol [ ⚡ Upgrade Bootloader Firmware ] di bawah untuk memperbarui BIOS."
        )
    else:
        lines.append("✨ Perangkat Anda telah menggunakan versi firmware dan sistem operasi paling mutakhir dan stabil.")

    return "\n".join(lines)
