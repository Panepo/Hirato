from typing import Any

from app.memory.store import BM25Index, _strip_embedding_boilerplate, vector_store
from app.agent.node_config import (
    VECTOR_SEARCH_TOP_K, BM25_SEARCH_TOP_K, RRF_TOP_K, RERANKER_TOP_K,
    RERANKER_SCORE_WEIGHT, BM25_SCORE_WEIGHT,
    DEBUG_RETRIEVER, reranker,
)


def reciprocal_rank_fusion(
    vector_docs: list[dict[str, Any]],
    bm25_docs: list[dict[str, Any]],
    top_k: int = RRF_TOP_K,
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
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (top_k + rank)

    _add_ranks(vector_docs)
    _add_ranks(bm25_docs)

    sorted_ids = sorted(rrf_scores, key=lambda doc_id: rrf_scores[doc_id], reverse=True)
    return [id_to_doc[doc_id] for doc_id in sorted_ids]

def _min_max_normalize(values: list[float]) -> list[float]:
    """Scale values to [0, 1] so scores from different rankers (unbounded BM25 vs. 0-1 reranker) are comparable."""
    if not values:
        return values
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [1.0] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def _blend_scores(
    query: str,
    docs: list[dict[str, Any]],
    bm25_index: BM25Index,
    reranker_weight: float = RERANKER_SCORE_WEIGHT,
    bm25_weight: float = BM25_SCORE_WEIGHT,
) -> list[dict[str, Any]]:
    """Blend reranker relevance with BM25 keyword score: Final_Score = reranker_weight*ScoreReranker + bm25_weight*ScoreBM25.

    Both scores are min-max normalized across the candidate set before blending, since raw
    BM25 scores are unbounded while the cross-encoder reranker score is already ~[0, 1].
    """
    if not docs:
        return docs

    ids = [doc.get("id") for doc in docs if doc.get("id") is not None]
    bm25_scores = bm25_index.scores_for_ids(query, ids)

    raw_rerank = [doc.get("metadata", {}).get("relevance_score", 0.0) for doc in docs]
    raw_bm25 = [bm25_scores.get(doc.get("id"), 0.0) for doc in docs]
    norm_rerank = _min_max_normalize(raw_rerank)
    norm_bm25 = _min_max_normalize(raw_bm25)

    blended: list[dict[str, Any]] = []
    for doc, rerank_score, bm25_score in zip(docs, norm_rerank, norm_bm25):
        final_score = reranker_weight * rerank_score + bm25_weight * bm25_score
        metadata = {**doc.get("metadata", {}), "bm25_score": bm25_scores.get(doc.get("id"), 0.0), "final_score": final_score}
        blended.append({**doc, "metadata": metadata})

    blended.sort(key=lambda d: d["metadata"]["final_score"], reverse=True)
    return blended


def _rerank_docs(
    query: str,
    docs: list[dict[str, Any]],
    top_k: int = RERANKER_TOP_K,
    bm25_index: BM25Index | None = None,
) -> list[dict[str, Any]]:
    """Rerank retrieved docs by relevance to the query, falling back to the original top-n if unconfigured/unavailable.

    When ``bm25_index`` is provided, the reranked results are re-scored via score blending
    (``_blend_scores``) so keyword relevance still has a say in the final ordering/top_k cut.
    """
    if not docs:
        return docs
    if not (reranker.model_name and reranker.base_url and reranker.api_key):
        return docs[:top_k]

    try:
        # Strip the "[Document: X | Section: Y]" header so it doesn't dilute the cross-encoder's relevance signal.
        doc_texts = [_strip_embedding_boilerplate(doc.get("content", "")) for doc in docs]
        results = reranker.rerank(query, doc_texts, top_n=len(docs))
    except Exception as exc:
        if DEBUG_RETRIEVER:
            print(f"Reranker failed, falling back to original order: {exc}")
        return docs[:top_k]

    reranked: list[dict[str, Any]] = []
    for result in sorted(results, key=lambda x: x["relevance_score"], reverse=True):
        doc = docs[result["index"]]
        metadata = {**doc.get("metadata", {}), "relevance_score": result["relevance_score"]}
        reranked.append({**doc, "metadata": metadata})

    if bm25_index is not None:
        reranked = _blend_scores(query, reranked, bm25_index)

    return reranked[:top_k]


def retrieve_hybrid(
    channel_id: str,
    query: str,
    bm25_index: BM25Index | None = None,
    vector_top_k: int = VECTOR_SEARCH_TOP_K,
    bm25_top_k: int = BM25_SEARCH_TOP_K,
    rrf_top_k: int = RRF_TOP_K,
    final_top_k: int = RERANKER_TOP_K,
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
    vector_top_k:
        Number of docs returned from the vector search.
    bm25_top_k:
        Number of docs returned from the BM25 search.
    rrf_top_k:
        RRF smoothing constant (default 30).
    bm25_index:
        Pre-built :class:`BM25Index` (e.g. from ``vector_store.build_bm25_index``).
        Pass a cached instance to avoid rebuilding it on every call.
    """
    vector_hits = vector_store.search_memory(channel_id, query, n_results=vector_top_k, sort_by_date=False)
    bm25_hits = vector_store.search_memory_bm25(channel_id, query, n_results=bm25_top_k, bm25_index=bm25_index)
    fused = reciprocal_rank_fusion(vector_hits, bm25_hits, top_k=rrf_top_k)

    return fused[:final_top_k]


