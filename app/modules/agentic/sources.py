import hashlib
import ipaddress
import json
import socket
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from anyio import to_thread
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.agentic import SourceVersion
from app.modules.agentic.schemas import (
    EscoSkill,
    SourceReview,
    SourceVersionCreate,
    SourceVersionResponse,
)
from app.modules.generative.service import require_capability


class SourceValidationError(Exception):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def _validate_external_url(url: str, settings: Settings) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold().rstrip(".")
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise SourceValidationError("source_url_invalid")
    allowed = any(
        host == domain or host.endswith(f".{domain}")
        for domain in settings.source_allowed_domains
    )
    if not allowed:
        raise SourceValidationError("source_domain_not_permitted")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except OSError as error:
        raise SourceValidationError("source_host_unavailable") from error
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise SourceValidationError("source_host_not_public")
    return url


def _fetch_metadata(source: SourceVersion, settings: Settings) -> dict[str, Any]:
    url = _validate_external_url(source.canonical_url, settings)
    headers = {
        "User-Agent": "CampusHire-SourceVerifier/1.0",
        "Accept": "text/html,application/json",
    }
    if source.etag:
        headers["If-None-Match"] = source.etag
    if source.last_modified:
        headers["If-Modified-Since"] = source.last_modified
    opener = build_opener(_NoRedirect())
    try:
        # URL scheme, host allowlist, and resolved public addresses are validated above.
        with opener.open(  # noqa: S310
            Request(url, headers=headers, method="HEAD"),  # noqa: S310
            timeout=10,
        ) as response:
            return {
                "status": response.status,
                "content_type": response.headers.get("Content-Type", "")[:200],
                "content_length": response.headers.get("Content-Length"),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "final_url": response.geturl(),
            }
    except (HTTPError, URLError, TimeoutError) as error:
        raise SourceValidationError("source_verification_failed") from error


def _metadata_digest(metadata: dict[str, Any]) -> str:
    stable = {key: value for key, value in metadata.items() if key != "status"}
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


