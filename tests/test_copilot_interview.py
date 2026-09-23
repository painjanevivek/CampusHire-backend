import pytest
from pydantic import ValidationError

from app.modules.copilot.schemas import InterviewPracticeResult
from app.modules.copilot.service import (
    _format_interview_practice,
    _interview_practice_prompt,
)


def test_interview_prompt_uses_only_role_and_sanitized_practice_transcript() -> None:
    prompt = _interview_practice_prompt(
        role_title="Backend Engineer",
        role_skills=["Python", "PostgreSQL"],
        history=[("assistant", "How would you design an API?")],
        answer="I built an API. Contact me at student@example.com or 9876543210.",
    )

    assert '"title": "Backend Engineer"' in prompt
    assert "Python" in prompt and "PostgreSQL" in prompt
    assert "student@example.com" not in prompt
    assert "9876543210" not in prompt
    assert "[email removed]" in prompt
    assert "[phone removed]" in prompt
    assert "not evaluating a candidate" in prompt


def test_interview_result_formats_feedback_and_next_question() -> None:
    result = InterviewPracticeResult(
        feedback="Add a concrete example.",
        strengths=["Clear structure"],
        improvements=["Explain the tradeoff"],
        next_question="How would you test that API?",
    )

    answer = _format_interview_practice(
        result, has_previous_turn=True, role_title="Backend Engineer"
    )

    assert "Feedback: Add a concrete example." in answer
    assert "What worked: Clear structure" in answer
    assert "Try improving: Explain the tradeoff" in answer
    assert "Next question: How would you test that API?" in answer


def test_interview_result_rejects_unexpected_model_fields() -> None:
    with pytest.raises(ValidationError):
        InterviewPracticeResult.model_validate(
            {
                "feedback": "",
                "strengths": [],
                "improvements": [],
                "next_question": "Tell me about a project.",
                "eligibility": "eligible",
            }
        )
