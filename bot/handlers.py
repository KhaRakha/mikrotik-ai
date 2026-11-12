"""
Telegram Bot Handlers.
Dispatches bot commands, callback queries, and natural language messages to Hermes AI Agent.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import time
from typing import Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from bot.formatters import (
    format_audit_logs,
    format_device_list,
    format_firmware_card,
    make_confirmation_keyboard,
    make_firmware_keyboard,
)
from config.settings import settings
from core.agent import conversation_memory, hermes_agent
from core.audit import audit_logger
from core.confirmation import confirmation_manager
from core.security import security_manager
from mikrotik.discovery import device_discovery
from mikrotik.manager import device_manager
from mikrotik.tools import TOOL_REGISTRY

logger = logging.getLogger(__name__)


async def _safe_reply_text(message: Any, text: str, reply_markup: Any = None) -> Any:
    """Send reply with Markdown parsing, chunking if message exceeds Telegram limit (4096 chars)."""
    # Guard against Telegram 4096 character limit
    if len(text) > 4000:
        chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]
        last_resp = None
        for idx, chunk in enumerate(chunks):
            # Only attach markup to the final chunk
            markup = reply_markup if idx == len(chunks) - 1 else None
            try:
                last_resp = await message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            except Exception:
                last_resp = await message.reply_text(chunk, reply_markup=markup)
        return last_resp

    try:
        return await message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    except Exception:
        return await message.reply_text(text, reply_markup=reply_markup)


async def _safe_edit_message_text(target: Any, text: str, reply_markup: Any = None) -> Any:
    """Edit message with Markdown parsing, fallback to plain text if malformed."""
    display_text = text[:4000] if len(text) > 4000 else text
    try:
        return await target.edit_message_text(display_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    except Exception:
        return await target.edit_message_text(display_text, reply_markup=reply_markup)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /start command."""
    user = update.effective_user
    if not user:
        return

    if not security_manager.is_user_authorized(user.id):
        await update.message.reply_text(
            f"⛔ **Akses Ditolak**\n\n"
            f"User ID Anda `{user.id}` belum terdaftar dalam daftar izin (whitelist).\n"
            f"Hubungi Administrator sistem untuk menambahkan ID Anda.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    role = security_manager.get_user_role(user.id)
    role_badge = "🛡️ **Administrator**" if role == "ADMIN" else "👁️ **Viewer (Read-Only)**"

    welcome_text = (
        f"👋 Halo, **{user.first_name}**!\n"
        f"Role Akses Anda: {role_badge}\n\n"
        f"Saya adalah **Hermes AI Agent** untuk otomatisasi dan pengelolaan MikroTik RouterOS.\n\n"
        f"🤖 **Fitur Utama:**\n"
        f"• **Natural Language**: Cukup gunakan bahasa sehari-hari tanpa perlu menghafal command RouterOS.\n"
        f"• **Multi-Perangkat**: Mendukung banyak router (Kantor Utama, Cabang, Lab).\n"
        f"• **Proactive Alerting**: Memantau router dan mengirim notifikasi otomatis jika down.\n"
        f"• **Sistem Konfirmasi Aman**: Perubahan konfigurasi wajib disetujui terlebih dahulu.\n"
        f"• **Perlindungan Berbahaya**: Menolak operasi destruktif (reset/reboot).\n\n"
        f"💡 **Contoh Pertanyaan:**\n"
        f"• *'Coba cek kondisi MikroTik kantor utama'* (Monitoring)\n"
        f"• *'Kenapa internet kantor terasa lambat?'* (Troubleshooting)\n"
        f"• *'Cek user hotspot yang sedang aktif'* (Status Hotspot)\n"
        f"• *'Cek port 80 pada web server 10.20.33.10'* (Server Check)\n"
        f"• *'Buatkan user hotspot untuk tamu bernama Tamu123, aktif satu hari'* (Konfigurasi)\n\n"
        f"Ketik `/help` untuk bantuan lengkap atau langsung kirimkan pertanyaan Anda!"
    )
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)


