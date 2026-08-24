import json
import os
from pathlib import Path

import pymupdf
import pytest

from app.core.config import Settings
from app.modules.resumes.parser import (
    MAX_RESULT_BYTES,
    DockerPdfParser,
    InvalidResumeError,
    ParserUnavailableError,
    SubprocessPdfParser,
    _decode_result,
    _minimal_subprocess_environment,
)


def sample_pdf(pages: int = 1) -> bytes:
    document = pymupdf.open()
    for index in range(pages):
        page = document.new_page()
        page.insert_text((72, 72), f"Sandboxed resume page {index + 1}")
    data = document.tobytes()
    document.close()
    return data


def encrypted_pdf() -> bytes:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Protected resume")
    data = document.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner-password",
        user_pw="user-password",
    )
    document.close()
    return data


def docker_parser() -> DockerPdfParser:
    return DockerPdfParser(
        image="campushire-pdf-parser:test",
        timeout_seconds=20,
        memory_megabytes=256,
        cpus=0.5,
        pids_limit=32,
    )


def test_production_configuration_accepts_only_the_sandbox_backend() -> None:
    settings = Settings(
        app_env="production",
        malware_scanner="clamav",
        resume_parser_backend="docker",
        resume_parser_image="registry.example.edu/campushire/parser@sha256:abc123",
        frontend_origins=["https://staging.example.edu"],
        trusted_hosts=["staging.example.edu"],
    )
    assert settings.resume_parser_backend == "docker"
    with pytest.raises(ValueError, match="valid image reference"):
        DockerPdfParser(
            image="--privileged",
            timeout_seconds=20,
            memory_megabytes=256,
            cpus=0.5,
            pids_limit=32,
        )


def test_subprocess_environment_excludes_application_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    environment = _minimal_subprocess_environment()
    assert "DATABASE_URL" not in environment
    assert "GEMINI_API_KEY" not in environment


def test_parser_result_rejects_extra_fields_and_oversized_output() -> None:
    payload = {
        "protocol_version": "1",
        "status": "ok",
        "page_count": 1,
        "text": "safe",
        "error_code": None,
        "unexpected": True,
    }
    with pytest.raises(ParserUnavailableError, match="resume_parser_invalid_output"):
        _decode_result(json.dumps(payload).encode(), max_pages=3)
    with pytest.raises(ParserUnavailableError, match="resume_parser_invalid_output"):
        _decode_result(b"x" * (MAX_RESULT_BYTES + 1), max_pages=3)


def test_docker_command_enforces_the_parser_security_boundary() -> None:
    command = docker_parser().create_command(
        "campushire-parser-test",
        max_bytes=5 * 1024 * 1024,
        max_pages=3,
        output_directory=Path("parser-output"),
    )
    joined = " ".join(command)
    assert "--network none" in joined
    assert "--read-only" in command
    assert "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined
    assert "--user 65532:65532" in joined
    assert "--pids-limit 32" in joined
    assert "--memory 256m" in joined
    assert "--memory-swap 256m" in joined
    assert "--cpus 0.5" in joined
    assert "--ulimit fsize=262144:262144" in joined
    assert "--env" not in command
    assert "--volume" not in command
    assert command.count("--mount") == 1
    assert "target=/output" in joined


def test_privileged_worker_path_has_no_native_parser_sink() -> None:
    repository = Path(__file__).resolve().parents[1]
    pipeline_source = (repository / "app/modules/resumes/pipeline.py").read_text(encoding="utf-8")
    worker_source = (repository / "app/worker.py").read_text(encoding="utf-8")
    for source in (pipeline_source, worker_source):
        assert "pymupdf" not in source
        assert "parse_pdf(" not in source


def test_subprocess_parser_preserves_valid_and_invalid_document_behavior() -> None:
    parser = SubprocessPdfParser(timeout_seconds=10)
    parsed = parser.parse(sample_pdf(), max_bytes=5_000_000, max_pages=3)
    assert parsed.page_count == 1
    assert "Sandboxed resume page 1" in parsed.text
    with pytest.raises(InvalidResumeError, match="resume_page_limit"):
        parser.parse(sample_pdf(4), max_bytes=5_000_000, max_pages=3)
    with pytest.raises(InvalidResumeError, match="resume_not_pdf"):
        parser.parse(b"not a pdf", max_bytes=5_000_000, max_pages=3)
    with pytest.raises(InvalidResumeError, match="resume_malformed"):
        parser.parse(b"%PDF-malformed", max_bytes=5_000_000, max_pages=3)
    with pytest.raises(InvalidResumeError, match="resume_encrypted"):
        parser.parse(encrypted_pdf(), max_bytes=5_000_000, max_pages=3)
    with pytest.raises(InvalidResumeError, match="resume_too_large"):
        parser.parse(sample_pdf() + b"x" * 2_000, max_bytes=1_024, max_pages=3)


@pytest.mark.skipif(
    os.getenv("RUN_PARSER_CONTAINER_TESTS") != "1",
    reason="requires the pinned parser container image",
)
def test_container_parser_preserves_valid_and_invalid_document_behavior() -> None:
    parser = docker_parser()
    parsed = parser.parse(sample_pdf(), max_bytes=5_000_000, max_pages=3)
    assert parsed.page_count == 1
    assert "Sandboxed resume page 1" in parsed.text
    with pytest.raises(InvalidResumeError, match="resume_page_limit"):
        parser.parse(sample_pdf(4), max_bytes=5_000_000, max_pages=3)
