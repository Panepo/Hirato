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

    def get_or_create_collection(self, project_id: str) -> chromadb.Collection:
        return self._client.get_or_create_collection(
            name=project_id,
            embedding_function=_chroma_ef,
            metadata={"hnsw:space": "cosine"},
        )

    def add_memory(
        self,
        project_id: str,
        content: str,
        metadata: dict[str, Any],
    ) -> None:
        """Upsert a single document. metadata MUST contain 'date' (YYYY-MM-DD) and 'type'."""
        collection = self.get_or_create_collection(project_id)
        doc_id = str(uuid.uuid4())
        collection.upsert(
            ids=[doc_id],
            documents=[content],
            metadatas=[metadata],
        )

    def search_memory(
        self,
        project_id: str,
        query: str,
        n_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Return relevant docs sorted by metadata['date'] descending (newest first)."""
        collection = self.get_or_create_collection(project_id)
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

    def list_projects(self) -> list[str]:
        return [col.name for col in self._client.list_collections()]

    def delete_project(self, project_id: str) -> None:
        """Delete a project collection entirely from ChromaDB."""
        self._client.delete_collection(name=project_id)

    def import_chunks(
        self,
        project_id: str,
        chunks: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Bulk upsert from pre-embedded JSON chunks. Returns {imported, skipped}."""
        collection = self.get_or_create_collection(project_id)
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


# Module-level singleton
chroma_store = ChromaStore()
