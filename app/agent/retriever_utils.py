from typing import Any

from app.agent.nodes import reranker, DEBUG_RETRIEVER, RERANK_TOP_N
from app.memory.store import BM25Index, vector_store


def reciprocal_rank_fusion(
    vector_docs: list[dict[str, Any]],
    bm25_docs: list[dict[str, Any]],
    k: int = 60,
) -> list[dict[str, Any]]:
    """Merge vector-search and BM25 doc lists via Reciprocal Rank Fusion, keyed by doc id."""
    rrf_scores: dict[str, float] = {}
    id_to_doc: dict[str, dict[str, Any]] = {}

    def _add_ranks(docs: list[dict[str, Any]]) -> None:
        for rank, doc in enumerate(docs, start=1):
            doc_id = doc.get("id")
            if doc_id is None:
                continue
            id_to_doc[doc_id] = doc
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank)

    _add_ranks(vector_docs)
    _add_ranks(bm25_docs)

    sorted_ids = sorted(rrf_scores, key=lambda doc_id: rrf_scores[doc_id], reverse=True)
    return [id_to_doc[doc_id] for doc_id in sorted_ids]


def retrieve_hybrid(
    channel_id: str,
    query: str,
    top_k: int,
    fetch_k: int | None = None,
    rrf_k: int = 60,
    bm25_index: BM25Index | None = None,
) -> list[dict[str, Any]]:
    """Hybrid retrieval: dense vector search + BM25 keyword search fused via RRF.

    Drop-in alternative to ``vector_store.search_memory`` that widens recall with
    keyword matches before downstream reranking narrows the result set back down.

    Parameters
    ----------
    channel_id:
        Channel/table to search.
    query:
        Natural-language query string.
    top_k:
        Number of docs returned after fusion.
    fetch_k:
        Number of candidates each search (vector and BM25) retrieves before fusion.
        Defaults to ``top_k`` when omitted.
    rrf_k:
        RRF smoothing constant (default 60).
    bm25_index:
        Pre-built :class:`BM25Index` (e.g. from ``vector_store.build_bm25_index``).
        Pass a cached instance to avoid rebuilding it on every call.
    """
    fetch_k = fetch_k or top_k
    vector_hits = vector_store.search_memory(channel_id, query, n_results=fetch_k, sort_by_date=False)
    bm25_hits = vector_store.search_memory_bm25(channel_id, query, n_results=fetch_k, bm25_index=bm25_index)
    fused = reciprocal_rank_fusion(vector_hits, bm25_hits, k=rrf_k)
    return fused[:top_k]


def _rerank_docs(query: str, docs: list[dict[str, Any]], top_n: int = RERANK_TOP_N) -> list[dict[str, Any]]:
    """Rerank retrieved docs by relevance to the query, falling back to the original top-n if unconfigured/unavailable."""
    if not docs:
        return docs
    if not (reranker.model_name and reranker.base_url and reranker.api_key):
        return docs[:top_n]

    try:
        results = reranker.rerank(query, [doc.get("content", "") for doc in docs], top_n=top_n)
    except Exception as exc:
        if DEBUG_RETRIEVER:
            print(f"Reranker failed, falling back to original order: {exc}")
        return docs[:top_n]

    reranked: list[dict[str, Any]] = []
    for result in sorted(results, key=lambda x: x["relevance_score"], reverse=True):
        doc = docs[result["index"]]
        metadata = {**doc.get("metadata", {}), "relevance_score": result["relevance_score"]}
        reranked.append({**doc, "metadata": metadata})
    return reranked
