"""Profile read-only experience queries using configured local synthetic accounts."""

import asyncio
import json
import platform
from pathlib import Path
from time import perf_counter

from sqlalchemy import event, func, select, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.core.database import SessionFactory, engine
from app.models.auth import User
from app.models.recruitment import Application, PlacementDrive, PlacementRole
from app.modules.engagement.service import dashboard
from app.modules.experience.publishing import publication_preview
from app.modules.experience.queries import review_queue
from app.modules.recruitment.service import list_opportunities


async def main() -> None:
    settings = get_settings()
    if (
        make_url(settings.database_url).host not in {"localhost", "127.0.0.1"}
        or not settings.demo_login_enabled
    ):
        raise RuntimeError("Use a configured local synthetic database only.")
    timings: list[float] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def before(conn, cursor, statement, parameters, context, executemany):
        context._experience_started = perf_counter()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def after(conn, cursor, statement, parameters, context, executemany):
        timings.append((perf_counter() - context._experience_started) * 1000)

    result: dict[str, object] = {
        "profile": "local PostgreSQL; configured synthetic student; no throttling",
        "hardware": platform.processor(),
        "measurements": [],
    }
    async with SessionFactory() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        student = await db.scalar(
            select(User).where(User.email == str(settings.demo_student_email))
        )
        assert student and student.institution_id
        institution = student.institution_id
        drive = await db.scalar(
            select(PlacementDrive).where(PlacementDrive.institution_id == institution).limit(1)
        )
        assert drive
        counts = {
            model.__tablename__: await db.scalar(
                select(func.count()).select_from(model).where(model.institution_id == institution)
            )
            for model in [Application, PlacementDrive, PlacementRole]
        }
        result["fixture_counts"] = counts
        result["queue_query_plan"] = (
            await db.execute(
                text(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT id, status, revision "
                    "FROM applications WHERE institution_id = :institution "
                    "ORDER BY created_at DESC, id LIMIT 25"
                ),
                {"institution": institution},
            )
        ).scalar()
        measurements = []
        for name, operation in [
            ("student_dashboard", lambda: dashboard(db, institution, student.id)),
            (
                "opportunities",
                lambda: list_opportunities(
                    db,
                    institution,
                    student.id,
                    query=None,
                    location=None,
                    work_mode=None,
                    skill=None,
                    saved_only=False,
                    page=1,
                    page_size=20,
                ),
            ),
            ("candidate_queue", lambda: review_queue(db, institution)),
            ("drive_publication_preview", lambda: publication_preview(db, institution, drive.id)),
        ]:
            samples = []
            for _ in range(30):
                timings.clear()
                start = perf_counter()
                await operation()
                samples.append(
                    {
                        "elapsed_ms": round((perf_counter() - start) * 1000, 2),
                        "query_count": len(timings),
                        "query_duration_ms": round(sum(timings), 2),
                    }
                )
            measurements.append({"flow": name, "samples": samples})
        result["measurements"] = measurements
        await db.rollback()
    output = Path(".data/experience-query-profile.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(
        output.write_text, json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(output), "fixture_counts": counts, "flows": len(measurements)}))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
