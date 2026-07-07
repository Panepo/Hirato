from __future__ import annotations

from datetime import date, timezone, datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from app.agent.prompts import ANSWER_PROMPT, EXTRACTOR_PROMPT, ROUTER_PROMPT
from app.core.config import settings
from app.memory.store import chroma_store

# ---------------------------------------------------------------------------
# LLM clients
# ---------------------------------------------------------------------------

_chat_kwargs: dict[str, Any] = {
    "base_url": settings.OLLAMA_CHAT_URL,
    "model": settings.CHAT_MODEL,
    "client_kwargs": {"headers": {"Authorization": f"Bearer {settings.OLLAMA_BEARER}"}},
}
if settings.CHAT_MODEL_THINK:
    _chat_kwargs["think"] = True

chat_llm = ChatOllama(**_chat_kwargs)

router_llm = ChatOllama(
    base_url=settings.OLLAMA_CHAT_URL,
    model=settings.CHAT_MODEL_ROUTER,
    client_kwargs={"headers": {"Authorization": f"Bearer {settings.OLLAMA_BEARER}"}},
)


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------


def router_node(state: dict[str, Any]) -> dict[str, Any]:
    """Classify user message as 'progress_report' or 'question'."""
    user_message: str = state["messages"][-1]
    response = router_llm.invoke(
        [
            SystemMessage(content=ROUTER_PROMPT),
            HumanMessage(content=user_message),
        ]
    )
    raw = response.content.strip().lower()
    intent = "progress_report" if "progress_report" in raw else "question"
    return {"intent": intent}


def extractor_node(state: dict[str, Any]) -> dict[str, Any]:
    """Extract structured summary from weekly progress report."""
    user_message: str = state["messages"][-1]
    response = chat_llm.invoke(
        [
            SystemMessage(content=EXTRACTOR_PROMPT),
            HumanMessage(content=user_message),
        ]
    )
    return {"extracted_summary": response.content.strip()}


def store_node(state: dict[str, Any]) -> dict[str, Any]:
    """Persist raw message + extracted summary into ChromaDB."""
    project_id: str = state["project_id"]
    user_message: str = state["messages"][-1]
    today = date.today().isoformat()

    chroma_store.add_memory(
        project_id=project_id,
        content=user_message,
        metadata={"date": today, "type": "raw"},
    )
    chroma_store.add_memory(
        project_id=project_id,
        content=state.get("extracted_summary", ""),
        metadata={"date": today, "type": "summary"},
    )
    return {"response": "Your progress report has been saved successfully."}


def retriever_node(state: dict[str, Any]) -> dict[str, Any]:
    """Retrieve relevant documents from ChromaDB (already sorted newest-first)."""
    project_id: str = state["project_id"]
    query: str = state["messages"][-1]
    docs = chroma_store.search_memory(project_id=project_id, query=query, n_results=5)
    return {"retrieved_docs": docs}


def answer_node(state: dict[str, Any]) -> dict[str, Any]:
    """Generate an answer using retrieved context docs."""
    user_message: str = state["messages"][-1]
    docs: list[dict[str, Any]] = state.get("retrieved_docs", [])

    if not docs:
        context_text = "(No relevant memories found for this project.)"
    else:
        parts: list[str] = []
        for i, doc in enumerate(docs, start=1):
            meta = doc.get("metadata", {})
            doc_date = meta.get("date", "unknown")
            doc_type = meta.get("type", "unknown")
            parts.append(f"[{i}] ({doc_date}, {doc_type})\n{doc['content']}")
        context_text = "\n\n---\n\n".join(parts)

    system_content = ANSWER_PROMPT.format(context=context_text)
    response = chat_llm.invoke(
        [
            SystemMessage(content=system_content),
            HumanMessage(content=user_message),
        ]
    )
    return {"response": response.content.strip()}
