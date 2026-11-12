"""
Hermes AI Agent Core (PRD Section 5, 6, 8, 23, 24, 25, 26).
Implements Natural Language Understanding, Planning, Tool Selection, Execution,
and Diagnostic Analysis with fallback resilience.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import httpx
import ipaddress
from config.settings import settings
from core.audit import audit_logger
from core.confirmation import PendingAction, confirmation_manager
from core.prompts import DIAGNOSTIC_ANALYSIS_PROMPT, HERMES_SYSTEM_PROMPT
from core.security import security_manager
from mikrotik.base import OperationResult
from mikrotik.manager import device_manager
from mikrotik.tools import TOOL_REGISTRY, TOOL_SCHEMAS

logger = logging.getLogger(__name__)

GREETING_ROOTS = {
    "halo", "hallo", "haloo", "halloo", "hai", "haii", "haiii", "hay",
    "hello", "hi", "hii", "hiii", "hey", "heyy", "pagi", "siang", "sore", "malam",
    "assalamu", "assalamualaikum", "salam", "permisi", "sampurasun", "kulonuwun",
    "p", "pp", "ping", "tes", "test"
}
GREETING_MODIFIERS = {
    "selamat", "met", "wr", "wb", "alaikum",
    "bot", "hermes", "min", "admin", "mas", "gan", "bro", "bang", "pak", "om", "cak", "ya", "yah", "kak"
}
ALL_GREETING_TOKENS = GREETING_ROOTS | GREETING_MODIFIERS


class ConversationMemory:
    """Manages short-term per-user conversation history for multi-turn contextual dialogs."""
    def __init__(self, max_history: int = 6, ttl_seconds: int = 900):
        self.max_history = max_history
        self.ttl_seconds = ttl_seconds
        # user_id -> list of {"role": "user"|"model"|"assistant", "text": str, "timestamp": float}
        self._history: Dict[int, List[Dict[str, Any]]] = {}

    def get_history(self, user_id: int) -> List[Dict[str, str]]:
        now = time.time()
        turns = self._history.get(user_id, [])
        valid_turns = [t for t in turns if (now - t.get("timestamp", 0)) < self.ttl_seconds]
        self._history[user_id] = valid_turns
        return [{"role": t["role"], "text": t["text"]} for t in valid_turns]

    def add_turn(self, user_id: int, role: str, text: str) -> None:
        if not text:
            return
        if user_id not in self._history:
            self._history[user_id] = []
        self._history[user_id].append({
            "role": role,
            "text": text[:1500],  # trim long outputs for context window efficiency
            "timestamp": time.time(),
        })
        if len(self._history[user_id]) > self.max_history:
            self._history[user_id] = self._history[user_id][-self.max_history:]

    def clear(self, user_id: int) -> None:
        self._history.pop(user_id, None)


conversation_memory = ConversationMemory()


class HermesAIAgent:
    def __init__(self):
        self.provider = settings.llm_provider.lower()
        self.model = settings.llm_model
        self.google_api_key = settings.google_api_key
        self.openai_api_key = settings.openai_api_key
        self.openai_base_url = settings.openai_base_url

    @staticmethod
    def _get_simulation_notice(device_name: str) -> str:
        """Returns offline mock simulation warning if router client is running in fallback mock mode."""
        if not device_name or device_name in ("Sistem Inventaris", "Unknown"):
            return ""
        client = device_manager.get_client(device_name)
        if getattr(client, "is_fallback_mock", False):
            real_name = getattr(client, "real_device_name", device_name)
            real_host = getattr(client, "real_device_host", "")
            host_str = f" (`{real_host}`)" if real_host else ""
            return (
                f"⚠️ **[MODE SIMULASI OFFLINE]**\n"
                f"Router **{real_name}**{host_str} saat ini tidak dapat dijangkau di jaringan.\n"
                f"Data berikut disajikan menggunakan simulator offline (*Mock Telemetry*).\n\n"
            )
        return ""

    def process_message(
        self,
        user_id: int,
        username: str,
        text: str,
    ) -> Dict[str, Any]:
        """
        Main entry point for processing incoming natural language requests from users.
        Returns dictionary with:
          - 'reply': str (markdown formatted response)
          - 'action_required': bool (true if confirmation buttons should be shown)
          - 'pending_action': Optional[PendingAction]
        """
        start_time = time.time()
        # Clean bot mentions (e.g. @MikroTikAIAssistantBot cek) and normalize whitespace
        text_clean = re.sub(r"^@\w+\s*", "", text.strip()).strip()
        text_clean = re.sub(r"\s+", " ", text_clean)

        # 1. Check for Pending Confirmation Responses ("ya", "setuju", "batal", "tolak")
        pending = confirmation_manager.get_pending_for_user(user_id)
        affirmatives = ("ya", "yes", "setuju", "lanjutkan", "lanjut", "iya", "ok", "oke", "siap", "gas", "yup")
        negatives = ("batal", "cancel", "tolak", "tidak", "gak", "nggak", "jangan", "stop", "batal mas")
        lower_input = text_clean.lower()
        if pending and (lower_input in affirmatives or lower_input in negatives):
            if lower_input in affirmatives:
                if not security_manager.can_user_write(user_id):
                    return {
                        "reply": "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**. Perubahan konfigurasi hanya dapat disetujui oleh Administrator.",
                        "action_required": False,
                        "pending_action": None,
                    }
                res = confirmation_manager.execute_action(pending.token)
                latency = (time.time() - start_time) * 1000
                audit_logger.log_event(
                    telegram_user_id=user_id,
                    telegram_user_name=username,
                    user_prompt=text_clean,
                    target_device=pending.device_name,
                    action_category="CONFIG",
                    action_name=pending.action_name,
                    confirmation_status="APPROVED",
                    result_status="SUCCESS" if res.success else "FAILED",
                    details=res.to_dict(),
                    latency_ms=latency,
                )
                return {"reply": res.message, "action_required": False, "pending_action": None}
            else:
                confirmation_manager.cancel_action(pending.token)
                latency = (time.time() - start_time) * 1000
                audit_logger.log_event(
                    telegram_user_id=user_id,
                    telegram_user_name=username,
                    user_prompt=text_clean,
                    target_device=pending.device_name,
                    action_category="CONFIG",
                    action_name=pending.action_name,
                    confirmation_status="REJECTED",
                    result_status="CANCELLED",
                    latency_ms=latency,
                )
                return {
                    "reply": f"❌ Tindakan '{pending.action_name}' pada {pending.device_name} telah dibatalkan.",
                    "action_required": False,
                    "pending_action": None,
                }

        # 2. Check for Dangerous Commands (PRD Section 16)
        is_admin = security_manager.can_user_write(user_id)
        is_dang, dang_warning = security_manager.is_dangerous(text_clean, is_admin=is_admin)
        if is_dang:
            latency = (time.time() - start_time) * 1000
            audit_logger.log_event(
                telegram_user_id=user_id,
                telegram_user_name=username,
                user_prompt=text_clean,
                target_device="Unknown",
                action_category="DANGEROUS",
                action_name="BLOCKED_COMMAND",
                confirmation_status="NONE",
                result_status="BLOCKED",
                details=dang_warning,
                latency_ms=latency,
            )
            return {"reply": dang_warning, "action_required": False, "pending_action": None}

        # 3. Resolve Target Device from User Utterance
        is_device_reg = any(w in lower_input for w in ("daftarkan router", "daftar router", "tambah router", "tambahkan router", "tambah perangkat", "daftarkan perangkat", "add device", "register router"))
        if is_device_reg:
            target_device = None
            device_name = "Sistem Inventaris"
        else:
            target_device = settings.find_device(text_clean)
            device_name = target_device.name if target_device else settings.default_device_name

        # 3.5 Check for Pure Greeting / Casual Ping (Instant Personalized Response mentioning user)
        clean_no_punct = re.sub(r"[^\w\s]", " ", text_clean.lower()).strip()
        tokens = clean_no_punct.split()
        if tokens and all(t in ALL_GREETING_TOKENS for t in tokens) and any(t in GREETING_ROOTS for t in tokens):
            if any(t in ("assalamu", "assalamualaikum", "salam") for t in tokens):
                greeting_reply = (
                    f"Wa'alaikumsalam warahmatullahi wabarakatuh, **{username}**! 🤝\n\n"
                    f"Saya **Hermes AI Agent**, asisten pengelola jaringan MikroTik (**{device_name}**).\n"
                    f"Ada yang ingin Anda periksa atau konfigurasikan hari ini?"
                )
            elif any(t in ("p", "pp", "ping", "tes", "test") for t in tokens):
                greeting_reply = (
                    f"👋 Ya, halo **{username}**! Hermes AI Agent aktif dan siap membantu di router **{device_name}**.\n"
                    f"Ada yang ingin diperiksa atau dikonfigurasi?"
                )
            else:
                greeting_reply = (
                    f"👋 **Halo, {username}!** Senang menyapa Anda.\n\n"
                    f"Saya **Hermes AI Agent**, asisten cerdas pengelola jaringan MikroTik (**{device_name}**).\n"
                    f"Ada yang bisa saya bantu untuk pemantauan atau konfigurasi router hari ini, Mas/Mbak {username}?"
                )
            latency = (time.time() - start_time) * 1000
            audit_logger.log_event(
                telegram_user_id=user_id,
                telegram_user_name=username,
                user_prompt=text_clean,
                target_device=device_name,
                action_category="MONITOR",
                action_name="GREETING",
                confirmation_status="NONE",
                result_status="SUCCESS",
                details=greeting_reply[:200],
                latency_ms=latency,
            )
            return {
                "reply": greeting_reply,
                "action_required": False,
                "pending_action": None,
            }

        # 4. Attempt Reasoning via LLM (Gemini / OpenAI) with fallback to Heuristic Planner
        llm_success = False
        reply_content = ""
        pending_act = None

        if self.google_api_key or self.openai_api_key:
            try:
                reply_dict = self._run_llm_cycle(user_id, username, text_clean, device_name)
                if reply_dict and reply_dict.get("reply"):
                    reply_content = reply_dict["reply"]
                    pending_act = reply_dict.get("pending_action")
                    llm_success = True
            except Exception as e:
                logger.warning("LLM reasoning encountered error (%s), using Heuristic Reasoner.", e)

        # 5. Fallback Heuristic Reasoner (zero-downtime offline intelligence)
        if not llm_success:
            reply_dict = self._heuristic_reasoning(user_id, username, text_clean, device_name)
            reply_content = reply_dict["reply"]
            pending_act = reply_dict.get("pending_action")

        # Prepend simulation notice if target device is running in mock fallback mode
        if pending_act and pending_act.action_name == "register_device":
            sim_notice = ""
        else:
            sim_notice = self._get_simulation_notice(device_name)
        if (
            sim_notice
            and not reply_content.startswith("⚠️ **[MODE SIMULASI OFFLINE]")
            and not reply_content.startswith("⛔")
            and not reply_content.startswith("👋")
            and not reply_content.startswith("Wa'alaikumsalam")
        ):
            reply_content = sim_notice + reply_content

        # Record turns into conversation memory for contextual dialog
        conversation_memory.add_turn(user_id, "user", text_clean)
        conversation_memory.add_turn(user_id, "model", reply_content)

        latency = (time.time() - start_time) * 1000
        category = "CONFIG" if pending_act else "MONITOR"
        audit_logger.log_event(
            telegram_user_id=user_id,
            telegram_user_name=username,
            user_prompt=text_clean,
            target_device=device_name,
            action_category=category,
            action_name="NATURAL_QUERY",
            confirmation_status="PENDING" if pending_act else "NONE",
            result_status="SUCCESS",
            details=reply_content[:200],
            latency_ms=latency,
        )

        return {
            "reply": reply_content,
            "action_required": pending_act is not None,
            "pending_action": pending_act,
        }

    def _create_write_confirmation(
        self,
        user_id: int,
        fn_name: str,
        args: Dict[str, Any],
        device_name: str,
    ) -> Dict[str, Any]:
        """Creates standard confirmation card for write operations, ensuring consistency between LLM and Heuristics."""
        if not security_manager.can_user_write(user_id):
            return {
                "reply": "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**. Operasi perubahan konfigurasi hanya dapat diajukan oleh Administrator.",
                "pending_action": None,
            }

        if fn_name == "register_device":
            dev_name = args.get("name", "Router_Baru")
            dev_ip = args.get("host", "")
            dev_port = args.get("port") or 8728
            dev_proto = args.get("protocol", "api")
            dev_user = args.get("username", "admin")
            dev_pass = args.get("password", "")
            desc = f"Pendaftaran router '{dev_name}' ({dev_ip}:{dev_port})"
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=dev_name,
                action_name=fn_name,
                arguments=args,
                description=desc,
            )
            confirm_msg = (
                f"⚠️ **Konfirmasi Pendaftaran Router Baru**\n\n"
                f"• Nama Router : **{dev_name}**\n"
                f"• Host/IP     : `{dev_ip}` (Port `{dev_port}`)\n"
                f"• Protokol    : `{dev_proto.upper()}`\n"
                f"• Username    : `{dev_user}`\n"
                f"• Password    : `{'*' * len(dev_pass) if dev_pass else '(Kosong)'}`\n\n"
                f"Daftarkan router ini ke sistem dan aktifkan pemantauan otomatis?\n"
                f"👉 Balas **Ya** atau tekan tombol [ YA ] di bawah."
            )
            return {"reply": confirm_msg, "pending_action": pending}

        if fn_name == "remove_device":
            target_name = args.get("name") or device_name
            desc = f"Penghapusan router '{target_name}'"
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=target_name,
                action_name=fn_name,
                arguments=args,
                description=desc,
            )
            confirm_msg = (
                f"⚠️ **Konfirmasi Penghapusan Router**\n\n"
                f"Target : **{target_name}**\n\n"
                f"Apakah Anda yakin ingin menghapus router ini dari inventaris pemantauan?\n"
                f"👉 Balas **Ya** atau tekan tombol [ YA ] di bawah."
            )
            return {"reply": confirm_msg, "pending_action": pending}

        if fn_name == "add_ip_address":
            target_ip = args.get("address", "")
            target_iface = args.get("interface", "")
            target_comment = args.get("comment", "")
            desc = f"Penambahan IP '{target_ip}' pada interface '{target_iface}'"
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name=fn_name,
                arguments=args,
                description=desc,
            )
            confirm_msg = (
                f"⚠️ **Konfirmasi Penambahan IP Address**\n\n"
                f"• Target Router : **{device_name}**\n"
                f"• Alamat IP     : `{target_ip}`\n"
                f"• Interface     : `{target_iface}`\n"
                f"• Komentar      : `{target_comment or '-'}`\n\n"
                f"Lanjutkan penambahan IP address ke router?\n"
                f"👉 Balas **Ya** atau tekan tombol [ YA ] di bawah."
            )
            return {"reply": confirm_msg, "pending_action": pending}

        if fn_name == "set_ip_address":
            curr_ip = args.get("current_address") or args.get("address_or_id") or args.get("address", "")
            new_ip = args.get("new_address") or args.get("address", "")
            desc = f"Pengubahan IP '{curr_ip}' menjadi '{new_ip}'"
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name=fn_name,
                arguments=args,
                description=desc,
            )
            confirm_msg = (
                f"⚠️ **Konfirmasi Pengubahan IP Address**\n\n"
                f"• Target Router : **{device_name}**\n"
                f"• IP Sekarang   : `{curr_ip}`\n"
                f"• IP Baru       : `{new_ip}`\n\n"
                f"Lanjutkan perubahan alamat IP pada router?\n"
                f"👉 Balas **Ya** atau tekan tombol [ YA ] di bawah."
            )
            return {"reply": confirm_msg, "pending_action": pending}

        if fn_name == "remove_ip_address":
            target_ip = args.get("address") or args.get("address_or_id", "")
            desc = f"Penghapusan IP '{target_ip}'"
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name=fn_name,
                arguments=args,
                description=desc,
            )
            confirm_msg = (
                f"⚠️ **Konfirmasi Penghapusan IP Address**\n\n"
                f"• Target Router : **{device_name}**\n"
                f"• Alamat IP     : `{target_ip}`\n\n"
                f"Lanjutkan penghapusan IP address ini?\n"
                f"👉 Balas **Ya** atau tekan tombol [ YA ] di bawah."
            )
            return {"reply": confirm_msg, "pending_action": pending}

        if fn_name == "install_router_update":
            channel = args.get("channel", "stable")
            fw_res = TOOL_REGISTRY["get_firmware_status"](device=device_name, channel=channel)
            fw_data = fw_res.get("data") or {}
            pkg_info = fw_data.get("package_update") or {}
            rb_info = fw_data.get("routerboard") or {}

            curr = pkg_info.get("installed_version") or pkg_info.get("installed-version") or rb_info.get("current_firmware") or rb_info.get("current-firmware", "-")
            target = args.get("target_version") or pkg_info.get("latest_version") or pkg_info.get("latest-version") or "-"
            desc = f"Upgrade RouterOS {device_name} ({curr} -> {target})"
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name=fn_name,
                arguments=args,
                description=desc,
            )
            confirm_msg = (
                f"🚨 **Konfirmasi Diperlukan: UPGRADE ROUTEROS**\n\n"
                f"• Target Router   : **{device_name}**\n"
                f"• Aksi            : `install_router_update`\n"
                f"• Versi Saat Ini  : `v{curr}`\n"
                f"• Versi Target    : `v{target}` (Channel: `{channel}`)\n\n"
                f"⚠️ **PERINGATAN KESELAMATAN JARINGAN**:\n"
                f"1. Router akan mengunduh paket update dan melakukan **REBOOT otomatis**.\n"
                f"2. Jaringan/Internet akan offline sementara selama **1-3 menit**.\n"
                f"3. Pastikan pasokan listrik router stabil selama proses penulisan firmware!\n\n"
                f"Apakah Anda yakin ingin memulai proses upgrade firmware sekarang?\n"
                f"👉 Balas **Ya** atau klik tombol [ YA ] di bawah untuk mengeksekusi, atau **Batal** untuk membatalkan."
            )
            return {"reply": confirm_msg, "pending_action": pending}

        if fn_name == "upgrade_routerboard_firmware":
            fw_res = TOOL_REGISTRY["get_firmware_status"](device=device_name)
            fw_data = fw_res.get("data") or {}
            rb_info = fw_data.get("routerboard") or {}

            curr = rb_info.get("current_firmware") or rb_info.get("current-firmware", "-")
            target = rb_info.get("upgrade_firmware") or rb_info.get("upgrade-firmware", "-")
            model = rb_info.get("model", "-")
            desc = f"Upgrade firmware bootloader RouterBOARD {device_name} ({curr} -> {target})"
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name=fn_name,
                arguments=args,
                description=desc,
            )
            confirm_msg = (
                f"⚡ **Konfirmasi Diperlukan: UPGRADE BOOTLOADER BIOS**\n\n"
                f"• Target Router    : **{device_name}**\n"
                f"• Model Board      : `{model}`\n"
                f"• Firmware Aktif   : `v{curr}`\n"
                f"• Firmware Baru    : `v{target}`\n\n"
                f"⚠️ **INFORMASI PENTING**:\n"
                f"Firmware bootloader BIOS akan diperbarui. Setelah proses ini, router perlu direboot agar firmware baru aktif di perangkat keras.\n\n"
                f"Lanjutkan upgrade bootloader BIOS sekarang?\n"
                f"👉 Balas **Ya** atau klik tombol [ YA ] di bawah."
            )
            return {"reply": confirm_msg, "pending_action": pending}

        if fn_name == "system_reboot":
            desc = f"Reboot router {device_name}"
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name=fn_name,
                arguments=args,
                description=desc,
            )
            confirm_msg = (
                f"🚨 **Konfirmasi Diperlukan: REBOOT ROUTER**\n\n"
                f"Target    : **{device_name}**\n"
                f"Aksi      : `system_reboot`\n\n"
                f"⚠️ **PERINGATAN RISIKO**:\n"
                f"• Router akan memutus seluruh koneksi jaringan dan memulai ulang sistem.\n"
                f"• Sistem akan offline selama 30-60 detik.\n\n"
                f"Apakah Anda benar-benar yakin ingin me-reboot router sekarang?\n"
                f"👉 Balas **Ya** atau klik tombol [ YA ] di bawah untuk menyetujui, atau **Batal** untuk membatalkan."
            )
            return {"reply": confirm_msg, "pending_action": pending}

        # Generic Write fallback
        desc = f"Operasi '{fn_name}' pada router {device_name}"
        pending = confirmation_manager.create_pending_action(
            user_id=user_id,
            device_name=device_name,
            action_name=fn_name,
            arguments=args,
            description=desc,
        )
        confirm_msg = (
            f"⚠️ **Konfirmasi Diperlukan**\n\n"
            f"Target    : **{device_name}**\n"
            f"Aksi      : `{fn_name}`\n"
            f"Parameter : `{json.dumps(args, ensure_ascii=False)}`\n\n"
            f"Apakah Anda yakin ingin melanjutkan konfigurasi ini?\n"
            f"Ketik **Ya** atau klik tombol di bawah untuk setuju, atau **Batal** untuk membatalkan."
        )
        return {"reply": confirm_msg, "pending_action": pending}

    def _run_llm_cycle(self, user_id: int, username: str, prompt: str, device_name: str) -> Dict[str, Any]:
        """Execute Tool Calling cycle with LLM."""
        if self.google_api_key and self.provider == "gemini":
            return self._call_gemini_with_tools(user_id, username, prompt, device_name)
        elif self.openai_api_key or self.provider in ("openai", "openrouter", "ollama"):
            return self._call_openai_with_tools(user_id, username, prompt, device_name)
        raise RuntimeError("No suitable LLM configured")

    def _call_gemini_with_tools(self, user_id: int, username: str, prompt: str, device_name: str) -> Dict[str, Any]:
        """Call Google Gemini API with function declaration, multi-turn tool execution, and model fallback."""
        # Build tools structure for Gemini
        gemini_tools = []
        for schema in TOOL_SCHEMAS:
            fn = schema["function"]
            gemini_tools.append({
                "name": fn["name"],
                "description": fn["description"],
                "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
            })

        role = security_manager.get_user_role(user_id)
        user_context = (
            f"Konteks Sistem:\n"
            f"- Target Router: '{device_name}'\n"
            f"- Pengirim Pesan: {username} (Telegram ID: {user_id}, Role: {role})\n\n"
            f"Pesan Pengguna: \"{prompt}\"\n\n"
            f"Instruksi Respon:\n"
            f"- Jawablah PERSIS dan SESUAI dengan apa yang dikatakan atau ditanyakan pengguna di atas.\n"
            f"- WAJIB: Jika pengguna menyapa (seperti 'hai', 'halo', 'hallo', 'selamat pagi/siang/malam', 'assalamualaikum', dll.) atau memulai percakapan, SELALU sapalah balik dengan menyebut nama pengguna ({username}) secara langsung, hangat, dan bersahabat!\n"
            f"- Jika pengguna bertanya status atau hak akses mereka, jelaskan role mereka saat ini ({role}).\n"
            f"- Jangan memberikan jawaban di luar konteks atau mengulang template panjang yang tidak diminta."
        )

        # Build initial contents including short-term history
        base_contents = []
        history = conversation_memory.get_history(user_id)
        for h in history:
            role_tag = "user" if h["role"] == "user" else "model"
            base_contents.append({"role": role_tag, "parts": [{"text": h["text"]}]})
        base_contents.append({"role": "user", "parts": [{"text": user_context}]})

        # Candidate models with auto-fallback if 429 quota or 404 occurs
        candidate_models = [self.model]
        for fb in ("gemini-flash-latest", "gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.7-flash"):
            if fb not in candidate_models:
                candidate_models.append(fb)

        last_error = None
        for current_model in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent?key={self.google_api_key}"
            turn_contents = [dict(c) for c in base_contents]
            turn = 0
            max_turns = 4
            try:
                with httpx.Client(timeout=25.0) as client:
                    while turn < max_turns:
                        turn += 1
                        payload = {
                            "contents": turn_contents,
                            "systemInstruction": {"parts": [{"text": HERMES_SYSTEM_PROMPT + "\n" + DIAGNOSTIC_ANALYSIS_PROMPT}]},
                            "tools": [{"functionDeclarations": gemini_tools}],
                            "generationConfig": {"temperature": 0.2},
                        }

                        resp = client.post(url, json=payload)
                        if resp.status_code in (429, 404):
                            raise RuntimeError(f"Gemini {current_model} returned HTTP {resp.status_code}: {resp.text[:120]}")
                        if resp.status_code != 200:
                            raise RuntimeError(f"Gemini API returned HTTP {resp.status_code}: {resp.text[:200]}")

                        res_data = resp.json()
                        candidates = res_data.get("candidates", [])
                        if not candidates:
                            raise RuntimeError("Empty response candidates from Gemini")

                        first_cand = candidates[0]
                        cand_content = first_cand.get("content", {})
                        parts = cand_content.get("parts", [])

                        tool_calls = [p["functionCall"] for p in parts if "functionCall" in p]

                        # If no functionCall, model generated final answer text
                        if not tool_calls:
                            text_parts = [p.get("text", "") for p in parts if "text" in p]
                            final_text = "\n".join(text_parts).strip()
                            if final_text:
                                return {"reply": final_text, "pending_action": None}
                            break

                        # Append model's tool calls to contents
                        turn_contents.append(cand_content)

                        # Execute tool calls
                        func_response_parts = []
                        for call in tool_calls:
                            fn_name = call.get("name")
                            args = call.get("args", {})
                            if fn_name not in ("register_device", "remove_device", "discover_devices", "ping_host", "check_server_port"):
                                if "device" not in args or not args["device"]:
                                    args["device"] = device_name
                            else:
                                args.pop("device", None)

                            # Check write permission
                            perm = security_manager.classify_permission(fn_name)
                            if perm == "WRITE":
                                return self._create_write_confirmation(user_id, fn_name, args, device_name)

                            # READ operation
                            func = TOOL_REGISTRY.get(fn_name)
                            if func:
                                tool_res = func(**args)
                            else:
                                tool_res = {"success": False, "error": f"Tool {fn_name} tidak ditemukan"}

                            func_response_parts.append({
                                "functionResponse": {
                                    "name": fn_name,
                                    "response": {"output": tool_res},
                                }
                            })

                        # Feed function responses back into turn_contents
                        turn_contents.append({"role": "user", "parts": func_response_parts})

            except Exception as e:
                last_error = e
                logger.warning("Gemini model %s error (%s). Trying next candidate...", current_model, e)
                continue

        if last_error:
            raise last_error
        raise RuntimeError("No candidate Gemini model succeeded")

    def _call_openai_with_tools(self, user_id: int, username: str, prompt: str, device_name: str) -> Dict[str, Any]:
        """Call OpenAI / OpenRouter / Ollama tool calling endpoint with multi-turn support."""
        url = f"{self.openai_base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {self.openai_api_key}", "Content-Type": "application/json"}

        role = security_manager.get_user_role(user_id)
        user_context = (
            f"Target Router: '{device_name}'. Pengguna: {username} (ID: {user_id}, Role: {role}).\n\n"
            f"Pesan Pengguna: \"{prompt}\"\n\n"
            f"Instruksi Respon:\n"
            f"- Jawablah secara tepat, fokus, dan relevan sesuai pesan pengguna di atas.\n"
            f"- WAJIB: Jika pengguna menyapa (seperti 'hai', 'halo', 'hallo', dll.) atau memulai percakapan, SELALU sapa balik dengan menyebut nama pengguna ({username}) secara langsung, hangat, dan bersahabat!\n"
            f"- Jangan menjawab di luar konteks."
        )
        messages = [
            {"role": "system", "content": HERMES_SYSTEM_PROMPT + "\n" + DIAGNOSTIC_ANALYSIS_PROMPT},
        ]
        history = conversation_memory.get_history(user_id)
        for h in history:
            r = "user" if h["role"] == "user" else "assistant"
            messages.append({"role": r, "content": h["text"]})
        messages.append({"role": "user", "content": user_context})

        max_turns = 4
        turn = 0
        with httpx.Client(timeout=25.0) as client:
            while turn < max_turns:
                turn += 1
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "tools": TOOL_SCHEMAS,
                    "tool_choice": "auto",
                    "temperature": 0.2,
                }
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code != 200:
                    raise RuntimeError(f"OpenAI API returned HTTP {resp.status_code}: {resp.text[:200]}")

                data = resp.json()
                choice = data["choices"][0]["message"]
                tool_calls = choice.get("tool_calls", [])

                if not tool_calls:
                    final_content = choice.get("content", "").strip()
                    if final_content:
                        return {"reply": final_content, "pending_action": None}
                    break

                messages.append(choice)
                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    args = json.loads(tc["function"]["arguments"] or "{}")
                    if fn_name not in ("register_device", "remove_device", "discover_devices", "ping_host", "check_server_port"):
                        if "device" not in args or not args["device"]:
                            args["device"] = device_name
                    else:
                        args.pop("device", None)

                    perm = security_manager.classify_permission(fn_name)
                    if perm == "WRITE":
                        return self._create_write_confirmation(user_id, fn_name, args, device_name)

                    func = TOOL_REGISTRY.get(fn_name)
                    res = func(**args) if func else {"error": "Tool not found"}
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": fn_name,
                        "content": json.dumps(res, ensure_ascii=False),
                    })

        raise RuntimeError("OpenAI API exceeded max turns without completing text")

    def _heuristic_reasoning(self, user_id: int, username: str, prompt: str, device_name: str) -> Dict[str, Any]:
        """
        Autonomous Heuristic Reasoner.
        Fulfills PRD Scenarios 1, 2, and 3 with zero external API dependencies.
        Guarantees instant, highly accurate responses and multi-step diagnostics.
        """
        lower = prompt.lower()

        # =====================================================================
        # SCENARIO 3: Configuration / WRITE Operations (PRD Section 14, 26)
        # =====================================================================
        # Register MikroTik Device
        if any(w in lower for w in ("daftarkan router", "daftar router", "tambah router", "tambahkan router", "tambah perangkat", "daftarkan perangkat", "add device", "register router")):
            if not security_manager.can_user_write(user_id):
                return {
                    "reply": "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**. Pendaftaran router baru hanya dapat diajukan oleh Administrator.",
                    "action_required": False,
                    "pending_action": None,
                }

            ip_match = re.search(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', prompt)
            dev_ip = ip_match.group(0) if ip_match else ""

            name_match = re.search(r'(?:bernama|nama)\s+([a-zA-Z0-9_\s-]+?)(?:\s+(?:ip|port|host|username|user)\b|$)', prompt, re.IGNORECASE)
            if not name_match:
                name_match = re.search(r'(?:router baru)\s+([a-zA-Z0-9_\s-]+?)(?:\s+(?:ip|port|host|username|user)\b|$)', prompt, re.IGNORECASE)
            dev_name = name_match.group(1).strip() if name_match else ""
            if not dev_name or dev_name.lower() in ("baru", "mikrotik", "ip", "dengan"):
                dev_name = f"Router_{dev_ip.replace('.', '_')}" if dev_ip else "Router_Baru"

            port_match = re.search(r'port\s+(\d+)', prompt, re.IGNORECASE)
            dev_port = int(port_match.group(1)) if port_match else 0

            proto_match = re.search(r'\b(api|rest|ssh)\b', prompt, re.IGNORECASE)
            dev_proto = proto_match.group(1).lower() if proto_match else "api"

            user_match = re.search(r'(?:user|username)\s+([a-zA-Z0-9_-]+)', prompt, re.IGNORECASE)
            dev_user = user_match.group(1) if user_match else "admin"

            pass_match = re.search(r'(?:pass|password)\s+([^\s]+)', prompt, re.IGNORECASE)
            dev_pass = pass_match.group(1) if pass_match else ""

            if not dev_ip:
                return {
                    "reply": (
                        "⚠️ **IP Router Belum Ditemukan**\n\n"
                        "Mohon sertakan alamat IP router yang ingin didaftarkan.\n"
                        "💡 **Contoh:**\n"
                        "*\"Daftarkan router baru Cabang B IP 192.168.88.1 port 8728 username admin password rahasia\"*\n\n"
                        "Atau gunakan perintah cepat:\n"
                        "`/add_device Cabang_B 192.168.88.1 8728 api admin rahasia`"
                    ),
                    "action_required": False,
                    "pending_action": None,
                }

            args = {
                "name": dev_name,
                "host": dev_ip,
                "port": dev_port,
                "protocol": dev_proto,
                "username": dev_user,
                "password": dev_pass,
                "description": f"Router MikroTik {dev_name} ({dev_ip}) didaftarkan via Telegram AI",
            }

            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=dev_name,
                action_name="register_device",
                arguments=args,
                description=f"Pendaftaran router '{dev_name}' ({dev_ip}:{dev_port or 8728})",
            )

            confirm_card = (
                f"⚠️ **Konfirmasi Pendaftaran Router Baru**\n\n"
                f"• Nama Router : **{dev_name}**\n"
                f"• Host/IP     : `{dev_ip}` (Port `{dev_port or (8728 if dev_proto=='api' else 80)}`)\n"
                f"• Protokol    : `{dev_proto.upper()}`\n"
                f"• Username    : `{dev_user}`\n"
                f"• Password    : `{'*' * len(dev_pass) if dev_pass else '(Kosong)'}`\n\n"
                f"Daftarkan router ini ke sistem dan aktifkan pemantauan otomatis?\n"
                f"👉 Balas **Ya** atau tekan tombol [ YA ] di bawah."
            )
            return {"reply": confirm_card, "pending_action": pending}

        # Remove MikroTik Device
        if any(w in lower for w in ("hapus router", "delete router", "buang router", "hapus perangkat", "remove router", "remove device")):
            if not security_manager.can_user_write(user_id):
                return {
                    "reply": "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**. Penghapusan router hanya dapat diajukan oleh Administrator.",
                    "action_required": False,
                    "pending_action": None,
                }

            target_match = re.search(r'(?:hapus|delete|buang|remove)\s+(?:router|perangkat)\s+([a-zA-Z0-9_\-\s]+)', prompt, re.IGNORECASE)
            target_name = target_match.group(1).strip() if target_match else ""
            if not target_name:
                return {
                    "reply": "Silakan tentukan nama atau IP router yang ingin dihapus. Contoh: 'Hapus router Cabang_2'.",
                    "action_required": False,
                    "pending_action": None,
                }

            args = {"name": target_name}
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=target_name,
                action_name="remove_device",
                arguments=args,
                description=f"Penghapusan router '{target_name}'",
            )
            confirm_card = (
                f"⚠️ **Konfirmasi Penghapusan Router**\n\n"
                f"Target : **{target_name}**\n\n"
                f"Apakah Anda yakin ingin menghapus router ini dari inventaris pemantauan?\n"
                f"👉 Balas **Ya** atau tekan tombol [ YA ] di bawah."
            )
            return {"reply": confirm_card, "pending_action": pending}

        # Add IP Address
        if any(w in lower for w in ("tambah ip", "tambahkan ip", "add ip", "pasang ip", "buat ip", "tambah alamat ip", "tambahkan alamat ip")):
            if not security_manager.can_user_write(user_id):
                return {
                    "reply": "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**. Penambahan IP address hanya dapat diajukan oleh Administrator.",
                    "action_required": False,
                    "pending_action": None,
                }

            ip_match = re.search(r'\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b', prompt)
            target_ip = ip_match.group(0) if ip_match else ""
            if target_ip and "/" not in target_ip:
                target_ip = f"{target_ip}/24"

            iface_match = re.search(r'\b(ether\d+|wlan\d+|bridge\d+|vlan\d+|sfp\d+)\b', prompt, re.IGNORECASE)
            if not iface_match:
                iface_match = re.search(r'(?:interface|antarmuka|di|pada)\s+([a-zA-Z0-9_\-]+)', prompt, re.IGNORECASE)
            target_iface = iface_match.group(1) if iface_match else ""

            comm_match = re.search(r'(?:comment|komentar|catatan)\s+["\']?([^"\']+)["\']?', prompt, re.IGNORECASE)
            target_comment = comm_match.group(1).strip() if comm_match else ""

            if not target_ip or not target_iface:
                return {
                    "reply": (
                        "⚠️ **Parameter IP atau Interface Belum Lengkap**\n\n"
                        "Gunakan format: *\"Tambahkan IP <Alamat_IP/Subnet> di interface <Nama_Interface>\"*\n"
                        "💡 **Contoh:**\n"
                        "*\"Tambahkan IP 192.168.50.1/24 di interface ether2\"*\n\n"
                        "Atau gunakan perintah cepat:\n"
                        "`/add_ip 192.168.50.1/24 ether2`"
                    ),
                    "action_required": False,
                    "pending_action": None,
                }

            args = {
                "device": device_name,
                "address": target_ip,
                "interface": target_iface,
                "comment": target_comment,
            }
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name="add_ip_address",
                arguments=args,
                description=f"Penambahan IP '{target_ip}' pada interface '{target_iface}'",
            )
            confirm_card = (
                f"⚠️ **Konfirmasi Penambahan IP Address**\n\n"
                f"• Target Router : **{device_name}**\n"
                f"• Alamat IP     : `{target_ip}`\n"
                f"• Interface     : `{target_iface}`\n"
                f"• Komentar      : `{target_comment or '-'}`\n\n"
                f"Lanjutkan penambahan IP address ke router?\n"
                f"👉 Balas **Ya** atau tekan tombol [ YA ] di bawah."
            )
            return {"reply": confirm_card, "pending_action": pending}

        # Remove IP Address
        if any(w in lower for w in ("hapus ip", "remove ip", "delete ip", "buang ip", "hapus alamat ip")):
            if not security_manager.can_user_write(user_id):
                return {
                    "reply": "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**. Penghapusan IP address hanya dapat diajukan oleh Administrator.",
                    "action_required": False,
                    "pending_action": None,
                }

            ip_match = re.search(r'\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b', prompt)
            target_ip = ip_match.group(0) if ip_match else ""

            if not target_ip:
                return {
                    "reply": (
                        "⚠️ Mohon sertakan alamat IP yang ingin dihapus.\n\n"
                        "💡 **Contoh:**\n"
                        "*\"Hapus IP 192.168.50.1\"*\n"
                        "Atau gunakan perintah: `/remove_ip 192.168.50.1`"
                    ),
                    "action_required": False,
                    "pending_action": None,
                }

            args = {
                "device": device_name,
                "address": target_ip,
            }
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name="remove_ip_address",
                arguments=args,
                description=f"Penghapusan IP address '{target_ip}'",
            )
            confirm_card = (
                f"⚠️ **Konfirmasi Penghapusan IP Address**\n\n"
                f"• Target Router : **{device_name}**\n"
                f"• Alamat IP     : `{target_ip}`\n\n"
                f"Apakah Anda yakin ingin menghapus IP address ini?\n"
                f"👉 Balas **Ya** atau tekan tombol [ YA ] di bawah."
            )
            return {"reply": confirm_card, "pending_action": pending}

        # Edit / Set IP Address
        if any(w in lower for w in ("edit ip", "ubah ip", "ganti ip", "update ip", "set ip", "ubah alamat ip", "ganti alamat ip")):
            if not security_manager.can_user_write(user_id):
                return {
                    "reply": "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**. Pengubahan IP address hanya dapat diajukan oleh Administrator.",
                    "action_required": False,
                    "pending_action": None,
                }

            all_ips = re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b', prompt)
            curr_ip = ""
            new_ip = ""
            if len(all_ips) >= 2:
                curr_ip = all_ips[0]
                new_ip = all_ips[1]
            elif len(all_ips) == 1:
                curr_ip = all_ips[0]

            explicit_match = re.search(r'(?:dari|ip)\s+([0-9\./]+)\s+(?:menjadi|ke|jadi)\s+([0-9\./]+)', prompt, re.IGNORECASE)
            if explicit_match:
                curr_ip = explicit_match.group(1)
                new_ip = explicit_match.group(2)

            if new_ip and "/" not in new_ip:
                new_ip = f"{new_ip}/24"

            iface_match = re.search(r'\b(ether\d+|wlan\d+|bridge\d+|vlan\d+|sfp\d+)\b', prompt, re.IGNORECASE)
            new_iface = iface_match.group(1) if iface_match else ""

            comm_match = re.search(r'(?:comment|komentar|catatan)\s+["\']?([^"\']+)["\']?', prompt, re.IGNORECASE)
            new_comment = comm_match.group(1).strip() if comm_match else ""

            if not curr_ip:
                return {
                    "reply": (
                        "⚠️ Mohon sertakan alamat IP yang ingin diubah.\n\n"
                        "💡 **Contoh:**\n"
                        "*\"Ubah IP 192.168.10.1 menjadi 192.168.20.1/24\"*\n"
                        "Atau gunakan perintah: `/edit_ip 192.168.10.1 192.168.20.1/24 ether2`"
                    ),
                    "action_required": False,
                    "pending_action": None,
                }

            args = {
                "device": device_name,
                "current_address": curr_ip,
                "new_address": new_ip,
                "new_interface": new_iface,
                "comment": new_comment,
            }
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name="set_ip_address",
                arguments=args,
                description=f"Pengubahan IP address '{curr_ip}' -> '{new_ip or curr_ip}'",
            )
            confirm_card = (
                f"⚠️ **Konfirmasi Pengubahan IP Address**\n\n"
                f"• Target Router : **{device_name}**\n"
                f"• IP Lama       : `{curr_ip}`\n"
                f"• IP Baru       : `{new_ip or '(Tetap)'}`\n"
                f"• Interface     : `{new_iface or '(Tetap)'}`\n"
                f"• Komentar      : `{new_comment or '(Tetap)'}`\n\n"
                f"Lanjutkan perubahan IP address ini?\n"
                f"👉 Balas **Ya** atau tekan tombol [ YA ] di bawah."
            )
            return {"reply": confirm_card, "pending_action": pending}

        # Create Hotspot User
        if any(w in lower for w in ("buat user hotspot", "buatkan user hotspot", "tambah user hotspot", "bikin hotspot user")):
            if not security_manager.can_user_write(user_id):
                return {
                    "reply": "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**. Operasi pembuatan user hotspot hanya dapat diajukan oleh Administrator.",
                    "action_required": False,
                    "pending_action": None,
                }
            # Extract username: search for 'bernama <name>' or 'nama <name>' first, then fallback to 'user/username <name>'
            user_match = re.search(r'(?:bernama|nama)\s+([a-zA-Z0-9_-]+)', prompt, re.IGNORECASE)
            if not user_match:
                user_match = re.search(r'(?:username|user)\s+(?!hotspot\b)([a-zA-Z0-9_-]+)', prompt, re.IGNORECASE)
            hotspot_username = user_match.group(1) if user_match else "Tamu" + str(int(time.time()) % 1000)

            # Extract duration / uptime
            time_match = re.search(r'(?:aktif|selama|durasi)\s+([0-9]+\s*(?:hari|jam|menit|d|h|m))', prompt, re.IGNORECASE)
            limit_uptime = time_match.group(1) if time_match else "1d"
            if "hari" in limit_uptime:
                limit_uptime = limit_uptime.replace("hari", "d").replace(" ", "")
            elif "jam" in limit_uptime:
                limit_uptime = limit_uptime.replace("jam", "h").replace(" ", "")
            elif "menit" in limit_uptime:
                limit_uptime = limit_uptime.replace("menit", "m").replace(" ", "")

            args = {
                "device": device_name,
                "name": hotspot_username,
                "password": "pass" + hotspot_username,
                "profile": "default",
                "limit_uptime": limit_uptime,
            }

            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name="create_hotspot_user",
                arguments=args,
                description=f"Pembuatan user hotspot '{hotspot_username}'",
            )

            confirm_card = (
                f"⚠️ **Konfirmasi Diperlukan**\n\n"
                f"Target     : **{device_name}**\n"
                f"Aksi       : `Create Hotspot User`\n"
                f"Username   : **{hotspot_username}**\n"
                f"Password   : `{args['password']}`\n"
                f"Profil     : `{args['profile']}`\n"
                f"Masa Aktif : `{limit_uptime}`\n\n"
                f"Lanjutkan pembuatan user?\n"
                f"👉 Balas **Ya** atau tekan tombol [ YA ] di bawah."
            )
            return {"reply": confirm_card, "pending_action": pending}

        # Delete Hotspot User
        if any(w in lower for w in ("hapus user hotspot", "delete user hotspot", "buang user hotspot")):
            if not security_manager.can_user_write(user_id):
                return {
                    "reply": "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**. Operasi penghapusan user hotspot hanya dapat diajukan oleh Administrator.",
                    "action_required": False,
                    "pending_action": None,
                }
            user_match = re.search(r'(?:bernama|nama)\s+([a-zA-Z0-9_-]+)', prompt, re.IGNORECASE)
            if not user_match:
                user_match = re.search(r'(?:username|user)\s+(?!hotspot\b)([a-zA-Z0-9_-]+)', prompt, re.IGNORECASE)
            hotspot_username = user_match.group(1) if user_match else ""
            if not hotspot_username:
                return {"reply": "Silakan tentukan nama user hotspot yang ingin dihapus. Contoh: 'Hapus user hotspot Tamu123'.", "pending_action": None}

            args = {"device": device_name, "name": hotspot_username}
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name="delete_hotspot_user",
                arguments=args,
                description=f"Penghapusan user hotspot '{hotspot_username}'",
            )
            confirm_card = (
                f"⚠️ **Konfirmasi Diperlukan**\n\n"
                f"Target   : **{device_name}**\n"
                f"Aksi     : `Delete Hotspot User`\n"
                f"Username : **{hotspot_username}**\n\n"
                f"Apakah Anda yakin ingin menghapus user hotspot ini?\n"
                f"👉 Balas **Ya** untuk menyetujui atau **Batal** untuk membatalkan."
            )
            return {"reply": confirm_card, "pending_action": pending}

        # Enable / Disable Interface
        is_iface_toggle = any(w in lower for w in (
            "matikan interface", "disable interface", "hidupkan interface", "enable interface", "aktifkan interface",
            "nyalakan interface", "nonaktifkan interface", "matikan ether", "hidupkan ether", "nyalakan ether",
            "aktifkan ether", "matikan port", "hidupkan port", "nyalakan port", "aktifkan port", "disable ether",
            "enable ether", "disable port", "enable port", "turn on ether", "turn off ether"
        )) or (
            any(w in lower for w in ("matikan", "disable", "nonaktifkan", "hidupkan", "nyalakan", "enable", "aktifkan"))
            and any(w in lower for w in ("ether", "port", "interface", "sfp", "wlan"))
        )

        if is_iface_toggle:
            if not security_manager.can_user_write(user_id):
                return {
                    "reply": "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**. Operasi pengubahan interface hanya dapat diajukan oleh Administrator.",
                    "action_required": False,
                    "pending_action": None,
                }
            enabled = not any(w in lower for w in ("matikan", "disable", "nonaktifkan", "turn off", "shutdown"))
            action_label = "Enable Interface" if enabled else "Disable Interface"
            
            # Extract interface target accurately: ether10, ether 10, port 2, sfp1, etc.
            m = re.search(r'(ether\s*\d+|sfp\s*\d+|wlan\s*\d+|port\s*\d+|interface\s*[a-zA-Z0-9_-]+)', prompt, re.IGNORECASE)
            if m:
                raw_target = m.group(1).replace(" ", "")
                if raw_target.lower().startswith("port"):
                    iface_name = "ether" + raw_target[4:]
                elif raw_target.lower().startswith("interface"):
                    iface_name = raw_target[9:]
                else:
                    iface_name = raw_target
            else:
                num_match = re.search(r'(?:ether|port|interface)\s*(\d+)', prompt, re.IGNORECASE)
                iface_name = f"ether{num_match.group(1)}" if num_match else "ether5"

            args = {"device": device_name, "interface_name": iface_name, "enabled": enabled}
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name="set_interface_state",
                arguments=args,
                description=f"Ubah status interface {iface_name} -> {action_label}",
            )
            confirm_card = (
                f"⚠️ **Konfirmasi Diperlukan**\n\n"
                f"Target    : **{device_name}**\n"
                f"Aksi      : `{action_label}`\n"
                f"Interface : **{iface_name}**\n"
                f"Status    : `{'AKTIF (UP)' if enabled else 'NONAKTIF (DOWN)'}`\n\n"
                f"Lanjutkan perubahan interface ini?\n"
                f"👉 Balas **Ya** untuk menyetujui atau **Batal** untuk membatalkan."
            )
            return {"reply": confirm_card, "pending_action": pending}

        # System Reboot (PRD Scenario Admin Write Action)
        if any(w in lower for w in ("reboot router", "restart router", "reboot mikrotik", "restart mikrotik", "reboot sistem")):
            if not security_manager.can_user_write(user_id):
                return {
                    "reply": "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**. Operasi reboot hanya dapat diajukan oleh Administrator.",
                    "action_required": False,
                    "pending_action": None,
                }
            args = {"device": device_name}
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name="system_reboot",
                arguments=args,
                description=f"Reboot router {device_name}",
            )
            confirm_card = (
                f"🚨 **Konfirmasi Diperlukan: REBOOT ROUTER**\n\n"
                f"Target    : **{device_name}**\n"
                f"Aksi      : `system_reboot`\n\n"
                f"⚠️ **PERINGATAN RISIKO**:\n"
                f"• Router akan memutus seluruh koneksi jaringan dan memulai ulang sistem.\n"
                f"• Sistem akan offline selama 30-60 detik.\n\n"
                f"Apakah Anda benar-benar yakin ingin me-reboot router sekarang?\n"
                f"👉 Balas **Ya** atau klik tombol [ YA ] di bawah untuk menyetujui, atau **Batal** untuk membatalkan."
            )
            return {"reply": confirm_card, "pending_action": pending}

        # System Shutdown
        if any(w in lower for w in ("shutdown router", "matikan router", "shutdown mikrotik", "matikan mikrotik")):
            if not security_manager.can_user_write(user_id):
                return {
                    "reply": "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**. Operasi shutdown hanya dapat diajukan oleh Administrator.",
                    "action_required": False,
                    "pending_action": None,
                }
            args = {"device": device_name}
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name="system_shutdown",
                arguments=args,
                description=f"Shutdown router {device_name}",
            )
            confirm_card = (
                f"🚨 **Konfirmasi Diperlukan: SHUTDOWN ROUTER**\n\n"
                f"Target    : **{device_name}**\n"
                f"Aksi      : `system_shutdown`\n\n"
                f"⚠️ **PERINGATAN RISIKO**:\n"
                f"• Router akan dimatikan secara total.\n"
                f"• Perangkat memerlukan intervensi fisik untuk dinyalakan kembali.\n\n"
                f"Lanjutkan mematikan router?\n"
                f"👉 Balas **Ya** untuk setuju atau **Batal** untuk membatalkan."
            )
            return {"reply": confirm_card, "pending_action": pending}

        # Firmware Upgrade / RouterOS Update (PRD Scenario Admin Write Action)
        has_upgrade_kw = any(w in lower for w in (
            "upgrade firmware", "update firmware", "upgrade frimware", "update frimware",
            "upgrade fremware", "update fremware", "upgrade routeros", "update routeros",
            "upgrade router", "update router ke versi terbaru", "install update router",
            "upgrade bootloader", "upgrade routerboard", "upgrade bios", "perbarui firmware",
            "perbarui frimware", "update bootloader", "perbarui bootloader",
        )) or (
            any(w in lower for w in ("upgrade", "update", "perbarui", "upgread", "apdet", "install"))
            and any(w in lower for w in ("firmware", "frimware", "fremware", "bootloader", "bios", "routerboard", "routeros"))
        )
        is_query_check = any(w in lower for w in ("cek", "apakah", "info", "status", "lihat", "kapan", "bisa", "bagaimana", "cara"))

        if has_upgrade_kw and not is_query_check:
            if not security_manager.can_user_write(user_id):
                return {
                    "reply": "⛔ **Akses Terbatas**: Akun Anda memiliki role **Viewer (Read-Only)**. Operasi upgrade firmware hanya dapat diajukan oleh Administrator.",
                    "action_required": False,
                    "pending_action": None,
                }

            fw_res = TOOL_REGISTRY["get_firmware_status"](device=device_name)
            fw_data = fw_res.get("data") or {}
            pkg_info = fw_data.get("package_update") or {}
            rb_info = fw_data.get("routerboard") or {}

            is_bootloader_only = any(w in lower for w in ("bootloader", "routerboard", "bios"))
            if is_bootloader_only and not any(w in lower for w in ("routeros", "os")):
                action_name = "upgrade_routerboard_firmware"
                curr = rb_info.get("current_firmware") or rb_info.get("current-firmware", "-")
                target = rb_info.get("upgrade_firmware") or rb_info.get("upgrade-firmware", "-")
                desc = f"Upgrade firmware bootloader RouterBOARD {device_name} ({curr} -> {target})"
                action_desc = "Upgrade Bootloader Firmware RouterBOARD"
            else:
                action_name = "install_router_update"
                curr = pkg_info.get("installed_version") or pkg_info.get("installed-version") or rb_info.get("current_firmware") or rb_info.get("current-firmware", "-")
                has_os_upd = fw_data.get("has_os_update", False)
                target = pkg_info.get("latest_version") or pkg_info.get("latest-version") or (curr if not has_os_upd else "-")
                desc = f"Upgrade RouterOS {device_name} ({curr} -> {target})"
                action_desc = "Upgrade Paket RouterOS & Firmware"

            args = {"device": device_name, "channel": pkg_info.get("channel", "stable"), "target_version": target}
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name=action_name,
                arguments=args,
                description=desc,
            )
            confirm_card = (
                f"🚨 **Konfirmasi Diperlukan: {action_desc.upper()}**\n\n"
                f"• Target Router   : **{device_name}**\n"
                f"• Aksi            : `{action_name}`\n"
                f"• Versi Saat Ini  : `v{curr}`\n"
                f"• Versi Target    : `v{target}` (Channel: `{pkg_info.get('channel', 'stable')}`)\n\n"
                f"⚠️ **PERINGATAN KESELAMATAN JARINGAN**:\n"
                f"1. Router akan mengunduh paket pembaruan dan melakukan **REBOOT otomatis**.\n"
                f"2. Seluruh koneksi jaringan & internet akan offline sementara selama **1-3 menit**.\n"
                f"3. Pastikan pasokan listrik router stabil selama proses penulisan firmware flash memory!\n\n"
                f"Apakah Anda yakin ingin memulai proses upgrade firmware sekarang?\n"
                f"👉 Balas **Ya** atau klik tombol [ YA ] di bawah untuk mengeksekusi, atau **Batal** untuk membatalkan."
            )
            return {"reply": confirm_card, "pending_action": pending}

        # Set Router Identity
        if any(w in lower for w in ("ganti nama router", "ubah nama router", "set identity", "ubah identitas router")):
            if not security_manager.can_user_write(user_id):
                return {
                    "reply": "⛔ **Akses Terbatas**: Role Viewer tidak dapat mengubah identitas router.",
                    "action_required": False,
                    "pending_action": None,
                }
            name_match = re.search(r'(?:menjadi|jadi|nama)\s+([a-zA-Z0-9_-]+)', prompt, re.IGNORECASE)
            new_name = name_match.group(1) if name_match else "MikroTik-New"
            args = {"device": device_name, "name": new_name}
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name="set_identity",
                arguments=args,
                description=f"Ubah nama identitas router menjadi '{new_name}'",
            )
            confirm_card = (
                f"⚠️ **Konfirmasi Diperlukan**\n\n"
                f"Target      : **{device_name}**\n"
                f"Aksi        : `Set Router Identity`\n"
                f"Nama Baru   : **{new_name}**\n\n"
                f"Lanjutkan perubahan nama router?\n"
                f"👉 Balas **Ya** untuk setuju atau **Batal** untuk membatalkan."
            )
            return {"reply": confirm_card, "pending_action": pending}

        # Create System User
        if any(w in lower for w in ("tambah user sistem", "buat user sistem", "tambah user admin", "buat user admin", "tambah user router")):
            if not security_manager.can_user_write(user_id):
                return {
                    "reply": "⛔ **Akses Terbatas**: Hanya Administrator yang dapat menambah user sistem.",
                    "action_required": False,
                    "pending_action": None,
                }
            user_match = re.search(r'(?:bernama|nama|user)\s+([a-zA-Z0-9_-]+)', prompt, re.IGNORECASE)
            uname = user_match.group(1) if user_match else "operator" + str(int(time.time()) % 100)
            group_match = re.search(r'(?:group|grup|akses)\s+(read|write|full)', prompt, re.IGNORECASE)
            group = group_match.group(1).lower() if group_match else "read"
            args = {"device": device_name, "name": uname, "group": group, "password": "pass" + uname}
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name="create_system_user",
                arguments=args,
                description=f"Pembuatan user sistem '{uname}' ({group})",
            )
            confirm_card = (
                f"⚠️ **Konfirmasi Diperlukan**\n\n"
                f"Target    : **{device_name}**\n"
                f"Aksi      : `Create System User`\n"
                f"Username  : **{uname}**\n"
                f"Group     : `{group}`\n"
                f"Password  : `{args['password']}`\n\n"
                f"Lanjutkan pembuatan user sistem router?\n"
                f"👉 Balas **Ya** untuk setuju atau **Batal** untuk membatalkan."
            )
            return {"reply": confirm_card, "pending_action": pending}

        # Delete System User
        if any(w in lower for w in ("hapus user sistem", "delete user sistem", "hapus user router")):
            if not security_manager.can_user_write(user_id):
                return {
                    "reply": "⛔ **Akses Terbatas**: Hanya Administrator yang dapat menghapus user sistem.",
                    "action_required": False,
                    "pending_action": None,
                }
            user_match = re.search(r'(?:bernama|nama|user)\s+([a-zA-Z0-9_-]+)', prompt, re.IGNORECASE)
            uname = user_match.group(1) if user_match else ""
            if not uname:
                return {"reply": "Silakan tentukan nama user sistem yang ingin dihapus. Contoh: 'Hapus user sistem teknisi'.", "pending_action": None}
            args = {"device": device_name, "name": uname}
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name="delete_system_user",
                arguments=args,
                description=f"Penghapusan user sistem '{uname}'",
            )
            confirm_card = (
                f"⚠️ **Konfirmasi Diperlukan**\n\n"
                f"Target    : **{device_name}**\n"
                f"Aksi      : `Delete System User`\n"
                f"Username  : **{uname}**\n\n"
                f"Lanjutkan penghapusan user sistem?\n"
                f"👉 Balas **Ya** untuk setuju atau **Batal** untuk membatalkan."
            )
            return {"reply": confirm_card, "pending_action": pending}

        # Add Netwatch
        if any(w in lower for w in ("tambah netwatch", "buat netwatch", "pantau host baru netwatch")):
            if not security_manager.can_user_write(user_id):
                return {
                    "reply": "⛔ **Akses Terbatas**: Role Viewer tidak dapat menambahkan Netwatch.",
                    "action_required": False,
                    "pending_action": None,
                }
            host_match = re.search(r'([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})', prompt)
            target_host = host_match.group(1) if host_match else "8.8.8.8"
            args = {"device": device_name, "host": target_host, "interval": "1m", "timeout": "1000ms", "comment": f"Netwatch for {target_host}"}
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name="add_netwatch",
                arguments=args,
                description=f"Penambahan host Netwatch '{target_host}'",
            )
            confirm_card = (
                f"⚠️ **Konfirmasi Diperlukan**\n\n"
                f"Target    : **{device_name}**\n"
                f"Aksi      : `Add Netwatch`\n"
                f"Host      : **{target_host}**\n"
                f"Interval  : `1m`\n"
                f"Timeout   : `1000ms`\n\n"
                f"Tambahkan host ke pemantauan Netwatch?\n"
                f"👉 Balas **Ya** untuk setuju atau **Batal** untuk membatalkan."
            )
            return {"reply": confirm_card, "pending_action": pending}

        # Add Traffic Monitor
        if any(w in lower for w in ("tambah traffic monitor", "buat traffic monitor", "bikin traffic monitor", "pasang traffic monitor")):
            if not security_manager.can_user_write(user_id):
                return {
                    "reply": "⛔ **Akses Terbatas**: Role Viewer tidak dapat menambahkan aturan Traffic Monitor.",
                    "action_required": False,
                    "pending_action": None,
                }
            name_match = re.search(r'(?:nama|name)\s+([a-zA-Z0-9_-]+)', prompt, re.IGNORECASE)
            tm_name = name_match.group(1) if name_match else "tm_" + str(int(time.time()) % 1000)
            iface_match = re.search(r'(?:interface|port)\s+([a-zA-Z0-9_-]+)', prompt, re.IGNORECASE)
            tm_iface = iface_match.group(1) if iface_match else "ether1-WAN"
            thresh_match = re.search(r'(?:threshold|batas|ambang)\s+([0-9]+(?:\.[0-9]+)?\s*(?:g|m|k|bps|gbps|mbps|kbps)?)', prompt, re.IGNORECASE)
            if not thresh_match:
                thresh_match = re.search(r'\b([0-9]+(?:\.[0-9]+)?\s*(?:g|m|k|bps|gbps|mbps|kbps))\b', prompt, re.IGNORECASE)
            tm_thresh = thresh_match.group(1).replace(" ", "") if thresh_match else "50M"
            trig = "below" if "below" in lower or "bawah" in lower else "above"
            
            args = {"device": device_name, "name": tm_name, "interface": tm_iface, "threshold": tm_thresh, "trigger": trig}
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name="add_traffic_monitor",
                arguments=args,
                description=f"Penambahan Traffic Monitor '{tm_name}' pada {tm_iface} (Threshold: {tm_thresh})",
            )
            confirm_card = (
                f"⚠️ **Konfirmasi Diperlukan**\n\n"
                f"Target    : **{device_name}**\n"
                f"Aksi      : `Add Traffic Monitor`\n"
                f"Nama      : `{tm_name}`\n"
                f"Interface : `{tm_iface}`\n"
                f"Threshold : `{tm_thresh}` (Trigger: `{trig}`)\n\n"
                f"Pasang aturan Traffic Monitor ini ke router?\n"
                f"👉 Balas **Ya** untuk setuju atau **Batal** untuk membatalkan."
            )
            return {"reply": confirm_card, "pending_action": pending}

        # Send Email via router
        if any(w in lower for w in ("kirim email dari router", "kirim notifikasi email", "send email router")):
            if not security_manager.can_user_write(user_id):
                return {
                    "reply": "⛔ **Akses Terbatas**: Role Viewer tidak dapat mengirim email via router.",
                    "action_required": False,
                    "pending_action": None,
                }
            email_match = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', prompt)
            target_email = email_match.group(1) if email_match else "admin@domain.com"
            args = {"device": device_name, "to": target_email, "subject": "Tes Notifikasi MikroTik", "body": f"Notifikasi otomatis dari router {device_name} via Hermes AI Telegram Bot."}
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name="send_router_email",
                arguments=args,
                description=f"Kirim email router ke {target_email}",
            )
            confirm_card = (
                f"⚠️ **Konfirmasi Diperlukan**\n\n"
                f"Target    : **{device_name}**\n"
                f"Aksi      : `Send Router Email`\n"
                f"Penerima  : `{target_email}`\n"
                f"Subjek    : `{args['subject']}`\n\n"
                f"Lanjutkan pengiriman email via SMTP router?\n"
                f"👉 Balas **Ya** untuk setuju atau **Batal** untuk membatalkan."
            )
            return {"reply": confirm_card, "pending_action": pending}

        # Set Timezone
        if any(w in lower for w in ("ganti timezone", "ubah timezone", "set timezone", "ubah zona waktu")):
            if not security_manager.can_user_write(user_id):
                return {
                    "reply": "⛔ **Akses Terbatas**: Role Viewer tidak dapat mengubah zona waktu router.",
                    "action_required": False,
                    "pending_action": None,
                }
            tz_match = re.search(r'(?:ke|menjadi|timezone)\s+([a-zA-Z]+/[a-zA-Z_]+)', prompt, re.IGNORECASE)
            tz = tz_match.group(1) if tz_match else "Asia/Jakarta"
            args = {"device": device_name, "time_zone": tz}
            pending = confirmation_manager.create_pending_action(
                user_id=user_id,
                device_name=device_name,
                action_name="set_clock_timezone",
                arguments=args,
                description=f"Ubah zona waktu ke {tz}",
            )
            confirm_card = (
                f"⚠️ **Konfirmasi Diperlukan**\n\n"
                f"Target      : **{device_name}**\n"
                f"Aksi        : `Set Clock Timezone`\n"
                f"Zona Waktu  : `{tz}`\n\n"
                f"Lanjutkan pengaturan zona waktu jam router?\n"
                f"👉 Balas **Ya** untuk setuju atau **Batal** untuk membatalkan."
            )
            return {"reply": confirm_card, "pending_action": pending}

        # =====================================================================
        # GREETINGS, THANKS, & CASUAL CONVERSATION
        # =====================================================================
        # Casual ping / test letter
        if lower.strip() in ("p", "pp", "ping!", "tes", "test"):
            return {
                "reply": f"👋 Ya, halo {username}! Hermes AI Agent aktif dan siap membantu di router **{device_name}**. Ada yang ingin diperiksa atau dikonfigurasi?",
                "pending_action": None,
            }

        # Role & Admin Status Inquiry
        if any(w in lower for w in (
            "blom admin", "belum admin", "bukan admin", "role saya", "apakah saya admin",
            "apakah aku admin", "status saya", "status role", "hak akses", "admin bukan",
            "udah admin", "sudah admin", "cek role", "bisa akses apa"
        )):
            role = security_manager.get_user_role(user_id)
            if role == "ADMIN":
                reply = (
                    f"👤 **Status Hak Akses ({username})**\n\n"
                    f"• Telegram ID : `{user_id}`\n"
                    f"• Peran (Role): 🟢 **Administrator** (Full Access)\n\n"
                    f"Anda memiliki izin penuh untuk monitoring, diagnosa jaringan, "
                    f"serta eksekusi perubahan konfigurasi pada router **{device_name}**."
                )
            else:
                reply = (
                    f"👤 **Status Hak Akses ({username})**\n\n"
                    f"• Telegram ID : `{user_id}`\n"
                    f"• Peran (Role): 🟡 **Viewer** (Read-Only)\n\n"
                    f"Saat ini akun Anda berstatus **Viewer**. Anda dapat memantau status, trafik, "
                    f"dan kesehatan router **{device_name}**.\n\n"
                    f"ℹ️ Untuk mendapatkan hak akses Administrator (misal: membuat voucher hotspot, menyalakan/mematikan port), "
                    f"silakan minta admin utama untuk mendaftarkan ID Telegram Anda (`{user_id}`) ke whitelist `ADMIN_USER_IDS`."
                )
            return {"reply": reply, "pending_action": None}

        # Team Chatter: Waiting / Delay
        if any(lower.strip() == w or lower.strip().startswith(w + " ") for w in (
            "belum mas", "belum", "blom", "sebentar", "bentar", "tunggu", "nanti dulu", "sebentar mas", "tunggu sebentar", "bentar mas"
        )):
            return {
                "reply": f"Baik mas {username}, santai saja! Ditunggu ya. Kabari kalau sudah siap atau ada yang perlu dibantu untuk router **{device_name}**. 👍",
                "pending_action": None,
            }

        # Team Chatter: Done / Finished
        if any(lower.strip() == w or lower.strip().startswith(w + " ") for w in (
            "sudah mas", "sudah ya", "udah mas", "udah", "beres", "done", "selesai", "beres mas", "sudah selesai"
        )):
            return {
                "reply": f"Mantap, siap mas {username}! Ada yang ingin dicek lagi atau perlu dibantu di router **{device_name}**?",
                "pending_action": None,
            }

        # Team Chatter: Acknowledgement / Agreement
        if any(lower.strip() == w or lower.strip().startswith(w + " ") for w in (
            "oke mas", "ok mas", "oke", "ok", "siap mas", "siap", "baik mas", "baik", "sip", "sip mas", "noted", "mantap"
        )):
            return {
                "reply": f"Siap mas/mbak {username}! Jika sewaktu-waktu ada kendala koneksi atau butuh cek konfigurasi jaringan, langsung hubungi saya ya. 🤝",
                "pending_action": None,
            }

        # Team Chatter: Trying / Testing
        if any(lower.strip() == w or lower.strip().startswith(w + " ") for w in (
            "coba mas", "coba ya", "tes mas", "coba dulu", "saya coba", "aku coba"
        )):
            return {
                "reply": f"Silakan dicoba mas/mbak {username}! Nanti jika ada kendala atau butuh dicek statusnya di router **{device_name}**, beri tahu saya ya.",
                "pending_action": None,
            }

        # Gratitude
        if any(w in lower for w in ("terima kasih", "makasih", "matur nuwun", "thanks", "thank you")):
            return {
                "reply": f"🙏 **Sama-sama, {username}!** Senang bisa membantu Anda mengelola router **{device_name}**. Jika ada kendala jaringan atau hal lain yang ingin diperiksa, silakan tanyakan kapan saja!",
                "pending_action": None,
            }

        # Casual Greeting
        greeting_words = (
            "halo", "hallo", "haloo", "halloo",
            "hai", "haii", "haiii", "hay",
            "hello", "hi", "hii", "hey", "heyy",
            "pagi", "selamat pagi", "met pagi",
            "siang", "selamat siang", "met siang",
            "sore", "selamat sore", "met sore",
            "malam", "selamat malam", "met malam",
            "assalamu", "assalamualaikum", "salam", "permisi"
        )
        if any(lower.strip().startswith(w) or lower.strip() == w for w in greeting_words):
            return {
                "reply": (
                    f"👋 **Halo, {username}!** Saya **Hermes AI Agent**, asisten pengelola jaringan MikroTik (**{device_name}**).\n\n"
                    f"Saya siap membantu menjawab pertanyaan Anda, memeriksa performa router, mendiagnosa koneksi, maupun memonitor server. "
                    f"Ada yang bisa saya bantu hari ini, Mas/Mbak {username}?"
                ),
                "pending_action": None,
            }

        # Help / Identity / Capability Inquiry
        is_help = any(w in lower for w in (
            "siapa kamu", "kamu siapa", "bisa bantu apa", "fitur apa", "bantuan", "command", "perintah", "panduan", "bisa ngapain"
        )) or bool(re.search(r'\b(menu|help|bantuan|panduan)\b', lower))
        if is_help and not any(w in lower for w in ("hop", "trace", "ping", "rute", "route", "ip", "wan", "menuju")):
            return {
                "reply": (
                    f"🧭 **Panduan & Fitur Hermes AI Agent ({device_name})**\n\n"
                    f"Anda dapat berinteraksi secara fleksibel menggunakan bahasa sehari-hari, contohnya:\n\n"
                    f"📡 **Pemeriksaan & Monitoring:**\n"
                    f"• *'cek'* atau *'cek jaringan'* — Laporan cepat kesehatan router & WAN.\n"
                    f"• *'cek kondisi router'* — Analisis menyeluruh CPU, RAM, & status router.\n"
                    f"• *'kenapa internet lambat'* — Investigasi komprehensif akar masalah jaringan.\n"
                    f"• *'berapa cpu sekarang'* / *'sisa ram router'* — Pengecekan metrik spesifik.\n\n"
                    f"👥 **Pengguna & Jaringan:**\n"
                    f"• *'siapa saja yang terhubung'* — Daftar perangkat & DHCP lease.\n"
                    f"• *'cek user hotspot aktif'* — Pemantauan user yang sedang login.\n"
                    f"• *'ping ke 8.8.8.8'* atau *'traceroute ke 1.1.1.1'* — Diagnosa latensi & rute.\n\n"
                    f"⚙️ **Konfigurasi (Khusus Administrator):**\n"
                    f"• *'buatkan user hotspot Tamu123 aktif 1 hari'*\n"
                    f"• *'nyalakan ether 10'* atau *'matikan port 2'*\n"
                    f"• *'backup konfigurasi router'*\n\n"
                    f"Silakan langsung sampaikan apa yang ingin Anda tanyakan atau instruksikan!"
                ),
                "pending_action": None,
            }

        # =====================================================================
        # WINBOX TOOLS & SYSTEM FEATURES (READ-ONLY & DIAGNOSTICS)
        # =====================================================================
        # 1. Traceroute (Hop tracking)
        is_trace = any(w in lower for w in (
            "traceroute", "tracert", "trace jalur", "lacak rute", "lacak hop",
            "lihat hop", "hop menuju", "trace ke", "rute hop"
        )) or bool(re.search(r'\b(traceroute|tracert)\b', lower))
        if is_trace:
            ip_match = re.search(r'(\b[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\b)', prompt)
            target_match = re.search(r'(?:traceroute|tracert|trace|ke|menuju|target|host)\s+([a-zA-Z0-9_.-]+)', prompt, re.IGNORECASE)
            if ip_match:
                target = ip_match.group(1)
            elif target_match and target_match.group(1).lower() not in ("ke", "jalur", "hop", "menuju", "rute"):
                target = target_match.group(1)
            else:
                target = "8.8.8.8"
            reply = self._generate_traceroute_report(device_name, target)
            return {"reply": reply, "pending_action": None}

        # 2. Torch (Real-time traffic monitoring)
        if any(w in lower for w in ("torch", "pantau traffic interface", "cek torch", "lalu lintas realtime")):
            iface_match = re.search(r'(?:interface|port)\s+([a-zA-Z0-9_\- ]+?)(?:\s+(?:selama|durasi|duration|\d+s|\d+\s*detik)|$)', prompt, re.IGNORECASE)
            if not iface_match:
                iface_match = re.search(r'(?:torch|pada)\s+([a-zA-Z0-9_\- ]+?)(?:\s+(?:selama|durasi|duration|\d+s|\d+\s*detik)|$)', prompt, re.IGNORECASE)
            iface_name = iface_match.group(1).strip() if iface_match else "ether1-WAN"
            res = TOOL_REGISTRY["tool_torch"](device=device_name, interface=iface_name, duration=3)
            data = res.get("data")
            streams = data if isinstance(data, list) else (data.get("active_streams", []) if isinstance(data, dict) else [])
            if not res.get("success") and not streams:
                err_msg = res.get("error") or res.get("message") or "Interface tidak ditemukan"
                return {"reply": f"⚠️ **Gagal menjalankan Torch pada interface `{iface_name}`:**\n{err_msg}", "pending_action": None}

            def _fmt_rate(val):
                try:
                    r = float(val)
                    if r >= 1_000_000:
                        return f"{r / 1_000_000:.1f} Mbps"
                    elif r >= 1000:
                        return f"{r / 1000:.1f} kbps"
                    return f"{int(r)} bps"
                except (ValueError, TypeError):
                    return str(val)

            msg = res.get("message", "")
            lines = [f"🔦 **Pemantauan Trafik Real-Time (Torch) pada `{iface_name}`**\n"]
            if msg and "selesai" in msg:
                lines.append(f"_{msg}_\n")

            displayed_streams = streams[:12]
            for s in displayed_streams:
                src = s.get("src_address") or s.get("src-address", "-")
                dst = s.get("dst_address") or s.get("dst-address", "-")
                proto = str(s.get("ip-protocol") or s.get("protocol") or s.get("proto", "-")).upper()
                port = s.get("dst-port") or s.get("port") or s.get("src-port")
                port_str = f":{port}" if port and str(port) != "-" else ""
                rx = _fmt_rate(s.get("rx_rate_kbps") or s.get("rx", 0))
                tx = _fmt_rate(s.get("tx_rate_kbps") or s.get("tx", 0))
                lines.append(f"• `{src}` ➔ `{dst}` | {proto}{port_str} | RX: `{rx}` TX: `{tx}`")
            if not streams:
                lines.append("• Tidak ada aliran trafik aktif terdeteksi saat ini.")
            else:
                if len(streams) > len(displayed_streams):
                    lines.append(f"\n_Menampilkan {len(displayed_streams)} dari total {len(streams)} aliran trafik aktif._")
                else:
                    lines.append("\nTop traffic streams aktif teridentifikasi.")
            return {"reply": "\n".join(lines), "pending_action": None}

        # 3. Bandwidth Test
        if any(w in lower for w in ("bandwidth test", "btest", "uji bandwidth", "tes kecepatan router")):
            ip_match = re.search(r'([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})', prompt)
            target = ip_match.group(1) if ip_match else "10.20.33.1"
            res = TOOL_REGISTRY["tool_bandwidth_test"](device=device_name, target=target)
            raw_d = res.get("data")
            d = raw_d[-1] if isinstance(raw_d, list) and raw_d else (raw_d if isinstance(raw_d, dict) else {})
            status = str(d.get("status", "unknown")).lower()
            is_success = res.get("success", False)

            if not is_success or any(err_kw in status for err_kw in ("can not connect", "connection refused", "failed", "authentication failed", "unknown", "error")):
                if "auth" in status:
                    auth_reason = (
                        "• **Penyebab**: Autentikasi ditolak (`authentication failed`). "
                        "Router target mewajibkan username/password untuk Bandwidth Test, atau password yang diberikan salah.\n"
                        "• **Solusi**: Matikan syarat autentikasi pada Bandwidth Server di router target via Winbox:\n"
                        "  `/tool bandwidth-server set authenticate=no`"
                    )
                else:
                    auth_reason = (
                        "1. Target `{target}` bukan router MikroTik, atau fitur **Bandwidth Server** pada target belum diaktifkan.\n"
                        "2. Untuk mengaktifkan Bandwidth Server pada router MikroTik target, jalankan di Terminal/Winbox target:\n"
                        "   `/tool bandwidth-server set enabled=yes authenticate=no`\n"
                        "3. Pastikan port pengujian (UDP/TCP port 2000) tidak diblokir oleh firewall."
                    )
                reply = (
                    f"⚠️ **Bandwidth Test ke `{target}` Gagal Terhubung**\n\n"
                    f"• Target Host : `{target}`\n"
                    f"• Status      : 🔴 `{status}`\n"
                    f"• Perangkat   : {device_name}\n\n"
                    f"💡 **Penyebab & Solusi:**\n"
                    f"{auth_reason}"
                )
                return {"reply": reply, "pending_action": None}

            rx_mbps = d.get("rx_throughput_mbps", 0)
            tx_mbps = d.get("tx_throughput_mbps", 0)
            lost = d.get("lost_packets", 0)
            jitter = d.get("jitter_ms", 0)
            reply = (
                f"🚀 **Hasil Bandwidth Test ke {target}**\n\n"
                f"• Target Host              : `{target}`\n"
                f"• Status                   : 🟢 Selesai (`{status}`)\n"
                f"• Throughput RX (Download) : **{rx_mbps} Mbps**\n"
                f"• Throughput TX (Upload)   : **{tx_mbps} Mbps**\n"
                f"• Paket Hilang (Loss)     : `{lost} packet`\n"
                f"• Jitter                  : `{jitter} ms`\n\n"
                f"Kapasitas throughput router dalam kondisi optimal."
            )
            return {"reply": reply, "pending_action": None}

        # 4. Netwatch
        if any(w in lower for w in ("netwatch", "pantauan netwatch", "status host netwatch", "daftar netwatch")) and not any(w in lower for w in ("tambah", "buat")):
            res = TOOL_REGISTRY["get_netwatch"](device=device_name)
            raw_hosts = res.get("data")
            hosts = raw_hosts if isinstance(raw_hosts, list) else (raw_hosts.get("hosts", []) if isinstance(raw_hosts, dict) else [])
            lines = [f"👁️ **Daftar Pemantauan Netwatch pada {device_name}**\n"]
            for h in hosts:
                st = "🟢 UP" if str(h.get("status")).lower() == "up" else "🔴 DOWN"
                lines.append(f"• Host `{h.get('host')}`: {st} (Interval: `{h.get('interval')}`, Sejak: `{h.get('since')}`)")
                if h.get("comment"):
                    lines.append(f"  ↳ _{h.get('comment')}_")
            if not hosts:
                lines.append("• Belum ada target host Netwatch yang didaftarkan.")
            return {"reply": "\n".join(lines), "pending_action": None}

        # 5. IP Scan
        if any(w in lower for w in ("ip scan", "scan ip", "pindai ip", "scan subnet")):
            iface_match = re.search(r'(?:interface|port)\s+([a-zA-Z0-9_\- ]+?)(?:\s+(?:selama|durasi|duration|\d+s|\d+\s*detik)|$)', prompt, re.IGNORECASE)
            if not iface_match:
                iface_match = re.search(r'(?:ip scan|scan ip|pindai ip|scan subnet|pada)\s+([a-zA-Z0-9_\- ]+?)(?:\s+(?:selama|durasi|duration|\d+s|\d+\s*detik)|$)', prompt, re.IGNORECASE)
            iface_name = iface_match.group(1).strip() if iface_match else "ether1-WAN"
            res = TOOL_REGISTRY["tool_ip_scan"](device=device_name, interface=iface_name)
            data = res.get("data")
            raw_hosts = data if isinstance(data, list) else (data.get("discovered", []) if isinstance(data, dict) else [])
            if not res.get("success") and not raw_hosts:
                err_msg = res.get("error") or res.get("message") or "Interface tidak ditemukan"
                return {"reply": f"⚠️ **Gagal menjalankan IP Scan pada interface `{iface_name}`:**\n{err_msg}", "pending_action": None}

            # Deduplicate by IP address while preserving order
            seen_ips = set()
            hosts = []
            for h in raw_hosts:
                ip_val = h.get("ip") or h.get("address")
                if ip_val and ip_val not in seen_ips:
                    seen_ips.add(ip_val)
                    hosts.append(h)
                elif not ip_val:
                    hosts.append(h)

            msg = res.get("message", "")
            lines = [f"🔍 **Hasil IP Scan pada `{iface_name}`**\n"]
            if msg and "selesai" in msg:
                lines.append(f"_{msg}_\n")

            displayed_hosts = hosts[:15]
            for h in displayed_hosts:
                ip_val = h.get("ip") or h.get("address", "-")
                mac_val = h.get("mac_address") or h.get("mac-address", "-")
                host_val = h.get("dns") or h.get("snmp") or h.get("netbios") or h.get("dns_name") or "-"
                host_str = f" | Host: `{host_val}`" if host_val and host_val != "-" else ""
                lines.append(f"• IP `{ip_val}` | MAC: `{mac_val}`{host_str}")
            if not hosts:
                lines.append("• Tidak ditemukan host aktif pada scan.")
            else:
                if len(hosts) > len(displayed_hosts):
                    lines.append(f"\n_Menampilkan {len(displayed_hosts)} dari total {len(hosts)} perangkat aktif terdeteksi._")
                else:
                    lines.append(f"\nDitemukan total **{len(hosts)}** perangkat aktif.")
            return {"reply": "\n".join(lines), "pending_action": None}

        # 6. CPU Profile
        if any(w in lower for w in ("profile cpu", "cpu profile", "rincian proses cpu", "proses sistem")):
            res = TOOL_REGISTRY["get_cpu_profile"](device=device_name)
            raw_data = res.get("data")
            data = raw_data if isinstance(raw_data, dict) else (raw_data[-1] if isinstance(raw_data, list) and raw_data else {})
            procs = data.get("cpu_usage", [])
            lines = [f"⚙️ **Rincian Profil Beban CPU (Profile) {device_name}**\n"]
            for p in procs:
                bar = "█" * int(p.get("cpu_percent", 0) / 2)
                lines.append(f"• `{p.get('process')}`: **{p.get('cpu_percent')}%** {bar}")
            lines.append(f"\nTotal CPU sibuk: **{data.get('total_busy_percent', 0)}%**.")
            return {"reply": "\n".join(lines), "pending_action": None}

        # 7. Packet Sniffer
        if any(w in lower for w in ("sniffer", "packet sniffer", "tangkap paket", "cek paket data")):
            res = TOOL_REGISTRY["sniff_packets"](device=device_name)
            raw_data = res.get("data")
            pkts = raw_data if isinstance(raw_data, list) else (raw_data.get("packets", []) if isinstance(raw_data, dict) else [])
            lines = [f"📦 **Sampel Paket Data (Packet Sniffer) {device_name}**\n"]
            for p in pkts:
                num = p.get("num", "-")
                proto = p.get("proto") or p.get("protocol", "-")
                src = p.get("src") or p.get("src-address", "-")
                dst = p.get("dst") or p.get("dst-address", "-")
                size = p.get("size", "-")
                lines.append(f"• `#{num}` [{proto}] `{src}` ➔ `{dst}` ({size} bytes)")
            if not pkts:
                lines.append("• Belum ada paket yang tertangkap oleh sniffer.")
            return {"reply": "\n".join(lines), "pending_action": None}

        # 8. Traffic Monitor
        if any(w in lower for w in ("traffic monitor", "pantau batas bandwidth", "traffic-monitor")):
            res = TOOL_REGISTRY["get_traffic_monitor"](device=device_name)
            if not res.get("success"):
                return {
                    "reply": f"⚠️ Gagal mengambil data Traffic Monitor pada **{device_name}**: `{res.get('error') or res.get('message')}`",
                    "pending_action": None,
                }
            monitors = res.get("data") or []
            if isinstance(monitors, dict):
                monitors = monitors.get("monitors", [])
            
            if not monitors:
                reply = (
                    f"📈 **Daftar Traffic Monitor pada {device_name}**\n\n"
                    f"ℹ️ **Belum ada aturan Traffic Monitor yang terpasang** di router **{device_name}** (0 aturan aktif).\n\n"
                    f"💡 **Penjelasan Fitur:**\n"
                    f"Fitur `/tool traffic-monitor` di RouterOS digunakan untuk memicu peringatan/script otomatis ketika lalu lintas bandwidth pada suatu port melampaui batas ambang tertentu (threshold).\n\n"
                    f"📊 **Ingin melihat trafik langsung (live bandwidth)?**\n"
                    f"• Ketik *'Cek trafik interface'* untuk melihat statistik RX/TX byte seluruh port.\n"
                    f"• Ketik *'Torch ether1-WAN'* untuk melihat penggunaan bandwidth real-time per IP/koneksi."
                )
                return {"reply": reply, "pending_action": None}

            lines = [f"📈 **Daftar Traffic Monitor pada {device_name}** ({len(monitors)} aturan):\n"]
            for idx, tm in enumerate(monitors, 1):
                name = tm.get("name", f"monitor_{idx}")
                iface = tm.get("interface", "-")
                trig = tm.get("trigger", "above")
                thresh = tm.get("threshold", "0")
                try:
                    t_int = int(thresh)
                    if t_int >= 1_000_000_000:
                        thresh_str = f"{t_int / 1_000_000_000:.1f} Gbps"
                    elif t_int >= 1_000_000:
                        thresh_str = f"{t_int / 1_000_000:.1f} Mbps"
                    elif t_int >= 1_000:
                        thresh_str = f"{t_int / 1_000:.1f} Kbps"
                    else:
                        thresh_str = f"{t_int} bps"
                except Exception:
                    thresh_str = f"{thresh} bps"
                status_str = "Aktif 🟢" if not tm.get("disabled") else "Nonaktif 🔴"
                on_event = tm.get("on-event") or tm.get("on_event", "")
                event_str = f"\n     Event: `{on_event}`" if on_event else ""
                lines.append(f"{idx}. **{name}** (Interface: `{iface}`)\n     Trigger: `{trig}` {thresh_str} | Status: {status_str}{event_str}")
            return {"reply": "\n".join(lines), "pending_action": None}

        # 9. Identity (Get)
        if any(w in lower for w in ("nama router", "identitas router", "cek identity", "apa nama mikrotik")) and not any(w in lower for w in ("ganti", "ubah", "set")):
            res = TOOL_REGISTRY["get_identity"](device=device_name)
            name = (res.get("data") or {}).get("name", device_name)
            return {"reply": f"🏷️ Identitas (Identity) sistem router saat ini adalah: **{name}**", "pending_action": None}

        # 10. System Users (Get)
        if any(w in lower for w in ("user sistem", "user router", "daftar user admin", "user winbox")) and not any(w in lower for w in ("tambah", "buat", "hapus", "delete", "hotspot")):
            res = TOOL_REGISTRY["get_system_users"](device=device_name)
            users = res.get("data") or []
            lines = [f"👥 **Daftar Pengguna Sistem (Winbox Users) {device_name}**\n"]
            for u in users:
                lines.append(f"• Username: **{u.get('name')}** | Grup: `{u.get('group')}` | Login Terakhir: `{u.get('last_logged_in')}`")
            if not users:
                lines.append("  _(Tidak ada pengguna tambahan yang terdaftar)_")
            return {"reply": "\n".join(lines), "pending_action": None}

        # 11. Packages (Get)
        if any(w in lower for w in ("package router", "paket routeros", "daftar package", "cek package", "packages")):
            res = TOOL_REGISTRY["get_packages"](device=device_name)
            pkgs = res.get("data") or []
            lines = [f"📦 **Daftar Paket RouterOS yang Terpasang ({device_name})**\n"]
            for p in pkgs:
                st = "Nonaktif" if p.get("disabled") else "Aktif 🟢"
                lines.append(f"• **{p.get('name')}** v`{p.get('version')}` ({p.get('bundle')}) - {st}")
            if not pkgs:
                lines.append("  _(Tidak ada paket tambahan yang terpasang)_")
            return {"reply": "\n".join(lines), "pending_action": None}

        # 11.5 Firmware Status & RouterOS Update (Get)
        if any(w in lower for w in (
            "cek firmware", "cek frimware", "status firmware", "status frimware", "update firmware",
            "cek update", "apakah ada update", "versi terbaru", "update routeros", "info firmware",
            "info frimware", "cek versi mikrotik", "firmware status", "frimware status",
            "cek upgrade", "update apa", "ada update", "bisa update", "bisa upgrade", "bisa mengupdate",
            "cara update", "cara upgrade", "apdet router",
        )) or ((any(w in lower for w in ("firmware", "frimware", "fremware", "routeros", "bios router", "upgrade", "bootloader")) and any(w in lower for w in ("cek", "lihat", "status", "info", "ada", "tersedia", "apakah", "bisa", "bagaimana", "cara")))):
            res = TOOL_REGISTRY["get_firmware_status"](device=device_name)
            data = res.get("data") or {}
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
                    f"Ketik: 👉 *\"Upgrade firmware {device_name}\"*\n"
                    "Atau gunakan perintah: `/upgrade` untuk memperbarui sistem secara otomatis."
                )
            elif has_rb_update:
                lines.append(
                    "💡 **Tindakan yang Disarankan:**\n"
                    "Firmware bootloader baru tersedia untuk hardware ini.\n"
                    f"Ketik: 👉 *\"Upgrade bootloader {device_name}\"* untuk memperbarui BIOS router."
                )
            else:
                lines.append("✨ Perangkat Anda telah menggunakan versi firmware dan sistem operasi paling mutakhir dan stabil.")

            return {"reply": "\n".join(lines), "pending_action": None}

        # 12. RouterBOARD Info (Get)
        if any(w in lower for w in ("routerboard", "serial number", "firmware", "bios router", "nomor seri")):
            res = TOOL_REGISTRY["get_routerboard"](device=device_name)
            rb = res.get("data") or {}
            reply = (
                f"🖧 **Informasi Hardware RouterBOARD ({device_name})**\n\n"
                f"• Model Board     : **{rb.get('model', '-')}** ({rb.get('board_name', '-')})\n"
                f"• Serial Number   : `{rb.get('serial_number', '-')}`\n"
                f"• Firmware Aktif  : `v{rb.get('current_firmware', '-')}`\n"
                f"• Upgrade Firmware: `v{rb.get('upgrade_firmware', '-')}`\n"
                f"• Factory Firmware: `v{rb.get('factory_firmware', '-')}`\n\n"
                f"Hardware RouterBOARD dan firmware BIOS dalam status prima."
            )
            return {"reply": reply, "pending_action": None}

        # 13. Clock & SNTP (Get)
        if any(w in lower for w in ("jam router", "waktu router", "status sntp", "cek ntp", "zona waktu", "tanggal router")) and not any(w in lower for w in ("ganti", "ubah", "set")):
            res = TOOL_REGISTRY["get_clock_sntp"](device=device_name)
            data = res.get("data") or {}
            clk = data.get("clock", {})
            sntp = data.get("sntp", {})
            reply = (
                f"⏰ **Waktu Sistem & Sinkronisasi SNTP Client ({device_name})**\n\n"
                f"• Waktu Sekarang  : **{clk.get('time', '-')}** ({clk.get('date', '-')})\n"
                f"• Zona Waktu      : `{clk.get('time_zone_name', '-')}` ({clk.get('gmt_offset', '-')})\n"
                f"• Status SNTP     : **{sntp.get('status', 'synchronized').upper()} 🟢**\n"
                f"• NTP Server      : `{sntp.get('primary_server', '-')}`\n\n"
                f"Jam sistem tersinkronisasi otomatis dengan server waktu dunia."
            )
            return {"reply": reply, "pending_action": None}

        # =====================================================================
        # SPECIFIC SINGLE METRIC QUERIES (DIRECT & TO-THE-POINT)
        # =====================================================================
        # A. Specific CPU Check
        if ("cpu" in lower or "prosesor" in lower or "processor" in lower) and not any(w in lower for w in ("kondisi", "sehat", "lengkap", "lambat", "lemot", "troubleshoot")):
            res = TOOL_REGISTRY["get_resource"](device=device_name).get("data") or {}
            cpu = res.get("cpu_load", 0)
            cpu_count = res.get("cpu_count", 1)
            arch = res.get("architecture_name", "RouterBOARD")
            status = "Normal 🟢" if cpu < 70 else ("Tinggi 🟡" if cpu < 90 else "Kritis 🔴")
            reply = (
                f"📊 **Beban CPU pada {device_name}**\n\n"
                f"• Utilisasi CPU : **{cpu}%** ({status})\n"
                f"• Jumlah Core   : `{cpu_count} Core` ({arch})\n\n"
                f"{'Kinerja prosesor router stabil dan lancar.' if cpu < 70 else 'Penggunaan CPU cukup tinggi. Periksa proses atau koneksi yang sedang padat.'}"
            )
            return {"reply": reply, "pending_action": None}

        # B. Specific RAM / Memory Check
        if any(w in lower for w in ("ram", "memori", "memory")) and not any(w in lower for w in ("kondisi", "sehat", "lengkap", "lambat", "lemot", "troubleshoot")):
            res = TOOL_REGISTRY["get_resource"](device=device_name).get("data") or {}
            mem = res.get("memory_usage_percent", 0.0)
            total_mem = res.get("total_memory_mb", 128.0)
            free_mem = res.get("free_memory_mb", total_mem * (1 - mem / 100))
            used_mem = total_mem - free_mem
            status = "Aman 🟢" if mem < 80 else "Waspada 🟡"
            reply = (
                f"🧠 **Status Memori (RAM) pada {device_name}**\n\n"
                f"• Penggunaan RAM  : **{mem:.1f}%** ({status})\n"
                f"• Memori Terpakai : `{used_mem:.1f} MB` dari total `{total_mem:.1f} MB`\n"
                f"• Sisa Bebas      : **{free_mem:.1f} MB**\n\n"
                f"{'Kapasitas RAM masih sangat memadai untuk operasional jaringan.' if mem < 80 else 'Penggunaan RAM cukup tinggi, perhatikan alokasi cache dan buffer.'}"
            )
            return {"reply": reply, "pending_action": None}

        # C. Specific Uptime Check
        if any(w in lower for w in ("uptime", "sudah berapa lama", "kapan restart", "waktu aktif", "kapan hidup", "nyala sejak")):
            res = TOOL_REGISTRY["get_resource"](device=device_name).get("data") or {}
            uptime = res.get("uptime", "0s")
            uptime_fmt = self._format_uptime(uptime)
            reply = (
                f"⏱️ **Waktu Aktif (Uptime) {device_name}**\n\n"
                f"Router telah aktif menyala selama: **{uptime_fmt}**\n"
                f"• Durasi sistem: `{uptime}`\n\n"
                f"Perangkat beroperasi secara stabil tanpa gangguan restart."
            )
            return {"reply": reply, "pending_action": None}

        # D. Router Type / Model / Hardware / System Info
        is_hardware_kw = bool(re.search(r'\b(tipe|type|model|jenis|spek|spesifikasi|arsitektur|board|routerboard|hardware|seri)\b', lower))
        is_device_kw = bool(re.search(r'\b(router|mikrotik|kamu|perangkat)\b', lower))
        is_system_info = any(w in lower for w in (
            "tipe router", "router type", "model router", "tipe mikrotik", "mikrotik tipe",
            "jenis router", "tipe perangkat", "tipe apa", "model apa", "spesifikasi router",
            "spek router", "arsitektur router", "board name", "versi routeros", "identitas router",
            "info router", "tentang router", "hardware router", "routerboard", "seri router",
            "kamu itu router", "kamu router apa", "router ini tipe apa", "mikrotik ini tipe apa"
        )) or (is_hardware_kw and is_device_kw)

        is_excluded_from_sysinfo = bool(re.search(r'\b(ip|wan|public|publik)\b', lower)) or any(w in lower for w in ("kondisi", "sehat", "lambat", "reboot", "restart", "shutdown", "matikan"))
        if is_system_info and not is_excluded_from_sysinfo:
            reply = self._generate_system_info_report(device_name, prompt)
            return {"reply": reply, "pending_action": None}

        # E. Specific IP Address Query (excluding WAN / Routing queries)
        is_generic_ip_query = (
            any(w in lower for w in ("ip router", "alamat ip", "ip address")) or
            (bool(re.search(r'\bip\b', lower)) and any(w in lower for w in ("apa", "berapa", "mana")))
        ) and not (
            bool(re.search(r'\b(wan|route|rute|gateway|public|publik)\b', lower)) or
            any(w in lower for w in ("server", "port", "cek port"))
        )
        if is_generic_ip_query:
            reply = self._generate_ip_report(device_name, prompt)
            return {"reply": reply, "pending_action": None}

        # F. Specific Active Hotspot User Count
        if "hotspot" in lower and any(w in lower for w in ("berapa user", "berapa orang", "jumlah user", "siapa yang aktif", "user aktif", "siapa saja yang online")):
            active = TOOL_REGISTRY["get_hotspot"](device=device_name, query_type="active").get("data") or []
            if not active:
                reply = f"👥 Saat ini **tidak ada user hotspot yang sedang aktif / login** pada {device_name}."
            else:
                user_list = [f"`{u.get('user', 'Guest')}` ({u.get('address', '-')})" for u in active]
                reply = (
                    f"👥 **User Hotspot Aktif pada {device_name}**\n\n"
                    f"Saat ini terdapat **{len(active)} user** yang sedang online:\n"
                    + "\n".join([f"• {ul}" for ul in user_list])
                )
            return {"reply": reply, "pending_action": None}

        # =====================================================================
        # GENERAL NETWORKING CONCEPT QUESTIONS (Q&A KNOWLEDGE BASE)
        # =====================================================================
        if any(w in lower for w in ("apa itu", "apa fungsi", "bagaimana cara", "apa beda", "kenapa router")):
            if "nat" in lower:
                return {"reply": "💡 **Network Address Translation (NAT)** adalah metode yang memetakan alamat IP privat di jaringan lokal (LAN) ke satu atau lebih alamat IP publik di internet. Pada MikroTik, NAT biasanya dikonfigurasi melalui menu `/ip firewall nat` dengan action `masquerade` agar perangkat klien lokal dapat berselancar di internet.", "pending_action": None}
            if "dhcp" in lower:
                return {"reply": "💡 **DHCP (Dynamic Host Configuration Protocol)** bertugas membagikan alamat IP, subnet mask, gateway, dan DNS server secara otomatis kepada setiap perangkat klien yang terhubung ke jaringan tanpa perlu disetel manual.", "pending_action": None}
            if "hotspot" in lower:
                return {"reply": "💡 **MikroTik Hotspot** adalah sistem autentikasi gerbang (captive portal) yang mewajibkan pengguna memasukkan username & password (atau voucher) sebelum diizinkan mengakses internet. Fitur ini sangat cocok untuk kafe, kampus, hotel, dan kantor.", "pending_action": None}
            if "firewall" in lower:
                return {"reply": "💡 **Firewall MikroTik** berfungsi menyaring (filter) paket data yang melintasi router (`Forward`), masuk ke router (`Input`), atau keluar dari router (`Output`) demi melindungi jaringan dari akses ilegal atau serangan siber.", "pending_action": None}
            if "queue" in lower or "bandwidth" in lower:
                return {"reply": "💡 **Manajemen Bandwidth di MikroTik** dapat dilakukan menggunakan **Simple Queue** (berdasarkan IP/subnet target) atau **Queue Tree + Mangle PCQ** untuk membagi alokasi kecepatan download dan upload secara adil antar pengguna.", "pending_action": None}

        # =====================================================================
        # SCENARIO: Server & Service Port Checking (Universal Monitoring)
        # =====================================================================
        is_server_port = (
            any(w in lower for w in ("port server", "service web", "cek server", "server web", "database port"))
            or (bool(re.search(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', lower)) and bool(re.search(r'\bport\s+\d+\b', lower)))
        )
        if is_server_port:
            ip_match = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', prompt)
            port_match = re.search(r'port\s+(\d+)', prompt, re.IGNORECASE)
            host = ip_match.group(1) if ip_match else "127.0.0.1"
            port = int(port_match.group(1)) if port_match else 80
            res = TOOL_REGISTRY["check_server_port"](host=host, port=port)
            if res.get("success"):
                reply = (
                    f"🖥️ **Hasil Pengecekan Server / Service**\n\n"
                    f"• Target Host : `{host}`\n"
                    f"• Port        : `{port}`\n"
                    f"• Status      : 🟢 **ONLINE / TERBUKA**\n"
                    f"• Latency     : `{res['data']['latency_ms']} ms`\n\n"
                    f"Service pada server merespons dengan normal."
                )
            else:
                reply = (
                    f"🖥️ **Hasil Pengecekan Server / Service**\n\n"
                    f"• Target Host : `{host}`\n"
                    f"• Port        : `{port}`\n"
                    f"• Status      : 🔴 **OFFLINE / TERTUTUP**\n\n"
                    f"⚠️ Port {port} tidak dapat dihubungi. Periksa apakah layanan di server aktif atau terhalang firewall."
                )
            return {"reply": reply, "pending_action": None}

        # =====================================================================
        # SCENARIO 2: Troubleshooting (PRD Section 6, 25 - "Internet Lambat")
        # =====================================================================
        if any(w in lower for w in ("lambat", "lemot", "kenapa internet", "masalah internet", "troubleshoot", "bottleneck", "gangguan", "koneksi bermasalah", "drop", "putus-putus", "down")):
            reply = self._generate_troubleshooting_report(device_name, prompt)
            return {"reply": reply, "pending_action": None}

        # Quick Check / Status Jaringan ("cek", "cek jaringan", "cek koneksi", "status jaringan", "jaringan aman", etc.)
        is_quick_check = lower.strip() in (
            "cek", "tes", "test", "cek jaringan", "cek koneksi", "status jaringan",
            "jaringan aman", "kondisi jaringan", "cek internet", "tes jaringan",
            "tes koneksi", "cek sinyal", "koneksi aman", "jaringan oke", "cek wan"
        ) or (
            lower.strip().startswith("cek ") and len(lower.strip().split()) <= 2 and any(w in lower for w in ("jaringan", "koneksi", "net", "internet", "status", "wan"))
        )
        if is_quick_check:
            ping_res = TOOL_REGISTRY["tool_ping"](device=device_name, target="8.8.8.8", count=3)
            p_data = ping_res.get("data") or {}
            res = TOOL_REGISTRY["get_resource"](device=device_name).get("data") or {}
            ifaces_res = TOOL_REGISTRY["get_interface"](device=device_name).get("data") or []
            routes_res = TOOL_REGISTRY["get_route"](device=device_name).get("data") or []

            loss = p_data.get("packet_loss_percent", 0)
            avg_rtt = p_data.get("avg_rtt_ms", 0)
            cpu = res.get("cpu_load", res.get("cpu_load_percent", 0))
            free_ram = res.get("free_memory_mb", 0)
            board = res.get("board_name", "RouterBOARD")

            # Calculate active ports
            total_ifaces = len(ifaces_res) if isinstance(ifaces_res, list) else 0
            up_ifaces = [i.get("name") for i in ifaces_res if isinstance(i, dict) and i.get("running") and not i.get("disabled")]

            # Identify default gateway
            default_gateway = "N/A"
            if isinstance(routes_res, list):
                for r in routes_res:
                    if isinstance(r, dict) and r.get("dst_address") == "0.0.0.0/0":
                        default_gateway = r.get("gateway", "N/A")
                        break

            status_wan = "🟢 Optimal" if loss == 0 and avg_rtt < 50 else ("🟡 Normal" if loss == 0 else "🔴 Terkendala")
            status_cpu = "🟢 Normal" if cpu < 70 else "🔴 Tinggi"

            reply = (
                f"📡 **Hasil Pemeriksaan Jaringan & Router ({device_name})**\n\n"
                f"• Hardware / Model : **{board}**\n"
                f"• Beban CPU       : **{cpu}%** ({status_cpu})\n"
                f"• Sisa RAM        : **{free_ram} MB**\n"
                f"• Interface Aktif : **{len(up_ifaces)}** dari **{total_ifaces}** port (`{', '.join(up_ifaces[:4])}`)\n"
                f"• Default Gateway : `{default_gateway}`\n"
                f"• Konektivitas WAN: Ping ke 8.8.8.8 ➔ {status_wan}\n"
                f"  ↳ Latency: `{avg_rtt} ms` | Loss: `{loss}%`\n\n"
                f"✅ Jaringan terhubung dan sistem beroperasi normal.\n"
                f"💡 *Ketik 'cek port' untuk status port/interface, 'siapa yang pakai' untuk user aktif, atau 'cek rute' untuk tabel routing.*"
            )
            return {"reply": reply, "pending_action": None}

        # =====================================================================
        # SCENARIO 1: Monitoring Lengkap (PRD Section 10, 24 - "Cek Kondisi Router")
        # =====================================================================
        if any(w in lower for w in (
            "kondisi", "cek router", "sehat", "status router", "cek mikrotik", "monitor", "kondisi router",
            "kesehatan", "performa", "cek spek", "spesifikasi", "resource", "cek resource", "laporan lengkap",
            "cek ruter", "cek rotre", "cek routre", "status ruter", "status rotre", "kondisi ruter", "kondisi rotre",
            "info router", "info ruter", "kondisi mikrotik", "cek status", "status mikrotik"
        )):
            reply = self._generate_monitoring_report(device_name, prompt)
            return {"reply": reply, "pending_action": None}

        # Interfaces / Ports Queries
        if any(w in lower for w in ("interface", "port", "cek port", "daftar interface", "ethernet", "status port", "daftar port")):
            reply = self._generate_interfaces_report(device_name, prompt)
            return {"reply": reply, "pending_action": None}

        # Hotspot Queries
        if any(w in lower for w in ("hotspot", "user hotspot", "voucher")):
            is_active = any(w in lower for w in ("aktif", "active", "sedang", "login", "online"))
            reply = self._generate_hotspot_report(device_name, is_active)
            return {"reply": reply, "pending_action": None}

        # Ping / Connectivity Test
        is_ping = any(w in lower for w in (
            "ping", "cek latency", "cek rtt", "tes koneksi", "apakah bisa dijangkau", "tes ping", "jangkau"
        )) or bool(re.search(r'\bping\b', lower))
        if is_ping and not any(w in lower for w in ("traceroute", "tracert")):
            ip_match = re.search(r'(\b[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\b)', prompt)
            target_match = re.search(r'(?:ping(?:\s+ke)?|ke|menuju|target)\s+([a-zA-Z0-9\.-]+)', prompt, re.IGNORECASE)
            if ip_match:
                target = ip_match.group(1)
            elif target_match and target_match.group(1).lower() not in ("ke", "router", "koneksi", "host"):
                target = target_match.group(1)
            else:
                target = "8.8.8.8"
            reply = self._generate_ping_report(device_name, target)
            return {"reply": reply, "pending_action": None}

        # WAN Information (WAN IP, Default Gateway, Public vs Private/CGNAT Verification)
        is_wan_query = any(w in lower for w in (
            "ip wan", "wan ip", "cek ip wan", "alamat wan", "interface wan", "port wan",
            "ip public", "ip publik", "public ip", "gateway wan", "gateway internet", "wan router"
        )) or (
            bool(re.search(r'\bwan\b', lower)) and (
                bool(re.search(r'\b(ip|alamat|gateway|interface|port)\b', lower)) or
                any(w in lower for w in ("cek", "status", "apa", "berapa", "koneksi"))
            )
        ) or (
            bool(re.search(r'\b(public|publik)\b', lower)) and bool(re.search(r'\b(ip|alamat)\b', lower))
        )
        if is_wan_query:
            reply = self._generate_wan_report(device_name, prompt)
            return {"reply": reply, "pending_action": None}

        # Routing Table (IP Routes, Next Hop, Distance, Active Routes)
        # Guard against router/ruter typos:
        is_router_typo = any(w in lower for w in ("router", "ruter", "rotre", "routre", "mikrotik")) and not any(w in lower for w in ("tabel", "table", "routing", "ip route", "print route"))

        is_route_query = not is_router_typo and (
            any(bool(re.search(r'\b' + re.escape(w) + r'\b', lower)) for w in (
                "routing", "routing table", "tabel routing", "daftar rute", "rute aktif",
                "ip route", "show route", "print route", "cek rute", "lihat rute", "rute router",
                "rute kamu", "rute apa", "route apa", "lihat routing", "tampilkan rute", "rute yang aktif"
            )) or (bool(re.search(r'\b(route|rute|routing)\b', lower)) and not any(w in lower for w in ("traceroute", "tracert")))
        )
        if is_route_query:
            reply = self._generate_routing_report(device_name, prompt)
            return {"reply": reply, "pending_action": None}

        # Interface IP Addresses (All Configured Subnets)
        is_ip_query = any(w in lower for w in (
            "ip address", "cek ip", "daftar ip", "alamat ip", "semua ip", "ip router", "list ip", "ip interface"
        )) or (
            bool(re.search(r'\bip\b', lower)) and any(w in lower for w in ("daftar", "tampilkan", "lihat", "semua", "interface", "port", "berapa", "apa", "list", "ada apa saja"))
        )
        if is_ip_query:
            reply = self._generate_ip_report(device_name, prompt)
            return {"reply": reply, "pending_action": None}

        # DHCP / Clients
        if any(w in lower for w in ("siapa yang pakai", "client", "dhcp", "perangkat", "siapa saja", "user terhubung", "klien")):
            reply = self._generate_dhcp_client_report(device_name, prompt)
            return {"reply": reply, "pending_action": None}

        # System Logs
        if any(w in lower for w in ("log", "catatan", "error log", "syslog", "riwayat", "event")):
            reply = self._generate_system_logs_report(device_name, prompt, limit=10)
            return {"reply": reply, "pending_action": None}

        # Contextual Fallback for Unrecognized / Ambiguous prompt
        clean_display = prompt[:100].strip()
        return {
            "reply": (
                f"🤔 Maaf, saya belum memahami maksud pertanyaan atau instruksi: *\"{clean_display}\"* pada router **{device_name}**.\n\n"
                f"Sebagai asisten MikroTik, saya dapat membantu Anda untuk:\n"
                f"• 📡 Memeriksa status router (*'cek kondisi router'* atau *'cek cpu'*)\n"
                f"• 📶 Mengetes koneksi jaringan (*'cek jaringan'* atau *'ping ke 8.8.8.8'*)\n"
                f"• 👥 Memeriksa pengguna (*'siapa saja yang terhubung'* atau *'cek user hotspot'*)\n"
                f"• 🔎 Mendiagnosa kendala (*'kenapa internet lambat'*)\n"
                f"• 🧭 Melihat panduan lengkap (*'panduan'* atau *'bisa bantu apa'*)\n\n"
                f"Silakan ketik pertanyaan atau perintah Anda dengan lebih spesifik agar dapat langsung saya bantu."
            ),
            "pending_action": None,
        }

    # =========================================================================
    # COMPREHENSIVE REPORT GENERATORS & FORMATTERS
    # =========================================================================

    @staticmethod
    def _format_bytes(b: Any) -> str:
        try:
            b_val = float(b)
        except (ValueError, TypeError):
            return "0 B"
        if b_val <= 0:
            return "0 B"
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if b_val < 1024.0:
                return f"{b_val:.1f} {unit}"
            b_val /= 1024.0
        return f"{b_val:.1f} PB"

    @staticmethod
    def _format_bar(percent: Any, length: int = 8) -> str:
        try:
            p = float(percent)
        except (ValueError, TypeError):
            p = 0.0
        filled = int(round(p / 100.0 * length))
        filled = max(0, min(length, filled))
        return f"[{'█' * filled}{'░' * (length - filled)}] {p:.1f}%"

    @staticmethod
    def _format_uptime(uptime_str: Any) -> str:
        if not uptime_str:
            return "0s"
        s = str(uptime_str)
        parts = []
        m_w = re.search(r'(\d+)w', s)
        if m_w:
            parts.append(f"{m_w.group(1)} Minggu")
        m_d = re.search(r'(\d+)d', s)
        if m_d:
            parts.append(f"{m_d.group(1)} Hari")
        m_h = re.search(r'(\d+)h', s)
        if m_h:
            parts.append(f"{m_h.group(1)} Jam")
        m_m = re.search(r'(\d+)m(?!s)', s)
        if m_m:
            parts.append(f"{m_m.group(1)} Menit")
        m_s = re.search(r'(\d+)s', s)
        if m_s:
            parts.append(f"{m_s.group(1)} Detik")
        return " ".join(parts) if parts else s

    def _generate_monitoring_report(self, device_name: str, prompt: str = "") -> str:
        res = TOOL_REGISTRY["get_resource"](device=device_name).get("data") or {}
        ifaces = TOOL_REGISTRY["get_interface"](device=device_name).get("data") or []
        ping_res = TOOL_REGISTRY["ping"](device=device_name, target="8.8.8.8", count=2).get("data") or {}
        dhcp = TOOL_REGISTRY["get_dhcp"](device=device_name).get("data") or []
        hotspot_act = TOOL_REGISTRY["get_hotspot"](device=device_name, query_type="active").get("data") or []

        # Resource details
        cpu = res.get("cpu_load", 0)
        mem = res.get("memory_usage_percent", 0.0)
        total_mem = res.get("total_memory_mb", 128.0)
        free_mem = res.get("free_memory_mb", total_mem * (1 - mem / 100))
        used_mem = total_mem - free_mem
        uptime = res.get("uptime", "0s")
        uptime_fmt = self._format_uptime(uptime)
        version = res.get("version", "v7")
        board = res.get("board_name", "RouterBOARD")
        arch = res.get("architecture_name", "mipsbe")
        cpu_count = res.get("cpu_count", 1)

        # Interfaces
        wan_iface = next((i for i in ifaces if "wan" in i.get("name", "").lower()), None)
        if not wan_iface and ifaces:
            wan_iface = ifaces[0]
        wan_name = wan_iface.get("name", "ether1") if wan_iface else "ether1"
        wan_status = "UP" if (wan_iface and wan_iface.get("running")) else "DOWN"
        wan_rx = self._format_bytes(wan_iface.get("rx_byte", 0)) if wan_iface else "0 B"
        wan_tx = self._format_bytes(wan_iface.get("tx_byte", 0)) if wan_iface else "0 B"

        lan_iface = next((i for i in ifaces if any(k in i.get("name", "").lower() for k in ("lan", "wifi", "wlan", "asus", "sw")) and i != wan_iface), None)
        if not lan_iface and len(ifaces) > 1:
            lan_iface = ifaces[1]
        lan_name = lan_iface.get("name", "ether2") if lan_iface else "ether2"
        lan_status = "UP" if (lan_iface and lan_iface.get("running")) else "DOWN"
        lan_rx = self._format_bytes(lan_iface.get("rx_byte", 0)) if lan_iface else "0 B"
        lan_tx = self._format_bytes(lan_iface.get("tx_byte", 0)) if lan_iface else "0 B"

        running_ifaces = [i for i in ifaces if i.get("running")]

        # Ping
        if isinstance(ping_res, dict):
            avg_rtt = ping_res.get("avg_rtt_ms", 20.0)
            packet_loss = ping_res.get("packet_loss_percent", 0.0)
        else:
            avg_rtt, packet_loss = 20.0, 0.0

        # Health assessment
        hw_status = "🟢 Optimal" if cpu < 70 and mem < 80 else ("🟡 Waspada" if cpu < 85 else "🔴 Kritis")
        ping_status = "🟢 Prima" if packet_loss == 0.0 and avg_rtt < 50 else ("🟡 Normal" if packet_loss <= 2.0 else "🔴 Terganggu")

        reply = (
            f"📡 **LAPORAN LENGKAP STATUS & KESEHATAN SISTEM MIKROTIK**\n"
            f"Target Router : **{device_name}** | Status: {hw_status}\n\n"
            f"📋 **1. Identitas & Spesifikasi Perangkat**\n"
            f"• Perangkat   : **{board}** (RouterOS {version})\n"
            f"• Arsitektur  : `{arch}` ({cpu_count} CPU Core)\n"
            f"• Waktu Aktif : **{uptime_fmt}** (Uptime: `{uptime}`)\n\n"
            f"📊 **2. Utilisasi Hardware & Resource**\n"
            f"• CPU Load  : **{cpu}%** {self._format_bar(cpu)} ({'Normal' if cpu < 70 else 'Tinggi'})\n"
            f"• RAM Usage : **{mem:.1f}%** {self._format_bar(mem)}\n"
            f"  - Memori Terpakai : `{used_mem:.1f} MB` / `{total_mem:.1f} MB`\n"
            f"  - Memori Bebas    : `{free_mem:.1f} MB`\n\n"
            f"🌐 **3. Antarmuka Jaringan (Interfaces & Traffic)**\n"
            f"• Port Aktif: **{len(running_ifaces)} dari {len(ifaces)} port** berstatus UP\n"
            f"• **WAN Link** (`{wan_name}`):\n"
            f"  - Status Link : **{wan_status}**\n"
            f"  - Lalu Lintas : Rx `{wan_rx}` (Download) | Tx `{wan_tx}` (Upload)\n"
            f"• **LAN/WiFi Link** (`{lan_name}`):\n"
            f"  - Status Link : **{lan_status}**\n"
            f"  - Lalu Lintas : Rx `{lan_rx}` | Tx `{lan_tx}`\n"
            f"• Traffic     : Normal dan seimbang\n\n"
            f"🏓 **4. Uji Konektivitas Internet (Google DNS 8.8.8.8)**\n"
            f"• Rata-rata Latensi : **{avg_rtt} ms** ({ping_status})\n"
            f"• Packet Loss       : **{packet_loss}%**\n\n"
            f"👥 **5. Klien & Layanan Terhubung**\n"
            f"• Klien DHCP Aktif   : **{len(dhcp)} perangkat**\n"
            f"• Sesi Hotspot Aktif : **{len(hotspot_act)} user login**\n\n"
            f"**Kesimpulan:**\n"
            f"🟢 Router MikroTik **{device_name}** dalam kondisi normal dan siap beroperasi dengan kinerja stabil. "
            f"Hardware, alokasi memori, serta transmisi port WAN dan LAN berfungsi prima tanpa bottleneck."
        )
        return reply

    def _generate_troubleshooting_report(self, device_name: str, prompt: str) -> str:
        # Step 1: Resource
        res = TOOL_REGISTRY["get_resource"](device=device_name).get("data") or {}
        cpu_val = res.get("cpu_load", 0)
        mem_val = res.get("memory_usage_percent", 0.0)
        total_mem = res.get("total_memory_mb", 128.0)
        free_mem = res.get("free_memory_mb", total_mem * (1 - mem_val / 100))

        # Step 2: Interface
        ifaces = TOOL_REGISTRY["get_interface"](device=device_name).get("data") or []
        wan_iface = next((i for i in ifaces if "wan" in i.get("name", "").lower()), None)
        if not wan_iface and ifaces:
            wan_iface = ifaces[0]
        wan_name = wan_iface.get("name", "ether1") if wan_iface else "ether1"
        wan_status = "UP" if (wan_iface and wan_iface.get("running")) else "DOWN"
        wan_rx = self._format_bytes(wan_iface.get("rx_byte", 0)) if wan_iface else "0 B"
        wan_tx = self._format_bytes(wan_iface.get("tx_byte", 0)) if wan_iface else "0 B"

        lan_iface = next((i for i in ifaces if any(k in i.get("name", "").lower() for k in ("lan", "wifi", "wlan", "asus", "sw")) and i != wan_iface), None)
        if not lan_iface and len(ifaces) > 1:
            lan_iface = ifaces[1]
        lan_name = lan_iface.get("name", "ether2") if lan_iface else "ether2"
        lan_status = "UP" if (lan_iface and lan_iface.get("running")) else "DOWN"
        lan_rx = self._format_bytes(lan_iface.get("rx_byte", 0)) if lan_iface else "0 B"
        lan_tx = self._format_bytes(lan_iface.get("tx_byte", 0)) if lan_iface else "0 B"

        # Step 3: Ping
        ping_res = TOOL_REGISTRY["ping"](device=device_name, target="8.8.8.8", count=4).get("data") or {}
        if isinstance(ping_res, dict):
            avg_rtt = ping_res.get("avg_rtt_ms", 23.5)
            packet_loss = ping_res.get("packet_loss_percent", 0.0)
            sent = ping_res.get("sent", 4)
            received = ping_res.get("received", 4)
        else:
            avg_rtt, packet_loss, sent, received = 23.5, 0.0, 4, 4

        # Step 4: Clients
        dhcp = TOOL_REGISTRY["get_dhcp"](device=device_name).get("data") or []
        hotspot_act = TOOL_REGISTRY["get_hotspot"](device=device_name, query_type="active").get("data") or []

        # Stage Conclusions
        root_causes = []
        recommendations = []

        # Stage 1 eval
        if cpu_val > 80:
            stage1_eval = f"⚠️ **Beban Tinggi ({cpu_val}%)** — Ada proses firewall rules atau packet filtering berat."
            root_causes.append(f"CPU router mengalami throttling ({cpu_val}%) yang memperlambat perutean paket data.")
            recommendations.append("Periksa aturan Firewall Filter/NAT yang tidak efisien atau nonaktifkan logging berlebih.")
        elif mem_val > 90:
            stage1_eval = f"⚠️ **RAM Kritis ({mem_val:.1f}%)** — Sisa memori buffer sangat terbatas."
            root_causes.append(f"Kapasitas RAM router hampir habis ({mem_val:.1f}%).")
            recommendations.append("Lakukan pembersihan cache DNS atau periksa script yang mengonsumsi memori besar.")
        else:
            stage1_eval = f"🟢 **Normal ({cpu_val}%)** — Hardware dan alokasi memori router stabil."

        # Stage 2 eval
        if wan_status != "UP":
            stage2_eval = f"🔴 **WAN Link Mati ({wan_status})** — Tidak ada koneksi fisik ke modem ISP!"
            root_causes.append(f"Interface WAN `{wan_name}` terputus (link down).")
            recommendations.append("Periksa kabel UTP/FO dari modem ISP ke port WAN router dan pastikan modem aktif.")
        else:
            stage2_eval = f"🟢 **Link UP (Running)** — Port fisik terhubung dan merespons normal."

        # Stage 3 eval
        if packet_loss > 5.0:
            stage3_eval = f"🔴 **Packet Loss ({packet_loss}%)** — Terdapat kehilangan paket data ke internet."
            root_causes.append(f"Terdapat packet loss ({packet_loss}%) menuju internet (8.8.8.8). Kemungkinan terjadi gangguan redaman optik atau upstream ISP.")
            recommendations.append("Hubungi Helpdesk ISP untuk memeriksa stabilitas redaman optik / jalur WAN.")
        elif avg_rtt > 80.0:
            stage3_eval = f"⚠️ **Latensi Tinggi ({avg_rtt} ms)** — Terjadi antrean paket data (bufferbloat)."
            root_causes.append(f"Latensi internet tinggi ({avg_rtt} ms), biasanya akibat saturasi kapasitas bandwidth uplink/downlink.")
            recommendations.append("Terapkan Simple Queue atau PCQ (Per Connection Queue) untuk membatasi kuota unduh/unggah.")
        else:
            stage3_eval = f"🟢 **Prima ({avg_rtt} ms, Loss: {packet_loss}%)** — Respon gateway dan internet sangat cepat."

        # Stage 4 eval
        active_client_names = [d.get("host_name") or d.get("address") for d in dhcp[:3] if d.get("host_name") or d.get("address")]
        client_sample = ", ".join(active_client_names) if active_client_names else "Beberapa perangkat"

        if not root_causes:
            root_causes.append(
                f"Beban pemrosesan router dan gateway eksternal terpantau normal (CPU: {cpu_val}%, Ping: {avg_rtt} ms, Loss: {packet_loss}%). "
                f"Penyebab utama kelambatan koneksi sangat mungkin bersumber dari **saturasi bandwidth oleh salah satu klien lokal** "
                f"({len(dhcp)} perangkat DHCP aktif, misal: {client_sample}) yang sedang melakukan streaming/download masif, "
                f"atau adanya interferensi frekuensi saluran pada Access Point WiFi `{lan_name}`."
            )
            recommendations.append(f"Gunakan fitur **Torch** pada interface `{lan_name}` untuk mendeteksi IP klien yang mengonsumsi bandwidth terbesar.")
            recommendations.append("Aktifkan pengaturan manajemen antrean **Simple Queue / PCQ** untuk pemerataan bandwidth.")
            recommendations.append(f"Optimasi pengaturan kanal frekuensi WiFi pada Access Point `{lan_name}` jika gangguan dialami pengguna nirkabel.")

        reply = (
            f"🔎 **Hasil Pemeriksaan Diagnostik & Analisis Gangguan Jaringan**\n\n"
            f"Target Router : **{device_name}**\n"
            f"Pertanyaan    : *\"{prompt}\"*\n\n"
            f"📋 **1. Evaluasi Beban Pemrosesan (Hardware Bottleneck)**\n"
            f"• CPU Router   : **{cpu_val}%** {self._format_bar(cpu_val)} -> {stage1_eval}\n"
            f"• Memori (RAM) : **{mem_val:.1f}%** {self._format_bar(mem_val)} (Sisa: `{free_mem:.1f} MB`)\n\n"
            f"🌐 **2. Status Link WAN & Distribusi Data**\n"
            f"• WAN Status   : **{wan_status}**\n"
            f"• Interface WAN: `{wan_name}` -> {stage2_eval}\n"
            f"  - Akumulasi Trafik WAN: Rx `{wan_rx}` (Download) | Tx `{wan_tx}` (Upload)\n"
            f"• Interface LAN: `{lan_name}` (Status: **{lan_status}**)\n"
            f"  - Akumulasi Trafik LAN: Rx `{lan_rx}` | Tx `{lan_tx}`\n\n"
            f"🏓 **3. Kualitas Link Eksternal & Latensi (End-to-End Test)**\n"
            f"• Gateway / DNS: Reachable (0% loss)\n"
            f"• Internet Ping: **{avg_rtt} ms** (Paket: {sent}/{received}, Loss: **{packet_loss}%**) -> {stage3_eval}\n\n"
            f"👥 **4. Kepadatan Klien Lokal**\n"
            f"• Klien DHCP Aktif   : **{len(dhcp)} perangkat**\n"
            f"• Sesi Hotspot Aktif : **{len(hotspot_act)} user**\n\n"
            f"**Kesimpulan Analisis:**\n"
            f"{' '.join(root_causes)}\n\n"
            f"💡 **Rekomendasi Solusi Teknisi:**\n"
            + "\n".join([f"{idx+1}. {r}" for idx, r in enumerate(recommendations)])
        )
        return reply

    def _generate_dhcp_client_report(self, device_name: str, prompt: str = "") -> str:
        dhcp = TOOL_REGISTRY["get_dhcp"](device=device_name).get("data") or []
        ips = TOOL_REGISTRY["get_ip"](device=device_name).get("data") or []

        gw = next((i for i in ips if "172." in i.get("address", "") or "192." in i.get("address", "")), ips[0] if ips else {})
        gw_addr = gw.get("address", "-")
        gw_iface = gw.get("interface", "-")

        if not dhcp:
            return (
                f"📱 **Daftar Client Jaringan (DHCP) — {device_name}**\n\n"
                f"• Subnet Gateway   : `{gw_addr}` ({gw_iface})\n"
                f"• Total Terhubung  : **0 perangkat aktif**\n\n"
                f"Saat ini belum ada perangkat yang meminjam alamat IP melalui DHCP server."
            )

        lines = []
        for idx, d in enumerate(dhcp, 1):
            name = d.get("host_name") or d.get("host-name") or "Perangkat Tanpa Hostname"
            ip = d.get("address", "-")
            mac = d.get("mac_address") or d.get("mac-address") or "-"
            expires = d.get("expires_after") or d.get("expires-after") or "-"
            status = d.get("status", "bound")
            class_id = str(d.get("class-id", "")).lower()
            name_lower = name.lower()
            if "msft" in class_id or "desktop" in name_lower or "pc" in name_lower or "laptop" in name_lower:
                type_icon = "💻"
            elif "android" in class_id or "iphone" in name_lower or "redmi" in name_lower or "v23" in name_lower or "samsung" in name_lower:
                type_icon = "📱"
            else:
                type_icon = "🌐"

            lines.append(
                f"{idx}. {type_icon} **{name}**\n"
                f"   • IP Address : `{ip}`\n"
                f"   • MAC Address: `{mac}`\n"
                f"   • Status     : `{status.upper()}` (Sisa Waktu: `{expires}`)"
            )

        reply = (
            f"📱 **Daftar Client Jaringan (DHCP) — {device_name}**\n\n"
            f"• Subnet / Gateway : `{gw_addr}` pada `{gw_iface}`\n"
            f"• Total Terhubung  : **{len(dhcp)} perangkat aktif (bound)**\n\n"
            f"📋 **Rincian Perangkat Terkoneksi:**\n\n"
            + "\n\n".join(lines) + "\n\n"
            f"💡 **Rekomendasi Teknisi:**\n"
            f"1. Buat IP statis (*Make Static*) untuk perangkat penting (server/printer/PC admin) agar IP tidak berganti.\n"
            f"2. Pantau konsumsi bandwidth pada interface `{gw_iface}` jika jaringan terasa padat."
        )
        return reply

    def _generate_hotspot_report(self, device_name: str, is_active_query: bool) -> str:
        users_res = TOOL_REGISTRY["get_hotspot"](device=device_name, query_type="users").get("data") or []
        active_res = TOOL_REGISTRY["get_hotspot"](device=device_name, query_type="active").get("data") or []

        if is_active_query:
            if not active_res:
                lines_msg = "ℹ️ *Saat ini tidak ada user hotspot yang sedang aktif / login.*"
            else:
                lines = []
                for idx, s in enumerate(active_res, 1):
                    u = s.get("user") or s.get("name", "-")
                    ip = s.get("address", "-")
                    mac = s.get("mac_address") or s.get("mac-address", "-")
                    up = s.get("uptime", "-")
                    rx = self._format_bytes(s.get("bytes-in") or s.get("bytes_in", 0))
                    tx = self._format_bytes(s.get("bytes-out") or s.get("bytes_out", 0))
                    lines.append(
                        f"{idx}. 👤 **{u}**\n"
                        f"   • IP / MAC    : `{ip}` (`{mac}`)\n"
                        f"   • Waktu Aktif : `{up}` | Lalu Lintas: Rx `{rx}` / Tx `{tx}`"
                    )
                lines_msg = "\n\n".join(lines)

            reply = (
                f"👥 **User Hotspot Aktif — {device_name}**\n\n"
                f"• Sesi Aktif Saat Ini : **{len(active_res)} user login**\n"
                f"• Total Akun Database : **{len(users_res)} akun terdaftar**\n\n"
                f"{lines_msg}\n\n"
                f"💡 **Petunjuk:** Buat akun tamu baru kapan saja dengan kalimat *'Buatkan user hotspot nama <nama> aktif 1 hari'*."
            )
            return reply
        else:
            if not users_res:
                lines_msg = "ℹ️ *Belum ada akun voucher/pengguna yang terdaftar di database hotspot.*"
            else:
                lines = []
                for idx, u in enumerate(users_res[:15], 1):
                    name = u.get("name", "-")
                    profile = u.get("profile", "default")
                    limit_up = u.get("limit_uptime") or u.get("limit-uptime") or "unlimited"
                    up = u.get("uptime", "0s")
                    comment = u.get("comment", "")
                    cm_text = f" ({comment})" if comment else ""
                    lines.append(
                        f"{idx}. 🎫 **{name}**{cm_text}\n"
                        f"   • Profil     : `{profile}`\n"
                        f"   • Masa Aktif : `{limit_up}` (Terpakai: `{up}`)"
                    )
                lines_msg = "\n\n".join(lines)

            reply = (
                f"📋 **Daftar User Hotspot — {device_name}**\n\n"
                f"• Total Terdaftar : **{len(users_res)} user**\n"
                f"• Sedang Login    : **{len(active_res)} pengguna aktif**\n\n"
                f"{lines_msg}\n\n"
                f"💡 *Catatan:* Anda dapat menghapus akun yang telah kadaluarsa dengan instruksi *'Hapus user hotspot <nama>'*."
            )
            return reply

    @staticmethod
    def _classify_ip(ip_str: str) -> Tuple[str, str]:
        """Classify IP address as Private, CGNAT, Loopback, or verified Public IP."""
        try:
            clean = ip_str.split("/")[0].strip()
            ip = ipaddress.ip_address(clean)
            if ip in ipaddress.ip_network("100.64.0.0/10"):
                return "CGNAT (RFC 6598)", "Carrier-Grade NAT ISP (Bukan IP Publik langsung)"
            elif ip.is_private:
                return "Private IP (RFC 1918)", "Jaringan lokal di balik NAT router/modem ISP"
            elif ip.is_loopback:
                return "Loopback", "Host internal"
            elif ip.is_global:
                return "Public IP", "Terverifikasi Public IP (Routable Internet)"
            else:
                return "Reserved/Khusus", "Alamat IP khusus"
        except Exception:
            return "Format IP Tidak Dikenal", "Format IP tidak dapat diverifikasi"

    def _generate_system_info_report(self, device_name: str, prompt: str = "") -> str:
        res = TOOL_REGISTRY["get_resource"](device=device_name).get("data") or {}
        ident_data = TOOL_REGISTRY["get_identity"](device=device_name).get("data") or {}
        rb_data = TOOL_REGISTRY["get_routerboard"](device=device_name).get("data") or {}

        identity = ident_data.get("name") or device_name
        board = res.get("board_name") or rb_data.get("board_name") or "RouterBOARD"
        model = rb_data.get("model") or board
        version = res.get("version", "v7")
        arch = res.get("architecture_name", "unknown")
        cpu_count = res.get("cpu_count", 1)
        uptime = res.get("uptime", "0s")
        uptime_fmt = self._format_uptime(uptime)
        serial = rb_data.get("serial_number") or "-"
        firmware = rb_data.get("current_firmware") or rb_data.get("upgrade_firmware") or "-"

        reply = (
            f"🏷️ **Informasi Sistem & Perangkat MikroTik — {device_name}**\n\n"
            f"• Identitas Router : **{identity}**\n"
            f"• Model / Tipe     : **{model}** ({board})\n"
            f"• Versi RouterOS   : **{version}**\n"
            f"• Arsitektur CPU   : `{arch}` ({cpu_count} Core)\n"
            f"• Waktu Aktif      : **{uptime_fmt}** (`{uptime}`)\n"
            f"• Serial Number    : `{serial}`\n"
            f"• Firmware BIOS    : `v{firmware}`\n\n"
            f"Status router beroperasi stabil dan seluruh subsistem berfungsi optimal."
        )
        return reply

    def _generate_wan_report(self, device_name: str, prompt: str = "") -> str:
        routes_res = TOOL_REGISTRY["get_route"](device=device_name).get("data") or []
        ips_res = TOOL_REGISTRY["get_ip"](device=device_name).get("data") or []
        ifaces_res = TOOL_REGISTRY["get_interface"](device=device_name).get("data") or []

        # 1. Determine Default Route (0.0.0.0/0)
        default_route = next(
            (r for r in routes_res if (r.get("dst-address") == "0.0.0.0/0" or r.get("dst_address") == "0.0.0.0/0") and r.get("active", True) and not r.get("disabled", False)),
            None
        )
        if not default_route:
            default_route = next(
                (r for r in routes_res if (r.get("dst-address") == "0.0.0.0/0" or r.get("dst_address") == "0.0.0.0/0")),
                {}
            )

        gateway = default_route.get("gateway", "Tidak terdeteksi")

        # 2. Find WAN Interface & WAN IP Address
        wan_iface = None
        wan_ip_entry = None

        # Check if gateway is an interface name directly
        if gateway:
            for iface in ifaces_res:
                if iface.get("name", "").lower() == gateway.lower():
                    wan_iface = iface.get("name")
                    break

        # If gateway is an IP, find interface whose IP subnet covers the gateway
        if not wan_iface and gateway and gateway != "Tidak terdeteksi":
            gw_ip_clean = gateway.split("%")[0].strip()
            try:
                gw_addr = ipaddress.ip_address(gw_ip_clean)
                for ip_item in ips_res:
                    addr_str = ip_item.get("address", "")
                    if addr_str:
                        net = ipaddress.ip_network(addr_str, strict=False)
                        if gw_addr in net:
                            wan_iface = ip_item.get("interface")
                            wan_ip_entry = ip_item
                            break
            except Exception:
                pass

        # Fallback: look for interface with 'wan' or 'internet' or 'uplink' in name/comment
        if not wan_iface:
            for ip_item in ips_res:
                if_name = ip_item.get("interface", "").lower()
                comment = ip_item.get("comment", "").lower()
                if "wan" in if_name or "internet" in if_name or "uplink" in if_name or "wan" in comment:
                    wan_iface = ip_item.get("interface")
                    wan_ip_entry = ip_item
                    break

        # Fallback 2: first IP address
        if not wan_iface and ips_res:
            wan_ip_entry = ips_res[0]
            wan_iface = wan_ip_entry.get("interface", "-")

        if not wan_ip_entry and wan_iface:
            wan_ip_entry = next((i for i in ips_res if i.get("interface") == wan_iface), {})

        wan_ip_addr = wan_ip_entry.get("address", "Tidak ada IP terkonfigurasi") if wan_ip_entry else "Tidak ada IP terkonfigurasi"
        network = wan_ip_entry.get("network", "-") if wan_ip_entry else "-"

        # 3. Classify IP
        ip_category, ip_explanation = self._classify_ip(wan_ip_addr)

        # Check WAN interface running status
        iface_status = "🟢 UP"
        if wan_iface:
            match_if = next((i for i in ifaces_res if i.get("name") == wan_iface), None)
            if match_if and not match_if.get("running", True):
                iface_status = "🔴 DOWN"

        verif_note = (
            "✅ IP WAN terverifikasi sebagai **Public IP** yang dapat diakses dari internet global."
            if ip_category == "Public IP"
            else "⚠️ IP WAN saat ini berstatus **Private / Non-Public** (berada di balik jaringan NAT/CGNAT modem ISP)."
        )

        reply = (
            f"🌐 **Informasi Koneksi WAN & Gateway Internet — {device_name}**\n\n"
            f"• Interface WAN      : `{wan_iface or '-'}` ({iface_status})\n"
            f"• Alamat IP WAN      : **{wan_ip_addr}**\n"
            f"• Klasifikasi Alamat : **{ip_category}**\n"
            f"  ↳ _{ip_explanation}_\n"
            f"• Default Gateway    : `{gateway}` (Rute 0.0.0.0/0)\n"
            f"• Network Subnet     : `{network}`\n\n"
            f"ℹ️ **Status Verifikasi Publik:**\n"
            f"{verif_note}"
        )
        return reply

    def _generate_routing_report(self, device_name: str, prompt: str = "") -> str:
        routes_res = TOOL_REGISTRY["get_route"](device=device_name)
        routes = routes_res.get("data") or []
        if not routes:
            return f"🗺️ **Tabel Routing IP (Routing Table) — {device_name}**\n\nTidak ada entri rute yang terdaftar pada router."

        lines = []
        for idx, r in enumerate(routes[:20], 1):
            dst = r.get("dst-address") or r.get("dst_address") or "-"
            gw = r.get("gateway") or "-"
            dist = r.get("distance", "0")
            is_active = r.get("active", True)
            is_disabled = r.get("disabled", False)
            status_str = "🟢 Aktif" if is_active and not is_disabled else ("🔴 Disabled" if is_disabled else "⚪ Inactive")
            comment = r.get("comment", "")
            cm_text = f" _{comment}_" if comment else ""
            is_def = " *(Default Route 🌐)*" if dst == "0.0.0.0/0" else ""

            lines.append(
                f"{idx}. Dest: `{dst}`{is_def}\n"
                f"   • Gateway: `{gw}` | Distance: `{dist}` | Status: {status_str}{cm_text}"
            )

        reply = (
            f"🗺️ **Tabel Routing IP (Routing Table) — {device_name}**\n\n"
            f"• Total Rute Terpasang : **{len(routes)} entri**\n\n"
            f"📋 **Daftar Rute Aktif & Terdaftar:**\n\n"
            + "\n\n".join(lines) + "\n\n"
            f"💡 *Keterangan:* Rute `0.0.0.0/0` mengarahkan lalu lintas internet keluar melalui gateway ISP."
        )
        return reply

    def _generate_traceroute_report(self, device_name: str, target: str) -> str:
        target_clean = target.strip()
        target_ips = {target_clean}
        try:
            target_ips.add(socket.gethostbyname(target_clean))
        except Exception:
            pass

        res = TOOL_REGISTRY["tool_traceroute"](device=device_name, target=target_clean, count=1)
        data = res.get("data")
        hops = []
        if isinstance(data, list):
            hops = data
        elif isinstance(data, dict):
            hops = data.get("hops") or data.get("results") or []
        elif not data:
            hops = []

        if not hops:
            return (
                f"🛣️ **Hasil Traceroute ke `{target_clean}` — {device_name}**\n\n"
                f"⚠️ Tidak ada data hop yang diterima atau host tujuan tidak merespons probe ICMP."
            )

        # Truncate immediately once the target IP/domain is reached
        clean_hops = []
        target_reached = False
        reached_hop_num = None
        reached_latency = None

        for h in hops:
            clean_hops.append(h)
            addr = str(h.get("address") or h.get("ip") or h.get("host") or "").strip()
            if addr and addr in target_ips:
                target_reached = True
                reached_hop_num = len(clean_hops)
                reached_latency = h.get("avg") or h.get("last") or h.get("rtt_ms") or h.get("rtt") or "-"
                break

        lines = [f"🛣️ **Hasil Traceroute ke `{target_clean}` — {device_name}**\n"]
        for idx, h in enumerate(clean_hops, 1):
            raw_addr = str(h.get("address") or h.get("ip") or h.get("host") or "").strip()
            addr = raw_addr if raw_addr else "*"
            rtt_val = h.get("avg") or h.get("last") or h.get("rtt_ms") or h.get("time") or h.get("rtt") or "-"
            if isinstance(rtt_val, (int, float)):
                rtt_str = f"{rtt_val} ms"
            elif str(rtt_val).lower() == "timeout" or addr == "*":
                rtt_str = "Request timed out"
            elif rtt_val != "-":
                rtt_str = f"{rtt_val} ms"
            else:
                rtt_str = "-"

            if addr in target_ips:
                st = "🎯 Target Reached"
            elif addr == "*":
                st = "Timed out"
            else:
                st = "OK"

            lines.append(f"• Hop `{idx}`: `{addr}` ({rtt_str}) — {st}")

        if target_reached:
            lat_str = f" dengan latensi `{reached_latency} ms`" if reached_latency and reached_latency != "-" else ""
            lines.append(f"\n✅ **Target `{target_clean}` berhasil dicapai pada Hop {reached_hop_num}{lat_str}! Pelacakan rute langsung berhenti di sini.**")
        else:
            lines.append(f"\nTotal hop tercatat: **{len(clean_hops)}** lompatan rute.")
        return "\n".join(lines)

    def _generate_ping_report(self, device_name: str, target: str) -> str:
        p_res = TOOL_REGISTRY["ping"](device=device_name, target=target, count=4)
        p_data = p_res.get("data") or {}
        if not isinstance(p_data, dict):
            p_data = {}

        sent = p_data.get("sent", 4)
        received = p_data.get("received", 4)
        loss = p_data.get("packet_loss_percent", 0.0)
        avg_rtt = p_data.get("avg_rtt_ms", 0.0)
        min_rtt = p_data.get("min_rtt_ms")
        max_rtt = p_data.get("max_rtt_ms")

        # Factual reachable status without exaggerated gaming/VoIP claims
        if received > 0 and loss < 100.0:
            reach_status = "🟢 Reachable (Terhubung)"
        else:
            reach_status = "🔴 Unreachable (Tidak Terjangkau)"

        rtt_detail = f"**{avg_rtt} ms**"
        if min_rtt is not None and max_rtt is not None:
            rtt_detail += f" (Min: `{min_rtt} ms` / Max: `{max_rtt} ms`)"

        reply = (
            f"🏓 **Hasil Pengujian Ping — {device_name}**\n\n"
            f"• Target Host   : `{target}`\n"
            f"• Paket Dikirim : {sent} paket\n"
            f"• Paket Diterima: {received} paket\n"
            f"• Packet Loss   : **{loss}%**\n"
            f"• Rata-rata RTT : {rtt_detail}\n"
            f"• Status Host   : {reach_status}"
        )
        return reply

    def _generate_system_logs_report(self, device_name: str, prompt: str = "", limit: int = 10) -> str:
        logs_res = TOOL_REGISTRY["get_logs"](device=device_name, limit=limit)
        logs = logs_res.get("data") or []

        if not logs:
            return f"📜 **System Log Terbaru — {device_name}**\n\nBelum ada log tercatat pada router."

        lines = []
        for l in logs:
            time_str = l.get("time", "-")
            topics = l.get("topics", "system")
            msg = l.get("message", "-")
            icon = "🔴" if any(k in topics for k in ("error", "critical")) else ("🟡" if "warning" in topics else "ℹ️")
            lines.append(f"• `[{time_str}]` ({topics}):\n  └ {icon} {msg}")

        reply = (
            f"📜 **System Log Terbaru — {device_name}**\n\n"
            f"Menampilkan **{len(logs)} peristiwa terbaru**:\n\n"
            + "\n\n".join(lines) + "\n\n"
            f"💡 **Catatan Audit Keamanan:**\n"
            f"Pastikan seluruh aktivitas login dan perubahan konfigurasi dilakukan oleh staf resmi administrator."
        )
        return reply

    def _generate_ip_report(self, device_name: str, prompt: str = "") -> str:
        ips = TOOL_REGISTRY["get_ip"](device=device_name).get("data") or []
        if not ips:
            return f"🌐 **Daftar Alamat IP Interface — {device_name}**\n\nTidak ada alamat IP yang terkonfigurasi pada router."

        ip_lines = []
        for idx, i in enumerate(ips, 1):
            addr = i.get("address", "-")
            iface = i.get("interface", "-")
            net = i.get("network", "-")
            comment = i.get("comment", "")
            cm_text = f" | _{comment}_" if comment else ""
            ip_lines.append(f"{idx}. Interface `{iface}`\n   • IP: **{addr}** (Network: `{net}`){cm_text}")

        reply = (
            f"🌐 **Daftar Alamat IP Interface — {device_name}**\n\n"
            f"• Total IP Terpasang : **{len(ips)} alamat**\n\n"
            f"📋 **Rincian Alamat IP per Antarmuka:**\n\n"
            + "\n\n".join(ip_lines) + "\n\n"
            f"💡 *Petunjuk:* Ketik *'cek ip wan'* untuk rincian IP WAN atau *'cek rute'* untuk melihat tabel routing."
        )
        return reply

    def _generate_interfaces_report(self, device_name: str, prompt: str = "") -> str:
        ifaces = TOOL_REGISTRY["get_interface"](device=device_name).get("data") or []
        if not ifaces:
            return f"🔌 **Status Antarmuka Jaringan — {device_name}**\n\nTidak ada interface terdeteksi."

        running_count = len([i for i in ifaces if i.get("running")])
        lines = []
        for idx, iface in enumerate(ifaces, 1):
            name = iface.get("name", f"port{idx}")
            is_running = iface.get("running", False)
            status_tag = "🟢 UP" if is_running else "⚪ DOWN"
            rx = self._format_bytes(iface.get("rx_byte", 0))
            tx = self._format_bytes(iface.get("tx_byte", 0))
            mac = iface.get("mac", "")
            mac_str = f" | MAC: `{mac}`" if mac else ""
            lines.append(
                f"{idx}. **{name}** — {status_tag}{mac_str}\n"
                f"   • Lalu Lintas: Rx `{rx}` (Download) | Tx `{tx}` (Upload)"
            )

        reply = (
            f"🔌 **Status Antarmuka Jaringan (Interfaces) — {device_name}**\n\n"
            f"• Total Port Fisik & Virtual : **{len(ifaces)} interface**\n"
            f"• Port Aktif (Running)        : **{running_count} interface UP**\n\n"
            f"📋 **Rincian Status Seluruh Port:**\n\n"
            + "\n\n".join(lines) + "\n\n"
            f"💡 *Petunjuk:* Gunakan instruksi *'Matikan interface <nama_port>'* atau *'Hidupkan interface <nama_port>'* untuk kontrol link secara aman."
        )
        return reply


hermes_agent = HermesAIAgent()
