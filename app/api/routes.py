from __future__ import annotations

import asyncio
import difflib
import json
import time
from typing import Any

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
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


class NewProjectRequest(BaseModel):
    name: str
    description: str = ""


class ChatRequest(BaseModel):
    message: str
    project_id: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    title_updated: bool = False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/projects")
async def list_projects() -> list[str]:
    return chroma_store.list_projects()


@router.post("/projects", status_code=201)
async def create_project(body: NewProjectRequest) -> dict[str, str]:
    project_id = body.name.strip().replace(" ", "_")
    if not project_id:
        raise HTTPException(status_code=400, detail="Project name cannot be empty.")
    chroma_store.get_or_create_collection(project_id)
    return {"project_id": project_id, "description": body.description}


# ---------------------------------------------------------------------------
# Shiratsuyu project search
# ---------------------------------------------------------------------------


@router.get("/shiratsuyu/projects")
async def search_shiratsuyu_projects(q: str = "") -> list[dict]:
    """Fetch all Shiratsuyu projects via REST and return those matching query q."""
    query = q.strip().lower()
    if not query or not settings.SHIRATSUYU_BEARER:
        return []

    url = settings.SHIRATSUYU_URL.rstrip("/") + "/project/"
    headers = {"Authorization": f"Bearer {settings.SHIRATSUYU_BEARER}"}

    async with httpx.AsyncClient(verify=False) as client:
        r = await client.get(url, headers=headers, timeout=15.0)
        r.raise_for_status()
        projects: list[dict] = r.json()

    scored: list[dict] = []
    for proj in projects:
        code: str = str(proj.get("code", "") or "")
        name: str = str(proj.get("name", "") or "")
        combined = f"{code} {name}".lower()

        if query in combined:
            score = 1.0 if query == combined else 0.9
        else:
            score = difflib.SequenceMatcher(None, query, combined).ratio()

        if score >= 0.8:
            scored.append({"score": score, "code": code, "name": name})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return [{"code": p["code"], "name": p["name"]} for p in scored[:15]]



# ---------------------------------------------------------------------------
# Session endpoints
# ---------------------------------------------------------------------------


@router.get("/sessions")
async def list_sessions(project_id: str) -> list[dict[str, Any]]:
    return await sessions_store.list_sessions(project_id)


@router.post("/sessions", status_code=201)
async def create_session(body: dict[str, str]) -> dict[str, Any]:
    project_id = body.get("project_id", "").strip()
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required.")
    return await sessions_store.create_session(project_id)


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
    if not body.project_id:
        raise HTTPException(status_code=400, detail="project_id is required.")

    # Resolve or create session
    session_id = body.session_id
    if not session_id:
        session = await sessions_store.create_session(body.project_id)
        session_id = session["id"]

    # Load prior messages to build context
    prior_messages = await sessions_store.get_messages(session_id)
    context_messages: list[str] = [m["content"] for m in prior_messages if m["role"] == "user"]
    context_messages.append(body.message)

    initial_state = {
        "messages": context_messages,
        "project_id": body.project_id,
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
    if not body.project_id:
        raise HTTPException(status_code=400, detail="project_id is required.")

    # Resolve or create session
    session_id = body.session_id
    if not session_id:
        session = await sessions_store.create_session(body.project_id)
        session_id = session["id"]

    prior_messages = await sessions_store.get_messages(session_id)
    context_messages: list[str] = [m["content"] for m in prior_messages if m["role"] == "user"]
    context_messages.append(body.message)

    state: dict = {
        "messages": context_messages,
        "project_id": body.project_id,
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


@router.post("/projects/{project_id}/import")
async def import_embedded_json(
    project_id: str,
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

    result = chroma_store.import_chunks(project_id=project_id, chunks=chunks)
    return result


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: str) -> None:
    try:
        chroma_store.delete_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Project not found: {exc}") from exc
