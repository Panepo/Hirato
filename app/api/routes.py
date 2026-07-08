from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.agent.graph import secretary_graph
from app.agent.nodes import chat_llm
from app.agent.prompts import TITLE_PROMPT
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
