from __future__ import annotations

import functools
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.telegram_sessions import telegram_session_manager


def require_auth(handler: Callable) -> Callable:
    """Decorator that gates a handler behind Telegram authentication."""

    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id: int = update.effective_chat.id  # type: ignore[union-attr]
        if not await telegram_session_manager.is_authed(chat_id):
            await update.effective_message.reply_text(  # type: ignore[union-attr]
                "🔒 You are not authenticated.\n"
                "Please use /auth <code> to authenticate first."
            )
            return
        return await handler(update, context)

    return wrapper
