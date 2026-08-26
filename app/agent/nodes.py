from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.node_config import (
    DEBUG_ANSWER, DEBUG_EXTRACTOR, DEBUG_RETRIEVER, DEBUG_ROUTER, DEBUG_STORE,
    chat_llm, router_llm
)
from app.agent.prompts import ANSWER_PROMPT, EXTRACTOR_PROMPT, ROUTER_PROMPT
from app.agent.extractor_utils import _normalize_extracted_chunks
from app.agent.retriever_utils import _rerank_docs, retrieve_hybrid
from app.memory.store import vector_store


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def compress_node(state: dict[str, Any]) -> dict[str, Any]:
    return state


def router_node(state: dict[str, Any]) -> dict[str, Any]:
    """Classify the user message and decide if it's to save memory or answer a question."""
    user_message: str = state["messages"][-1]
    report_segment: str | None = ""
    question_segment: str | None = ""

    if DEBUG_ROUTER:
      print(f"Router node inputs: {user_message}")

    response = router_llm.generate_response(
        messages=[
            SystemMessage(content=ROUTER_PROMPT),
            HumanMessage(content=user_message),
        ],
        max_tokens=256,
        think=False
    )
    try:
        if DEBUG_ROUTER:
          print(f"Router LLM raw response: {response}")

        raw = response if isinstance(response, str) else ""
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        data = json.loads(raw)
        decision: str = data.get("decision", "answer_question")

        if decision == "save_memory":
            report_segment = state["messages"][-1]
        elif decision == "answer_question":
            question_segment = state["messages"][-1]

        # Ensure decision is valid
        if decision not in ["save_memory", "answer_question"]:
            decision = "answer_question"
            question_segment = state["messages"][-1]

    except (json.JSONDecodeError, AttributeError):
        decision = "answer_question"

    response = {
        "decision": decision,
        "report_segment": report_segment,
        "question_segment": question_segment,
    }

    if DEBUG_ROUTER:
      print(f"Router node outputs: {response}")

    return response


def extractor_node(state: dict[str, Any]) -> dict[str, Any]:
    """Split the report segment into raw, non-summarized chunks grouped by week."""
    if state.get("decision") != "save_memory":
        return {}
    report_text: str = state.get("report_segment") or state["messages"][-1]
    today = date.today().isoformat()

    if DEBUG_EXTRACTOR:
      print(f"Extractor node inputs: {report_text}")

    raw = chat_llm.generate_response(
        messages=[
            SystemMessage(content=EXTRACTOR_PROMPT.format(today=today)),
            HumanMessage(content=report_text),
        ]
    )
    chunks = _normalize_extracted_chunks(raw, fallback_content=report_text)
    if DEBUG_EXTRACTOR:
      print(f"Extractor node outputs: {chunks}")
    return {"extracted_chunks": chunks}


def store_node(state: dict[str, Any]) -> dict[str, Any]:
    """Persist each extracted per-week raw chunk into the vector store as its own memory."""
    if state.get("decision") != "save_memory":
        return {}
    channel_id: str = state["channel_id"]
    report_text: str = state.get("report_segment") or state["messages"][-1]
    today = date.today().isoformat()

    chunks = state.get("extracted_chunks") or _normalize_extracted_chunks({}, fallback_content=report_text)

    for chunk in chunks:
        vector_store.add_memory(
            channel_id=channel_id,
            content=chunk["content"],
            metadata={
                "date": chunk.get("week", today),
                "type": "raw",
                "source": "raw",
                "title": chunk.get("title", "Progress report"),
                "tags": json.dumps(chunk.get("tags", ["report", "progress"]), ensure_ascii=False),
            },
        )
    return {"store_response": "Your progress report has been saved successfully.", "response": "Your progress report has been saved successfully."}


def retriever_node(state: dict[str, Any]) -> dict[str, Any]:
    """Retrieve relevant documents from the vector store using the question segment."""
    if state.get("decision") != "answer_question":
        return {}
    channel_id: str = state["channel_id"]
    query: str = state.get("question_segment") or state["messages"][-1]

    # Augment query with tags from recent memories if available
    augmented_query = query
    if DEBUG_RETRIEVER:
        print(f"Retriever node inputs: {query}")

    bm25_index = vector_store.build_bm25_index(channel_id)
    docs = retrieve_hybrid(channel_id=channel_id, query=query, bm25_index=bm25_index)
    docs = _rerank_docs(query, docs, bm25_index=bm25_index)

    if DEBUG_RETRIEVER:
        print(f"Retriever node outputs:")
        for doc in docs:
            meta = doc.get("metadata", {})
            doc_source = meta.get("source", "unknown")
            doc_section = meta.get("section", "unknown")
            doc_content = doc.get("content", "")
            print(f"Doc: ({doc_source}, {doc_section})\n{doc_content}\n---")

    return {"retrieved_docs": docs}


def answer_node(state: dict[str, Any]) -> dict[str, Any]:
    """Generate an answer using retrieved context docs."""
    if state.get("decision") != "answer_question":
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
    if DEBUG_ANSWER:
        print(f"Answer node inputs: {system_content}")
    response = chat_llm.generate_response(
        messages=[
            SystemMessage(content=system_content),
            HumanMessage(content=question),
        ]
    )
    if DEBUG_ANSWER:
        print(f"Answer node outputs: {response}")
    return {"answer_response": response.strip(), "response": response.strip()}
