"""Validate private, optional academic marksheet uploads."""

from io import BytesIO
from pathlib import PurePath

import pymupdf
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_ACADEMIC_DOCUMENT_BYTES = 5 * 1024 * 1024
MAX_ACADEMIC_IMAGE_PIXELS = 24_000_000


class InvalidAcademicDocument(ValueError):
    pass


def normalize_academic_document(data: bytes, content_type: str, filename: str) -> tuple[str, bytes]:
    """Allow bounded PDFs and freshly encoded still images, never trusting the extension alone."""
    if not data or len(data) > MAX_ACADEMIC_DOCUMENT_BYTES:
        raise InvalidAcademicDocument("Choose a marksheet smaller than 5 MB.")
    extension = PurePath(filename).suffix.lower()
    if content_type == "application/pdf" and extension == ".pdf":
        try:
            with pymupdf.open(stream=data, filetype="pdf") as document:  # type: ignore[no-untyped-call]
                if document.needs_pass or not 1 <= len(document) <= 5:
                    raise InvalidAcademicDocument("Choose an unlocked PDF with up to five pages.")
        except (pymupdf.FileDataError, pymupdf.EmptyFileError) as error:
            raise InvalidAcademicDocument("This PDF could not be read.") from error
        return "application/pdf", data
    expected = {"image/jpeg": ("JPEG", {".jpg", ".jpeg"}),
                "image/png": ("PNG", {".png"})}.get(content_type)
    if expected is None or extension not in expected[1]:
        raise InvalidAcademicDocument("Choose a PDF, JPEG, or PNG marksheet.")
    try:
        with Image.open(BytesIO(data), formats=["JPEG", "PNG"]) as source:
            if (
                source.format != expected[0]
                or source.width * source.height > MAX_ACADEMIC_IMAGE_PIXELS
            ):
                raise InvalidAcademicDocument("Choose a still image with at most 24 megapixels.")
            if getattr(source, "n_frames", 1) != 1:
                raise InvalidAcademicDocument("Animated images are not supported.")
            source.verify()
        with Image.open(BytesIO(data), formats=["JPEG", "PNG"]) as source:
            image = ImageOps.exif_transpose(source)
            image.load()
            clean = Image.new("RGB", image.size, "white")
            rgba = image.convert("RGBA")
            clean.paste(rgba, mask=rgba.getchannel("A"))
            output = BytesIO()
            clean.save(output, format="JPEG", quality=90)
            if output.tell() > MAX_ACADEMIC_DOCUMENT_BYTES:
                raise InvalidAcademicDocument("The marksheet is too large after processing.")
            return "image/jpeg", output.getvalue()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise InvalidAcademicDocument("This image could not be read.") from error
