from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.agent.graph import secretary_graph
from app.agent.nodes import (
    answer_node_astream,
    chat_llm,
    extractor_node,
    retriever_node,
    router_node,
    store_node,
)
from app.agent.prompts import TITLE_PROMPT
from app.core.config import settings
from app.memory.sessions import sessions_store
from app.memory.store import chroma_store

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class NewChannelRequest(BaseModel):
    name: str
    description: str = ""


class UpdateMemoryRequest(BaseModel):
    content: str


class ImportMemoriesRequest(BaseModel):
    memories: list[dict]


class ChatRequest(BaseModel):
    message: str
    channel_id: str = ""
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    title_updated: bool = False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/channels")
async def list_channels() -> list[str]:
    return chroma_store.list_channels()


@router.post("/channels", status_code=201)
async def create_channel(body: NewChannelRequest) -> dict[str, str]:
    channel_id = re.sub(r"[^a-zA-Z0-9._-]", "_", body.name.strip())
    channel_id = re.sub(r"_+", "_", channel_id).strip("_.-")
    if len(channel_id) < 3:
        raise HTTPException(status_code=400, detail="Channel name too short or contains only invalid characters (min 3 alphanumeric).")
    if not channel_id:
        raise HTTPException(status_code=400, detail="Channel name cannot be empty.")
    chroma_store.get_or_create_collection(channel_id)
    return {"channel_id": channel_id, "description": body.description}


