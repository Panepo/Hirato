from __future__ import annotations

import json

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.agent.graph import secretary_graph
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


class ChatResponse(BaseModel):
    response: str


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


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    if not body.project_id:
        raise HTTPException(status_code=400, detail="project_id is required.")
    initial_state = {
        "messages": [body.message],
        "project_id": body.project_id,
        "intent": None,
        "extracted_summary": None,
        "retrieved_docs": None,
        "response": None,
    }
    final_state = await secretary_graph.ainvoke(initial_state)
    return ChatResponse(response=final_state.get("response", ""))


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
