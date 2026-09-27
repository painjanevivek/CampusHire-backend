"""Bounded, one-turn media preparation for student Copilot questions."""

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

import pymupdf
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 12_000_000
MAX_WORD_UNCOMPRESSED_BYTES = 30 * 1024 * 1024
MAX_DOCUMENT_CONTEXT_CHARS = 25_000
_WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class InvalidChatAttachment(ValueError):
    pass


@dataclass(frozen=True)
class ChatAttachment:
    filename: str
    mime_type: str
    model_bytes: bytes | None
    extracted_text: str


def _safe_name(filename: str) -> str:
    leaf = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    return re.sub(r"[^A-Za-z0-9._ -]", "_", leaf).strip(" .")[:120] or "attachment"


def _word_text(data: bytes) -> str:
    try:
        with ZipFile(BytesIO(data)) as archive:
            members = archive.infolist()
            if (
                len(members) > 300
                or sum(item.file_size for item in members) > MAX_WORD_UNCOMPRESSED_BYTES
            ):
                raise InvalidChatAttachment("This Word document is too complex to process.")
            if "word/document.xml" not in archive.namelist() or any(
                item.filename.lower().endswith("vbaproject.bin") for item in members
            ):
                raise InvalidChatAttachment("Choose a standard .docx document without macros.")
            document = archive.open("word/document.xml").read(MAX_WORD_UNCOMPRESSED_BYTES + 1)
            if len(document) > MAX_WORD_UNCOMPRESSED_BYTES:
                raise InvalidChatAttachment("This Word document is too large to read.")
            if b"<!DOCTYPE" in document.upper() or b"<!ENTITY" in document.upper():
                raise InvalidChatAttachment("This Word document contains unsupported XML.")
        # DOCX does not require DTDs; bounded input and the check above reject entity expansion.
        root = ElementTree.fromstring(document)  # noqa: S314
        paragraphs = [
            "".join(node.text or "" for node in paragraph.iter(f"{_WORD_NAMESPACE}t"))
            for paragraph in root.iter(f"{_WORD_NAMESPACE}p")
        ]
        content = "\n".join(line for line in paragraphs if line.strip()).strip()
        if not content:
            raise InvalidChatAttachment(
                "This Word document has no readable text. Export it as a PDF and try again."
            )
        return content[:MAX_DOCUMENT_CONTEXT_CHARS]
    except (BadZipFile, KeyError, ElementTree.ParseError, OSError) as exc:
        raise InvalidChatAttachment("This Word document could not be read.") from exc


def prepare_chat_attachment(data: bytes, content_type: str, filename: str) -> ChatAttachment:
    name = _safe_name(filename)
    extension = PurePath(name).suffix.lower()
    if not data or len(data) > MAX_ATTACHMENT_BYTES:
        raise InvalidChatAttachment("Choose a file smaller than 10 MB.")

    if extension == ".pdf":
        if content_type not in {"application/pdf", "application/octet-stream", ""}:
            raise InvalidChatAttachment("The file type does not match its .pdf extension.")
        if not data.startswith(b"%PDF-"):
            raise InvalidChatAttachment("This is not a valid PDF.")
        try:
            with pymupdf.open(stream=data, filetype="pdf") as document:  # type: ignore[no-untyped-call]
                if document.needs_pass or not 1 <= document.page_count <= 80:
                    raise InvalidChatAttachment("Choose an unlocked PDF with 1 to 80 pages.")
                excerpt = "\n".join(
                    document[index].get_text() for index in range(min(document.page_count, 12))
                )[:MAX_DOCUMENT_CONTEXT_CHARS]
        except (ValueError, RuntimeError) as exc:
            raise InvalidChatAttachment("This PDF could not be read.") from exc
        return ChatAttachment(name, "application/pdf", data, excerpt)

    if extension == ".docx":
        if content_type not in {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/octet-stream",
            "",
        }:
            raise InvalidChatAttachment("The file type does not match its .docx extension.")
        return ChatAttachment(name, "text/plain", None, _word_text(data))

    if extension in {".jpg", ".jpeg", ".png"}:
        expected = "JPEG" if extension in {".jpg", ".jpeg"} else "PNG"
        mime_type = "image/jpeg" if expected == "JPEG" else "image/png"
        if content_type not in {mime_type, "application/octet-stream", ""}:
            raise InvalidChatAttachment("The image type does not match its extension.")
        try:
            with Image.open(BytesIO(data), formats=["JPEG", "PNG"]) as image:
                if image.format != expected or image.width * image.height > MAX_IMAGE_PIXELS:
                    raise InvalidChatAttachment("Choose a JPEG or PNG image under 12 megapixels.")
                if getattr(image, "n_frames", 1) != 1:
                    raise InvalidChatAttachment("Choose a still image.")
                image.load()
                oriented = ImageOps.exif_transpose(image)
                oriented.thumbnail((2048, 2048))
                output = BytesIO()
                if expected == "JPEG":
                    oriented.convert("RGB").save(output, format="JPEG", quality=88)
                else:
                    oriented.convert("RGBA").save(output, format="PNG", optimize=True)
                normalized = output.getvalue()
                if len(normalized) > MAX_ATTACHMENT_BYTES:
                    raise InvalidChatAttachment("Choose a smaller image.")
                return ChatAttachment(name, mime_type, normalized, "")
        except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
            raise InvalidChatAttachment("This image could not be read.") from exc

    raise InvalidChatAttachment("Upload a PDF, Word (.docx), JPEG, or PNG file.")