@router.delete("/channels/{channel_id}", status_code=200)
async def delete_channel(channel_id: str) -> dict[str, bool]:
    try:
        chroma_store.delete_channel(channel_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/channels/{channel_id}/memories")
async def list_memories(channel_id: str) -> list[dict]:
    try:
        return chroma_store.list_memories(channel_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/channels/{channel_id}/memories/{memory_id}", status_code=200)
async def delete_memory(channel_id: str, memory_id: str) -> dict[str, bool]:
    try:
        chroma_store.delete_memory(channel_id, memory_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.put("/channels/{channel_id}/memories/{memory_id}")
async def update_memory(channel_id: str, memory_id: str, body: UpdateMemoryRequest) -> dict[str, bool]:
    try:
        chroma_store.update_memory(channel_id, memory_id, body.content)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/channels/{channel_id}/memories/import", status_code=200)
async def import_memories_endpoint(channel_id: str, body: ImportMemoriesRequest) -> dict[str, int]:
    try:
        result = chroma_store.import_memories(channel_id, body.memories)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result


# ---------------------------------------------------------------------------
# Session endpoints
# ---------------------------------------------------------------------------


@router.get("/sessions")
async def list_sessions(channel_id: str) -> list[dict[str, Any]]:
    return await sessions_store.list_sessions(channel_id)


@router.post("/sessions", status_code=201)
async def create_session(body: dict[str, str]) -> dict[str, Any]:
    channel_id = body.get("channel_id", "").strip()
    if not channel_id:
        raise HTTPException(status_code=400, detail="channel_id is required.")
    return await sessions_store.create_session(channel_id)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    session = await sessions_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return session


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str) -> None:
    deleted = await sessions_store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found.")


@router.put("/sessions/{session_id}/title")
async def rename_session(session_id: str, body: dict[str, str]) -> dict[str, str]:
    title = body.get("title", "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required.")
    session = await sessions_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    await sessions_store.update_title(session_id, title)
    return {"session_id": session_id, "title": title}


# ---------------------------------------------------------------------------
# Title generation helper
# ---------------------------------------------------------------------------


async def _generate_title(message: str) -> str:
    response = chat_llm.invoke(
        [
            SystemMessage(content=TITLE_PROMPT),
            HumanMessage(content=message),
        ]
    )
    return response.content.strip()


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    # Resolve or create session (channel_id may be empty if not provided)
    session_id = body.session_id
    if body.channel_id and not session_id:
        session = await sessions_store.create_session(body.channel_id)
        session_id = session["id"]

    # Load prior messages to build context
    prior_messages = await sessions_store.get_messages(session_id) if session_id else []
    context_messages: list[str] = [m["content"] for m in prior_messages if m["role"] == "user"]
    context_messages.append(body.message)

    initial_state = {
        "messages": context_messages,
        "channel_id": body.channel_id,
        "intents": [],
        "report_segment": None,
        "question_segment": None,
        "extracted_summary": None,
        "retrieved_docs": None,
        "store_response": None,
        "answer_response": None,
        "response": None,
    }
    final_state = await secretary_graph.ainvoke(initial_state)

    # Validate that we have a channel after resolution
    resolved_channel_id: str = final_state.get("channel_id", "")
    if not resolved_channel_id:
        raise HTTPException(status_code=400, detail="Could not identify a channel. Please specify channel_id in your request.")

    # Create session now if channel was resolved from the message
    if not session_id:
        session = await sessions_store.create_session(resolved_channel_id)
        session_id = session["id"]

    agent_response: str = final_state.get("response", "")

    # Persist messages
    await sessions_store.add_message(session_id, "user", body.message)
    await sessions_store.add_message(session_id, "assistant", agent_response)

    # Generate title on first complete exchange (no prior messages means this is the first turn)
    title_updated = False
    if not prior_messages:
        try:
            title = await _generate_title(body.message)
            await sessions_store.update_title(session_id, title)
            title_updated = True
        except Exception:
            pass  # title generation is best-effort

    return ChatResponse(response=agent_response, session_id=session_id, title_updated=title_updated)


# ---------------------------------------------------------------------------
# Streaming chat
# ---------------------------------------------------------------------------

@router.post("/chat/stream")
async def chat_stream(body: ChatRequest) -> StreamingResponse:
    # Resolve or create session (channel_id may be empty if resolved from message)
    session_id = body.session_id
    if body.channel_id and not session_id:
        session = await sessions_store.create_session(body.channel_id)
        session_id = session["id"]

    prior_messages = await sessions_store.get_messages(session_id) if session_id else []
    context_messages: list[str] = [m["content"] for m in prior_messages if m["role"] == "user"]
    context_messages.append(body.message)

    state: dict = {
        "messages": context_messages,
        "channel_id": body.channel_id,
        "intents": [],
        "report_segment": None,
        "question_segment": None,
        "extracted_summary": None,
        "retrieved_docs": None,
        "store_response": None,
        "answer_response": None,
        "response": None,
    }

    # Run preprocessing nodes in thread pool (they make blocking LLM calls)
    router_result = await asyncio.to_thread(router_node, state)
    state.update(router_result)

    if not state.get("channel_id"):
        raise HTTPException(status_code=400, detail="Could not identify a channel. Please specify channel_id in your request.")

    # Create session now if it was resolved from the message
    if not session_id:
        session = await sessions_store.create_session(state["channel_id"])
        session_id = session["id"]

    extractor_result = await asyncio.to_thread(extractor_node, state)
    state.update(extractor_result)

    store_result = await asyncio.to_thread(store_node, state)
    state.update(store_result)

    retriever_result = await asyncio.to_thread(retriever_node, state)
    state.update(retriever_result)

    frozen_state = dict(state)
    frozen_session_id = session_id
    is_first_turn = not prior_messages
    user_message = body.message

    async def event_generator():
        full_response_parts: list[str] = []

        yield f"data: {json.dumps({'type': 'session', 'session_id': frozen_session_id})}\n\n"

        # Emit store response (progress report ack) immediately if present
        store_resp: str | None = frozen_state.get("store_response")
        if store_resp:
            full_response_parts.append(store_resp)
            yield f"data: {json.dumps({'type': 'token', 'content': store_resp})}\n\n"

        # Stream the answer if there is a question intent
        if "question" in frozen_state.get("intents", []):
            if store_resp:
                sep = "\n\n"
                full_response_parts.append(sep)
                yield f"data: {json.dumps({'type': 'token', 'content': sep})}\n\n"

            gen_start = time.perf_counter()
            first_chunk_at: float | None = None
            last_chunk_at: float | None = None
            answer_chunks: list[str] = []

            async for chunk in answer_node_astream(frozen_state):
                now = time.perf_counter()
                if first_chunk_at is None:
                    first_chunk_at = now
                last_chunk_at = now
                answer_chunks.append(chunk)
                full_response_parts.append(chunk)
                yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

            ttfw = round(first_chunk_at - gen_start, 2) if first_chunk_at is not None else 0.0
            total = round((last_chunk_at or gen_start) - gen_start, 2)
            gen_duration = round((last_chunk_at - first_chunk_at), 2) if (last_chunk_at and first_chunk_at and last_chunk_at > first_chunk_at) else 0.01
            word_count = len("".join(answer_chunks).split())
            wps = round(word_count / gen_duration, 1) if gen_duration > 0 else 0.0

            yield f"data: {json.dumps({'type': 'metrics', 'ttfw': ttfw, 'wps': wps, 'total': total})}\n\n"

        full_response = "".join(full_response_parts) or "No response generated."

        # Persist messages
        await sessions_store.add_message(frozen_session_id, "user", user_message)
        await sessions_store.add_message(frozen_session_id, "assistant", full_response)

        # Generate title on first turn (best-effort)
        title_updated = False
        if is_first_turn:
            try:
                title_resp = await asyncio.to_thread(
                    chat_llm.invoke,
                    [SystemMessage(content=TITLE_PROMPT), HumanMessage(content=user_message)],
                )
                await sessions_store.update_title(frozen_session_id, title_resp.content.strip())
                title_updated = True
            except Exception:
                pass

        yield f"data: {json.dumps({'type': 'done', 'session_id': frozen_session_id, 'title_updated': title_updated})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/channels/{channel_id}/import")
async def import_embedded_json(
    channel_id: str,
    file: UploadFile = File(...),
) -> dict[str, int]:
    if not file.filename or not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only .json files are accepted.")

    raw_bytes = await file.read()
    try:
        data = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    if not isinstance(data, dict) or "chunks" not in data:
        raise HTTPException(
            status_code=422,
            detail="JSON must have a top-level 'chunks' array.",
        )
    chunks = data["chunks"]
    if not isinstance(chunks, list):
        raise HTTPException(status_code=422, detail="'chunks' must be an array.")
    for i, chunk in enumerate(chunks):
        if "chunk_id" not in chunk or "chunk_text_embedded" not in chunk:
            raise HTTPException(
                status_code=422,
                detail=f"Chunk at index {i} is missing 'chunk_id' or 'chunk_text_embedded'.",
            )

    result = chroma_store.import_chunks(channel_id=channel_id, chunks=chunks)
    return result


@router.delete("/channels/{channel_id}", status_code=204)
async def delete_channel_nocontent(channel_id: str) -> None:
    try:
        chroma_store.delete_channel(channel_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Channel not found: {exc}") from exc
