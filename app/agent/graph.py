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
    project_id: str
    intent: Optional[str]
    extracted_summary: Optional[str]
    retrieved_docs: Optional[list[dict[str, Any]]]
    response: Optional[str]


def _route_intent(state: AgentState) -> str:
    return state.get("intent", "question")


builder = StateGraph(AgentState)

builder.add_node("router_node", router_node)
builder.add_node("extractor_node", extractor_node)
builder.add_node("store_node", store_node)
builder.add_node("retriever_node", retriever_node)
builder.add_node("answer_node", answer_node)

builder.add_edge(START, "router_node")
builder.add_conditional_edges(
    "router_node",
    _route_intent,
    {
        "progress_report": "extractor_node",
        "question": "retriever_node",
    },
)
builder.add_edge("extractor_node", "store_node")
builder.add_edge("store_node", END)
builder.add_edge("retriever_node", "answer_node")
builder.add_edge("answer_node", END)

secretary_graph = builder.compile()
