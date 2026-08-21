from __future__ import annotations

import asyncio
import json
import re
from datetime import date
from typing import Any, AsyncGenerator

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.node_config import (
    RERANK_ENABLED, RERANK_TOP_N, STORE_SAVE_RAW, TOP_N,
    DEBUG_ANSWER, DEBUG_EXTRACTOR, DEBUG_RETRIEVER, DEBUG_ROUTER, DEBUG_STORE,
    chat_llm, router_llm, reranker
)
from app.agent.prompts import ANSWER_PROMPT, EXTRACTOR_PROMPT, ROUTER_PROMPT
from app.agent.extractor_utils import _normalize_extracted_summary, _normalize_tags, _render_summary_text
from app.agent.retriever_utils import _rerank_docs
from app.core.config import settings
from app.memory.store import vector_store


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def compress_node(state: dict[str, Any]) -> dict[str, Any]:
    return state

async def router_node_async(state: dict[str, Any]) -> dict[str, Any]:
    """Classify the user message and decide if it's to save memory or answer a question."""
    user_message: str = state["messages"][-1]
    report_segment: str | None = ""
    question_segment: str | None = ""

    if DEBUG_ROUTER:
      print(f"Router node inputs: {user_message}")

    response = await router_llm.agenerate_response(
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
    """Extract structured summary from the report segment."""
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
    # Enforce today as the default week if the LLM left it unspecified
    try:
        extracted = _normalize_extracted_summary(raw)
        week_val = extracted.get("week", "")
        if not week_val or week_val.lower() in ("unspecified", "unknown", "n/a", ""):
            extracted["week"] = today
        extracted["tags"] = _normalize_tags(extracted.get("tags", ["report", "progress"]))
        if not extracted["tags"]:
            extracted["tags"] = ["report", "progress"]
        summary_text = _render_summary_text(extracted)
        if DEBUG_EXTRACTOR:
          print(f"Extractor node outputs: {summary_text}")
        raw = summary_text

    except (json.JSONDecodeError, AttributeError):
        extracted = _normalize_extracted_summary({})
        raw = _render_summary_text(extracted)
    return {
        "extracted_summary": raw,
        "extracted_title": extracted.get("title", "Progress report"),
        "extracted_tags": extracted.get("tags", ["report", "progress"])
    }


def store_node(state: dict[str, Any]) -> dict[str, Any]:
    """Persist report segment + extracted summary into the vector store."""
    if state.get("decision") != "save_memory":
        return {}
    channel_id: str = state["channel_id"]
    report_text: str = state.get("report_segment") or state["messages"][-1]
    today = date.today().isoformat()

    title = state.get("extracted_title", "Progress report")
    tags = _normalize_tags(state.get("extracted_tags", ["report", "progress"]))
    if not tags:
        tags = ["report", "progress"]

    normalized_summary = state.get("extracted_summary", "")
    if isinstance(normalized_summary, dict):
        normalized_summary = _render_summary_text(normalized_summary)

    if STORE_SAVE_RAW:
        vector_store.add_memory(
            channel_id=channel_id,
            content=report_text,
            metadata={"date": today, "type": "raw", "source": "raw", "title": title, "tags": json.dumps(tags, ensure_ascii=False)},
        )

    vector_store.add_memory(
        channel_id=channel_id,
        content=normalized_summary,
        metadata={"date": today, "type": "summary", "source": "summary", "title": title, "tags": json.dumps(tags, ensure_ascii=False)},
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

    docs = vector_store.search_memory(channel_id=channel_id, query=query, n_results=TOP_N, sort_by_date=False)

    if RERANK_ENABLED:
        docs = _rerank_docs(query, docs)

    if DEBUG_RETRIEVER:
        print(f"Retriever node outputs:")
        for doc in docs:
            meta = doc.get("metadata", {})
            doc_source = meta.get("source", "unknown")
            doc_section = meta.get("section", "unknown")
            doc_content = doc.get("content", "")
            print(f"Doc: ({doc_source}, {doc_section})\n{doc_content}\n---")

    return {"retrieved_docs": docs}


async def extractor_node_async(state: dict[str, Any]) -> dict[str, Any]:
    """Extract structured summary from the report segment."""
    if state.get("decision") != "save_memory":
        return {}
    report_text: str = state.get("report_segment") or state["messages"][-1]
    today = date.today().isoformat()

    if DEBUG_EXTRACTOR:
      print(f"Extractor node inputs: {report_text}")

    raw = await chat_llm.agenerate_response(
        messages=[
            SystemMessage(content=EXTRACTOR_PROMPT.format(today=today)),
            HumanMessage(content=report_text),
        ]
    )
    # Enforce today as the default week if the LLM left it unspecified
    try:
        extracted = _normalize_extracted_summary(raw)
        week_val = extracted.get("week", "")
        if not week_val or week_val.lower() in ("unspecified", "unknown", "n/a", ""):
            extracted["week"] = today
        extracted["tags"] = _normalize_tags(extracted.get("tags", ["report", "progress"]))
        if not extracted["tags"]:
            extracted["tags"] = ["report", "progress"]
        summary_text = _render_summary_text(extracted)
        if DEBUG_EXTRACTOR:
          print(f"Extractor node outputs: {summary_text}")
        raw = summary_text

    except (json.JSONDecodeError, AttributeError):
        extracted = _normalize_extracted_summary({})
        raw = _render_summary_text(extracted)
    return {
        "extracted_summary": raw,
        "extracted_title": extracted.get("title", "Progress report"),
        "extracted_tags": extracted.get("tags", ["report", "progress"])
    }


async def store_node_async(state: dict[str, Any]) -> dict[str, Any]:
    """Persist report segment + extracted summary into the vector store."""
    if state.get("decision") != "save_memory":
        return {}
    channel_id: str = state["channel_id"]
    report_text: str = state.get("report_segment") or state["messages"][-1]
    today = date.today().isoformat()

    title = state.get("extracted_title", "Progress report")
    tags = _normalize_tags(state.get("extracted_tags", ["report", "progress"]))
    if not tags:
        tags = ["report", "progress"]

    normalized_summary = state.get("extracted_summary", "")
    if isinstance(normalized_summary, dict):
        normalized_summary = _render_summary_text(normalized_summary)

    if STORE_SAVE_RAW:
        await asyncio.to_thread(
            vector_store.add_memory,
            channel_id=channel_id,
            content=report_text,
            metadata={"date": today, "type": "raw", "source": "raw", "title": title, "tags": json.dumps(tags, ensure_ascii=False)},
        )

    await asyncio.to_thread(
        vector_store.add_memory,
        channel_id=channel_id,
        content=normalized_summary,
        metadata={"date": today, "type": "summary", "source": "summary", "title": title, "tags": json.dumps(tags, ensure_ascii=False)},
    )
    return {"store_response": "Your progress report has been saved successfully.", "response": "Your progress report has been saved successfully."}


async def retriever_node_async(state: dict[str, Any]) -> dict[str, Any]:
    """Retrieve relevant documents from the vector store using the question segment."""
    if state.get("decision") != "answer_question":
        return {}
    channel_id: str = state["channel_id"]
    query: str = state.get("question_segment") or state["messages"][-1]

    # Augment query with tags from recent memories if available
    augmented_query = query
    if DEBUG_RETRIEVER:
        print(f"Retriever node inputs: {query}")

    docs = await asyncio.to_thread(vector_store.search_memory, channel_id=channel_id, query=query, n_results=TOP_N, sort_by_date=False)

    if RERANK_ENABLED:
        docs = await asyncio.to_thread(_rerank_docs, query, docs)

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


async def answer_node_async(state: dict[str, Any]) -> dict[str, Any]:
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
    response = await chat_llm.agenerate_response(
        messages=[
            SystemMessage(content=system_content),
            HumanMessage(content=question),
        ]
    )
    if DEBUG_ANSWER:
        print(f"Answer node outputs: {response}")
    return {"answer_response": response.strip(), "response": response.strip()}


async def answer_node_astream(state: dict[str, Any]) -> AsyncGenerator[str, None]:
    """Stream answer tokens from the LLM for the streaming chat endpoint."""
    if state.get("decision") != "answer_question":
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

    if DEBUG_ANSWER:
        print(f"Answer node inputs: {system_content}")
    # Use stream_response instead of astream
    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=question),
    ]

    # stream_response is a synchronous generator, so we iterate over it directly
    for chunk in chat_llm.stream_response(messages=messages):
        if chunk:
            yield chunk
