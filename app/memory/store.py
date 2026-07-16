from __future__ import annotations

import uuid
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_ollama import OllamaEmbeddings

from app.core.config import settings

_embedding_fn = OllamaEmbeddings(
    base_url=settings.OLLAMA_CHAT_URL,
    model=settings.EMBEDDING_MODEL,
    client_kwargs={"headers": {"Authorization": f"Bearer {settings.OLLAMA_BEARER}"}},
)


def _embed(texts: list[str]) -> list[list[float]]:
    return _embedding_fn.embed_documents(texts)


class _OllamaEmbeddingFunction(chromadb.EmbeddingFunction):
    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return _embed(input)


_chroma_ef = _OllamaEmbeddingFunction()


class ChromaStore:
    def __init__(self) -> None:
        self._client = chromadb.PersistentClient(
            path=settings.CHROMA_PERSIST_PATH,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

    def get_or_create_collection(self, channel_id: str) -> chromadb.Collection:
        return self._client.get_or_create_collection(
            name=channel_id,
            embedding_function=_chroma_ef,
            metadata={"hnsw:space": "cosine"},
        )

    def add_memory(
        self,
        channel_id: str,
        content: str,
        metadata: dict[str, Any],
    ) -> None:
        """Upsert a single document. metadata MUST contain 'date' (YYYY-MM-DD) and 'type'."""
        collection = self.get_or_create_collection(channel_id)
        doc_id = str(uuid.uuid4())
        collection.upsert(
            ids=[doc_id],
            documents=[content],
            metadatas=[metadata],
        )

    def search_memory(
        self,
        channel_id: str,
        query: str,
        n_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Return relevant docs sorted by metadata['date'] descending (newest first)."""
        collection = self.get_or_create_collection(channel_id)
        count = collection.count()
        if count == 0:
            return []
        actual_n = min(n_results, count)
        results = collection.query(
            query_texts=[query],
            n_results=actual_n,
            include=["documents", "metadatas", "distances"],
        )
        docs: list[dict[str, Any]] = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            docs.append({"content": doc, "metadata": meta, "distance": dist})
        docs.sort(key=lambda d: d["metadata"].get("date", "1970-01-01"), reverse=True)
        return docs

    def list_channels(self) -> list[str]:
        return [col.name for col in self._client.list_collections()]

    def delete_channel(self, channel_id: str) -> None:
        """Delete a channel collection entirely from ChromaDB."""
        self._client.delete_collection(name=channel_id)

    def import_chunks(
        self,
        channel_id: str,
        chunks: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Bulk upsert from pre-embedded JSON chunks. Returns {imported, skipped}."""
        collection = self.get_or_create_collection(channel_id)
        existing_ids: set[str] = set(collection.get(include=[])["ids"])

        to_add_ids: list[str] = []
        to_add_docs: list[str] = []
        to_add_metas: list[dict[str, Any]] = []
        skipped = 0

        for chunk in chunks:
            chunk_id: str = str(chunk["chunk_id"])
            if chunk_id in existing_ids:
                skipped += 1
                continue
            to_add_ids.append(chunk_id)
            to_add_docs.append(chunk["chunk_text_embedded"])
            to_add_metas.append(
                {
                    "date": "1970-01-01",
                    "type": "reference_doc",
                    "source": chunk.get("source", ""),
                    "section": chunk.get("section", ""),
                }
            )

        if to_add_ids:
            # Upsert in batches of 100 to avoid oversized requests
            batch_size = 100
            for i in range(0, len(to_add_ids), batch_size):
                collection.upsert(
                    ids=to_add_ids[i : i + batch_size],
                    documents=to_add_docs[i : i + batch_size],
                    metadatas=to_add_metas[i : i + batch_size],
                )

        return {"imported": len(to_add_ids), "skipped": skipped}

    def list_memories(self, channel_id: str) -> list[dict[str, Any]]:
        """Return all documents for a channel as preview dicts, sorted by date descending."""
        try:
            collection = self._client.get_collection(name=channel_id)
        except Exception as exc:
            raise ValueError(f"Channel '{channel_id}' not found.") from exc
        result = collection.get(include=["documents", "metadatas"])
        items: list[dict[str, Any]] = []
        for doc_id, doc, meta in zip(result["ids"], result["documents"], result["metadatas"]):
            meta = meta or {}
            items.append({
                "id": doc_id,
                "content": doc or "",
                "preview": (doc or "")[:150],
                "date": meta.get("date", ""),
                "type": meta.get("type", ""),
                "source": meta.get("source", ""),
                "section": meta.get("section", ""),
            })
        items.sort(key=lambda x: x["date"], reverse=True)
        return items

    def delete_memory(self, channel_id: str, memory_id: str) -> bool:
        """Delete a single document from the channel collection."""
        try:
            collection = self._client.get_collection(name=channel_id)
        except Exception as exc:
            raise ValueError(f"Channel '{channel_id}' not found.") from exc
        collection.delete(ids=[memory_id])
        return True

    def update_memory(self, channel_id: str, memory_id: str, content: str) -> bool:
        """Update the text content of a single document (re-embeds new content)."""
        try:
            collection = self._client.get_collection(name=channel_id)
        except Exception as exc:
            raise ValueError(f"Channel '{channel_id}' not found.") from exc
        result = collection.get(ids=[memory_id], include=["metadatas"])
        if not result["ids"]:
            raise ValueError(f"Memory '{memory_id}' not found.")
        meta = result["metadatas"][0] or {}
        collection.update(
            ids=[memory_id],
            documents=[content],
            metadatas=[meta],
        )
        return True

    def import_memories(
        self,
        channel_id: str,
        memories: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Import memories from browser export format. Returns {imported, skipped}."""
        collection = self.get_or_create_collection(channel_id)
        existing_ids: set[str] = set(collection.get(include=[])["ids"])

        to_add_ids: list[str] = []
        to_add_docs: list[str] = []
        to_add_metas: list[dict[str, Any]] = []
        skipped = 0

        for mem in memories:
            mem_id: str = str(mem.get("id", str(uuid.uuid4())))
            if mem_id in existing_ids:
                skipped += 1
                continue
            to_add_ids.append(mem_id)
            to_add_docs.append(mem.get("content", ""))
            to_add_metas.append({
                "date": mem.get("date", "1970-01-01"),
                "type": mem.get("type", "raw"),
                "source": mem.get("source", ""),
                "section": mem.get("section", ""),
            })

        if to_add_ids:
            batch_size = 100
            for i in range(0, len(to_add_ids), batch_size):
                collection.upsert(
                    ids=to_add_ids[i : i + batch_size],
                    documents=to_add_docs[i : i + batch_size],
                    metadatas=to_add_metas[i : i + batch_size],
                )

        return {"imported": len(to_add_ids), "skipped": skipped}


# Module-level singleton
chroma_store = ChromaStore()
