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
    terms = set(state["question"].casefold().split())
    approved = [chunk for chunk in state["chunks"] if chunk["approved"]]
    ranked = sorted(
        approved, key=lambda chunk: len(terms & set(chunk["text"].casefold().split())), reverse=True
    )[:3]
    return {"chunks": ranked, "iterations": state["iterations"] + 1}


def explain(state: PolicyState) -> dict[str, object]:
    if not state["chunks"]:
        return {
            "answer": "Policy evidence not found.",
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
