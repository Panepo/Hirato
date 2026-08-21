"""LanceDB-backed memory store: one table per channel_id, holding both chat
memories (progress reports/summaries) and imported reference-doc chunks.

Structured after the ingest.py / retriever.py reference pair: module-level
helpers build the schema and rows (`_build_schema`, `_build_rows`) and open
tables (`_open_or_create_table`, `_require_table`), while `LanceStore` stays a
thin class wrapping them for saving (`add_memory`, `import_chunks`,
`import_memories`) and retrieving (`search_memory`, `list_memories`).
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

import lancedb
import pyarrow as pa
from rank_bm25 import BM25Okapi

from app.core.config import settings
from app.core.embedding import EmbeddingInference

_embedding_inference = EmbeddingInference()

_METADATA_FIELDS = ["date", "type", "source", "section", "title"]

# Indexer prepends this to every chunk of a document (e.g. "[Document: X | Section: Y]").
# Embedding it verbatim repeats the document/model name across hundreds of unrelated
# chunks and skews similarity scores toward that boilerplate instead of real content.
_DOC_HEADER_RE = re.compile(r"^\[Document:[^\]]*\]\s*\n*", re.IGNORECASE)


def _embed(texts: list[str]) -> list[list[float]]:
    return _embedding_inference.embed_documents(texts)


def _strip_embedding_boilerplate(text: str) -> str:
    """Remove the leading '[Document: ... | Section: ...]' header before embedding."""
    stripped = _DOC_HEADER_RE.sub("", text, count=1).strip()
    return stripped or text


def _quote(value: str) -> str:
    """Escape a string for safe use inside a LanceDB SQL filter literal."""
    return value.replace("'", "''")


def _ids_filter(ids: list[str]) -> str:
    return "id IN (" + ", ".join(f"'{_quote(i)}'" for i in ids) + ")"


def _normalize_tags(tags: Any) -> list[str]:
    if isinstance(tags, str):
        try:
            parsed = json.loads(tags)
            tags = parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            tags = [part.strip() for part in tags.split(',') if part.strip()]
    elif not isinstance(tags, list):
        tags = [tags] if tags is not None else []

    return [str(tag).strip() for tag in tags if str(tag).strip()][:5]


def _normalize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    metadata = metadata or {}
    row: dict[str, Any] = {key: str(metadata.get(key) or "") for key in _METADATA_FIELDS}
    row["tags"] = json.dumps(_normalize_tags(metadata.get("tags", [])), ensure_ascii=False)
    return row


def _row_to_doc(row: dict[str, Any]) -> dict[str, Any]:
    metadata = {key: row.get(key, "") for key in _METADATA_FIELDS}
    metadata["tags"] = row.get("tags", "[]")
    return {"id": row.get("id"), "content": row.get("document", ""), "metadata": metadata, "distance": row.get("_distance")}


def _tokenize(text: str) -> list[str]:
    """Lowercase whitespace tokenisation (fast, language-agnostic) for BM25."""
    return text.lower().split()


class BM25Index:
    """Keyword (BM25) index over a channel's rows.

    Build once per channel with :meth:`from_rows` (or ``LanceStore.build_bm25_index``)
    and reuse across queries to avoid re-tokenising the whole table every call.
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        tokenized = [_tokenize(row.get("document", "")) for row in rows]
        self._bm25 = BM25Okapi(tokenized) if tokenized else None

    @staticmethod
    def from_rows(rows: list[dict[str, Any]]) -> "BM25Index":
        return BM25Index(rows)

    def search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        """Return the top_k highest-scoring rows for query as doc dicts."""
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(_tokenize(query))
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        return [_row_to_doc(self._rows[i]) for i in top_indices]


# ---------------------------------------------------------------------------
# Schema + table helpers
# ---------------------------------------------------------------------------


def _build_schema(embedding_dim: int) -> pa.Schema:
    """Per-channel table schema shared by chat memories and imported reference chunks."""
    return pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), embedding_dim)),
            pa.field("document", pa.string()),
            *(pa.field(key, pa.string()) for key in _METADATA_FIELDS),
            pa.field("tags", pa.string()),
        ]
    )


def _open_or_create_table(db: lancedb.DBConnection, name: str, schema: pa.Schema) -> lancedb.table.Table:
    try:
        return db.open_table(name)
    except ValueError:
        return db.create_table(name, schema=schema)


def _require_table(db: lancedb.DBConnection, name: str) -> lancedb.table.Table:
    """Open a channel table that must already exist, or raise ValueError."""
    try:
        return db.open_table(name)
    except ValueError as exc:
        raise ValueError(f"Channel '{name}' not found.") from exc


