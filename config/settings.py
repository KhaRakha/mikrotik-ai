"""
Configuration management module for MikroTik AI Agent Automation.
Loads configuration from environment variables, .env, and YAML files.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from dotenv import dotenv_values, load_dotenv

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

# Ensure runtime directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Load environment values
local_env_path = PROJECT_ROOT / ".env"
hermes_env_path = Path(os.path.expanduser("~")) / "AppData" / "Local" / "hermes" / ".env"

local_values = dotenv_values(local_env_path) if local_env_path.exists() else {}
hermes_values = dotenv_values(hermes_env_path) if hermes_env_path.exists() else {}


def get_conf_val(key: str, default: str = "") -> str:
    """Get value from os.environ, then local .env, then hermes .env."""
    v = os.getenv(key)
    if v is not None and v.strip():
        return v.strip()
    v_loc = local_values.get(key)
    if v_loc is not None and str(v_loc).strip():
        return str(v_loc).strip()
    v_hermes = hermes_values.get(key)
    if v_hermes is not None and str(v_hermes).strip():
        return str(v_hermes).strip()
    return default


def load_yaml(file_path: Path) -> Dict[str, Any]:
    if not file_path.exists():
        return {}
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            return yaml.safe_load(f) or {}
        except Exception:
            return {}


class DeviceConfig:
    def __init__(self, data: Dict[str, Any]):
        self.id: str = data.get("id", "")
        self.name: str = data.get("name", "Unknown")
        self.aliases: List[str] = [a.lower() for a in data.get("aliases", [])]
        self.host: str = data.get("host", "127.0.0.1")
        self.port: int = int(data.get("port", 80))
        self.protocol: str = data.get("protocol", "rest").lower()
        self.use_ssl: bool = bool(data.get("use_ssl", False))
        self.username: str = data.get("username", "admin")
        self.password: str = data.get("password", "")
        self.is_default: bool = bool(data.get("is_default", False))
        self.description: str = data.get("description", "")

    def matches(self, term: str) -> bool:
        term_clean = term.lower().strip()
        if not term_clean:
            return False
        if term_clean == self.id.lower():
            return True
        if term_clean == self.name.lower():
            return True
        if term_clean == self.host.lower():
            return True
        # Match full device name as word/phrase
        if re.search(r'\b' + re.escape(self.name.lower()) + r'\b', term_clean):
            return True
        for alias in self.aliases:
            if not alias:
                continue
            # Match alias as word/phrase to avoid substring collisions (e.g. 'lab' in 'lambat')
            if re.search(r'\b' + re.escape(alias.lower()) + r'\b', term_clean):
                return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "aliases": self.aliases,
            "host": self.host,
            "port": self.port,
            "protocol": self.protocol,
            "use_ssl": self.use_ssl,
            "username": self.username,
            "is_default": self.is_default,
            "description": self.description,
        }


class Settings:
    def __init__(self):
        self.config_data = load_yaml(CONFIG_DIR / "config.yaml")
        self.devices_data = load_yaml(CONFIG_DIR / "devices.yaml")

        # Telegram Configuration & RBAC
        self.telegram_bot_token: str = get_conf_val("TELEGRAM_BOT_TOKEN")

        allowed_raw = get_conf_val("ALLOWED_TELEGRAM_IDS") or get_conf_val("TELEGRAM_ALLOWED_USERS") or ""
        self.allowed_telegram_ids: List[int] = []
        for uid in allowed_raw.split(","):
            uid = uid.strip()
            if uid.isdigit():
                self.allowed_telegram_ids.append(int(uid))

        admin_raw = get_conf_val("ADMIN_TELEGRAM_IDS") or ""
        self.admin_telegram_ids: List[int] = []
        for uid in admin_raw.split(","):
            uid = uid.strip()
            if uid.isdigit():
                self.admin_telegram_ids.append(int(uid))

        viewer_raw = get_conf_val("VIEWER_TELEGRAM_IDS") or ""
        self.viewer_telegram_ids: List[int] = []
        for uid in viewer_raw.split(","):
            uid = uid.strip()
            if uid.isdigit():
                self.viewer_telegram_ids.append(int(uid))

        # Backward compatibility: if no admin IDs explicitly declared, default all allowed IDs to admin
        if not self.admin_telegram_ids and self.allowed_telegram_ids:
            self.admin_telegram_ids = [uid for uid in self.allowed_telegram_ids if uid not in self.viewer_telegram_ids]

        # Ensure all admin and viewer IDs are in allowed_telegram_ids
        for uid in self.admin_telegram_ids + self.viewer_telegram_ids:
            if uid not in self.allowed_telegram_ids:
                self.allowed_telegram_ids.append(uid)

        # AI Agent & LLM Configuration
        self.llm_provider: str = get_conf_val("LLM_PROVIDER", self.config_data.get("agent", {}).get("provider", "gemini"))
        self.google_api_key: str = get_conf_val("GOOGLE_API_KEY", "")
        self.openai_api_key: str = get_conf_val("OPENAI_API_KEY", "")
        self.openai_base_url: str = get_conf_val("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.llm_model: str = get_conf_val("LLM_MODEL", self.config_data.get("agent", {}).get("model", "gemini-2.5-flash"))

        # MikroTik Defaults
        self.default_device_name: str = get_conf_val("DEFAULT_MIKROTIK_DEVICE", "Kantor Utama")
        self.enable_mock_fallback: bool = get_conf_val("ENABLE_MOCK_FALLBACK", "true").lower() in ("true", "1", "yes")

        # Confirmation & Security
        conf_sec = get_conf_val("CONFIRMATION_TIMEOUT_SECONDS")
        self.confirmation_timeout_seconds: int = (
            int(conf_sec) if conf_sec and conf_sec.isdigit()
            else int(self.config_data.get("confirmation", {}).get("timeout_seconds", 300))
        )
        self.dangerous_operations: List[str] = self.config_data.get("security", {}).get("dangerous_operations", [])
        self.write_operations: List[str] = self.config_data.get("security", {}).get("write_operations", [])

        # Proactive Monitoring Configuration
        mon_cfg = self.config_data.get("monitoring", {})
        self.monitoring_enabled: bool = (
            get_conf_val("MONITORING_ENABLED", str(mon_cfg.get("enabled", "true"))).lower() in ("true", "1", "yes")
        )
        mon_interval_str = get_conf_val("MONITORING_INTERVAL_SECONDS", str(mon_cfg.get("interval_seconds", 60)))
        self.monitoring_interval_seconds: int = int(mon_interval_str) if mon_interval_str.isdigit() else 60

        cpu_thresh_str = get_conf_val("CPU_THRESHOLD_PERCENT", str(mon_cfg.get("cpu_threshold_percent", 90)))
        try:
            self.cpu_threshold_percent: float = float(cpu_thresh_str)
        except ValueError:
            self.cpu_threshold_percent = 90.0

        alert_chats_raw = get_conf_val("ALERT_TELEGRAM_CHAT_ID") or ""
        self.alert_chat_ids: List[int] = []
        if alert_chats_raw:
            for cid in alert_chats_raw.split(","):
                cid = cid.strip()
                if cid.lstrip("-").isdigit():
                    self.alert_chat_ids.append(int(cid))
        elif mon_cfg.get("alert_chat_ids"):
            self.alert_chat_ids = [int(c) for c in mon_cfg.get("alert_chat_ids") if str(c).lstrip("-").isdigit()]
        else:
            self.alert_chat_ids = list(self.admin_telegram_ids)

        # Paths
        self.database_path: Path = PROJECT_ROOT / os.getenv("DATABASE_PATH", self.config_data.get("audit", {}).get("database_path", "data/audit.db"))
        self.log_file_path: Path = PROJECT_ROOT / os.getenv("LOG_FILE_PATH", self.config_data.get("audit", {}).get("jsonl_path", "logs/audit.jsonl"))

        # Load Devices
        self.devices: List[DeviceConfig] = []
        raw_devices = self.devices_data.get("devices", [])
        for dev_raw in raw_devices:
            self.devices.append(DeviceConfig(dev_raw))

    def get_default_device(self) -> Optional[DeviceConfig]:
        for dev in self.devices:
            if dev.is_default:
                return dev
        for dev in self.devices:
            if dev.name.lower() == self.default_device_name.lower():
                return dev
        return self.devices[0] if self.devices else None

    def find_device(self, query: str, fallback: bool = True) -> Optional[DeviceConfig]:
        if not query:
            return self.get_default_device() if fallback else None

        clean_query = query.lower().strip()

        # Phase 1: Exact match (id, name, host, or exact alias)
        for dev in self.devices:
            if clean_query in (dev.id.lower(), dev.name.lower(), dev.host.lower()):
                return dev
            if any(clean_query == a.lower() for a in dev.aliases if a):
                return dev

        # Phase 2: Longest matching name or alias (prevents 'Kantor Cabang' stealing 'Kantor Cabang 2')
        best_match = None
        best_len = 0
        for dev in self.devices:
            if re.search(r'\b' + re.escape(dev.name.lower()) + r'\b', clean_query):
                if len(dev.name) > best_len:
                    best_match = dev
                    best_len = len(dev.name)
            for alias in dev.aliases:
                if alias and re.search(r'\b' + re.escape(alias.lower()) + r'\b', clean_query):
                    if len(alias) > best_len:
                        best_match = dev
                        best_len = len(alias)

        if best_match:
            return best_match

        return self.get_default_device() if fallback else None

    def reload(self) -> None:
        """Reload configuration and devices from disk."""
        self.config_data = load_yaml(CONFIG_DIR / "config.yaml")
        self.devices_data = load_yaml(CONFIG_DIR / "devices.yaml")
        self.devices = []
        raw_devices = self.devices_data.get("devices", [])
        for dev_raw in raw_devices:
            self.devices.append(DeviceConfig(dev_raw))


settings = Settings()
