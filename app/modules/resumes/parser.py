import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.config import Settings

PROTOCOL_VERSION = "1"
MAX_EXTRACTED_TEXT_CHARS = 100_000
MAX_RESULT_BYTES = 192 * 1024
PARSER_ERROR_CODES = {
    "resume_encrypted",
    "resume_malformed",
    "resume_not_pdf",
    "resume_page_limit",
    "resume_too_large",
}
_IMAGE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}$")


class InvalidResumeError(ValueError):
    pass


class ParserUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class ParsedResume:
    page_count: int
    text: str


class PdfParser(Protocol):
    def parse(self, data: bytes, *, max_bytes: int, max_pages: int) -> ParsedResume: ...


class _ParserResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    protocol_version: Literal["1"]
    status: Literal["ok", "error"]
    page_count: int | None = Field(default=None, ge=1, le=20)
    text: str | None = Field(default=None, max_length=MAX_EXTRACTED_TEXT_CHARS)
    error_code: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_shape(self) -> "_ParserResult":
        if self.status == "ok":
            if self.page_count is None or self.text is None or self.error_code is not None:
                raise ValueError("invalid success result")
        elif (
            self.page_count is not None
            or self.text is not None
            or self.error_code not in PARSER_ERROR_CODES
        ):
            raise ValueError("invalid error result")
        return self


def _decode_result(raw: bytes, *, max_pages: int) -> ParsedResume:
    if not raw or len(raw) > MAX_RESULT_BYTES:
        raise ParserUnavailableError("resume_parser_invalid_output")
    try:
        result = _ParserResult.model_validate_json(raw)
    except ValidationError as error:
        raise ParserUnavailableError("resume_parser_invalid_output") from error
    if result.status == "error":
        if result.error_code is None:
            raise ParserUnavailableError("resume_parser_invalid_output")
        raise InvalidResumeError(result.error_code)
    if result.page_count is None or result.text is None or result.page_count > max_pages:
        raise ParserUnavailableError("resume_parser_invalid_output")
    return ParsedResume(page_count=result.page_count, text=result.text)


def _minimal_subprocess_environment() -> dict[str, str]:
    allowed = (
        "PATH",
        "SystemRoot",
        "SYSTEMROOT",
        "SystemDrive",
        "SYSTEMDRIVE",
        "WINDIR",
        "ProgramData",
        "PROGRAMDATA",
        "LOCALAPPDATA",
        "TEMP",
        "TMP",
    )
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


class SubprocessPdfParser:
    """Credential-minimized development adapter; never valid for staging or production."""

    def __init__(self, *, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        self.runtime_script = Path(__file__).resolve().parents[3] / "parser_runtime" / "main.py"

    def parse(self, data: bytes, *, max_bytes: int, max_pages: int) -> ParsedResume:
        command = [
            sys.executable,
            "-I",
            str(self.runtime_script),
            "--max-bytes",
            str(max_bytes),
            "--max-pages",
            str(max_pages),
            "--max-text-chars",
            str(MAX_EXTRACTED_TEXT_CHARS),
            "--output",
            "-",
        ]
        try:
            result = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
                command,
                input=data,
                capture_output=True,
                check=False,
                timeout=self.timeout_seconds,
                env=_minimal_subprocess_environment(),
            )
        except subprocess.TimeoutExpired as error:
            raise ParserUnavailableError("resume_parser_timeout") from error
        except OSError as error:
            raise ParserUnavailableError("resume_parser_unavailable") from error
        if result.returncode != 0:
            raise ParserUnavailableError("resume_parser_unavailable")
        return _decode_result(result.stdout, max_pages=max_pages)


