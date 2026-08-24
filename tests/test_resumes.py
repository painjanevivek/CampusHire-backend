import pymupdf
import pytest

from app.core.config import Settings
from app.modules.resumes.parser import InvalidResumeError, SubprocessPdfParser
from app.modules.resumes.scanner import MarkerScanner
from app.modules.resumes.service import sanitize_filename, validate_upload_envelope


def sample_pdf(pages: int = 1) -> bytes:
    document = pymupdf.open()
    for index in range(pages):
        page = document.new_page()
        page.insert_text((72, 72), f"Resume page {index + 1}")
    data = document.tobytes()
    document.close()
    return data


def test_valid_pdf_is_parsed_with_selectable_text() -> None:
    data = sample_pdf()
    validate_upload_envelope(data, "application/pdf", 5_000_000)
    parsed = SubprocessPdfParser(timeout_seconds=10).parse(
        data, max_bytes=5_000_000, max_pages=3
    )
    assert parsed.page_count == 1
    assert "Resume page 1" in parsed.text


def test_non_pdf_and_excess_pages_are_rejected() -> None:
    with pytest.raises(InvalidResumeError, match="resume_not_pdf"):
        validate_upload_envelope(b"not a pdf", "application/pdf", 5_000_000)
    with pytest.raises(InvalidResumeError, match="resume_page_limit"):
        SubprocessPdfParser(timeout_seconds=10).parse(
            sample_pdf(4), max_bytes=5_000_000, max_pages=3
        )


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


def test_production_requires_the_container_parser() -> None:
    with pytest.raises(ValueError, match="RESUME_PARSER_BACKEND=docker"):
        Settings(app_env="production", malware_scanner="clamav", resume_parser_backend="subprocess")


def test_staging_requires_https_and_explicit_trusted_hosts() -> None:
    with pytest.raises(ValueError, match="HTTPS FRONTEND_ORIGINS"):
        Settings(
            app_env="staging",
            malware_scanner="clamav",
            resume_parser_backend="docker",
            frontend_origins=["http://staging.example.edu"],
        )
    with pytest.raises(ValueError, match="explicit TRUSTED_HOSTS"):
        Settings(
            app_env="staging",
            malware_scanner="clamav",
            resume_parser_backend="docker",
            frontend_origins=["https://staging.example.edu"],
            trusted_hosts=["*"],
        )