async def register_source(
    db: AsyncSession,
    *,
    institution_id: UUID,
    payload: SourceVersionCreate,
) -> SourceVersionResponse:
    await require_capability(db, institution_id, "live_sources")
    _validate_external_url(payload.canonical_url, get_settings())
    latest = await db.scalar(
        select(SourceVersion)
        .where(
            SourceVersion.institution_id == institution_id,
            SourceVersion.canonical_url == payload.canonical_url,
        )
        .order_by(SourceVersion.version.desc())
        .limit(1)
    )
    item = SourceVersion(
        institution_id=institution_id,
        source_type=payload.source_type,
        canonical_url=payload.canonical_url,
        title=payload.title,
        version=(latest.version + 1) if latest else 1,
        review_status="pending",
        access_scope="institution",
        permitted_use=payload.permitted_use,
        source_metadata={},
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return source_response(item)


async def list_sources(db: AsyncSession, institution_id: UUID) -> list[SourceVersionResponse]:
    items = (
        await db.scalars(
            select(SourceVersion)
            .where(SourceVersion.institution_id == institution_id)
            .order_by(SourceVersion.canonical_url, SourceVersion.version.desc())
        )
    ).all()
    return [source_response(item) for item in items]


async def review_source(
    db: AsyncSession,
    *,
    institution_id: UUID,
    source_id: UUID,
    payload: SourceReview,
) -> SourceVersionResponse:
    item = await db.scalar(
        select(SourceVersion)
        .where(
            SourceVersion.id == source_id,
            SourceVersion.institution_id == institution_id,
        )
        .with_for_update()
    )
    if item is None:
        raise SourceValidationError("source_not_found")
    if item.version != payload.expected_version or item.review_status != "pending":
        raise SourceValidationError("source_review_conflict")
    item.review_status = "approved" if payload.decision == "approve" else "rejected"
    item.active = payload.decision == "approve"
    await db.commit()
    await db.refresh(item)
    return source_response(item)


async def sync_next_source(db: AsyncSession, *, settings: Settings | None = None) -> UUID | None:
    configured = settings or get_settings()
    due_before = datetime.now(UTC) - timedelta(days=1)
    item = await db.scalar(
        select(SourceVersion)
        .where(
            SourceVersion.review_status == "approved",
            (
                SourceVersion.last_verified_at.is_(None)
                | (SourceVersion.last_verified_at < due_before)
            ),
        )
        .order_by(SourceVersion.last_verified_at.asc().nullsfirst())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if item is None:
        return None
    now = datetime.now(UTC)
    try:
        metadata = await to_thread.run_sync(_fetch_metadata, item, configured)
        digest = _metadata_digest(metadata)
        if item.content_digest and digest != item.content_digest:
            pending = await db.scalar(
                select(SourceVersion).where(
                    SourceVersion.institution_id == item.institution_id,
                    SourceVersion.canonical_url == item.canonical_url,
                    SourceVersion.review_status == "pending",
                )
            )
            if pending is None:
                latest_version = await db.scalar(
                    select(SourceVersion.version)
                    .where(
                        SourceVersion.institution_id == item.institution_id,
                        SourceVersion.canonical_url == item.canonical_url,
                    )
                    .order_by(SourceVersion.version.desc())
                    .limit(1)
                )
                pending = SourceVersion(
                    institution_id=item.institution_id,
                    source_type=item.source_type,
                    canonical_url=item.canonical_url,
                    title=item.title,
                    version=int(latest_version or item.version) + 1,
                    review_status="pending",
                    access_scope=item.access_scope,
                    permitted_use=item.permitted_use,
                    source_metadata=metadata,
                    content_digest=digest,
                    retrieved_at=now,
                    last_verified_at=now,
                    etag=metadata.get("etag"),
                    last_modified=metadata.get("last_modified"),
                )
                db.add(pending)
            else:
                pending.source_metadata = metadata
                pending.content_digest = digest
                pending.retrieved_at = now
                pending.last_verified_at = now
                pending.etag = metadata.get("etag")
                pending.last_modified = metadata.get("last_modified")
            item.safe_error = "changed_source_pending_review"
            item.last_verified_at = now
        else:
            item.source_metadata = metadata
            item.content_digest = digest
            item.retrieved_at = now
            item.last_verified_at = now
            item.etag = metadata.get("etag")
            item.last_modified = metadata.get("last_modified")
            item.failed_at = None
            item.safe_error = None
            item.active = True
    except (SourceValidationError, HTTPError, URLError, TimeoutError):
        item.failed_at = now
        item.safe_error = "source_verification_failed"
        last_success = item.last_verified_at or item.retrieved_at
        stale_before = now - timedelta(days=configured.source_stale_after_days)
        if last_success is None or last_success < stale_before:
            item.active = False
    await db.commit()
    return item.id


def _esco_request(term: str) -> list[EscoSkill]:
    query = urlencode({"text": term, "type": "skill", "language": "en", "limit": 10})
    request = Request(
        f"https://ec.europa.eu/esco/api/search?{query}",
        headers={"User-Agent": "CampusHire-ESCO/1.0", "Accept": "application/json"},
    )
    try:
        with build_opener(_NoRedirect()).open(request, timeout=10) as response:
            payload = json.loads(response.read(512_000))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise SourceValidationError("esco_unavailable") from error
    embedded = payload.get("_embedded", {}) if isinstance(payload, dict) else {}
    results = embedded.get("results", []) if isinstance(embedded, dict) else []
    skills: list[EscoSkill] = []
    for result in results[:10]:
        if not isinstance(result, dict):
            continue
        uri = str(result.get("uri") or "")
        label = str(result.get("preferredLabel") or result.get("title") or "")
        if uri and label:
            skills.append(
                EscoSkill(
                    uri=uri,
                    preferred_label=label,
                    description=str(result.get("description") or "") or None,
                )
            )
    return skills


async def lookup_esco(
    db: AsyncSession, *, institution_id: UUID, term: str
) -> list[EscoSkill]:
    await require_capability(db, institution_id, "live_sources")
    clean_term = term.strip()
    if len(clean_term) < 2 or len(clean_term) > 120:
        raise SourceValidationError("esco_term_invalid")
    return await to_thread.run_sync(_esco_request, clean_term)


def source_response(item: SourceVersion) -> SourceVersionResponse:
    return SourceVersionResponse(
        id=item.id,
        source_type=item.source_type,
        canonical_url=item.canonical_url,
        title=item.title,
        version=item.version,
        review_status=item.review_status,
        access_scope=item.access_scope,
        permitted_use=item.permitted_use,
        metadata=dict(item.source_metadata),
        last_verified_at=item.last_verified_at,
        safe_error=item.safe_error,
        active=item.active,
    )
