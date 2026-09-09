from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.agent.node_config import chat_llm, router_llm
from app.agent.node_async import (
    answer_node_async,
    answer_node_astream,
    router_node_async,
    extractor_node_async,
    store_node_async,
    retriever_node_async,
)
from app.agent.prompts import TITLE_PROMPT
from app.core.auth import AuthUser, get_current_user, require_channel_creator, require_site_admin, shiratsuyu_query_user
from app.core.channel_acl import get_effective_role, require_channel_manage, require_channel_view, require_channel_write
from app.core.config import settings
from app.core.indexer import IndexerClient
from app.memory.auth_store import auth_store
from app.memory.sessions import sessions_store
from app.memory.store import vector_store

router = APIRouter(prefix="/api")

_WRITE_ROLES = {"writer", "manager", "admin"}


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


class BulkDeleteMemoriesRequest(BaseModel):
    memory_ids: list[str]


class ChatRequest(BaseModel):
    message: str
    channel_id: str = ""
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    title_updated: bool = False


class RegenerateRequest(BaseModel):
    channel_id: str = ""
    session_id: str


class ChannelSettingsRequest(BaseModel):
    is_open: bool


class RoleAssignmentRequest(BaseModel):
    user_id: str
    name: str = ""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/user/query/{identifier}")
async def query_user(
    identifier: str,
    authorization: str = Header(...),
    _: AuthUser = Depends(get_current_user),
) -> list[dict]:
    return await shiratsuyu_query_user(identifier)


@router.get("/channels")
async def list_channels(user: AuthUser = Depends(get_current_user)) -> list[dict[str, Any]]:
    result = []
    for channel_id in vector_store.list_channels():
        is_open = await auth_store.is_channel_open(channel_id)
        role = await get_effective_role(channel_id, user)
        if is_open or role is not None:
            result.append({"channel_id": channel_id, "is_open": is_open, "role": role})
    return result


@router.post("/channels", status_code=201)
async def create_channel(body: NewChannelRequest, _: AuthUser = Depends(require_channel_creator)) -> dict[str, str]:
    channel_id = re.sub(r"[^a-zA-Z0-9._-]", "_", body.name.strip())
    channel_id = re.sub(r"_+", "_", channel_id).strip("_.-")
    if len(channel_id) < 3:
        raise HTTPException(status_code=400, detail="Channel name too short or contains only invalid characters (min 3 alphanumeric).")
    if not channel_id:
        raise HTTPException(status_code=400, detail="Channel name cannot be empty.")
    vector_store.get_or_create_collection(channel_id)
    await auth_store.ensure_channel_settings_row(channel_id)
    return {"channel_id": channel_id, "description": body.description}


