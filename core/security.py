"""
Security and RBAC Module (PRD Section 16 & 17).
Handles Telegram whitelist, permission classification, dangerous command protection,
and credential redaction.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from config.settings import settings


class SecurityManager:
    def __init__(self):
        # Exact dangerous command patterns that are unconditionally forbidden
        self.dangerous_patterns = [
            r"\breset-configuration\b",
            r"\breset\s+configuration\b",
            r"\bfactory-reset\b",
            r"\bfactory\s+reset\b",
            r"\bsetelan\s+pabrik\b",
            r"/system\s+reset(-configuration)?\b",
            r"\bformat\s+(disk|drive|nand|storage|system)\b",
            r"/system\s+format\b",
            r"\bhapus\s+semua\s+(konfigurasi|data|setting)\b",
            r"\bdelete\s+all\s+(config|configuration)\b",
            r"\bwipe\s+(router|config|configuration|all)\b",
        ]
        # Imperative reset commands on the router
        self.imperative_reset_patterns = [
            r"\b(reset|wipe)\s+(router|mikrotik|perangkat)\b",
            r"\b(lakukan|tolong|coba)?\s*reset\s+(total|sekarang|ulang)\b",
        ]

    def is_user_authorized(self, telegram_user_id: int) -> bool:
        """Check if Telegram user is in the authorized whitelist."""
        # If whitelist is empty, allow access or default to false
        if not settings.allowed_telegram_ids:
            return True
        return telegram_user_id in settings.allowed_telegram_ids

    def get_user_role(self, telegram_user_id: int) -> str:
        """
        Get the RBAC role for the user: 'ADMIN', 'VIEWER', or 'UNAUTHORIZED'.
        """
        if not self.is_user_authorized(telegram_user_id):
            return "UNAUTHORIZED"
        if telegram_user_id in settings.viewer_telegram_ids:
            return "VIEWER"
        if telegram_user_id in settings.admin_telegram_ids or not settings.admin_telegram_ids:
            return "ADMIN"
        return "VIEWER"

    def can_user_write(self, telegram_user_id: int) -> bool:
        """
        Check if user has permission to execute WRITE / configuration changes.
        """
        return self.get_user_role(telegram_user_id) == "ADMIN"

    def is_dangerous(self, text: str, is_admin: bool = False) -> Tuple[bool, str]:
        """
        Check if user request contains high-risk / destructive commands.
        PRD Section 16: Dangerous Operation Protection.
        If is_admin is True, reboot and shutdown proceed to Two-Phase Confirmation.
        Innocent questions containing 'format' or 'reset' (e.g. 'format ip apa', 'kenapa router reset') are NOT blocked.
        """
        lower = text.lower().strip()

        # Check if query is merely informational / inquiring about format, history, reasons
        is_informational = any(
            w in lower for w in (
                "kenapa", "mengapa", "kapan", "apakah", "apa format", "formatnya apa",
                "format perintah", "format pesan", "bagaimana format", "contoh format",
                "riwayat", "history", "log", "catatan", "alasan", "penyebab"
            )
        )
        if is_informational and not any(re.search(p, lower) for p in self.dangerous_patterns):
            return False, ""

        # Check unconditional destructive patterns
        for pat in self.dangerous_patterns:
            m = re.search(pat, lower)
            if m:
                kw = m.group(0)
                warning_msg = (
                    "⚠️ OPERASI BERISIKO TINGGI DITOLAK\n\n"
                    "Operasi ini terdeteksi sebagai tindakan berbahaya (Reset / Factory Reset / Format / Wipe):\n"
                    f"• Pola terdeteksi: `{kw}`\n\n"
                    "Dampak risiko:\n"
                    "- Seluruh konfigurasi router dapat hilang permanen\n"
                    "- Koneksi jaringan terputus total\n"
                    "- Akses manajemen router terisolasi\n\n"
                    "Operasi ini TIDAK TERSEDIA melalui AI Bot / Telegram Bot demi keamanan.\n"
                    "Silakan lakukan secara manual melalui Winbox atau konsol fisik router."
                )
                return True, warning_msg

        # Check imperative reset commands
        for pat in self.imperative_reset_patterns:
            m = re.search(pat, lower)
            if m:
                kw = m.group(0)
                warning_msg = (
                    "⚠️ OPERASI BERISIKO TINGGI - RESET ROUTER DITOLAK\n\n"
                    f"Perintah terdeteksi: `{kw}`\n"
                    "Reset konfigurasi MikroTik tidak diizinkan melalui Telegram Bot untuk mencegah kehilangan konfigurasi jaringan.\n"
                    "Operasi ini **TIDAK TERSEDIA** melalui AI Bot / Telegram Bot demi keamanan.\n"
                    "Gunakan Winbox atau Netinstall jika benar-benar ingin mereset router secara langsung."
                )
                return True, warning_msg

        # Reboots / Shutdowns:
        # If Admin: permitted to proceed to 2-Phase confirmation
        # If Viewer: blocked if it's an imperative command to reboot
        is_reboot_cmd = bool(re.search(r"\b(reboot|restart|shutdown|matikan\s+router)\b", lower))
        if is_reboot_cmd:
            if is_admin:
                return False, ""
            else:
                return True, (
                    "⚠️ OPERASI BERISIKO TINGGI: ⛔ **Akses Terbatas**\n"
                    "Akun Anda memiliki role **Viewer (Read-Only)**.\n"
                    "Perintah reboot atau shutdown router hanya dapat diajukan oleh Administrator."
                )

        # Firmware Upgrade / RouterOS Update:
        # If Admin: permitted to proceed to 2-Phase confirmation
        # If Viewer: blocked if it's an imperative command to upgrade
        is_upgrade_cmd = bool(re.search(r"\b(upgrade|update|perbarui|install)\s+(firmware|frimware|fremware|routeros|router|bootloader|bios|routerboard)\b", lower))
        is_check_query = any(w in lower for w in ("cek", "status", "info", "lihat", "apakah", "kapan", "ada"))
        if is_upgrade_cmd and not is_check_query:
            if is_admin:
                return False, ""
            else:
                return True, (
                    "⚠️ OPERASI BERISIKO TINGGI: ⛔ **Akses Terbatas**\n"
                    "Akun Anda memiliki role **Viewer (Read-Only)**.\n"
                    "Perintah upgrade firmware atau update RouterOS hanya dapat diajukan oleh Administrator."
                )

        return False, ""

    def classify_permission(self, action_name: str) -> str:
        """Classify action as READ, WRITE, or DANGEROUS."""
        action_clean = action_name.lower().strip()

        # Check dangerous
        for dang in settings.dangerous_operations:
            if dang.lower() in action_clean:
                return "DANGEROUS"

        # Check built-in write operations
        built_in_writes = [
            "create_hotspot_user",
            "delete_hotspot_user",
            "set_interface_state",
            "system_reboot",
            "system_shutdown",
            "set_identity",
            "create_system_user",
            "delete_system_user",
            "set_clock_timezone",
            "send_router_email",
            "add_netwatch",
            "add_traffic_monitor",
            "install_router_update",
            "upgrade_routerboard_firmware",
        ]
        for w in built_in_writes:
            if w.lower() in action_clean:
                return "WRITE"

        # Check write from config
        for write in settings.write_operations:
            if write.lower() in action_clean:
                return "WRITE"

        return "READ"

    def redact_secrets(self, text: str) -> str:
        """Scrub router credentials and secret keys from logs or LLM responses."""
        if not text:
            return text
        # Redact passwords (quoted or unquoted)
        redacted = re.sub(r'(?i)(password\s*[:=]\s*)(["\']?)([^"\'\s,]+)\2', r'\1\2[REDACTED]\2', text)
        # Redact API keys and tokens
        redacted = re.sub(r'(?i)(api[_-]?key\s*[:=]\s*)(["\']?)([^"\'\s,]+)\2', r'\1\2[REDACTED]\2', redacted)
        redacted = re.sub(r'(?i)(bot[_-]?token\s*[:=]\s*)(["\']?)([^"\'\s,]+)\2', r'\1\2[REDACTED]\2', redacted)
        redacted = re.sub(r'(?i)(secret\s*[:=]\s*)(["\']?)([^"\'\s,]+)\2', r'\1\2[REDACTED]\2', redacted)

        # Scrub known active device passwords if present
        for dev in settings.devices:
            if dev.password and len(dev.password) >= 4:
                redacted = redacted.replace(dev.password, "[REDACTED]")

        return redacted


security_manager = SecurityManager()
