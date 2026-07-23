from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, AsyncGenerator

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from app.agent.prompts import ANSWER_PROMPT, EXTRACTOR_PROMPT, SPLITTER_PROMPT
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

# Fast model — router_node only, no thinking mode
router_llm = ChatOllama(
    base_url=settings.OLLAMA_CHAT_URL,
    model=settings.CHAT_MODEL_ROUTER,
    client_kwargs={"headers": {"Authorization": f"Bearer {settings.OLLAMA_BEARER}"}},
)


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------


def router_node(state: dict[str, Any]) -> dict[str, Any]:
    """Classify and segment the user message using router_llm."""
    user_message: str = state["messages"][-1]
    response = router_llm.invoke(
        [
            SystemMessage(content=SPLITTER_PROMPT),
            HumanMessage(content=user_message),
        ]
    )
    try:
        raw = response.content if isinstance(response.content, str) else ""
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        data = json.loads(raw)
        intents: list[str] = data.get("intents", [])
        report_segment: str | None = data.get("report_segment") or None
        question_segment: str | None = data.get("question_segment") or None
    except (json.JSONDecodeError, AttributeError):
        intents = []
        report_segment = None
        question_segment = None

    # Reconcile: remove an intent when its segment is missing
    if "progress_report" in intents and not report_segment:
        intents = [i for i in intents if i != "progress_report"]
    if "question" in intents and not question_segment:
        intents = [i for i in intents if i != "question"]

    # Fallback: treat entire message as a question
    if not intents:
        intents = ["question"]
        question_segment = user_message

    return {
        "intents": intents,
        "report_segment": report_segment,
        "question_segment": question_segment,
    }


def extractor_node(state: dict[str, Any]) -> dict[str, Any]:
    """Extract structured summary from the report segment."""
    if "progress_report" not in state.get("intents", []):
        return {}
    report_text: str = state.get("report_segment") or state["messages"][-1]
    today = date.today().isoformat()
    response = chat_llm.invoke(
        [
            SystemMessage(content=EXTRACTOR_PROMPT.format(today=today)),
            HumanMessage(content=report_text),
        ]
    )
    raw = response.content.strip()
    # Enforce today as the default week if the LLM left it unspecified
    try:
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        extracted = json.loads(cleaned)
        week_val = extracted.get("week", "")
        if not week_val or week_val.lower() in ("unspecified", "unknown", "n/a", ""):
            extracted["week"] = today
        raw = json.dumps(extracted, ensure_ascii=False)
    except (json.JSONDecodeError, AttributeError):
        pass
    return {"extracted_summary": raw}


def store_node(state: dict[str, Any]) -> dict[str, Any]:
    """Persist report segment + extracted summary into ChromaDB."""
    if "progress_report" not in state.get("intents", []):
        return {}
    channel_id: str = state["channel_id"]
    report_text: str = state.get("report_segment") or state["messages"][-1]
    today = date.today().isoformat()

    chroma_store.add_memory(
        channel_id=channel_id,
        content=report_text,
        metadata={"date": today, "type": "raw"},
    )
    chroma_store.add_memory(
        channel_id=channel_id,
        content=state.get("extracted_summary", ""),
        metadata={"date": today, "type": "summary"},
    )
    return {"store_response": "Your progress report has been saved successfully."}


def retriever_node(state: dict[str, Any]) -> dict[str, Any]:
    """Retrieve relevant documents from ChromaDB using the question segment."""
    if "question" not in state.get("intents", []):
        return {}
    channel_id: str = state["channel_id"]
    query: str = state.get("question_segment") or state["messages"][-1]
    docs = chroma_store.search_memory(channel_id=channel_id, query=query, n_results=5)
    return {"retrieved_docs": docs}


def answer_node(state: dict[str, Any]) -> dict[str, Any]:
    """Generate an answer using retrieved context docs."""
    if "question" not in state.get("intents", []):
        return {}
    question: str = state.get("question_segment") or state["messages"][-1]
    docs: list[dict[str, Any]] = state.get("retrieved_docs") or []

    if not docs:
        context_text = "(No relevant memories found for this channel.)"
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
            HumanMessage(content=question),
        ]
    )
    return {"answer_response": response.content.strip()}


def combiner_node(state: dict[str, Any]) -> dict[str, Any]:
    """Combine store and answer responses into a single final response."""
    parts: list[str] = []
    if state.get("store_response"):
        parts.append(state["store_response"])
    if state.get("answer_response"):
        parts.append(state["answer_response"])
    return {"response": "\n\n".join(parts) if parts else "No response generated."}


async def answer_node_astream(state: dict[str, Any]) -> AsyncGenerator[str, None]:
    """Stream answer tokens from the LLM for the streaming chat endpoint."""
    if "question" not in state.get("intents", []):
        return
    question: str = state.get("question_segment") or state["messages"][-1]
    docs: list[dict[str, Any]] = state.get("retrieved_docs") or []

    if not docs:
        context_text = "(No relevant memories found for this channel.)"
    else:
        parts: list[str] = []
        for i, doc in enumerate(docs, start=1):
            meta = doc.get("metadata", {})
            doc_date = meta.get("date", "unknown")
            doc_type = meta.get("type", "unknown")
            parts.append(f"[{i}] ({doc_date}, {doc_type})\n{doc['content']}")
        context_text = "\n\n---\n\n".join(parts)

    system_content = ANSWER_PROMPT.format(context=context_text)
    async for chunk in chat_llm.astream(
        [
            SystemMessage(content=system_content),
            HumanMessage(content=question),
        ]
    ):
        if chunk.content:
            yield chunk.content