async def role_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /role command."""
    user = update.effective_user
    if not user or not security_manager.is_user_authorized(user.id):
        return

    role = security_manager.get_user_role(user.id)
    can_write = security_manager.can_user_write(user.id)
    text = (
        f"👤 **Profil & Hak Akses Pengguna**\n\n"
        f"• Nama: **{user.first_name}**\n"
        f"• Telegram User ID: `{user.id}`\n"
        f"• Role Sistem: **{role}**\n"
        f"• Izin Konfigurasi (Write): {'✅ Diizinkan' if can_write else '❌ Terbatas (Read-Only)'}\n\n"
        f"💡 *Role dapat dikonfigurasi melalui ADMIN_TELEGRAM_IDS dan VIEWER_TELEGRAM_IDS pada file .env.*"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /help command."""
    user = update.effective_user
    if not user or not security_manager.is_user_authorized(user.id):
        return

    role = security_manager.get_user_role(user.id)
    help_text = (
        f"📖 **Panduan Penggunaan Hermes AI Agent MikroTik**\n"
        f"Role Anda: **{role}**\n\n"
        f"**Perintah Cepat:**\n"
        f"• `/status` - Cek ringkas kondisi router aktif\n"
        f"• `/topology` - Peta topologi jaringan (`/topology scan`, `/topology image`, `/topology diff`)\n"
        f"• `/firmware` - Cek status versi RouterOS dan firmware bootloader RouterBOARD\n"
        f"• `/upgrade` - Upgrade sistem RouterOS & firmware router langsung dari bot\n"
        f"• `/reboot` - Mulai ulang (reboot) router secara aman dengan konfirmasi 2 tahap\n"
        f"• `/devices` - Tampilkan daftar semua router MikroTik\n"
        f"• `/add_device` - Daftarkan router baru langsung dari Telegram\n"
        f"• `/remove_device` - Hapus router dari daftar pemantauan\n"
        f"• `/add_ip` - Tambahkan IP address baru pada interface MikroTik\n"
        f"• `/remove_ip` - Hapus IP address dari router MikroTik\n"
        f"• `/edit_ip` - Ubah (edit) IP address atau interface router\n"
        f"• `/discover` - Pindai subnet untuk menemukan router baru\n"
        f"• `/audit` - Tampilkan log riwayat aktivitas administrasi\n"
        f"• `/role` - Cek status profil dan hak akses Anda\n"
        f"• `/clear` - Bersihkan riwayat sesi obrolan (reset context memori)\n\n"
        f"**Bahasa Natural (AI):**\n"
        f"Anda tidak perlu mengetik command garis miring! Anda bebas bertanya:\n"
        f"1. *\"Cek update firmware router saat ini\"*\n"
        f"2. *\"Upgrade firmware router Kantor Utama\"*\n"
        f"3. *\"Upgrade bootloader router\"*\n"
        f"4. *\"Tambahkan IP 192.168.50.1/24 di interface ether2\"*\n"
        f"5. *\"Ubah IP 192.168.10.1 menjadi 192.168.20.1/24\"*\n"
        f"6. *\"Hapus IP 192.168.50.1\"*\n"
        f"7. *\"Daftarkan router baru Cabang B IP 192.168.20.1 port 8728 username admin password rahasia\"*\n"
        f"8. *\"Cek kondisi Kantor Cabang\"*\n"
        f"9. *\"Reboot router\"*\n\n"
        f"🔒 **Keamanan:**\n"
        f"Setiap operasi yang mengubah konfigurasi router akan memunculkan tombol konfirmasi `[ YA ]` dan `[ BATAL ]` (khusus Administrator)."
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def devices_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /devices command."""
    user = update.effective_user
    if not user or not security_manager.is_user_authorized(user.id):
        return

    dev_list = device_manager.list_devices()
    text = format_device_list(dev_list)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def add_device_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /add_device command."""
    user = update.effective_user
    if not user or not security_manager.is_user_authorized(user.id):
        return

    if not security_manager.can_user_write(user.id):
        await update.message.reply_text(
            "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**. Pendaftaran perangkat hanya dapat dilakukan oleh Administrator.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    args = context.args or []
    if not args:
        guide = (
            "📋 **Panduan Pendaftaran Router Baru (/add_device)**\n\n"
            "Format perintah:\n"
            "`/add_device <Nama> <IP> [Port] [Protokol] [Username] [Password]`\n\n"
            "💡 **Contoh Cepat:**\n"
            "`/add_device Cabang_2 192.168.88.1 8728 api admin rahasia123`\n"
            "`/add_device Lab_PTI 192.168.10.1 80 rest admin pass456`\n\n"
            "Keterangan:\n"
            "• **Nama**: Nama router (gunakan `_` jika lebih dari 1 kata)\n"
            "• **IP**: Alamat IP host router / IP VPN\n"
            "• **Port**: `8728` (RouterOS API), `80` (REST), atau `22` (SSH)\n"
            "• **Protokol**: `api` (rekomendasi), `rest`, atau `ssh`\n"
            "• **Username**: default `admin`\n"
            "• **Password**: password login router\n\n"
            "💡 *Anda juga bisa langsung chat bahasa biasa, contoh:*\n"
            "*\"Daftarkan router baru Cabang B dengan IP 192.168.20.1 port 8728 username admin password rahasia\"*"
        )
        await update.message.reply_text(guide, parse_mode=ParseMode.MARKDOWN)
        return

    # Find IP address argument to allow multi-word names without quoting
    ip_index = -1
    for i, a in enumerate(args):
        if re.match(r'^(?:\d{1,3}\.){3}\d{1,3}$', a) or ('.' in a and not a.startswith('@')):
            ip_index = i
            break

    if ip_index > 0:
        name = "_".join(args[:ip_index])
        host = args[ip_index]
        rem = args[ip_index + 1:]
    else:
        name = args[0]
        host = args[1] if len(args) > 1 else ""
        rem = args[2:]

    if not host or not (re.match(r'^(?:\d{1,3}\.){3}\d{1,3}$', host) or '.' in host):
        await update.message.reply_text(
            "⚠️ Mohon cantumkan alamat IP router target yang valid.\nContoh: `/add_device Cabang_2 192.168.88.1`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    port = 0
    proto = "api"
    username = "admin"
    password = ""

    if len(rem) > 0 and rem[0].isdigit():
        port = int(rem[0])
    if len(rem) > 1 and rem[1].lower() in ("api", "rest", "ssh", "mock"):
        proto = rem[1].lower()
    if len(rem) > 2:
        username = rem[2]
    if len(rem) > 3:
        password = rem[3]

    loading_msg = await update.message.reply_text(
        f"⏳ Mendaftarkan dan menguji router **{name}** (`{host}`)...",
        parse_mode=ParseMode.MARKDOWN,
    )

    res = await asyncio.to_thread(
        device_discovery.register_device,
        name=name,
        host=host,
        protocol=proto,
        port=port,
        username=username,
        password=password,
        description=f"Router MikroTik {name} (Didaftarkan via Telegram)",
    )

    if not res.get("success"):
        await loading_msg.edit_text(
            f"❌ **Gagal Mendaftarkan Router**\n\n{res.get('message')}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Test connection directly without mock fallback masking offline status
    dev_config = settings.find_device(name, fallback=False)
    if dev_config:
        direct_client = device_manager._create_client(dev_config)
        test_res = await asyncio.to_thread(direct_client.test_connection)
    else:
        client = device_manager.get_client(name)
        test_res = await asyncio.to_thread(client.test_connection)

    status_icon = "🟢 **Online**" if test_res.success else "🔴 **Offline / Belum Terjangkau**"
    latency_info = f"• Latency: `{test_res.latency_ms} ms`\n" if test_res.success else f"• Keterangan: `{test_res.message}`\n"
    offline_hint = ""
    if not test_res.success:
        offline_hint = (
            "\n⚠️ *Catatan Jaringan:*\n"
            "Perangkat berhasil disimpan, namun port/jaringan belum merespons. Pastikan:\n"
            "1. Service API MikroTik aktif (`/ip service enable api`)\n"
            "2. Jika router berada di LAN privat dan bot di VPS, gunakan VPN (ZeroTier/WireGuard) atau port forwarding.\n"
        )

    audit_logger.log_event(
        telegram_user_id=user.id,
        telegram_user_name=user.username or user.first_name,
        user_prompt=f"/add_device {' '.join(args)}",
        target_device=name,
        action_category="INVENTORY",
        action_name="register_device",
        confirmation_status="APPROVED",
        result_status="SUCCESS",
        details=res.get("data", {}),
    )

    success_text = (
        f"✅ **Router Berhasil Didaftarkan ke Sistem!**\n\n"
        f"• Nama: **{name}**\n"
        f"• Host/IP: `{host}` (Port `{res['data']['port']}`)\n"
        f"• Protokol: `{proto.upper()}`\n"
        f"• Status Koneksi: {status_icon}\n"
        f"{latency_info}"
        f"{offline_hint}\n"
        f"🔄 Perangkat ini sekarang otomatis dipantau oleh background monitor.\n"
        f"💡 Anda bisa langsung mengontrolnya, contoh:\n"
        f"👉 *\"Cek kondisi {name}\"*\n"
        f"👉 `/devices`"
    )
    await loading_msg.edit_text(success_text, parse_mode=ParseMode.MARKDOWN)


async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /reload command to reload configuration and devices from disk."""
    user = update.effective_user
    if not user or not security_manager.is_user_authorized(user.id):
        return

    if not security_manager.can_user_write(user.id):
        await update.message.reply_text(
            "⛔ **Akses Terbatas**: Hanya Administrator yang dapat memuat ulang konfigurasi sistem.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    settings.reload()
    device_manager._clients.clear()
    device_manager._status_cache.clear()
    total = len(settings.devices)
    dev_names = ", ".join(f"*{d.name}*" for d in settings.devices)
    await update.message.reply_text(
        f"🔄 **Konfigurasi & Inventaris Berhasil Dimuat Ulang!**\n\n"
        f"Total perangkat terdaftar: **{total}**\n"
        f"Daftar: {dev_names}\n\n"
        f"Semua perubahan pada `config/devices.yaml` telah aktif.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def remove_device_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /remove_device command."""
    user = update.effective_user
    if not user or not security_manager.is_user_authorized(user.id):
        return

    if not security_manager.can_user_write(user.id):
        await update.message.reply_text(
            "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**. Penghapusan perangkat hanya dapat dilakukan oleh Administrator.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "⚠️ **Format Perintah /remove_device**\n\n"
            "Ketik: `/remove_device <Nama_atau_ID>`\n"
            "Contoh: `/remove_device Cabang_2`\n\n"
            "Gunakan `/devices` untuk melihat daftar nama perangkat yang terdaftar.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    target = " ".join(args).strip()
    res = await asyncio.to_thread(device_discovery.remove_device, name_or_id=target)
    if res.get("success"):
        audit_logger.log_event(
            telegram_user_id=user.id,
            telegram_user_name=user.username or user.first_name,
            user_prompt=f"/remove_device {target}",
            target_device=target,
            action_category="INVENTORY",
            action_name="remove_device",
            confirmation_status="APPROVED",
            result_status="SUCCESS",
            details=res.get("data", {}),
        )
        await update.message.reply_text(f"🗑️ {res.get('message')}", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"❌ {res.get('message')}", parse_mode=ParseMode.MARKDOWN)


async def add_ip_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /add_ip command."""
    user = update.effective_user
    if not user or not security_manager.is_user_authorized(user.id):
        return

    if not security_manager.can_user_write(user.id):
        await update.message.reply_text(
            "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**. Penambahan IP address hanya dapat dilakukan oleh Administrator.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    args = context.args or []
    if len(args) < 2:
        guide = (
            "📋 **Panduan Penambahan IP Address (/add_ip)**\n\n"
            "Format perintah:\n"
            "`/add_ip <IP/CIDR> <Interface> [Komentar] [Router]`\n\n"
            "💡 **Contoh Cepat:**\n"
            "`/add_ip 192.168.50.1/24 ether2`\n"
            "`/add_ip 10.10.10.1/24 ether3 \"LAN Guru\" Kantor_Cabang`\n\n"
            "Keterangan:\n"
            "• **IP/CIDR**: Alamat IP dan prefix subnet (contoh: `192.168.50.1/24`)\n"
            "• **Interface**: Nama port interface MikroTik (contoh: `ether2`, `wlan1`)\n"
            "• **Komentar**: Catatan opsional\n"
            "• **Router**: Nama router target jika ada lebih dari 1 router\n\n"
            "💡 *Bisa juga via chat natural:*\n"
            "*\"Tambahkan IP 192.168.50.1/24 di interface ether2\"*"
        )
        await update.message.reply_text(guide, parse_mode=ParseMode.MARKDOWN)
        return

    address = args[0]
    if "/" not in address:
        address = f"{address}/24"
    interface = args[1]
    comment = args[2] if len(args) > 2 else ""
    device_arg = args[3] if len(args) > 3 else ""
    dev = settings.find_device(device_arg)
    dev_name = dev.name if dev else settings.default_device_name

    arguments = {
        "device": dev_name,
        "address": address,
        "interface": interface,
        "comment": comment,
    }

    pending = confirmation_manager.create_pending_action(
        user_id=user.id,
        device_name=dev_name,
        action_name="add_ip_address",
        arguments=arguments,
        description=f"Penambahan IP '{address}' pada interface '{interface}' ({dev_name})",
    )

    confirm_card = (
        f"⚠️ **Konfirmasi Penambahan IP Address**\n\n"
        f"• Target Router : **{dev_name}**\n"
        f"• Alamat IP     : `{address}`\n"
        f"• Interface     : `{interface}`\n"
        f"• Komentar      : `{comment or '-'}`\n\n"
        f"Tambahkan IP ini ke router?\n"
        f"👉 Balas **Ya** atau tekan tombol [ YA ] di bawah."
    )
    keyboard = make_confirmation_keyboard(pending.token)
    await _safe_reply_text(update.message, confirm_card, reply_markup=keyboard)


async def remove_ip_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /remove_ip command."""
    user = update.effective_user
    if not user or not security_manager.is_user_authorized(user.id):
        return

    if not security_manager.can_user_write(user.id):
        await update.message.reply_text(
            "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**. Penghapusan IP address hanya dapat dilakukan oleh Administrator.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    args = context.args or []
    if not args:
        guide = (
            "📋 **Panduan Penghapusan IP Address (/remove_ip)**\n\n"
            "Format perintah:\n"
            "`/remove_ip <IP_Address> [Router]`\n\n"
            "💡 **Contoh:**\n"
            "`/remove_ip 192.168.50.1`\n"
            "`/remove_ip 192.168.50.1/24 Kantor_Cabang`\n\n"
            "💡 *Bisa juga via chat natural:*\n"
            "*\"Hapus IP 192.168.50.1\"*"
        )
        await update.message.reply_text(guide, parse_mode=ParseMode.MARKDOWN)
        return

    address = args[0]
    device_arg = args[1] if len(args) > 1 else ""
    dev = settings.find_device(device_arg)
    dev_name = dev.name if dev else settings.default_device_name

    arguments = {
        "device": dev_name,
        "address": address,
    }

    pending = confirmation_manager.create_pending_action(
        user_id=user.id,
        device_name=dev_name,
        action_name="remove_ip_address",
        arguments=arguments,
        description=f"Penghapusan IP address '{address}' ({dev_name})",
    )

    confirm_card = (
        f"⚠️ **Konfirmasi Penghapusan IP Address**\n\n"
        f"• Target Router : **{dev_name}**\n"
        f"• Alamat IP     : `{address}`\n\n"
        f"Hapus konfigurasi IP address ini dari router?\n"
        f"👉 Balas **Ya** atau tekan tombol [ YA ] di bawah."
    )
    keyboard = make_confirmation_keyboard(pending.token)
    await _safe_reply_text(update.message, confirm_card, reply_markup=keyboard)


async def edit_ip_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /edit_ip command."""
    user = update.effective_user
    if not user or not security_manager.is_user_authorized(user.id):
        return

    if not security_manager.can_user_write(user.id):
        await update.message.reply_text(
            "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**. Pengubahan IP address hanya dapat dilakukan oleh Administrator.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    args = context.args or []
    if len(args) < 2:
        guide = (
            "📋 **Panduan Ubah / Edit IP Address (/edit_ip)**\n\n"
            "Format perintah:\n"
            "`/edit_ip <IP_Lama> <IP_Baru> [Interface_Baru] [Router]`\n\n"
            "💡 **Contoh:**\n"
            "`/edit_ip 192.168.10.1 192.168.20.1/24`\n"
            "`/edit_ip 192.168.10.1 192.168.20.1/24 ether3 Kantor_Cabang`\n\n"
            "💡 *Bisa juga via chat natural:*\n"
            "*\"Ubah IP 192.168.10.1 menjadi 192.168.20.1/24\"*"
        )
        await update.message.reply_text(guide, parse_mode=ParseMode.MARKDOWN)
        return

    curr_ip = args[0]
    new_ip = args[1]
    if "/" not in new_ip:
        new_ip = f"{new_ip}/24"
    new_iface = args[2] if len(args) > 2 else ""
    device_arg = args[3] if len(args) > 3 else ""
    dev = settings.find_device(device_arg)
    dev_name = dev.name if dev else settings.default_device_name

    arguments = {
        "device": dev_name,
        "current_address": curr_ip,
        "new_address": new_ip,
        "new_interface": new_iface,
    }

    pending = confirmation_manager.create_pending_action(
        user_id=user.id,
        device_name=dev_name,
        action_name="set_ip_address",
        arguments=arguments,
        description=f"Pengubahan IP address '{curr_ip}' -> '{new_ip}' ({dev_name})",
    )

    confirm_card = (
        f"⚠️ **Konfirmasi Pengubahan IP Address**\n\n"
        f"• Target Router : **{dev_name}**\n"
        f"• IP Lama       : `{curr_ip}`\n"
        f"• IP Baru       : `{new_ip}`\n"
        f"• Interface     : `{new_iface or '(Tetap)'}`\n\n"
        f"Lanjutkan perubahan IP address ini?\n"
        f"👉 Balas **Ya** atau tekan tombol [ YA ] di bawah."
    )
    keyboard = make_confirmation_keyboard(pending.token)
    await _safe_reply_text(update.message, confirm_card, reply_markup=keyboard)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /status command."""
    user = update.effective_user
    if not user or not security_manager.is_user_authorized(user.id):
        return

    # Trigger monitoring scenario on default device
    result = await asyncio.to_thread(
        hermes_agent.process_message,
        user_id=user.id,
        username=user.username or user.first_name,
        text="Cek kondisi router",
    )
    await _safe_reply_text(update.message, result["reply"])


async def firmware_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /firmware and /check_update command to inspect RouterOS & RouterBOARD firmware."""
    user = update.effective_user
    if not user or not security_manager.is_user_authorized(user.id):
        return

    args = context.args or []
    channel = "stable"
    clean_args = []
    for a in args:
        if a.lower() in ("stable", "long-term", "testing", "development"):
            channel = a.lower()
        else:
            clean_args.append(a)

    target_query = " ".join(clean_args).strip()
    target_dev = settings.find_device(target_query)
    resolved_name = target_dev.name if target_dev else settings.default_device_name

    loading_msg = await update.message.reply_text(
        f"⏳ Memeriksa status firmware dan pembaruan RouterOS pada **{resolved_name}** (Channel: `{channel}`)...",
        parse_mode=ParseMode.MARKDOWN,
    )

    fw_res = await asyncio.to_thread(TOOL_REGISTRY["get_firmware_status"], device=resolved_name, channel=channel)
    fw_data = fw_res.get("data") or {}

    can_write = security_manager.can_user_write(user.id)
    keyboard = make_firmware_keyboard(
        device_name=resolved_name,
        has_os_update=fw_data.get("has_os_update", False) and can_write,
        has_rb_update=fw_data.get("has_rb_update", False) and can_write,
        can_write=can_write,
    )
    card_text = format_firmware_card(fw_data, resolved_name)
    await _safe_edit_message_text(loading_msg, card_text, reply_markup=keyboard)


async def upgrade_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /upgrade command to update RouterOS and firmware with 2-phase safety confirmation."""
    user = update.effective_user
    if not user or not security_manager.is_user_authorized(user.id):
        return

    if not security_manager.can_user_write(user.id):
        await update.message.reply_text(
            "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**.\n"
            "Operasi upgrade firmware hanya dapat diajukan oleh Administrator sistem.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    args = context.args or []
    # Syntax: /upgrade [device_name] [channel] [force]
    force = "force" in [a.lower() for a in args]
    clean_args = [a for a in args if a.lower() != "force"]

    channel = "stable"
    for ch in ("stable", "long-term", "testing", "development"):
        if any(a.lower() == ch for a in clean_args):
            channel = ch
            clean_args = [a for a in clean_args if a.lower() != ch]
            break

    target_query = " ".join(clean_args).strip()
    target_dev = settings.find_device(target_query)
    resolved_name = target_dev.name if target_dev else settings.default_device_name

    loading_msg = await update.message.reply_text(
        f"⏳ Memeriksa server pembaruan MikroTik untuk **{resolved_name}** (Channel: `{channel}`)...",
        parse_mode=ParseMode.MARKDOWN,
    )

    fw_res = await asyncio.to_thread(TOOL_REGISTRY["get_firmware_status"], device=resolved_name, channel=channel)
    fw_data = fw_res.get("data") or {}
    pkg_info = fw_data.get("package_update") or {}
    rb_info = fw_data.get("routerboard") or {}

    curr = pkg_info.get("installed_version") or pkg_info.get("installed-version") or rb_info.get("current_firmware") or rb_info.get("current-firmware") or "-"
    has_os_update = fw_data.get("has_os_update", False)
    latest = pkg_info.get("latest_version") or pkg_info.get("latest-version") or (curr if not has_os_update else "-")

    if not has_os_update and not force:
        already_up_to_date_msg = (
            f"✅ **Sistem Sudah Versi Terbaru!**\n\n"
            f"• Target Router : **{resolved_name}**\n"
            f"• Versi Aktif   : `v{curr}` (Channel: `{channel}`)\n"
            f"• Versi Terbaru : `v{latest}`\n"
            f"• Status        : Tidak ada paket update baru di server MikroTik.\n\n"
            f"💡 *Jika Anda ingin memaksakan instalasi ulang paket, gunakan perintah:*\n"
            f"`/upgrade {resolved_name} {channel} force`"
        )
        keyboard = make_firmware_keyboard(
            device_name=resolved_name,
            has_os_update=False,
            has_rb_update=fw_data.get("has_rb_update", False) and security_manager.can_user_write(user.id),
            can_write=security_manager.can_user_write(user.id),
        )
        await _safe_edit_message_text(loading_msg, already_up_to_date_msg, reply_markup=keyboard)
        return

    # Trigger Two-Phase Confirmation
    pending = confirmation_manager.create_pending_action(
        user_id=user.id,
        device_name=resolved_name,
        action_name="install_router_update",
        arguments={"device": resolved_name, "channel": channel, "target_version": latest},
        description=f"Upgrade RouterOS {resolved_name} ({curr} -> {latest})",
    )

    confirm_card = (
        f"🚨 **Konfirmasi Diperlukan: UPGRADE ROUTEROS**\n\n"
        f"• Target Router   : **{resolved_name}**\n"
        f"• Aksi            : `install_router_update`\n"
        f"• Versi Saat Ini  : `v{curr}`\n"
        f"• Versi Target    : `v{latest}` (Channel: `{channel}`)\n\n"
        f"⚠️ **PERINGATAN KESELAMATAN JARINGAN**:\n"
        f"1. Router akan mengunduh paket pembaruan dan melakukan **REBOOT otomatis**.\n"
        f"2. Seluruh koneksi jaringan & internet akan offline sementara selama **1-3 menit**.\n"
        f"3. Pastikan pasokan listrik router stabil selama proses penulisan firmware flash memory!\n\n"
        f"Apakah Anda yakin ingin memulai proses upgrade firmware sekarang?\n"
        f"👉 Balas **Ya** atau klik tombol [ YA ] di bawah untuk mengeksekusi, atau **Batal** untuk membatalkan."
    )
    keyboard = make_confirmation_keyboard(pending.token)
    await _safe_edit_message_text(loading_msg, confirm_card, reply_markup=keyboard)


async def reboot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /reboot and /restart command with 2-phase safety confirmation."""
    user = update.effective_user
    if not user or not security_manager.is_user_authorized(user.id):
        return

    if not security_manager.can_user_write(user.id):
        await update.message.reply_text(
            "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**.\n"
            "Operasi reboot router hanya dapat dilakukan oleh Administrator sistem.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    args = context.args or []
    target_query = " ".join(args).strip()
    target_dev = settings.find_device(target_query)
    resolved_name = target_dev.name if target_dev else settings.default_device_name

    pending = confirmation_manager.create_pending_action(
        user_id=user.id,
        device_name=resolved_name,
        action_name="system_reboot",
        arguments={"device": resolved_name},
        description=f"Reboot router {resolved_name}",
    )

    confirm_card = (
        f"🚨 **Konfirmasi Diperlukan: REBOOT ROUTER**\n\n"
        f"• Target Router : **{resolved_name}**\n"
        f"• Aksi          : `system_reboot`\n\n"
        f"⚠️ **PERINGATAN RISIKO**:\n"
        f"1. Router akan memutus seluruh koneksi jaringan & internet untuk sementara.\n"
        f"2. Perangkat akan melakukan booting ulang dan aktif kembali dalam 30-60 detik.\n\n"
        f"Apakah Anda yakin ingin me-reboot router sekarang?\n"
        f"👉 Klik tombol [ YA ] di bawah atau balas **Ya** untuk mengeksekusi, atau **Batal** untuk membatalkan."
    )
    keyboard = make_confirmation_keyboard(pending.token)
    await _safe_reply_text(update.message, confirm_card, reply_markup=keyboard)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /clear command to reset user conversation memory buffer."""
    user = update.effective_user
    if not user or not security_manager.is_user_authorized(user.id):
        return

    conversation_memory.clear(user.id)
    await _safe_reply_text(
        update.message,
        "🧹 **Riwayat percakapan telah dibersihkan.**\nSesi dialog baru dimulai!"
    )


async def audit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /audit command."""
    user = update.effective_user
    if not user or not security_manager.is_user_authorized(user.id):
        return

    logs = audit_logger.get_recent_logs(limit=8)
    text = format_audit_logs(logs)
    await _safe_reply_text(update.message, text)


async def discover_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /discover command."""
    user = update.effective_user
    if not user or not security_manager.is_user_authorized(user.id):
        return

    msg = await update.message.reply_text("🔍 Memindai jaringan lokal untuk menemukan router MikroTik...", parse_mode=ParseMode.MARKDOWN)

    # Scan default subnet non-blockingly
    discovered = await asyncio.to_thread(device_discovery.scan_subnet, subnet_cidr="10.20.33.0/24")
    if not discovered:
        # Also try default 192.168.88.0/24
        discovered = await asyncio.to_thread(device_discovery.scan_subnet, subnet_cidr="192.168.88.0/24")

    if not discovered:
        await msg.edit_text("🔍 Pemindaian selesai. Tidak ditemukan perangkat MikroTik baru pada subnet lokal.", parse_mode=ParseMode.MARKDOWN)
        return

    lines = [f"🔍 **Hasil Pemindaian Jaringan MikroTik:**\n"]
    for d in discovered:
        p_str = ", ".join(map(str, d.get("open_ports", [])))
        proto = d.get('suggested_protocol', 'api')
        port = 8728 if proto == 'api' else 80
        lines.append(f"• IP: `{d.get('ip')}` | Open Ports: `[{p_str}]` | Saran: `{proto.upper()}`")
        lines.append(f"  👉 Salin: `/add_device Router_Baru {d.get('ip')} {port} {proto} admin password`\n")

    lines.append("💡 *Klik atau salin perintah di atas untuk langsung mendaftarkan router tanpa membuka kode!*")
    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def topology_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /topology command (view map, scan, diagram, compare diff)."""
    user = update.effective_user
    if not user:
        return

    if not security_manager.is_user_authorized(user.id):
        await update.message.reply_text(
            f"⛔ **Akses Ditolak**\nUser ID `{user.id}` tidak diizinkan menggunakan bot ini.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    args = context.args or []
    subcmd = args[0].lower() if args else "summary"

    await update.message.chat.send_action("typing")

    if subcmd in ("scan", "refresh", "pindai"):
        progress_msg = await update.message.reply_text("🔄 **Memindai seluruh router MikroTik...**\n_Mohon tunggu sebentar._", parse_mode=ParseMode.MARKDOWN)
        subnet = args[1] if len(args) > 1 else ""
        res = await asyncio.to_thread(TOOL_REGISTRY["scan_network_topology"], subnet=subnet, force_refresh=True)
        img_path = res.get("image_path")
        text_summary = res.get("text_summary", "✅ Pemindaian topologi selesai.")

        if img_path and Path(img_path).exists():
            try:
                with open(img_path, "rb") as photo_f:
                    await update.message.reply_photo(
                        photo=photo_f,
                        caption=text_summary[:1024],
                        parse_mode=ParseMode.MARKDOWN,
                    )
                await progress_msg.delete()
                return
            except Exception as pe:
                logger.warning("Gagal mengirim gambar topologi: %s", pe)

        await _safe_edit_message_text(progress_msg, text_summary)

    elif subcmd in ("image", "diagram", "gambar", "visual"):
        progress_msg = await update.message.reply_text("🎨 **Menghasilkan diagram visual topologi jaringan...**", parse_mode=ParseMode.MARKDOWN)
        res = await asyncio.to_thread(TOOL_REGISTRY["generate_topology_diagram"])
        img_path = res.get("image_path")
        caption = res.get("caption", "🌐 Bagan Topologi Jaringan MikroTik")

        if img_path and Path(img_path).exists():
            try:
                with open(img_path, "rb") as photo_f:
                    await update.message.reply_photo(
                        photo=photo_f,
                        caption=caption[:1024],
                        parse_mode=ParseMode.MARKDOWN,
                    )
                await progress_msg.delete()
                return
            except Exception as pe:
                logger.warning("Gagal mengirim photo: %s", pe)

        await _safe_edit_message_text(progress_msg, "⚠️ Gagal menghasilkan diagram visual gambar topologi.")

    elif subcmd in ("diff", "compare", "perubahan", "bandingkan"):
        res = await asyncio.to_thread(TOOL_REGISTRY["compare_topology_snapshots"])
        summary = res.get("summary_text", "✅ Tidak ada riwayat snapshot untuk dibandingkan.")
        await _safe_reply_text(update.message, summary)

    else:
        # Default: summary view
        res = await asyncio.to_thread(TOOL_REGISTRY["get_network_topology"], format="summary")
        text = res.get("text", "🌐 Tidak ada data topologi yang tersedia.")
        await _safe_reply_text(update.message, text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for natural language user messages."""
    user = update.effective_user
    if not user:
        return

    if not security_manager.is_user_authorized(user.id):
        await update.message.reply_text(
            f"⛔ **Akses Ditolak**\nUser ID `{user.id}` tidak diizinkan menggunakan bot ini.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    text = update.message.text
    if not text:
        return

    # Send typing action indicator
    await update.message.chat.send_action("typing")

    username = user.first_name or user.username or f"User_{user.id}"
    prior_pending = confirmation_manager.get_pending_for_user(user.id)
    try:
        result = await asyncio.to_thread(hermes_agent.process_message, user_id=user.id, username=username, text=text)
        reply_text = result.get("reply", "Maaf, tidak ada respon.")
        pending_act = result.get("pending_action")

        if pending_act:
            keyboard = make_confirmation_keyboard(pending_act.token)
            await _safe_reply_text(update.message, reply_text, reply_markup=keyboard)
        else:
            chat_id = update.effective_chat.id if update.effective_chat else user.id
            if prior_pending and not confirmation_manager.get_pending_for_user(user.id):
                if prior_pending.action_name == "upgrade_routerboard_firmware":
                    reboot_kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Reboot Router Sekarang", callback_data=f"fw_reboot:{prior_pending.device_name}")]
                    ])
                    await _safe_reply_text(update.message, reply_text, reply_markup=reboot_kb)
                else:
                    await _safe_reply_text(update.message, reply_text)

                if prior_pending.action_name == "install_router_update":
                    target_ver = prior_pending.arguments.get("target_version", "")
                    asyncio.create_task(
                        watch_router_upgrade(
                            bot=context.bot,
                            chat_id=chat_id,
                            device_name=prior_pending.device_name,
                            target_version=target_ver,
                        )
                    )
                elif prior_pending.action_name == "system_reboot":
                    asyncio.create_task(
                        watch_router_reboot(
                            bot=context.bot,
                            chat_id=chat_id,
                            device_name=prior_pending.device_name,
                        )
                    )
            else:
                image_path = result.get("image_path")
                if image_path and Path(image_path).exists():
                    try:
                        with open(image_path, "rb") as photo_f:
                            await update.message.reply_photo(
                                photo=photo_f,
                                caption=reply_text[:1024] if reply_text else None,
                                parse_mode=ParseMode.MARKDOWN,
                            )
                    except Exception as pe:
                        logger.warning("Gagal mengirim photo Telegram: %s. Fallback ke teks biasa.", pe)
                        await _safe_reply_text(update.message, reply_text)
                else:
                    await _safe_reply_text(update.message, reply_text)
    except Exception as e:
        logger.error("Error saat memproses pesan user: %s", e, exc_info=True)
        await _safe_reply_text(
            update.message,
            f"⚠️ Terjadi kendala saat memproses permintaan Anda: `{e}`\n"
            f"Silakan coba sesaat lagi atau gunakan perintah `/status`.",
        )


async def watch_router_upgrade(
    bot: Any,
    chat_id: int,
    device_name: str,
    target_version: str = "",
    timeout_seconds: int = 300,
) -> None:
    """
    Background watcher that monitors router recovery after a RouterOS upgrade.
    Polls the router until it comes back online and sends a completion notification.
    """
    start_time = time.time()
    # Initial pause for the router to initiate download & trigger hardware reboot
    await asyncio.sleep(20)

    client = device_manager.get_client(device_name)
    is_back = False

    while (time.time() - start_time) < timeout_seconds:
        try:
            conn = await asyncio.to_thread(client.test_connection)
            if conn.success:
                is_back = True
                break
        except Exception:
            pass
        await asyncio.sleep(8)

    elapsed_min = int((time.time() - start_time) / 60)
    elapsed_sec = int((time.time() - start_time) % 60)
    time_str = f"{elapsed_min}m {elapsed_sec}s" if elapsed_min > 0 else f"{elapsed_sec}s"

    if is_back:
        await asyncio.sleep(4)
        fw = await asyncio.to_thread(client.get_firmware_status)
        fw_data = fw.data if fw.success and isinstance(fw.data, dict) else {}
        pkg = fw_data.get("package_update") or {}
        rb = fw_data.get("routerboard") or {}
        new_version = (
            pkg.get("installed_version")
            or pkg.get("installed-version")
            or rb.get("current_firmware")
            or rb.get("current-firmware")
            or target_version
            or "terbaru"
        )
        rb_upg = rb.get("upgrade_firmware") or rb.get("upgrade-firmware", "")

        msg = (
            f"🎉 **UPGRADE ROUTEROS SELESAI & ROUTER KEMBALI ONLINE!**\n\n"
            f"• Target Router : **{device_name}**\n"
            f"• Versi Baru    : `v{new_version}`\n"
            f"• Waktu Proses  : `{time_str}`\n"
            f"• Status        : 🟢 **Normal & Siap Digunakan**\n\n"
        )
        if fw_data.get("has_rb_update"):
            msg += (
                f"⚡ *Catatan: Firmware bootloader BIOS baru (`v{rb_upg}`) tersedia!*\n"
                f"Ketik `/firmware {device_name}` atau klik tombol firmware untuk memperbarui bootloader chip BIOS."
            )
        else:
            msg += "✨ Seluruh paket sistem RouterOS dan firmware telah mutakhir."

        try:
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error("Gagal mengirim notifikasi upgrade selesai ke chat_id %s: %s", chat_id, e)
    else:
        warn_msg = (
            f"⚠️ **Pemberitahuan Waktu Reboot Router**\n\n"
            f"Perangkat **{device_name}** belum merespons setelah `{time_str}`.\n"
            f"Router mungkin memerlukan waktu tambahan untuk memproses penulisan flash memory.\n"
            f"Gunakan perintah `/status` atau `/firmware {device_name}` beberapa saat lagi untuk mengecek status."
        )
        try:
            await bot.send_message(chat_id=chat_id, text=warn_msg, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error("Gagal mengirim notifikasi timeout upgrade ke chat_id %s: %s", chat_id, e)


async def watch_router_reboot(
    bot: Any,
    chat_id: int,
    device_name: str,
    timeout_seconds: int = 180,
) -> None:
    """Background watcher that monitors router recovery after a reboot."""
    start_time = time.time()
    await asyncio.sleep(15)

    client = device_manager.get_client(device_name)
    is_back = False

    while (time.time() - start_time) < timeout_seconds:
        try:
            conn = await asyncio.to_thread(client.test_connection)
            if conn.success:
                is_back = True
                break
        except Exception:
            pass
        await asyncio.sleep(5)

    elapsed_sec = int(time.time() - start_time)
    if is_back:
        msg = (
            f"🟢 **ROUTER TELAH KEMBALI ONLINE!**\n\n"
            f"• Target Router : **{device_name}**\n"
            f"• Durasi Reboot : `{elapsed_sec} detik`\n"
            f"• Status Jaringan: Normal & Terkoneksi kembali."
        )
        try:
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error("Gagal mengirim notifikasi reboot selesai ke chat_id %s: %s", chat_id, e)


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for inline button confirmation clicks."""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    data = query.data or ""

    if not security_manager.is_user_authorized(user.id):
        await query.edit_message_text("⛔ Anda tidak memiliki izin untuk tindakan ini.")
        return

    if data.startswith("conf_yes:"):
        token = data.split(":", 1)[1]
        action = confirmation_manager.get_action_by_token(token)
        if not action:
            await query.edit_message_text("⚠️ Aksi telah kedaluwarsa atau sudah dieksekusi sebelumnya.")
            return

        if not security_manager.can_user_write(user.id):
            await query.answer(
                "⛔ Akses Terbatas: Role Anda adalah Viewer (Read-Only). Hanya Admin yang dapat menyetujui perubahan.",
                show_alert=True,
            )
            return

        if action.user_id != user.id:
            await query.answer("Konfirmasi hanya dapat disetujui oleh pengguna yang mengajukan.", show_alert=True)
            return

        await _safe_edit_message_text(query, f"⏳ **Memproses eksekusi `{action.action_name}` pada {action.device_name}...**")
        res = await asyncio.to_thread(confirmation_manager.execute_action, token)

        audit_logger.log_event(
            telegram_user_id=user.id,
            telegram_user_name=user.username or user.first_name,
            user_prompt=f"Callback Approval for {action.action_name}",
            target_device=action.device_name,
            action_category="CONFIG",
            action_name=action.action_name,
            confirmation_status="APPROVED",
            result_status="SUCCESS" if res.success else "FAILED",
            details=res.to_dict(),
        )

        chat_id = query.message.chat_id if query.message else user.id

        if action.action_name == "upgrade_routerboard_firmware" and res.success:
            final_msg = (
                f"{res.message}\n\n"
                f"💡 *Klik tombol di bawah jika Anda ingin langsung me-reboot router sekarang agar firmware baru aktif.*"
            )
            reboot_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Reboot Router Sekarang", callback_data=f"fw_reboot:{action.device_name}")]
            ])
            await _safe_edit_message_text(query, final_msg, reply_markup=reboot_kb)
        else:
            final_msg = f"{res.message}\n\nOperasi selesai."
            await _safe_edit_message_text(query, final_msg)

        # Trigger proactive background recovery watchers
        if action.action_name == "install_router_update" and res.success:
            target_ver = action.arguments.get("target_version", "")
            asyncio.create_task(
                watch_router_upgrade(
                    bot=context.bot,
                    chat_id=chat_id,
                    device_name=action.device_name,
                    target_version=target_ver,
                )
            )
        elif action.action_name == "system_reboot" and res.success:
            asyncio.create_task(
                watch_router_reboot(
                    bot=context.bot,
                    chat_id=chat_id,
                    device_name=action.device_name,
                )
            )

    elif data.startswith("conf_no:"):
        token = data.split(":", 1)[1]
        action = confirmation_manager.get_action_by_token(token)
        if action:
            confirmation_manager.cancel_action(token)
            audit_logger.log_event(
                telegram_user_id=user.id,
                telegram_user_name=user.username or user.first_name,
                user_prompt=f"Callback Cancel for {action.action_name}",
                target_device=action.device_name,
                action_category="CONFIG",
                action_name=action.action_name,
                confirmation_status="REJECTED",
                result_status="CANCELLED",
            )
        await _safe_edit_message_text(query, "❌ **Konfigurasi telah dibatalkan oleh pengguna.**")

    elif data.startswith("fw_reboot:"):
        dev_name = data.split(":", 1)[1]
        if not security_manager.can_user_write(user.id):
            await query.answer("⛔ Akses Terbatas: Hanya Administrator yang dapat me-reboot router.", show_alert=True)
            return

        target_dev = settings.find_device(dev_name)
        resolved_name = target_dev.name if target_dev else dev_name

        pending = confirmation_manager.create_pending_action(
            user_id=user.id,
            device_name=resolved_name,
            action_name="system_reboot",
            arguments={"device": resolved_name},
            description=f"Reboot router {resolved_name}",
        )

        confirm_card = (
            f"🚨 **Konfirmasi Diperlukan: REBOOT ROUTER**\n\n"
            f"• Target Router : **{resolved_name}**\n"
            f"• Aksi          : `system_reboot`\n\n"
            f"⚠️ **PERINGATAN RISIKO**:\n"
            f"1. Seluruh koneksi jaringan & internet akan terputus sementara.\n"
            f"2. Router akan booting ulang dan kembali aktif dalam 30-60 detik.\n\n"
            f"Lanjutkan reboot perangkat sekarang?"
        )
        keyboard = make_confirmation_keyboard(pending.token)
        await _safe_edit_message_text(query, confirm_card, reply_markup=keyboard)

    elif data.startswith("fw_os_upg:"):
        dev_name = data.split(":", 1)[1]
        if not security_manager.can_user_write(user.id):
            await query.answer("⛔ Akses Terbatas: Hanya Administrator yang dapat melakukan upgrade firmware.", show_alert=True)
            return

        target_dev = settings.find_device(dev_name)
        resolved_name = target_dev.name if target_dev else dev_name

        fw_res = await asyncio.to_thread(TOOL_REGISTRY["get_firmware_status"], device=resolved_name)
        fw_data = fw_res.get("data") or {}
        pkg_info = fw_data.get("package_update") or {}
        rb_info = fw_data.get("routerboard") or {}

        curr = pkg_info.get("installed_version") or pkg_info.get("installed-version") or rb_info.get("current_firmware") or rb_info.get("current-firmware", "-")
        target = pkg_info.get("latest_version") or pkg_info.get("latest-version") or "-"
        channel = pkg_info.get("channel", "stable")

        pending = confirmation_manager.create_pending_action(
            user_id=user.id,
            device_name=resolved_name,
            action_name="install_router_update",
            arguments={"device": resolved_name, "channel": channel, "target_version": target},
            description=f"Upgrade RouterOS {resolved_name} ({curr} -> {target})",
        )

        confirm_card = (
            f"🚨 **Konfirmasi Diperlukan: UPGRADE ROUTEROS**\n\n"
            f"• Target Router   : **{resolved_name}**\n"
            f"• Aksi            : `install_router_update`\n"
            f"• Versi Saat Ini  : `v{curr}`\n"
            f"• Versi Target    : `v{target}` (Channel: `{channel}`)\n\n"
            f"⚠️ **PERINGATAN KESELAMATAN JARINGAN**:\n"
            f"1. Router akan mengunduh paket update dan melakukan **REBOOT otomatis**.\n"
            f"2. Jaringan/Internet akan offline sementara selama **1-3 menit**.\n"
            f"3. Pastikan catu daya listrik stabil selama proses upgrade.\n\n"
            f"Lanjutkan upgrade firmware sekarang?"
        )
        keyboard = make_confirmation_keyboard(pending.token)
        await _safe_edit_message_text(query, confirm_card, reply_markup=keyboard)

    elif data.startswith("fw_rb_upg:"):
        dev_name = data.split(":", 1)[1]
        if not security_manager.can_user_write(user.id):
            await query.answer("⛔ Akses Terbatas: Hanya Administrator yang dapat meng-upgrade bootloader.", show_alert=True)
            return

        target_dev = settings.find_device(dev_name)
        resolved_name = target_dev.name if target_dev else dev_name

        fw_res = await asyncio.to_thread(TOOL_REGISTRY["get_firmware_status"], device=resolved_name)
        fw_data = fw_res.get("data") or {}
        rb_info = fw_data.get("routerboard") or {}

        curr = rb_info.get("current_firmware") or rb_info.get("current-firmware") or "-"
        target = rb_info.get("upgrade_firmware") or rb_info.get("upgrade-firmware") or "-"

        pending = confirmation_manager.create_pending_action(
            user_id=user.id,
            device_name=resolved_name,
            action_name="upgrade_routerboard_firmware",
            arguments={"device": resolved_name},
            description=f"Upgrade bootloader firmware RouterBOARD {resolved_name} ({curr} -> {target})",
        )

        confirm_card = (
            f"⚡ **Konfirmasi Diperlukan: UPGRADE BOOTLOADER BIOS**\n\n"
            f"• Target Router    : **{resolved_name}**\n"
            f"• Model Board      : `{rb_info.get('model', '-')}`\n"
            f"• Firmware Aktif   : `v{curr}`\n"
            f"• Firmware Baru    : `v{target}`\n\n"
            f"⚠️ **INFORMASI PENTING**:\n"
            f"Firmware bootloader BIOS akan diperbarui. Setelah proses ini, router perlu direboot agar firmware baru aktif.\n\n"
            f"Lanjutkan upgrade bootloader BIOS sekarang?"
        )
        keyboard = make_confirmation_keyboard(pending.token)
        await _safe_edit_message_text(query, confirm_card, reply_markup=keyboard)

    elif data.startswith("fw_check:"):
        dev_name = data.split(":", 1)[1]
        target_dev = settings.find_device(dev_name)
        resolved_name = target_dev.name if target_dev else (dev_name or settings.default_device_name)

        fw_res = await asyncio.to_thread(TOOL_REGISTRY["get_firmware_status"], device=resolved_name)
        fw_data = fw_res.get("data") or {}

        can_write = security_manager.can_user_write(user.id)
        keyboard = make_firmware_keyboard(
            device_name=resolved_name,
            has_os_update=fw_data.get("has_os_update", False) and can_write,
            has_rb_update=fw_data.get("has_rb_update", False) and can_write,
            can_write=can_write,
        )
        card_text = format_firmware_card(fw_data, resolved_name)
        await _safe_edit_message_text(query, card_text, reply_markup=keyboard)
