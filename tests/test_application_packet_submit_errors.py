from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.routes import application_packets
from app.modules.application_packets.schemas import DraftSubmitRequest
from app.modules.recruitment.service import RecruitmentError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "expected_status"),
    [("application_already_exists", 409), ("application_not_eligible", 422)],
)
async def test_submit_maps_known_recruitment_errors(
    monkeypatch: pytest.MonkeyPatch, code: str, expected_status: int
) -> None:
    async def reject_submission(*_args: object, **_kwargs: object) -> None:
        raise RecruitmentError(code)

    monkeypatch.setattr(application_packets, "submit_draft", reject_submission)
    tenant = SimpleNamespace(institution_id=uuid4(), user_id=uuid4())
    payload = DraftSubmitRequest(
        expected_revision=1, confirmation="I CONFIRM THIS APPLICATION IS ACCURATE"
    )

    with pytest.raises(HTTPException) as raised:
        await application_packets.submit_application_draft(
            request=SimpleNamespace(),
            draft_id=uuid4(),
            payload=payload,
            db=SimpleNamespace(),
            tenant=tenant,
            idempotency_key="safe-retry-key",
        )

    assert raised.value.status_code == expected_status
    assert raised.value.detail == code
