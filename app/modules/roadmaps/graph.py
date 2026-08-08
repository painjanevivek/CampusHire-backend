from dataclasses import dataclass


@dataclass(frozen=True)
class RoadmapNode:
    key: str
    title: str
    completion: str
    prerequisites: tuple[str, ...] = ()


def validate_dag(nodes: list[RoadmapNode]) -> None:
    graph = {node.key: node.prerequisites for node in nodes}
    visited: set[str] = set()
    active: set[str] = set()

    def visit(key: str) -> None:
        if key in active:
            raise ValueError("Roadmap contains a cycle")
        if key in visited:
            return
        if key not in graph:
            raise ValueError(f"Unknown roadmap prerequisite: {key}")
        active.add(key)
        for parent in graph[key]:
            visit(parent)
        active.remove(key)
        visited.add(key)

    for key in graph:
        visit(key)


def next_nodes(nodes: list[RoadmapNode], completed: set[str]) -> list[RoadmapNode]:
    validate_dag(nodes)
    return [
        node for node in nodes if node.key not in completed and set(node.prerequisites) <= completed
    ][:3]


AI_ENGINEER = [
    RoadmapNode("python", "Python foundations", "Build and test one command-line data project"),
    RoadmapNode("math", "Applied statistics", "Explain and implement evaluation metrics"),
    RoadmapNode(
        "ml",
        "Machine-learning workflow",
        "Train, evaluate, and document a baseline model",
        ("python", "math"),
    ),
    RoadmapNode(
        "llm", "LLM application safety", "Build a grounded workflow with injection tests", ("ml",)
    ),
    RoadmapNode(
        "deploy", "Deploy evidence", "Publish a monitored API and project write-up", ("llm",)
    ),
]
