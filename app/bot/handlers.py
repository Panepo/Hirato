from __future__ import annotations

import hmac

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.agent.graph import secretary_graph
from app.agent.prompts import TITLE_PROMPT
from app.bot.auth import require_auth
from app.bot.telegram_sessions import telegram_session_manager
from app.core.config import settings
from app.memory.sessions import sessions_store
from app.memory.store import chroma_store
from langchain_core.messages import HumanMessage, SystemMessage
from app.agent.nodes import chat_llm


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id: int = update.effective_chat.id  # type: ignore[union-attr]
    authed = await telegram_session_manager.is_authed(chat_id)

    if not authed:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "👋 Welcome to the *Hirato* bot!\n\n"
            "This bot requires authentication before use.\n"
            "Please authenticate with:\n`/auth <code>`",
            parse_mode="Markdown",
        )
        return

    projects = chroma_store.list_channels()
    if not projects:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "✅ You are authenticated.\n"
            "No channels exist yet — create one via the web interface first, then use /channel to select one."
        )
        return

    keyboard = _build_channel_keyboard(projects)
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "✅ You are authenticated. Select a channel to get started:",
        reply_markup=keyboard,
    )


# ---------------------------------------------------------------------------
# /auth <code>
# ---------------------------------------------------------------------------


async def auth_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id: int = update.effective_chat.id  # type: ignore[union-attr]
    args = context.args or []

    if not args:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "Usage: /auth <code>"
        )
        return

    provided_code = args[0]
    expected_code = settings.TELEGRAM_ACCESS_CODE

    if not expected_code:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "❌ Authentication is not configured on this server."
        )
        return

    if hmac.compare_digest(provided_code, expected_code):
        await telegram_session_manager.grant_auth(chat_id)
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "✅ Authenticated! Use /channel to get started."
        )
    else:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "❌ Invalid code."
        )


# ---------------------------------------------------------------------------
# /channel
# ---------------------------------------------------------------------------


@require_auth
async def channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id: int = update.effective_chat.id  # type: ignore[union-attr]
    args = context.args or []

    all_channels = chroma_store.list_channels()

    # /channel new <name> — create a new channel
    if args and args[0].lower() == "new":
        name = " ".join(args[1:]).strip()
        if not name:
            await update.effective_message.reply_text(  # type: ignore[union-attr]
                "Usage: /channel new <name>"
            )
            return
        import re
        channel_id = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
        channel_id = re.sub(r"_+", "_", channel_id).strip("_.-")
        if len(channel_id) < 3:
            await update.effective_message.reply_text(  # type: ignore[union-attr]
                "❌ Channel name too short (min 3 alphanumeric characters)."
            )
            return
        from app.memory.store import chroma_store as _store
        _store.get_or_create_collection(channel_id)
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            f"✅ Channel *{channel_id}* created.",
            parse_mode="Markdown",
        )
        return

    # /channel <name> — fuzzy-select a channel
    if args:
        import difflib
        query = " ".join(args).strip().lower()
        matches = difflib.get_close_matches(query, [c.lower() for c in all_channels], n=1, cutoff=0.5)
        if matches:
            # find original-case name
            channel_id = next(c for c in all_channels if c.lower() == matches[0])
        else:
            # fallback: substring match
            channel_id_candidates = [c for c in all_channels if query in c.lower()]
            channel_id = channel_id_candidates[0] if channel_id_candidates else None

        if not channel_id:
            await update.effective_message.reply_text(  # type: ignore[union-attr]
                f'No channel found matching "{" ".join(args)}". Use /channel to list all channels.'
            )
            return

        session = await sessions_store.create_session(channel_id)
        await telegram_session_manager.set_state(chat_id, channel_id, session["id"])
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            f"✅ Channel *{channel_id}* selected. New session started.",
            parse_mode="Markdown",
        )
        return

    # /channel (no args) — show inline keyboard
    if not all_channels:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "No channels exist yet. Use /channel new <name> to create one."
        )
        return

    keyboard = _build_channel_keyboard(all_channels)
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "Select a channel:", reply_markup=keyboard
    )


# ---------------------------------------------------------------------------
# /new
# ---------------------------------------------------------------------------


