import re
from pathlib import Path
from uuid import uuid4

from app.modules.resumes.parser import InvalidResumeError


def sanitize_filename(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(value).name).strip(" .")
    return (clean or "resume.pdf")[:200]


def validate_upload_envelope(data: bytes, declared_type: str, max_bytes: int) -> None:
    if len(data) > max_bytes:
        raise InvalidResumeError("resume_too_large")
    if declared_type != "application/pdf" or not data.startswith(b"%PDF-"):
        raise InvalidResumeError("resume_not_pdf")


def store_pdf(data: bytes, root: str) -> str:
    base = Path(root).resolve()
    base.mkdir(parents=True, exist_ok=True)
    key = f"{uuid4()}.pdf"
    target = (base / key).resolve()
    if target.parent != base:
        raise InvalidResumeError("resume_storage_path")
    target.write_bytes(data)
    return key


def resolve_storage_key(root: str, key: str) -> Path:
    base = Path(root).resolve()
    target = (base / key).resolve()
    if target.parent != base or target.suffix != ".pdf":
        raise InvalidResumeError("resume_storage_path")
    return target
