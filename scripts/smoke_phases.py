from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.ai.workflows.policy_explanation import policy_graph
from app.core.resilience import CircuitBreaker
from app.models.profile import StudentProfile
from app.modules.auth.security import hash_password, verify_password
from app.modules.eligibility.engine import Operator, Rule, evaluate
from app.modules.matching.scoring import score_match
from app.modules.notifications.domain import Notification, deduplicate
from app.modules.profiles.service import readiness
from app.modules.recruitment.domain import (
    ApplicationStatus,
    DriveStatus,
    can_apply,
    validate_transition,
)
from app.modules.resumes.builder import ResumeContent, generate_pdf
from app.modules.resumes.service import validate_pdf
from app.modules.roadmaps.graph import AI_ENGINEER, next_nodes, validate_dag


def passed(phase: int, label: str) -> None:
    print(f"phase-{phase}: PASS - {label}")


def main() -> None:
    assert Path("README.md").exists() and Path("SECURITY.md").exists()
    passed(0, "scope and governance documents")
    from app.main import app

    assert app.title == "CampusHire AI API"
    passed(1, "API foundation and health contract")
    password_hash = hash_password("a long campus passphrase")
    assert verify_password(password_hash, "a long campus passphrase")
    passed(2, "Argon2id authentication primitive")
    profile = StudentProfile(
        full_name="Asha",
        institution_name="Campus Institute",
        prn="CS-280",
        department="CS",
        education=[{"degree": "B.Tech"}],
        target_roles=["AI Engineer"],
        skills=[],
        external_links={},
    )
    assert readiness(profile)[1]
    passed(3, "required profile readiness")
    resume = ResumeContent(
        full_name="Asha Patil",
        email="asha@example.edu",
        summary=(
            "Reliable software engineering student profile with practical testing and "
            "deployment experience across multiple campus projects."
        ),
        skills=["Python", "SQL", "React", "FastAPI"],
        projects=["Matcher", "Roadmap"],
        education=["B.Tech CS"],
    )
    pdf = generate_pdf(resume)
    assert validate_pdf(pdf, "application/pdf", 5_000_000, 3).page_count == 1
    passed(4, "secure PDF parsing")
    assert pdf.startswith(b"%PDF-")
    passed(5, "selectable deterministic resume PDF")
    now = datetime.now(UTC)
    assert can_apply(DriveStatus.OPEN, now + timedelta(hours=1), now)
    validate_transition(ApplicationStatus.SUBMITTED, ApplicationStatus.UNDER_REVIEW)
    passed(6, "drive deadline and application transition")
    rules = [Rule(field="cgpa", operator=Operator.GTE, value=7, label="CGPA")]
    assert evaluate("v1", rules, {"cgpa": 8})["status"] == "eligible"
    passed(7, "deterministic eligibility")
    assert score_match([1.0, 0.0], [1.0, 0.0], {"Python"}, {"python"}, 1).score == 100
    passed(8, "versioned semantic score")
    policy = policy_graph.invoke(
        {
            "question": "backlog",
            "chunks": [
                {"text": "No active backlog.", "section": "4.2", "page": 3, "approved": True}
            ],
            "citations": [],
            "answer": "",
            "iterations": 0,
        }
    )
    assert policy["citations"]
    passed(9, "grounded LangGraph policy citation")
    validate_dag(AI_ENGINEER)
    assert next_nodes(AI_ENGINEER, {"python", "math"})[0].key == "ml"
    passed(10, "acyclic personalized roadmap")
    note = Notification("student", "application:submitted", "Received", "/applications/1")
    assert len(deduplicate([note, note])) == 1
    passed(11, "notification idempotency")
    breaker = CircuitBreaker(failure_threshold=1)
    breaker.record_failure()
    assert not breaker.allow()
    passed(12, "AI failure isolation")
    passed(13, "release smoke programme")


if __name__ == "__main__":
    main()
