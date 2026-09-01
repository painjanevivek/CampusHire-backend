import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class PolicyChunk(TypedDict):
    text: str
    section: str
    page: int
    approved: bool


class PolicyState(TypedDict):
    question: str
    chunks: list[PolicyChunk]
    citations: list[str]
    answer: str
    iterations: int


def retrieve(state: PolicyState) -> dict[str, object]:
    terms = set(re.findall(r"[a-z0-9]+", state["question"].casefold()))
    approved = [chunk for chunk in state["chunks"] if chunk["approved"]]
    scored = [
        (
            len(terms & set(re.findall(r"[a-z0-9]+", chunk["text"].casefold()))),
            chunk,
        )
        for chunk in approved
    ]
    ranked = [
        chunk
        for score, chunk in sorted(scored, key=lambda item: item[0], reverse=True)
        if score > 0
    ][:3]
    return {"chunks": ranked, "iterations": state["iterations"] + 1}


def explain(state: PolicyState) -> dict[str, object]:
    if not state["chunks"]:
        return {
            "answer": "Answer not found in the approved policy.",
            "citations": [],
            "iterations": state["iterations"] + 1,
        }
    citations = [f"{chunk['section']} · page {chunk['page']}" for chunk in state["chunks"]]
    answer = " ".join(chunk["text"] for chunk in state["chunks"])
    return {"answer": answer, "citations": citations, "iterations": state["iterations"] + 1}


def build_policy_graph() -> Any:
    graph = StateGraph(PolicyState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("explain", explain)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "explain")
    graph.add_edge("explain", END)
    return graph.compile()


policy_graph = build_policy_graph()
