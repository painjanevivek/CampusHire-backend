from app.models.profile import StudentProfile
from app.modules.profiles.schemas import ProfileUpdate
from app.modules.profiles.service import readiness


def test_required_readiness_is_separate_from_recommendations() -> None:
    profile = StudentProfile(
        full_name="Asha Patil",
        institution_name="Campus Institute",
        prn="CS-280",
        department="Computer Science",
        education=[{"degree": "B.Tech"}],
        target_roles=["AI Engineer"],
        skills=[],
        external_links={},
    )
    score, complete, checklist = readiness(profile)
    assert complete is True
    assert score == 50
    assert any(not item.required and not item.complete for item in checklist)


def test_github_requires_https_github_profile() -> None:
    payload = ProfileUpdate(github_url="https://github.com/asha")
    assert payload.github_url == "https://github.com/asha"