class DockerPdfParser:
    """Runs each parse in an ephemeral container with no credentials, network, or mounts."""

    def __init__(
        self,
        *,
        image: str,
        timeout_seconds: float,
        memory_megabytes: int,
        cpus: float,
        pids_limit: int,
        docker_binary: str = "docker",
    ) -> None:
        if not _IMAGE_PATTERN.fullmatch(image) or image.startswith("-"):
            raise ValueError("RESUME_PARSER_IMAGE must be a valid image reference")
        self.image = image
        self.timeout_seconds = timeout_seconds
        self.memory_megabytes = memory_megabytes
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.docker_binary = docker_binary

    def create_command(
        self,
        container_name: str,
        *,
        max_bytes: int,
        max_pages: int,
        output_directory: Path,
    ) -> list[str]:
        return [
            self.docker_binary,
            "create",
            "--interactive",
            "--name",
            container_name,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65532:65532",
            "--pids-limit",
            str(self.pids_limit),
            "--memory",
            f"{self.memory_megabytes}m",
            "--memory-swap",
            f"{self.memory_megabytes}m",
            "--cpus",
            str(self.cpus),
            "--ulimit",
            "fsize=262144:262144",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",  # noqa: S108
            "--mount",
            f"type=bind,source={output_directory.resolve()},target=/output",
            self.image,
            "--max-bytes",
            str(max_bytes),
            "--max-pages",
            str(max_pages),
            "--max-text-chars",
            str(MAX_EXTRACTED_TEXT_CHARS),
            "--output",
            "/output/result.json",
        ]

    def _run_control(self, command: list[str], *, timeout: float = 15.0) -> None:
        try:
            result = subprocess.run(  # noqa: S603 - argv is constructed without a shell
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ParserUnavailableError("resume_parser_unavailable") from error
        if result.returncode != 0:
            raise ParserUnavailableError("resume_parser_unavailable")

    def parse(self, data: bytes, *, max_bytes: int, max_pages: int) -> ParsedResume:
        container_name = f"campushire-parser-{uuid4().hex}"
        created = False
        with tempfile.TemporaryDirectory(prefix="campushire-parser-result-") as directory:
            output_directory = Path(directory)
            output_directory.chmod(0o733)
            try:
                self._run_control(
                    self.create_command(
                        container_name,
                        max_bytes=max_bytes,
                        max_pages=max_pages,
                        output_directory=output_directory,
                    )
                )
                created = True
                try:
                    process = subprocess.Popen(  # noqa: S603 - fixed docker operation and name
                        [self.docker_binary, "start", "--attach", "--interactive", container_name],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    process.communicate(input=data, timeout=self.timeout_seconds)
                except subprocess.TimeoutExpired as error:
                    self._terminate_container(container_name)
                    process.kill()
                    process.wait(timeout=5)
                    raise ParserUnavailableError("resume_parser_timeout") from error
                except OSError as error:
                    raise ParserUnavailableError("resume_parser_unavailable") from error
                if process.returncode != 0:
                    raise ParserUnavailableError("resume_parser_unavailable")

                target = Path(directory) / "result.json"
                try:
                    size = target.stat().st_size
                    if size < 1 or size > MAX_RESULT_BYTES:
                        raise ParserUnavailableError("resume_parser_invalid_output")
                    raw = target.read_bytes()
                except OSError as error:
                    raise ParserUnavailableError("resume_parser_invalid_output") from error
                return _decode_result(raw, max_pages=max_pages)
            finally:
                if created:
                    self._terminate_container(container_name)

    def _terminate_container(self, container_name: str) -> None:
        try:
            subprocess.run(  # noqa: S603 - fixed cleanup operation and generated name
                [self.docker_binary, "rm", "--force", container_name],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return


def build_pdf_parser(settings: Settings) -> PdfParser:
    if settings.resume_parser_backend == "docker":
        return DockerPdfParser(
            image=settings.resume_parser_image,
            timeout_seconds=settings.resume_parser_timeout_seconds,
            memory_megabytes=settings.resume_parser_memory_megabytes,
            cpus=settings.resume_parser_cpus,
            pids_limit=settings.resume_parser_pids_limit,
        )
    return SubprocessPdfParser(timeout_seconds=settings.resume_parser_timeout_seconds)
