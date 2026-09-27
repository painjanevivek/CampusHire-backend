from dataclasses import dataclass


@dataclass(frozen=True)
class RoadmapNode:
    key: str
    title: str
    completion: str
    prerequisites: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()


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
        "llm", "LLM application safety", "Build a source-based workflow with safety tests", ("ml",)
    ),
    RoadmapNode(
        "deploy",
        "Show your deployed work",
        "Publish a monitored API and project write-up",
        ("llm",),
    ),
]


def _software_path(final_title: str, final_completion: str) -> list[RoadmapNode]:
    return [
        RoadmapNode(
            "fundamentals", "Programming foundations", "Build and test one focused application"
        ),
        RoadmapNode(
            "problem-solving", "Problem-solving work", "Document three explained solutions"
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
            "Placement project pack",
            "Attach the project, impact note, and reviewed resume",
            ("specialization",),
        ),
    ]


LEGACY_ROADMAPS: dict[str, tuple[str, str, list[RoadmapNode]]] = {
    "software-developer": (
        "Software Developer",
        "Build reliable software from requirements through delivery.",
        _software_path(
            "Software design", "Explain architecture and trade-offs in a tested project"
        ),
    ),
    "frontend-developer": (
        "Frontend Developer",
        "Create accessible, responsive product interfaces and show your work.",
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
            "Analysis project", "Publish an analysis that others can repeat, with clear assumptions"
        ),
    ),
    "machine-learning-engineer": (
        "Machine Learning Engineer",
        "Build tested ML systems with saved data and model versions.",
        _software_path("Evaluated ML workflow", "Train and evaluate a documented baseline model"),
    ),
    "ai-engineer": (
        "AI Engineer",
        "Build source-based AI workflows with testing and deployment records.",
        AI_ENGINEER,
    ),
}


