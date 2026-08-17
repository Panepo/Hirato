from __future__ import annotations

from typing import Any, Optional

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.agent.nodes import (
    answer_node,
    extractor_node,
    retriever_node,
    router_node,
    store_node,
)


class AgentState(TypedDict):
    messages: list[str]
    channel_id: str
    decision: str  # "save_memory" or "answer_question"
    report_segment: Optional[str]
    question_segment: Optional[str]
    extracted_summary: Optional[str]
    retrieved_docs: Optional[list[dict[str, Any]]]
    store_response: Optional[str]
    answer_response: Optional[str]
    response: Optional[str]


def route_decision(state: AgentState) -> str:
    """Route to either save_memory or answer_question based on router_node decision."""
    decision = state.get("decision", "answer_question")
    if decision == "save_memory":
        return "extractor_node"
    else:
        return "retriever_node"


builder = StateGraph(AgentState)

builder.add_node("router_node", router_node)
builder.add_node("extractor_node", extractor_node)
builder.add_node("store_node", store_node)
builder.add_node("retriever_node", retriever_node)
builder.add_node("answer_node", answer_node)

builder.add_edge(START, "router_node")

# Conditional routing based on decision
builder.add_conditional_edges(
    "router_node",
    route_decision,
    {
        "extractor_node": "extractor_node",
        "retriever_node": "retriever_node",
    }
)

# Path 1: save_memory -> extractor -> store -> END
builder.add_edge("extractor_node", "store_node")
builder.add_edge("store_node", END)

# Path 2: answer_question -> retriever -> answer -> END
builder.add_edge("retriever_node", "answer_node")
builder.add_edge("answer_node", END)

secretary_graph = builder.compile()
