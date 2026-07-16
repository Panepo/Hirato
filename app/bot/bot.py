from __future__ import annotations

import logging

from telegram.ext import Application

from app.bot.handlers import get_handlers

logger = logging.getLogger(__name__)


def build_application(token: str) -> Application:
    application = Application.builder().token(token).build()
    for handler in get_handlers():
        application.add_handler(handler)
    return application


async def start_bot(application: Application) -> None:
    await application.initialize()
    await application.start()
    await application.updater.start_polling()  # type: ignore[union-attr]
    logger.info("Telegram bot started and polling for updates.")


async def stop_bot(application: Application) -> None:
    await application.updater.stop()  # type: ignore[union-attr]
    await application.stop()
    await application.shutdown()
    logger.info("Telegram bot stopped.")
