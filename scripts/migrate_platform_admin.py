"""Nominate the one Platform Admin. Dry-run is the default and is safe to repeat."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from uuid import UUID

from app.core.database import SessionFactory
from app.modules.platform_admin.service import (
    PlatformAdminAssignmentError,
    preview_platform_admin_migration,
    transfer_platform_admin,
)


async def run(*, user_id: UUID, apply: bool, reason: str) -> dict[str, object]:
    async with SessionFactory() as db:
        preview = await preview_platform_admin_migration(db, user_id=user_id)
        result: dict[str, object] = {
            **asdict(preview),
            "nominated_user_id": str(preview.nominated_user_id),
            "current_admin_user_id": (
                str(preview.current_admin_user_id) if preview.current_admin_user_id else None
            ),
            "nominated_membership_ids": [str(item) for item in preview.nominated_membership_ids],
            "mode": "apply" if apply else "dry-run",
        }
        if not apply:
            return result
        assignment = await transfer_platform_admin(
            db,
            user_id=user_id,
            reason=reason,
            actor_user_id=None,
        )
        result.update({"assignment_revision": assignment.revision, "sessions_revoked": True})
        return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=UUID, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--reason",
        default="Explicit Platform Admin authority migration",
        help="Audited reason used only with --apply",
    )
    args = parser.parse_args()
    try:
        result = asyncio.run(run(user_id=args.user_id, apply=args.apply, reason=args.reason))
        print(json.dumps(result))
    except PlatformAdminAssignmentError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