@require_auth
async def new_session_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id: int = update.effective_chat.id  # type: ignore[union-attr]
    state = await telegram_session_manager.get_state(chat_id)

    if not state or not state.get("channel_id"):
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "No channel selected. Use /channel to select one first."
        )
        return

    session = await sessions_store.create_session(state["channel_id"])
    await telegram_session_manager.set_state(chat_id, state["channel_id"], session["id"])
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"✅ New session created for channel *{state['channel_id']}*.\nSession ID: `{session['id']}`",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# /session
# ---------------------------------------------------------------------------


@require_auth
async def session_info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id: int = update.effective_chat.id  # type: ignore[union-attr]
    state = await telegram_session_manager.get_state(chat_id)

    if not state or not state.get("channel_id"):
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "No channel selected. Use /channel to select one."
        )
        return

    channel_id = state["channel_id"]
    session_id = state.get("session_id") or "_(none — new session will be created on first message)_"
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"📋 *Current state*\nChannel: `{channel_id}`\nSession: `{session_id}`",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# /logout
# ---------------------------------------------------------------------------


@require_auth
async def logout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id: int = update.effective_chat.id  # type: ignore[union-attr]
    await telegram_session_manager.revoke_auth(chat_id)
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "👋 You have been logged out. Use /auth <code> to authenticate again."
    )


# ---------------------------------------------------------------------------
# Inline keyboard — channel selection callback
# ---------------------------------------------------------------------------


@require_auth
async def channel_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    chat_id: int = update.effective_chat.id  # type: ignore[union-attr]
    channel_id: str = query.data  # type: ignore[union-attr]

    # Create a fresh session for the newly selected channel
    session = await sessions_store.create_session(channel_id)
    await telegram_session_manager.set_state(chat_id, channel_id, session["id"])

    await query.edit_message_text(  # type: ignore[union-attr]
        f"✅ Channel *{channel_id}* selected. New session started.\nStart chatting or use /new for a fresh session.",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# Plain-text message handler — main chat flow
# ---------------------------------------------------------------------------


@require_auth
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id: int = update.effective_chat.id  # type: ignore[union-attr]
    user_text: str = update.effective_message.text or ""  # type: ignore[union-attr]

    state = await telegram_session_manager.get_state(chat_id)
    if not state or not state.get("channel_id"):
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "No channel selected. Use /channel to choose one first."
        )
        return

    channel_id: str = state["channel_id"]
    session_id: str | None = state.get("session_id")

    # Ensure a session exists
    if not session_id:
        session = await sessions_store.create_session(channel_id)
        session_id = session["id"]
        await telegram_session_manager.set_state(chat_id, channel_id, session_id)

    # Load prior messages for context
    prior_messages = await sessions_store.get_messages(session_id)
    context_messages: list[str] = [m["content"] for m in prior_messages if m["role"] == "user"]
    context_messages.append(user_text)

    # Show typing indicator
    await update.effective_chat.send_action(ChatAction.TYPING)  # type: ignore[union-attr]

    agent_state = {
        "messages": context_messages,
        "channel_id": channel_id,
        "intents": [],
        "report_segment": None,
        "question_segment": None,
        "extracted_summary": None,
        "retrieved_docs": None,
        "store_response": None,
        "answer_response": None,
        "response": None,
    }

    final_state = await secretary_graph.ainvoke(agent_state)
    agent_response: str = final_state.get("response", "")

    # Persist messages
    await sessions_store.add_message(session_id, "user", user_text)
    await sessions_store.add_message(session_id, "assistant", agent_response)

    # Auto-generate title on first turn
    if not prior_messages:
        try:
            title_response = chat_llm.invoke(
                [
                    SystemMessage(content=TITLE_PROMPT),
                    HumanMessage(content=user_text),
                ]
            )
            await sessions_store.update_title(session_id, title_response.content.strip())
        except Exception:
            pass

    await update.effective_message.reply_text(agent_response)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_channel_keyboard(channels: list[str]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=c, callback_data=c)]
        for c in channels
    ]
    return InlineKeyboardMarkup(buttons)


# ---------------------------------------------------------------------------
# Handler list for registration
# ---------------------------------------------------------------------------


def get_handlers():
    return [
        CommandHandler("start", start_handler),
        CommandHandler("auth", auth_handler),
        CommandHandler("channel", channel_handler),
        CommandHandler("new", new_session_handler),
        CommandHandler("session", session_info_handler),
        CommandHandler("logout", logout_handler),
        CallbackQueryHandler(channel_callback_handler),
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler),
    ]
