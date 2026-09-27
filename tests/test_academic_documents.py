from io import BytesIO

import pymupdf
import pytest
from PIL import Image

from app.modules.onboarding.documents import InvalidAcademicDocument, normalize_academic_document


def test_academic_image_upload_strips_metadata_but_keeps_readable_resolution() -> None:
    image = Image.new("RGB", (1600, 1100), "white")
    source = BytesIO()
    image.save(source, format="PNG")
    content_type, content = normalize_academic_document(
        source.getvalue(), "image/png", "marks.png"
    )
    assert content_type == "image/jpeg"
    with Image.open(BytesIO(content)) as clean:
        assert clean.size == (1600, 1100)


def test_academic_pdf_upload_requires_valid_pdf() -> None:
    document = pymupdf.open()
    document.new_page()
    pdf = document.tobytes()
    assert normalize_academic_document(pdf, "application/pdf", "marks.pdf") == (
        "application/pdf",
        pdf,
    )
    with pytest.raises(InvalidAcademicDocument):
        normalize_academic_document(b"not a pdf", "application/pdf", "marks.pdf")


def test_academic_upload_rejects_mismatched_file_extension() -> None:
    with pytest.raises(InvalidAcademicDocument):
        normalize_academic_document(b"irrelevant", "image/png", "marks.pdf")
