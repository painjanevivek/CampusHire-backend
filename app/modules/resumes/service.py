import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pymupdf


class InvalidResumeError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedResume:
    page_count: int
    text: str


def sanitize_filename(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(value).name).strip(" .")
    return (clean or "resume.pdf")[:200]


def validate_pdf(data: bytes, declared_type: str, max_bytes: int, max_pages: int) -> ParsedResume:
    if len(data) > max_bytes:
        raise InvalidResumeError("resume_too_large")
    if declared_type != "application/pdf" or not data.startswith(b"%PDF-"):
        raise InvalidResumeError("resume_not_pdf")
    try:
        document = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
        if document.needs_pass:
            raise InvalidResumeError("resume_encrypted")
        if document.page_count < 1 or document.page_count > max_pages:
            raise InvalidResumeError("resume_page_limit")
        page_count = document.page_count
        text = "\n".join(
            document[index].get_text("text")  # type: ignore[no-untyped-call]
            for index in range(page_count)
        )[:100_000]
        document.close()  # type: ignore[no-untyped-call]
    except InvalidResumeError:
        raise
    except Exception as error:
        raise InvalidResumeError("resume_malformed") from error
    return ParsedResume(page_count=page_count, text=text)


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
