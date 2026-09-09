from __future__ import annotations

import json
import os
import re
import tempfile
from typing import Any

from app.core.indexer import IndexerClient
from app.memory.store import vector_store

_DOCLING_EXTENSIONS = {'.pdf', '.docx', '.doc', '.odt', '.rtf', '.html', '.htm'}
_EXCEL_EXTENSIONS = {'.xlsx', '.xls'}
_CSV_EXTENSIONS = {'.csv'}
_PPTX_EXTENSIONS = {'.pptx', '.ppt'}
_JSON_EXTENSIONS = {'.json'}
_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp'}
_PASSTHROUGH_EXTENSIONS = {'.md', '.txt'}

SUPPORTED_DOCUMENT_EXTENSIONS = (
    _DOCLING_EXTENSIONS | _EXCEL_EXTENSIONS | _CSV_EXTENSIONS |
    _PPTX_EXTENSIONS | _JSON_EXTENSIONS | _IMAGE_EXTENSIONS | _PASSTHROUGH_EXTENSIONS
)


def import_document_bytes(channel_id: str, filename: str, content: bytes) -> dict[str, int]:
    """Send one document's bytes through the indexer and import the resulting chunks.

    Raises ValueError for an unsupported extension, or the underlying exception if
    indexing/import fails — callers (REST route, MCP tool) decide how to report per-file failures.
    """
    file_ext = os.path.splitext(filename)[1].lower()
    if file_ext not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {file_ext}")

    # Use the full filename to preserve folder structure and avoid collisions
    # (webkitdirectory uploads put a relative path in filename).
    safe_filename = re.sub(r'[^\w\-_\. ]', '_', filename)
    tmp_file_path = os.path.join(tempfile.gettempdir(), safe_filename)

    tmp_dir = os.path.dirname(tmp_file_path)
    if tmp_dir and tmp_dir != tempfile.gettempdir() and not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir, exist_ok=True)

    if os.path.exists(tmp_file_path):
        os.remove(tmp_file_path)

    with open(tmp_file_path, 'wb') as tmp_file:
        tmp_file.write(content)

    indexer_client = IndexerClient()
    try:
        chunks_data = indexer_client.process_document(tmp_file_path)
        if "chunks" not in chunks_data or not isinstance(chunks_data["chunks"], list):
            raise Exception("No chunks found in indexer response")
        return vector_store.import_chunks(channel_id=channel_id, chunks=chunks_data["chunks"])
    finally:
        indexer_client.close()
        if os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)


def import_embedded_json_bytes(channel_id: str, content: bytes) -> dict[str, int]:
    """Parse+validate a pre-chunked JSON document and import its chunks. Raises ValueError on invalid input."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc

    if not isinstance(data, dict) or "chunks" not in data:
        raise ValueError("JSON must have a top-level 'chunks' array.")
    chunks = data["chunks"]
    if not isinstance(chunks, list):
        raise ValueError("'chunks' must be an array.")
    for i, chunk in enumerate(chunks):
        if "chunk_id" not in chunk or "chunk_text_embedded" not in chunk:
            raise ValueError(f"Chunk at index {i} is missing 'chunk_id' or 'chunk_text_embedded'.")

    return vector_store.import_chunks(channel_id=channel_id, chunks=chunks)
