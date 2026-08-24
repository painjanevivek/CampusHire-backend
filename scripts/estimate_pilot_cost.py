from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path


@dataclass(frozen=True)
class PilotCostInputs:
    students: int
    resumes_per_student_month: float
    semantic_requests_per_student_month: float
    average_resume_megabytes: float
    average_embedding_tokens: int
    fixed_infrastructure_usd: float
    storage_usd_per_gb_month: float
    embedding_usd_per_million_tokens: float
    scanner_usd_per_upload: float
    monthly_ceiling_usd: float
    pricing_source: str | None


def money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def estimate(inputs: PilotCostInputs) -> dict[str, object]:
    monthly_uploads = inputs.students * inputs.resumes_per_student_month
    monthly_semantic_requests = inputs.students * inputs.semantic_requests_per_student_month
    retained_gigabytes = monthly_uploads * inputs.average_resume_megabytes / 1_024
    embedding_tokens = monthly_semantic_requests * inputs.average_embedding_tokens
    storage_cost = retained_gigabytes * inputs.storage_usd_per_gb_month
    embedding_cost = embedding_tokens / 1_000_000 * inputs.embedding_usd_per_million_tokens
    scanner_cost = monthly_uploads * inputs.scanner_usd_per_upload
    total = inputs.fixed_infrastructure_usd + storage_cost + embedding_cost + scanner_cost
    pricing_complete = bool(inputs.pricing_source)
    return {
        "basis": "proposal-only until approved provider rates and pilot volume are supplied",
        "inputs": asdict(inputs),
        "monthly_demand": {
            "resume_uploads": round(monthly_uploads, 2),
            "semantic_requests": round(monthly_semantic_requests, 2),
            "retained_resume_gigabytes": round(retained_gigabytes, 3),
            "embedding_tokens": round(embedding_tokens),
        },
        "monthly_cost_usd": {
            "fixed_infrastructure": money(inputs.fixed_infrastructure_usd),
            "resume_storage": money(storage_cost),
            "embeddings": money(embedding_cost),
            "malware_scanning": money(scanner_cost),
            "estimated_total": money(total),
            "proposed_ceiling": money(inputs.monthly_ceiling_usd),
        },
        "pricing_complete": pricing_complete,
        "within_proposed_ceiling": total <= inputs.monthly_ceiling_usd
        if pricing_complete
        else None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Estimate a bounded CampusHire pilot cost model.")
    parser.add_argument("--students", type=int, default=500)
    parser.add_argument("--resumes-per-student-month", type=float, default=2)
    parser.add_argument("--semantic-requests-per-student-month", type=float, default=20)
    parser.add_argument("--average-resume-megabytes", type=float, default=1)
    parser.add_argument("--average-embedding-tokens", type=int, default=2_500)
    parser.add_argument("--fixed-infrastructure-usd", type=float, default=200)
    parser.add_argument("--storage-usd-per-gb-month", type=float, default=0)
    parser.add_argument("--embedding-usd-per-million-tokens", type=float, default=0)
    parser.add_argument("--scanner-usd-per-upload", type=float, default=0)
    parser.add_argument("--monthly-ceiling-usd", type=float, default=300)
    parser.add_argument("--pricing-source")
    parser.add_argument("--output", default=".data/pilot-cost-estimate.json")
    args = parser.parse_args()
    numeric = [
        args.students,
        args.resumes_per_student_month,
        args.semantic_requests_per_student_month,
        args.average_resume_megabytes,
        args.average_embedding_tokens,
        args.fixed_infrastructure_usd,
        args.storage_usd_per_gb_month,
        args.embedding_usd_per_million_tokens,
        args.scanner_usd_per_upload,
        args.monthly_ceiling_usd,
    ]
    if any(value < 0 for value in numeric) or args.students < 1:
        parser.error(
            "Demand, price, and ceiling inputs must be non-negative; students must be positive."
        )
    return args


def main() -> None:
    args = parse_args()
    inputs = PilotCostInputs(
        students=args.students,
        resumes_per_student_month=args.resumes_per_student_month,
        semantic_requests_per_student_month=args.semantic_requests_per_student_month,
        average_resume_megabytes=args.average_resume_megabytes,
        average_embedding_tokens=args.average_embedding_tokens,
        fixed_infrastructure_usd=args.fixed_infrastructure_usd,
        storage_usd_per_gb_month=args.storage_usd_per_gb_month,
        embedding_usd_per_million_tokens=args.embedding_usd_per_million_tokens,
        scanner_usd_per_upload=args.scanner_usd_per_upload,
        monthly_ceiling_usd=args.monthly_ceiling_usd,
        pricing_source=args.pricing_source,
    )
    result = estimate(inputs)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