@router.delete("/channels/{channel_id}", status_code=200)
async def delete_channel(channel_id: str, _: AuthUser = Depends(require_site_admin)) -> dict[str, bool]:
    try:
        vector_store.delete_channel(channel_id)
        # Delete all chat sessions belonging to this channel
        await sessions_store.delete_channel_sessions(channel_id)
        await auth_store.delete_channel_settings(channel_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.put("/channels/{channel_id}")
async def update_channel_settings(
    channel_id: str, body: ChannelSettingsRequest, _: AuthUser = Depends(require_channel_manage)
) -> dict[str, Any]:
    await auth_store.set_channel_open(channel_id, body.is_open)
    return {"channel_id": channel_id, "is_open": body.is_open}


@router.get("/channels/{channel_id}/roles")
async def list_channel_roles(channel_id: str, _: AuthUser = Depends(require_channel_manage)) -> list[dict[str, Any]]:
    return await auth_store.list_channel_roles(channel_id)


@router.post("/channels/{channel_id}/managers", status_code=201)
async def add_manager(
    channel_id: str, body: RoleAssignmentRequest, _: AuthUser = Depends(require_site_admin)
) -> dict[str, bool]:
    await auth_store.set_channel_role(channel_id, body.user_id, "manager", body.name)
    return {"ok": True}


@router.delete("/channels/{channel_id}/managers/{user_id}", status_code=200)
async def remove_manager(channel_id: str, user_id: str, _: AuthUser = Depends(require_site_admin)) -> dict[str, bool]:
    await auth_store.remove_channel_role(channel_id, user_id)
    return {"ok": True}


@router.post("/channels/{channel_id}/writers", status_code=201)
async def add_writer(
    channel_id: str, body: RoleAssignmentRequest, _: AuthUser = Depends(require_channel_manage)
) -> dict[str, bool]:
    await auth_store.set_channel_role(channel_id, body.user_id, "writer", body.name)
    return {"ok": True}


@router.delete("/channels/{channel_id}/writers/{user_id}", status_code=200)
async def remove_writer(channel_id: str, user_id: str, _: AuthUser = Depends(require_channel_manage)) -> dict[str, bool]:
    await auth_store.remove_channel_role(channel_id, user_id)
    return {"ok": True}


@router.post("/channels/{channel_id}/viewers", status_code=201)
async def add_viewer(
    channel_id: str, body: RoleAssignmentRequest, _: AuthUser = Depends(require_channel_manage)
) -> dict[str, bool]:
    await auth_store.set_channel_role(channel_id, body.user_id, "viewer", body.name)
    return {"ok": True}


@router.delete("/channels/{channel_id}/viewers/{user_id}", status_code=200)
async def remove_viewer(channel_id: str, user_id: str, _: AuthUser = Depends(require_channel_manage)) -> dict[str, bool]:
    await auth_store.remove_channel_role(channel_id, user_id)
    return {"ok": True}


@router.get("/channels/{channel_id}/memories")
async def list_memories(channel_id: str, _: AuthUser = Depends(require_channel_write)) -> list[dict]:
    try:
        return vector_store.list_memories(channel_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/channels/{channel_id}/memories", status_code=200)
async def delete_memories(
    channel_id: str, body: BulkDeleteMemoriesRequest, _: AuthUser = Depends(require_channel_write)
) -> dict[str, int]:
    try:
        deleted = len([memory_id for memory_id in body.memory_ids if str(memory_id).strip()])
        if deleted == 0:
            return {"deleted": 0, "ok": True}
        vector_store.delete_memories(channel_id, body.memory_ids)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": deleted, "ok": True}


@router.delete("/channels/{channel_id}/memories/{memory_id}", status_code=200)
async def delete_memory(channel_id: str, memory_id: str, _: AuthUser = Depends(require_channel_write)) -> dict[str, bool]:
    try:
        vector_store.delete_memory(channel_id, memory_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.put("/channels/{channel_id}/memories/{memory_id}")
async def update_memory(
    channel_id: str, memory_id: str, body: UpdateMemoryRequest, _: AuthUser = Depends(require_channel_write)
) -> dict[str, bool]:
    try:
        vector_store.update_memory(channel_id, memory_id, body.content)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/channels/{channel_id}/memories/import", status_code=200)
async def import_memories_endpoint(
    channel_id: str, body: ImportMemoriesRequest, _: AuthUser = Depends(require_channel_write)
) -> dict[str, int]:
    try:
        result = vector_store.import_memories(channel_id, body.memories)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result


# ---------------------------------------------------------------------------
# Session endpoints
# ---------------------------------------------------------------------------


@router.get("/sessions")
async def list_sessions(channel_id: str, user: AuthUser = Depends(get_current_user)) -> list[dict[str, Any]]:
    await require_channel_view(channel_id, user)
    return await sessions_store.list_sessions(channel_id)


@router.post("/sessions", status_code=201)
async def create_session(body: dict[str, str], user: AuthUser = Depends(get_current_user)) -> dict[str, Any]:
    channel_id = body.get("channel_id", "").strip()
    if not channel_id:
        raise HTTPException(status_code=400, detail="channel_id is required.")
    await require_channel_view(channel_id, user)
    return await sessions_store.create_session(channel_id)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user: AuthUser = Depends(get_current_user)) -> dict[str, Any]:
    session = await sessions_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    await require_channel_view(session["channel_id"], user)
    return session


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, user: AuthUser = Depends(get_current_user)) -> None:
    session = await sessions_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    await require_channel_view(session["channel_id"], user)
    deleted = await sessions_store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found.")


@router.put("/sessions/{session_id}/title")
async def rename_session(session_id: str, body: dict[str, str], user: AuthUser = Depends(get_current_user)) -> dict[str, str]:
    title = body.get("title", "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required.")
    session = await sessions_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    await require_channel_view(session["channel_id"], user)
    await sessions_store.update_title(session_id, title)
    return {"session_id": session_id, "title": title}


# ---------------------------------------------------------------------------
# Title generation helper
# ---------------------------------------------------------------------------


async def _generate_title(message: str) -> str:
    response = router_llm.generate_response(
        messages=[
            SystemMessage(content=TITLE_PROMPT),
            HumanMessage(content=message),
        ]
    )
    return response.strip()


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, user: AuthUser = Depends(get_current_user)) -> ChatResponse:
    if not body.channel_id:
        raise HTTPException(status_code=400, detail="Please specify channel_id in your request.")
    await require_channel_view(body.channel_id, user)

    # Resolve or create session
    session_id = body.session_id
    if not session_id:
        session = await sessions_store.create_session(body.channel_id)
        session_id = session["id"]

    # Load prior messages to build context
    prior_messages = await sessions_store.get_messages(session_id) if session_id else []
    context_messages = [body.message]

    state: dict = {
        "messages": context_messages,
        "channel_id": body.channel_id,
        "intents": [],
        "report_segment": None,
        "question_segment": None,
        "extracted_chunks": None,
        "retrieved_docs": None,
        "store_response": None,
        "answer_response": None,
        "response": None,
    }

    router_result = await router_node_async(state)
    state.update(router_result)

    if state.get("decision") == "save_memory":
        role = await get_effective_role(body.channel_id, user)
        if role not in _WRITE_ROLES:
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

    agent_response: str = state.get("response", "")

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

