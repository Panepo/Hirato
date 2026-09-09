from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.node_async import (
    answer_node_async,
    extractor_node_async,
    retriever_node_async,
    router_node_async,
    store_node_async,
)
from app.agent.node_config import router_llm
from app.agent.prompts import TITLE_PROMPT
from app.core.auth import AuthUser
from app.core.channel_acl import get_effective_role, require_channel_view
from app.memory.sessions import sessions_store

WRITE_ROLES = {"writer", "manager", "admin"}


def _new_state(channel_id: str, message: str) -> dict[str, Any]:
    return {
        "messages": [message],
        "channel_id": channel_id,
        "intents": [],
        "report_segment": None,
        "question_segment": None,
        "extracted_chunks": None,
        "retrieved_docs": None,
        "store_response": None,
        "answer_response": None,
        "response": None,
    }


async def _generate_title(message: str) -> str:
    response = router_llm.generate_response(
        messages=[
            SystemMessage(content=TITLE_PROMPT),
            HumanMessage(content=message),
        ]
    )
    return response.strip()


async def _run_state_machine(state: dict[str, Any], channel_id: str, user: AuthUser) -> dict[str, Any]:
    """Run router -> (extractor+store | retriever+answer) against a freshly built state, returning the updated state."""
    router_result = await router_node_async(state)
    state.update(router_result)

    if state.get("decision") == "save_memory":
        role = await get_effective_role(channel_id, user)
        if role not in WRITE_ROLES:
            raise HTTPException(status_code=403, detail="Write access required to save progress reports.")
        extractor_result = await extractor_node_async(state)
        state.update(extractor_result)
        store_result = await store_node_async(state)
        state.update(store_result)
    else:
        retriever_result = await retriever_node_async(state)
        state.update(retriever_result)
        answer_result = await answer_node_async(state)
        state.update(answer_result)

    return state


async def run_chat_turn(channel_id: str, session_id: str | None, message: str, user: AuthUser) -> dict[str, Any]:
    """Non-streaming chat turn: resolve/create session, run the agent state machine, persist, title. Shared by REST /chat and the MCP chat tool."""
    if not channel_id:
        raise HTTPException(status_code=400, detail="Please specify channel_id in your request.")
    await require_channel_view(channel_id, user)

    if not session_id:
        session = await sessions_store.create_session(channel_id)
        session_id = session["id"]

    prior_messages = await sessions_store.get_messages(session_id)

    state = await _run_state_machine(_new_state(channel_id, message), channel_id, user)
    agent_response: str = state.get("response", "")

    await sessions_store.add_message(session_id, "user", message)
    await sessions_store.add_message(session_id, "assistant", agent_response)

    title_updated = False
    if not prior_messages:
        try:
            title = await _generate_title(message)
            await sessions_store.update_title(session_id, title)
            title_updated = True
        except Exception:
            pass  # title generation is best-effort

    return {"response": agent_response, "session_id": session_id, "title_updated": title_updated}


async def run_regenerate_turn(channel_id: str, session_id: str, user: AuthUser) -> dict[str, Any]:
    """Non-streaming regenerate: discard the last assistant reply and rerun the state machine on the prior user message."""
    if not channel_id:
        raise HTTPException(status_code=400, detail="Please specify channel_id in your request.")
    await require_channel_view(channel_id, user)
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required to regenerate a response.")

    prior_messages = await sessions_store.get_messages(session_id)
    if len(prior_messages) < 2 or prior_messages[-1]["role"] != "assistant" or prior_messages[-2]["role"] != "user":
        raise HTTPException(status_code=400, detail="Nothing to regenerate for this session.")

    user_message: str = prior_messages[-2]["content"]
    await sessions_store.delete_last_message(session_id)

    state = await _run_state_machine(_new_state(channel_id, user_message), channel_id, user)
    agent_response: str = state.get("response", "")

    await sessions_store.add_message(session_id, "assistant", agent_response)

    return {"response": agent_response, "session_id": session_id, "title_updated": False}
