from typing import Any

from app.agent.nodes import reranker, DEBUG_RETRIEVER, RERANK_TOP_N

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
