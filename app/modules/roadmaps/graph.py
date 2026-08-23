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


def _software_path(final_title: str, final_completion: str) -> list[RoadmapNode]:
    return [
        RoadmapNode(
            "fundamentals", "Programming foundations", "Build and test one focused application"
        ),
        RoadmapNode(
            "problem-solving", "Problem-solving evidence", "Document three explained solutions"
        ),
        RoadmapNode(
            "delivery",
            "Production delivery",
            "Ship a versioned project with tests and a clear README",
            ("fundamentals", "problem-solving"),
        ),
        RoadmapNode("specialization", final_title, final_completion, ("delivery",)),
        RoadmapNode(
            "placement-proof",
            "Placement evidence pack",
            "Attach the project, impact note, and reviewed resume evidence",
            ("specialization",),
        ),
    ]


CURATED_ROADMAPS: dict[str, tuple[str, str, list[RoadmapNode]]] = {
    "software-developer": (
        "Software Developer",
        "Build reliable software from requirements through delivery.",
        _software_path(
            "Software design", "Explain architecture and trade-offs in a tested project"
        ),
    ),
    "frontend-developer": (
        "Frontend Developer",
        "Create accessible, responsive product interfaces with evidence.",
        _software_path("Accessible frontend", "Ship a responsive interface with keyboard tests"),
    ),
    "backend-developer": (
        "Backend Developer",
        "Design secure APIs, durable data, and observable services.",
        _software_path("Reliable backend", "Deploy an authenticated API with database migrations"),
    ),
    "full-stack-developer": (
        "Full-Stack Developer",
        "Connect a polished interface to accountable backend workflows.",
        _software_path(
            "End-to-end product", "Ship one traced workflow across UI, API, and storage"
        ),
    ),
    "mobile-application-developer": (
        "Mobile Application Developer",
        "Build resilient mobile experiences with tested offline states.",
        _software_path("Mobile delivery", "Ship a tested mobile flow with offline recovery"),
    ),
    "data-analyst": (
        "Data Analyst",
        "Turn reviewed data into reproducible decisions and narratives.",
        _software_path(
            "Analytical evidence", "Publish a reproducible analysis with stated assumptions"
        ),
    ),
    "machine-learning-engineer": (
        "Machine Learning Engineer",
        "Build evaluated ML systems with versioned data and model evidence.",
        _software_path("Evaluated ML workflow", "Train and evaluate a documented baseline model"),
    ),
    "ai-engineer": (
        "AI Engineer",
        "Build grounded AI workflows with evaluation and deployment evidence.",
        AI_ENGINEER,
    ),
}
