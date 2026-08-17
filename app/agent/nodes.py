from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, AsyncGenerator

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.prompts import ANSWER_PROMPT, EXTRACTOR_PROMPT, ROUTER_PROMPT
from app.core.config import settings
from app.core.llm import LLMInference
from app.core.router import RouterInference
from app.memory.store import chroma_store

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
STORE_SAVE_RAW = False

# ---------------------------------------------------------------------------
# DEBUG
# ---------------------------------------------------------------------------
DEBUG_ROUTER = False
DEBUG_EXTRACTOR = False
DEBUG_STORE = False
DEBUG_RETRIEVER = False
DEBUG_ANSWER = False

# ---------------------------------------------------------------------------
# LLM clients
# ---------------------------------------------------------------------------

chat_llm = LLMInference(temperature=0.3)
router_llm = RouterInference(temperature=0.1) # Fast model


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
        max_tokens=256
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
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        extracted = json.loads(cleaned)
        week_val = extracted.get("week", "")
        if not week_val or week_val.lower() in ("unspecified", "unknown", "n/a", ""):
            extracted["week"] = today
        raw = json.dumps(extracted, ensure_ascii=False)
        if DEBUG_EXTRACTOR:
          print(f"Extractor node outputs: {raw}")

    except (json.JSONDecodeError, AttributeError):
        pass
    return {"extracted_summary": raw}


def store_node(state: dict[str, Any]) -> dict[str, Any]:
    """Persist report segment + extracted summary into ChromaDB."""
    if state.get("decision") != "save_memory":
        return {}
    channel_id: str = state["channel_id"]
    report_text: str = state.get("report_segment") or state["messages"][-1]
    today = date.today().isoformat()

    if STORE_SAVE_RAW:
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
    return {"store_response": "Your progress report has been saved successfully.", "response": "Your progress report has been saved successfully."}


def retriever_node(state: dict[str, Any]) -> dict[str, Any]:
    """Retrieve relevant documents from ChromaDB using the question segment."""
    if state.get("decision") != "answer_question":
        return {}
    channel_id: str = state["channel_id"]
    query: str = state.get("question_segment") or state["messages"][-1]

    if DEBUG_RETRIEVER:
        print(f"Retriever node inputs: {query}")

    docs = chroma_store.search_memory(channel_id=channel_id, query=query, n_results=5)

    if DEBUG_RETRIEVER:
        print(f"Retriever node outputs: {docs}")

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