def _build_rows(
    ids: list[str],
    vectors: list[list[float]],
    texts: list[str],
    metas: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [{"id": i, "vector": v, "document": t, **m} for i, v, t, m in zip(ids, vectors, texts, metas)]


class LanceStore:
    def __init__(self) -> None:
        self._client = lancedb.connect(settings.LANCEDB_PERSIST_PATH)
        self._dim: int | None = None

    def _embedding_dim(self) -> int:
        if self._dim is None:
            self._dim = settings.EMBEDDING_DIMENSION or len(_embed(["_dimension_probe_"])[0])
        return self._dim

    def get_or_create_collection(self, channel_id: str) -> lancedb.table.Table:
        return _open_or_create_table(self._client, channel_id, _build_schema(self._embedding_dim()))

    def _add_rows(
        self,
        collection: lancedb.table.Table,
        ids: list[str],
        texts: list[str],
        metas: list[dict[str, Any]],
        embed_texts: list[str] | None = None,
    ) -> None:
        if not ids:
            return
        vectors = _embed(embed_texts if embed_texts is not None else texts)
        rows = _build_rows(ids, vectors, texts, metas)
        batch_size = 100
        for i in range(0, len(rows), batch_size):
            collection.add(rows[i : i + batch_size])

    def _existing_ids(self, collection: lancedb.table.Table) -> set[str]:
        return {row["id"] for row in collection.search().select(["id"]).to_list()}

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------

    def add_memory(
        self,
        channel_id: str,
        content: str,
        metadata: dict[str, Any],
    ) -> None:
        """Insert a single document. metadata MUST contain 'date' (YYYY-MM-DD) and 'type'."""
        collection = self.get_or_create_collection(channel_id)
        doc_id = str(uuid.uuid4())
        vector = _embed([content])[0]
        row = {"id": doc_id, "vector": vector, "document": content, **_normalize_metadata(metadata)}
        collection.add([row])

    def import_chunks(
        self,
        channel_id: str,
        chunks: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Bulk insert from pre-embedded JSON chunks. Returns {imported, skipped}."""
        collection = self.get_or_create_collection(channel_id)
        existing_ids = self._existing_ids(collection)

        ids: list[str] = []
        texts: list[str] = []
        embed_texts: list[str] = []
        metas: list[dict[str, Any]] = []
        skipped = 0

        for chunk in chunks:
            chunk_id: str = str(chunk["chunk_id"])
            if chunk_id in existing_ids:
                skipped += 1
                continue
            chunk_text: str = chunk["chunk_text_embedded"]
            ids.append(chunk_id)
            texts.append(chunk_text)
            embed_texts.append(_strip_embedding_boilerplate(chunk_text))
            metas.append(
                {
                    "date": "1970-01-01",
                    "type": "reference_doc",
                    "source": chunk.get("source", "reference_doc"),
                    "section": chunk.get("section_title", ""),
                    "title": chunk.get("chunk_title", "Reference document"),
                    "tags": json.dumps(_normalize_tags(chunk.get("chunk_tags", ["reference_doc"])), ensure_ascii=False),
                }
            )

        self._add_rows(collection, ids, texts, metas, embed_texts=embed_texts)
        return {"imported": len(ids), "skipped": skipped}

    def import_memories(
        self,
        channel_id: str,
        memories: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Import memories from browser export format. Returns {imported, skipped}."""
        collection = self.get_or_create_collection(channel_id)
        existing_ids = self._existing_ids(collection)

        ids: list[str] = []
        texts: list[str] = []
        metas: list[dict[str, Any]] = []
        skipped = 0

        for mem in memories:
            mem_id: str = str(mem.get("id", str(uuid.uuid4())))
            if mem_id in existing_ids:
                skipped += 1
                continue
            ids.append(mem_id)
            texts.append(mem.get("content", ""))
            metas.append(
                {
                    "date": mem.get("date", "1970-01-01"),
                    "type": mem.get("type", "raw"),
                    "source": mem.get("source", mem.get("type", "raw")),
                    "section": mem.get("section", ""),
                    "title": mem.get("title", ""),
                    "tags": json.dumps(_normalize_tags(mem.get("tags", [])), ensure_ascii=False),
                }
            )

        self._add_rows(collection, ids, texts, metas)
        return {"imported": len(ids), "skipped": skipped}

    def resync_embeddings(self, channel_id: str) -> int:
        """Recompute vectors for existing rows using de-boilerplated text. Returns rows updated."""
        collection = _require_table(self._client, channel_id)
        rows = collection.search().to_list()
        if not rows:
            return 0

        ids = [row["id"] for row in rows]
        texts = [row.get("document", "") for row in rows]
        embed_texts = [_strip_embedding_boilerplate(t) for t in texts]
        metas: list[dict[str, Any]] = []
        for row in rows:
            meta = {key: row.get(key, "") for key in _METADATA_FIELDS}
            meta["tags"] = row.get("tags", "[]")
            metas.append(meta)

        collection.delete(_ids_filter(ids))
        self._add_rows(collection, ids, texts, metas, embed_texts=embed_texts)
        return len(ids)

    def update_memory(self, channel_id: str, memory_id: str, content: str) -> bool:
        """Update the text content of a single document (re-embeds new content)."""
        collection = _require_table(self._client, channel_id)
        existing = collection.search().where(_ids_filter([memory_id])).to_list()
        if not existing:
            raise ValueError(f"Memory '{memory_id}' not found.")
        vector = _embed([content])[0]
        collection.update(where=_ids_filter([memory_id]), values={"document": content, "vector": vector})
        return True

    # ------------------------------------------------------------------
    # Retrieving
    # ------------------------------------------------------------------

    def search_memory(
        self,
        channel_id: str,
        query: str,
        n_results: int = 5,
        sort_by_date: bool = True,
    ) -> list[dict[str, Any]]:
        """Return relevant docs; sorted by metadata['date'] descending unless sort_by_date=False keeps similarity order (needed before reranking)."""
        collection = self.get_or_create_collection(channel_id)
        count = collection.count_rows()
        if count == 0:
            return []
        query_vector = _embed([query])[0]
        rows = collection.search(query_vector).metric("cosine").limit(min(n_results, count)).to_list()
        docs = [_row_to_doc(row) for row in rows]
        if sort_by_date:
            docs.sort(key=lambda d: d["metadata"].get("date") or "1970-01-01", reverse=True)
        return docs

    def build_bm25_index(self, channel_id: str) -> BM25Index:
        """Build a keyword index over a channel's rows; reuse across queries via search_memory_bm25's bm25_index arg."""
        collection = self.get_or_create_collection(channel_id)
        rows = collection.search().to_list()
        return BM25Index(rows)

    def search_memory_bm25(
        self,
        channel_id: str,
        query: str,
        n_results: int = 5,
        bm25_index: BM25Index | None = None,
    ) -> list[dict[str, Any]]:
        """Keyword (BM25) search over a channel, complementing search_memory's dense vector search."""
        index = bm25_index or self.build_bm25_index(channel_id)
        return index.search(query, top_k=n_results)

    def list_memories(self, channel_id: str) -> list[dict[str, Any]]:
        """Return all documents for a channel as preview dicts, sorted by date descending."""
        collection = _require_table(self._client, channel_id)
        rows = collection.search().to_list()
        items: list[dict[str, Any]] = []
        for row in rows:
            content = row.get("document") or ""
            items.append(
                {
                    "id": row["id"],
                    "content": content,
                    "preview": content[:150],
                    "date": row.get("date", ""),
                    "type": row.get("type", ""),
                    "source": row.get("source") or row.get("type", ""),
                    "section": row.get("section", ""),
                    "title": row.get("title", ""),
                    "tags": _normalize_tags(row.get("tags", [])),
                }
            )
        items.sort(key=lambda x: x["date"], reverse=True)
        return items

    # ------------------------------------------------------------------
    # Channel / row management
    # ------------------------------------------------------------------

    def list_channels(self) -> list[str]:
        names: list[str] = []
        page_token: str | None = None
        while True:
            response = self._client.list_tables(page_token=page_token)
            names.extend(response.tables)
            page_token = response.page_token
            if not page_token:
                break
        return names

    def delete_channel(self, channel_id: str) -> None:
        """Delete a channel table entirely from LanceDB."""
        self._client.drop_table(channel_id)

    def delete_memories(self, channel_id: str, memory_ids: list[str]) -> bool:
        """Delete multiple documents from the channel table in batches."""
        if not memory_ids:
            return True
        collection = _require_table(self._client, channel_id)

        seen: set[str] = set()
        unique_ids: list[str] = []
        for memory_id in memory_ids:
            memory_id = str(memory_id).strip()
            if memory_id and memory_id not in seen:
                seen.add(memory_id)
                unique_ids.append(memory_id)
        if not unique_ids:
            return True

        batch_size = 100
        for i in range(0, len(unique_ids), batch_size):
            collection.delete(_ids_filter(unique_ids[i : i + batch_size]))
        return True

    def delete_memory(self, channel_id: str, memory_id: str) -> bool:
        """Delete a single document from the channel table."""
        return self.delete_memories(channel_id, [memory_id])


# Module-level singleton
vector_store = LanceStore()
