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

    projects = chroma_store.list_projects()
    if not projects:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "✅ You are authenticated.\n"
            "No projects exist yet — create one via the web interface first, then use /projects to select one."
        )
        return

    keyboard = _build_project_keyboard(projects)
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "✅ You are authenticated. Select a project to get started:",
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
            "✅ Authenticated! Use /projects to get started."
        )
    else:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "❌ Invalid code."
        )


# ---------------------------------------------------------------------------
# /projects
# ---------------------------------------------------------------------------


@require_auth
async def projects_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args).strip().lower() if context.args else ""
    all_projects = chroma_store.list_projects()
    projects = (
        [p for p in all_projects if query in p.lower()]
        if query
        else all_projects
    )
    if not projects:
        msg = (
            f'No projects found matching "{query}". Try a different search term.'
            if query
            else "No projects found. Create one via the web interface first."
        )
        await update.effective_message.reply_text(msg)  # type: ignore[union-attr]
        return

    keyboard = _build_project_keyboard(projects)
    title = f'Projects matching "{query}":' if query else "Select a project:"
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        title, reply_markup=keyboard
    )


# ---------------------------------------------------------------------------
# /new
# ---------------------------------------------------------------------------


@require_auth
async def new_session_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id: int = update.effective_chat.id  # type: ignore[union-attr]
    state = await telegram_session_manager.get_state(chat_id)

    if not state or not state.get("project_id"):
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "No project selected. Use /projects to select one first."
        )
        return

    session = await sessions_store.create_session(state["project_id"])
    await telegram_session_manager.set_state(chat_id, state["project_id"], session["id"])
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"✅ New session created for project *{state['project_id']}*.\nSession ID: `{session['id']}`",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# /session
# ---------------------------------------------------------------------------


@require_auth
async def session_info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id: int = update.effective_chat.id  # type: ignore[union-attr]
    state = await telegram_session_manager.get_state(chat_id)

    if not state or not state.get("project_id"):
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "No project selected. Use /projects to select one."
        )
        return

    project_id = state["project_id"]
    session_id = state.get("session_id") or "_(none — new session will be created on first message)_"
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"📋 *Current state*\nProject: `{project_id}`\nSession: `{session_id}`",
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
# Inline keyboard — project selection callback
# ---------------------------------------------------------------------------


@require_auth
async def project_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    chat_id: int = update.effective_chat.id  # type: ignore[union-attr]
    project_id: str = query.data  # type: ignore[union-attr]

    # Create a fresh session for the newly selected project
    session = await sessions_store.create_session(project_id)
    await telegram_session_manager.set_state(chat_id, project_id, session["id"])

    await query.edit_message_text(  # type: ignore[union-attr]
        f"✅ Project *{project_id}* selected. New session started.\nStart chatting or use /new for a fresh session.",
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
    if not state or not state.get("project_id"):
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "No project selected. Use /projects to choose one first."
        )
        return

    project_id: str = state["project_id"]
    session_id: str | None = state.get("session_id")

    # Ensure a session exists
    if not session_id:
        session = await sessions_store.create_session(project_id)
        session_id = session["id"]
        await telegram_session_manager.set_state(chat_id, project_id, session_id)

    # Load prior messages for context
    prior_messages = await sessions_store.get_messages(session_id)
    context_messages: list[str] = [m["content"] for m in prior_messages if m["role"] == "user"]
    context_messages.append(user_text)

    # Show typing indicator
    await update.effective_chat.send_action(ChatAction.TYPING)  # type: ignore[union-attr]

    agent_state = {
        "messages": context_messages,
        "project_id": project_id,
        "project_hint": None,
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


def _build_project_keyboard(projects: list[str]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=p, callback_data=p)]
        for p in projects
    ]
    return InlineKeyboardMarkup(buttons)


# ---------------------------------------------------------------------------
# Handler list for registration
# ---------------------------------------------------------------------------


def get_handlers():
    return [
        CommandHandler("start", start_handler),
        CommandHandler("auth", auth_handler),
        CommandHandler("projects", projects_handler),
        CommandHandler("project", projects_handler),
        CommandHandler("new", new_session_handler),
        CommandHandler("session", session_info_handler),
        CommandHandler("logout", logout_handler),
        CallbackQueryHandler(project_callback_handler),
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler),
    ]
