import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pymupdf

PROTOCOL_VERSION = "1"


class SafeParseError(ValueError):
    pass


def _success(page_count: int, text: str) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "status": "ok",
        "page_count": page_count,
        "text": text,
        "error_code": None,
    }


def _failure(code: str) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "status": "error",
        "page_count": None,
        "text": None,
        "error_code": code,
    }


def parse_pdf(data: bytes, *, max_pages: int, max_text_chars: int) -> dict[str, Any]:
    if not data.startswith(b"%PDF-"):
        raise SafeParseError("resume_not_pdf")
    try:
        with pymupdf.open(  # type: ignore[no-untyped-call]
            stream=data, filetype="pdf"
        ) as document:
            if document.needs_pass:
                raise SafeParseError("resume_encrypted")
            if document.page_count < 1 or document.page_count > max_pages:
                raise SafeParseError("resume_page_limit")
            chunks: list[str] = []
            remaining = max_text_chars
            for index in range(document.page_count):
                if remaining <= 0:
                    break
                chunk = document[index].get_text("text")[:remaining]
                chunks.append(chunk)
                remaining -= len(chunk)
            return _success(document.page_count, "\n".join(chunks)[:max_text_chars])
    except SafeParseError:
        raise
    except Exception as error:
        raise SafeParseError("resume_malformed") from error


def write_result(payload: dict[str, Any], output: str) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if output == "-":
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
        return
    target = Path(output)
    target.write_bytes(encoded)


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse one bounded PDF from standard input")
    parser.add_argument("--max-bytes", required=True, type=int)
    parser.add_argument("--max-pages", required=True, type=int)
    parser.add_argument("--max-text-chars", required=True, type=int)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not 1_024 <= args.max_bytes <= 50 * 1024 * 1024:
        return 2
    if not 1 <= args.max_pages <= 20:
        return 2
    if not 1_000 <= args.max_text_chars <= 100_000:
        return 2
    data = sys.stdin.buffer.read(args.max_bytes + 1)
    if len(data) > args.max_bytes:
        payload = _failure("resume_too_large")
    else:
        try:
            payload = parse_pdf(
                data,
                max_pages=args.max_pages,
                max_text_chars=args.max_text_chars,
            )
        except SafeParseError as error:
            payload = _failure(str(error))
    write_result(payload, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
