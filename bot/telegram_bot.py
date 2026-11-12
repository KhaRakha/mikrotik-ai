"""
Main Telegram Bot Application Module.
Integrates telegram handlers with the application lifecycle.
"""

from __future__ import annotations

import asyncio
import logging
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from bot.handlers import (
    add_device_command,
    add_ip_command,
    audit_command,
    clear_command,
    devices_command,
    discover_command,
    edit_ip_command,
    firmware_command,
    handle_callback_query,
    handle_message,
    help_command,
    reload_command,
    remove_device_command,
    remove_ip_command,
    reboot_command,
    role_command,
    start_command,
    status_command,
    upgrade_command,
)
from config.settings import settings
from core.monitor import proactive_monitor

logger = logging.getLogger(__name__)


async def on_post_init(app: Application) -> None:
    """Trigger background proactive monitoring task on startup."""
    if settings.monitoring_enabled:
        logger.info("Mendaftarkan background proactive monitoring task...")
        asyncio.create_task(proactive_monitor.run_monitoring_loop(app.bot))


def create_bot_app() -> Application:
    """Build and configure the Telegram application."""
    token = settings.telegram_bot_token
    if not token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN belum disetel! "
            "Isikan token bot Anda di file .env atau jalankan wizard setup."
        )

    app = ApplicationBuilder().token(token).post_init(on_post_init).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("devices", devices_command))
    app.add_handler(CommandHandler("add_device", add_device_command))
    app.add_handler(CommandHandler("remove_device", remove_device_command))
    app.add_handler(CommandHandler("reload", reload_command))
    app.add_handler(CommandHandler("add_ip", add_ip_command))
    app.add_handler(CommandHandler("remove_ip", remove_ip_command))
    app.add_handler(CommandHandler("edit_ip", edit_ip_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("firmware", firmware_command))
    app.add_handler(CommandHandler("check_update", firmware_command))
    app.add_handler(CommandHandler("upgrade", upgrade_command))
    app.add_handler(CommandHandler("reboot", reboot_command))
    app.add_handler(CommandHandler("restart", reboot_command))
    app.add_handler(CommandHandler("audit", audit_command))
    app.add_handler(CommandHandler("discover", discover_command))
    app.add_handler(CommandHandler("role", role_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("reset", clear_command))

    # Register callback query handler for inline confirmation buttons
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # Register natural language message handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app


def run_bot() -> None:
    """Start Telegram bot in polling mode."""
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=getattr(logging, settings.config_data.get("audit", {}).get("log_level", "INFO")),
    )
    logger.info("Memulai Hermes AI Agent Telegram Bot...")
    app = create_bot_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES)
