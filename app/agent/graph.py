from __future__ import annotations

from typing import Any, Optional

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.agent.nodes import (
    answer_node,
    combiner_node,
    extractor_node,
    project_resolver_node,
    retriever_node,
    router_node,
    store_node,
)


class AgentState(TypedDict):
    messages: list[str]
    project_id: str
    project_hint: Optional[str]
    intents: list[str]
    report_segment: Optional[str]
    question_segment: Optional[str]
    extracted_summary: Optional[str]
    retrieved_docs: Optional[list[dict[str, Any]]]
    store_response: Optional[str]
    answer_response: Optional[str]
    response: Optional[str]


builder = StateGraph(AgentState)

builder.add_node("router_node", router_node)
builder.add_node("project_resolver_node", project_resolver_node)
builder.add_node("extractor_node", extractor_node)
builder.add_node("store_node", store_node)
builder.add_node("retriever_node", retriever_node)
builder.add_node("answer_node", answer_node)
builder.add_node("combiner_node", combiner_node)

builder.add_edge(START, "router_node")
builder.add_edge("router_node", "project_resolver_node")
builder.add_edge("project_resolver_node", "extractor_node")
builder.add_edge("extractor_node", "store_node")
builder.add_edge("store_node", "retriever_node")
builder.add_edge("retriever_node", "answer_node")
builder.add_edge("answer_node", "combiner_node")
builder.add_edge("combiner_node", END)

secretary_graph = builder.compile()
