from __future__ import annotations

import httpx

from scripts.estimate_pilot_cost import PilotCostInputs, estimate
from scripts.measure_pilot_http import measure, percentile


def test_percentile_interpolates_bounded_samples() -> None:
    assert percentile([10, 20, 30, 40], 0.5) == 25
    assert percentile([10, 20, 30, 40], 0.95) == 38.5


async def test_measure_aggregates_rounds_and_validates_response_body() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "unavailable"})

    async with httpx.AsyncClient(
        base_url="https://performance.example.com",
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await measure(
            client=client,
            name="provider_degraded",
            method="POST",
            path="/match",
            samples=5,
            rounds=2,
            concurrency=2,
            budget_p95_ms=1_000,
            expected_json={"status": "unavailable"},
        )

    assert result.status_counts == {"200": 10}
    assert result.error_rate == 0
    assert result.rounds == 2
    assert result.throughput_rps > 0
    assert result.passed


def test_cost_estimate_never_claims_an_unpriced_ceiling() -> None:
    result = estimate(
        PilotCostInputs(
            students=500,
            resumes_per_student_month=2,
            semantic_requests_per_student_month=20,
            average_resume_megabytes=1,
            average_embedding_tokens=2_500,
            fixed_infrastructure_usd=200,
            storage_usd_per_gb_month=0,
            embedding_usd_per_million_tokens=0,
            scanner_usd_per_upload=0,
            monthly_ceiling_usd=300,
            pricing_source=None,
        )
    )

    assert result["pricing_complete"] is False
    assert result["within_proposed_ceiling"] is None
