import pymupdf
import pytest

from app.modules.resumes.service import InvalidResumeError, sanitize_filename, validate_pdf


def sample_pdf(pages: int = 1) -> bytes:
    document = pymupdf.open()
    for index in range(pages):
        page = document.new_page()
        page.insert_text((72, 72), f"Resume page {index + 1}")
    data = document.tobytes()
    document.close()
    return data


def test_valid_pdf_is_parsed_with_selectable_text() -> None:
    parsed = validate_pdf(sample_pdf(), "application/pdf", 5_000_000, 3)
    assert parsed.page_count == 1
    assert "Resume page 1" in parsed.text


def test_non_pdf_and_excess_pages_are_rejected() -> None:
    with pytest.raises(InvalidResumeError, match="resume_not_pdf"):
        validate_pdf(b"not a pdf", "application/pdf", 5_000_000, 3)
    with pytest.raises(InvalidResumeError, match="resume_page_limit"):
        validate_pdf(sample_pdf(4), "application/pdf", 5_000_000, 3)


def test_filename_is_reduced_to_safe_metadata() -> None:
    assert sanitize_filename("../../Vivek<resume>.pdf") == "Vivek_resume_.pdf"