# CampusHire-owned learning sequences. Signals are used only to describe recorded
# profile/project context; they never verify proficiency or change eligibility.
ROLE_STEPS: dict[str, list[tuple[str, str, tuple[str, ...]]]] = {
    "software-developer": [
        (
            "Programming fundamentals",
            "Build a small application with clear inputs, errors, and tests.",
            ("python", "java", "javascript"),
        ),
        (
            "Data structures & problem solving",
            "Explain the trade-offs in three tested solutions.",
            ("algorithms", "data structures"),
        ),
        (
            "Software design",
            "Separate a project into maintainable components and document the choices.",
            ("design patterns", "architecture"),
        ),
        (
            "Testing & delivery",
            "Add automated tests and a repeatable release process.",
            ("testing", "ci", "github actions"),
        ),
        (
            "Project portfolio",
            "Publish the project, a README, and an honest account of your contribution.",
            ("github", "documentation"),
        ),
    ],
    "frontend-developer": [
        (
            "HTML, CSS & JavaScript",
            "Build a semantic interface with predictable interactions.",
            ("html", "css", "javascript"),
        ),
        (
            "Responsive product UI",
            "Adapt one user flow across mobile, tablet, and desktop.",
            ("responsive", "react", "next.js"),
        ),
        (
            "Accessibility",
            "Make the flow usable with a keyboard and screen reader.",
            ("accessibility", "aria"),
        ),
        (
            "Frontend testing",
            "Test important UI states, navigation, and failure cases.",
            ("vitest", "playwright", "testing library"),
        ),
        (
            "Frontend portfolio",
            "Publish a working interface and explain design and engineering choices.",
            ("github", "deployment"),
        ),
    ],
    "backend-developer": [
        (
            "API foundations",
            "Build and document a REST API with validation and error handling.",
            ("fastapi", "express", "spring"),
        ),
        (
            "Database design",
            "Build a PostgreSQL-backed API with a clear schema and migrations.",
            ("postgresql", "sql", "database"),
        ),
        (
            "Authentication & security",
            "Protect endpoints and test authorization boundaries.",
            ("authentication", "authorization", "security"),
        ),
        (
            "Testing & operations",
            "Add integration tests, logs, and a repeatable deployment.",
            ("pytest", "docker", "monitoring"),
        ),
        (
            "Backend portfolio",
            "Publish an API contract, README, and architecture trade-offs.",
            ("openapi", "github", "documentation"),
        ),
    ],
    "full-stack-developer": [
        (
            "User flow & interface",
            "Build one accessible, responsive product flow.",
            ("react", "next.js", "frontend"),
        ),
        (
            "API & data model",
            "Connect the flow to validated endpoints and persistent data.",
            ("api", "postgresql", "database"),
        ),
        (
            "Authentication & permissions",
            "Secure the flow across browser, API, and data access.",
            ("authentication", "authorization"),
        ),
        (
            "End-to-end testing",
            "Test success, error, and recovery states across the full stack.",
            ("playwright", "testing", "ci"),
        ),
        (
            "Shipped product",
            "Deploy the flow and document your technical decisions.",
            ("deployment", "github"),
        ),
    ],
    "mobile-application-developer": [
        (
            "Mobile UI foundations",
            "Build a usable navigation flow for a small screen.",
            ("android", "ios", "flutter", "react native"),
        ),
        (
            "Device data & state",
            "Persist user data and handle loading and error states.",
            ("sqlite", "state management", "storage"),
        ),
        (
            "Offline recovery",
            "Make one key flow recover gracefully after connectivity loss.",
            ("offline", "sync"),
        ),
        (
            "Mobile testing",
            "Test the flow on multiple screen sizes and failure paths.",
            ("espresso", "xctest", "testing"),
        ),
        (
            "Mobile release portfolio",
            "Share a build, screenshots, and implementation notes.",
            ("play store", "app store", "github"),
        ),
    ],
    "data-analyst": [
        (
            "Data questions & SQL",
            "Frame a question and extract a reproducible dataset.",
            ("sql", "postgresql"),
        ),
        (
            "Data quality",
            "Check missing values, duplicates, and source assumptions.",
            ("data cleaning", "pandas"),
        ),
        (
            "Exploratory analysis",
            "Compare segments and explain uncertainty without overclaiming.",
            ("python", "statistics", "excel"),
        ),
        (
            "Decision-ready visuals",
            "Create clear charts with definitions and accessible labels.",
            ("power bi", "tableau", "visualization"),
        ),
        (
            "Analysis portfolio",
            "Publish a reproducible notebook or report with source notes.",
            ("jupyter", "reporting", "github"),
        ),
    ],
    "machine-learning-engineer": [
        (
            "Python & data pipelines",
            "Build a repeatable data preparation pipeline.",
            ("python", "pandas"),
        ),
        (
            "Baseline modelling",
            "Train and evaluate a simple baseline before tuning.",
            ("scikit-learn", "machine learning"),
        ),
        (
            "Evaluation & leakage",
            "Measure performance with held-out data and check for leakage.",
            ("evaluation", "statistics"),
        ),
        (
            "Model delivery",
            "Version the model and expose a tested inference endpoint.",
            ("mlflow", "docker", "api"),
        ),
        (
            "ML system portfolio",
            "Document data, experiments, limitations, and monitoring.",
            ("monitoring", "github"),
        ),
    ],
    "ai-engineer": [
        ("Python foundations", "Build and test one command-line data project.", ("python",)),
        ("Applied statistics", "Explain and implement evaluation metrics.", ("statistics",)),
        (
            "Machine-learning workflow",
            "Train, evaluate, and document a baseline model.",
            ("machine learning", "scikit-learn"),
        ),
        (
            "Grounded AI application",
            "Build a source-based workflow with safety and evaluation tests.",
            ("retrieval", "llm", "rag"),
        ),
        (
            "AI deployment record",
            "Publish a monitored API with a limitations write-up.",
            ("deployment", "monitoring"),
        ),
    ],
}


def _role_nodes(slug: str) -> list[RoadmapNode]:
    keys = ("foundations", "practice", "delivery", "specialization", "portfolio")
    steps = ROLE_STEPS[slug]
    return [
        RoadmapNode(
            key=keys[index],
            title=title,
            completion=completion,
            prerequisites=(keys[index - 1],) if index else (),
            signals=signals,
        )
        for index, (title, completion, signals) in enumerate(steps)
    ]


CURATED_ROADMAPS: dict[str, tuple[str, str, list[RoadmapNode]]] = {
    slug: (title, summary, _role_nodes(slug))
    for slug, (title, summary, _) in LEGACY_ROADMAPS.items()
}