async def _stream_chat_response(
    frozen_state: dict,
    frozen_session_id: str,
    gen_start: float,
    user_message: str,
    persist_user_message: bool,
    is_first_turn: bool,
):
    """Stream tokens for an already-routed agent state, then persist and report metrics."""
    full_response_parts: list[str] = []
    first_chunk_at: float | None = None
    last_chunk_at: float | None = None

    yield f"data: {json.dumps({'type': 'session', 'session_id': frozen_session_id})}\n\n"

    # Emit store response (progress report ack) immediately if present
    store_resp: str | None = frozen_state.get("store_response")
    if store_resp:
        now = time.perf_counter()
        first_chunk_at = now
        last_chunk_at = now
        full_response_parts.append(store_resp)
        yield f"data: {json.dumps({'type': 'token', 'content': store_resp})}\n\n"

    # Stream the answer if the router decided to answer a question
    if frozen_state.get("decision") == "answer_question":
        if store_resp:
            sep = "\n\n"
            full_response_parts.append(sep)
            yield f"data: {json.dumps({'type': 'token', 'content': sep})}\n\n"

        async for chunk in answer_node_astream(frozen_state):
            now = time.perf_counter()
            if first_chunk_at is None:
                first_chunk_at = now
            last_chunk_at = now
            full_response_parts.append(chunk)
            yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

    # Always report timing metrics for whatever content was produced above
    ttfw = round(first_chunk_at - gen_start, 2) if first_chunk_at is not None else 0.0
    total = round((last_chunk_at or gen_start) - gen_start, 2)
    gen_duration = round((last_chunk_at - first_chunk_at), 2) if (last_chunk_at and first_chunk_at and last_chunk_at > first_chunk_at) else 0.01
    word_count = len("".join(full_response_parts).split())
    wps = round(word_count / gen_duration, 1) if gen_duration > 0 else 0.0

    yield f"data: {json.dumps({'type': 'metrics', 'ttfw': ttfw, 'wps': wps, 'total': total})}\n\n"

    full_response = "".join(full_response_parts) or "No response generated."

    # Persist messages
    if persist_user_message:
        await sessions_store.add_message(frozen_session_id, "user", user_message)
    await sessions_store.add_message(frozen_session_id, "assistant", full_response)

    # Generate title on first turn (best-effort)
    title_updated = False
    if is_first_turn:
        try:
            title_resp = await asyncio.to_thread(
                chat_llm.generate_response,
                messages=[SystemMessage(content=TITLE_PROMPT), HumanMessage(content=user_message)],
            )
            await sessions_store.update_title(frozen_session_id, title_resp.strip())
            title_updated = True
        except Exception:
            pass

    yield f"data: {json.dumps({'type': 'done', 'session_id': frozen_session_id, 'title_updated': title_updated})}\n\n"


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, user: AuthUser = Depends(get_current_user)) -> StreamingResponse:
    if not body.channel_id:
        raise HTTPException(status_code=400, detail="Please specify channel_id in your request.")
    await require_channel_view(body.channel_id, user)

    gen_start = time.perf_counter()  # start timing from user input, before any preprocessing

    # Resolve or create session
    session_id = body.session_id
    if not session_id:
        session = await sessions_store.create_session(body.channel_id)
        session_id = session["id"]

    prior_messages = await sessions_store.get_messages(session_id) if session_id else []
    context_messages = [body.message]

    state: dict = {
        "messages": context_messages,
        "channel_id": body.channel_id,
        "intents": [],
        "report_segment": None,
        "question_segment": None,
        "extracted_chunks": None,
        "retrieved_docs": None,
        "store_response": None,
        "answer_response": None,
        "response": None,
    }

    # Run preprocessing nodes asynchronously
    router_result = await router_node_async(state)
    state.update(router_result)

    if state.get("decision") == "save_memory":
        role = await get_effective_role(body.channel_id, user)
        if role not in _WRITE_ROLES:
            raise HTTPException(status_code=403, detail="Write access required to save progress reports.")

    extractor_result = await extractor_node_async(state)
    state.update(extractor_result)

    store_result = await store_node_async(state)
    state.update(store_result)

    retriever_result = await retriever_node_async(state)
    state.update(retriever_result)

    frozen_state = dict(state)
    frozen_session_id = session_id
    is_first_turn = not prior_messages
    user_message = body.message

    return StreamingResponse(
        _stream_chat_response(
            frozen_state,
            frozen_session_id,
            gen_start,
            user_message,
            persist_user_message=True,
            is_first_turn=is_first_turn,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/regenerate")
async def chat_regenerate(body: RegenerateRequest, user: AuthUser = Depends(get_current_user)) -> StreamingResponse:
    if not body.channel_id:
        raise HTTPException(status_code=400, detail="Please specify channel_id in your request.")
    await require_channel_view(body.channel_id, user)

    if not body.session_id:
        raise HTTPException(status_code=400, detail="session_id is required to regenerate a response.")

    gen_start = time.perf_counter()

    prior_messages = await sessions_store.get_messages(body.session_id)
    if len(prior_messages) < 2 or prior_messages[-1]["role"] != "assistant" or prior_messages[-2]["role"] != "user":
        raise HTTPException(status_code=400, detail="Nothing to regenerate for this session.")

    user_message: str = prior_messages[-2]["content"]

    # Discard the previous assistant reply; it will be replaced by the regenerated one
    await sessions_store.delete_last_message(body.session_id)

    state: dict = {
        "messages": [user_message],
        "channel_id": body.channel_id,
        "intents": [],
        "report_segment": None,
        "question_segment": None,
        "extracted_chunks": None,
        "retrieved_docs": None,
        "store_response": None,
        "answer_response": None,
        "response": None,
    }

    router_result = await router_node_async(state)
    state.update(router_result)

    if state.get("decision") == "save_memory":
        role = await get_effective_role(body.channel_id, user)
        if role not in _WRITE_ROLES:
            raise HTTPException(status_code=403, detail="Write access required to save progress reports.")

    extractor_result = await extractor_node_async(state)
    state.update(extractor_result)

    store_result = await store_node_async(state)
    state.update(store_result)

    retriever_result = await retriever_node_async(state)
    state.update(retriever_result)

    frozen_state = dict(state)
    frozen_session_id = body.session_id

    return StreamingResponse(
        _stream_chat_response(
            frozen_state,
            frozen_session_id,
            gen_start,
            user_message,
            persist_user_message=False,
            is_first_turn=False,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/channels/{channel_id}/import/json")
async def import_embedded_json(
    channel_id: str,
    file: UploadFile = File(...),
    _: AuthUser = Depends(require_channel_write),
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

    result = vector_store.import_chunks(channel_id=channel_id, chunks=chunks)
    return result


@router.post("/channels/{channel_id}/import/documents")
async def import_documents(
    channel_id: str,
    files: list[UploadFile] = File(...),
    _: AuthUser = Depends(require_channel_write),
) -> dict[str, Any]:
    """Upload multiple documents for indexing and save to channel memory."""
    indexer_client = IndexerClient()

    imported_count = 0
    skipped_count = 0
    failed_files = []

    import tempfile
    import os

    # Document processing extensions
    _DOCLING_EXTENSIONS = {'.pdf', '.docx', '.doc', '.odt', '.rtf', '.html', '.htm'}
    _EXCEL_EXTENSIONS = {'.xlsx', '.xls'}
    _CSV_EXTENSIONS = {'.csv'}
    _PPTX_EXTENSIONS = {'.pptx', '.ppt'}
    _JSON_EXTENSIONS = {'.json'}
    _IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp'}
    _PASSTHROUGH_EXTENSIONS = {'.md', '.txt'}

    _SUPPORTED_EXTENSIONS = (
        _DOCLING_EXTENSIONS | _EXCEL_EXTENSIONS | _CSV_EXTENSIONS |
        _PPTX_EXTENSIONS | _JSON_EXTENSIONS | _IMAGE_EXTENSIONS | _PASSTHROUGH_EXTENSIONS
    )

    for file in files:
        if not file.filename:
            continue

        # Check file extension
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in _SUPPORTED_EXTENSIONS:
            failed_files.append({"file": file.filename, "error": f"Unsupported file type: {file_ext}"})
            continue

        # Create a temporary file to store the uploaded document
        # Use the full filename to preserve folder structure and avoid collisions
        # For webkitdirectory uploads, file.filename contains the relative path
        safe_filename = re.sub(r'[^\w\-_\. ]', '_', file.filename)
        tmp_file_path = os.path.join(tempfile.gettempdir(), safe_filename)

        # Ensure the directory structure exists in temp dir
        tmp_dir = os.path.dirname(tmp_file_path)
        if tmp_dir and tmp_dir != tempfile.gettempdir() and not os.path.exists(tmp_dir):
            os.makedirs(tmp_dir, exist_ok=True)

        # Remove if exists to ensure a clean write
        if os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)

        with open(tmp_file_path, 'wb') as tmp_file:
            content = await file.read()
            tmp_file.write(content)

        try:
            # Process document through indexer
            chunks_data = indexer_client.process_document(tmp_file_path)

            # Import chunks to the vector store
            if "chunks" in chunks_data and isinstance(chunks_data["chunks"], list):
                result = vector_store.import_chunks(channel_id=channel_id, chunks=chunks_data["chunks"])
                imported_count += result.get("imported", 0)
                skipped_count += result.get("skipped", 0)
            else:
                raise Exception("No chunks found in indexer response")

        except Exception as e:
            failed_files.append({"file": file.filename, "error": str(e)})
        finally:
            # Clean up temporary file
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)

    indexer_client.close()

    return {
        "imported": imported_count,
        "skipped": skipped_count,
        "failed_files": failed_files,
    }
