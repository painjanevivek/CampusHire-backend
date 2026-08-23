import pymupdf
import pytest

from app.core.config import Settings
from app.modules.resumes.scanner import MarkerScanner
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


@pytest.mark.asyncio
async def test_development_scanner_quarantines_standard_malware_marker() -> None:
    result = await MarkerScanner().scan(b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE")
    assert result.clean is False
    assert result.signature == "EICAR-Test-Signature"


def test_production_cannot_start_with_the_marker_scanner() -> None:
    with pytest.raises(ValueError, match="MALWARE_SCANNER=clamav"):
        Settings(app_env="production", malware_scanner="marker")
