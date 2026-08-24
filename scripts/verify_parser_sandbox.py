import argparse
import json
import subprocess
from typing import Any
from uuid import uuid4

import pymupdf

from app.modules.resumes.parser import DockerPdfParser, ParserUnavailableError

SENSITIVE_ENVIRONMENT = {
    "CLAMAV_HOST",
    "DATABASE_URL",
    "GEMINI_API_KEY",
    "QDRANT_URL",
    "REDIS_URL",
    "SESSION_COOKIE_NAME",
}


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - fixed Docker operations and generated container name
        command,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=60,
    )


def sample_pdf() -> bytes:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    page = document.new_page()
    page.insert_text((72, 72), "CampusHire parser isolation evidence")
    data = bytes(document.tobytes())  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]
    return data


def assert_policy(document: dict[str, Any]) -> None:
    config = document["Config"]
    host = document["HostConfig"]
    assert config["User"] == "65532:65532"
    assert host["NetworkMode"] == "none"
    assert host["ReadonlyRootfs"] is True
    assert "ALL" in host["CapDrop"]
    assert "no-new-privileges" in host["SecurityOpt"]
    assert host["PidsLimit"] == 32
    assert host["Memory"] == 256 * 1024 * 1024
    assert host["MemorySwap"] == 256 * 1024 * 1024
    assert host["NanoCpus"] == 500_000_000
    assert "/tmp" in host["Tmpfs"]  # noqa: S108 - verifying the isolated tmpfs mount
    assert host["Ulimits"] == [{"Name": "fsize", "Hard": 262144, "Soft": 262144}]
    assert document["Mounts"] == []
    assert config["Cmd"][-2:] == ["--output", "-"]
    names = {item.partition("=")[0] for item in config.get("Env") or []}
    assert names.isdisjoint(SENSITIVE_ENVIRONMENT)


def main() -> int:
    argument_parser = argparse.ArgumentParser(description="Verify the PDF parser container policy")
    argument_parser.add_argument("--image", default="campushire-pdf-parser:test")
    args = argument_parser.parse_args()
    parser = DockerPdfParser(
        image=args.image,
        timeout_seconds=20,
        memory_megabytes=256,
        cpus=0.5,
        pids_limit=32,
    )
    container_name = f"campushire-parser-policy-{uuid4().hex}"
    try:
        run(
            parser.create_command(
                container_name,
                max_bytes=5 * 1024 * 1024,
                max_pages=3,
            )
        )
        inspected = run(["docker", "inspect", container_name], capture=True)
        document = json.loads(inspected.stdout)[0]
        assert_policy(document)
    finally:
        subprocess.run(  # noqa: S603 - fixed cleanup operation and generated name
            ["docker", "rm", "--force", container_name],  # noqa: S607
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
    parsed = parser.parse(sample_pdf(), max_bytes=5 * 1024 * 1024, max_pages=3)
    assert parsed.page_count == 1
    assert "CampusHire parser isolation evidence" in parsed.text
    timeout_parser = DockerPdfParser(
        image=args.image,
        timeout_seconds=0.000_001,
        memory_megabytes=256,
        cpus=0.5,
        pids_limit=32,
    )
    try:
        timeout_parser.parse(sample_pdf(), max_bytes=5 * 1024 * 1024, max_pages=3)
    except ParserUnavailableError as error:
        assert str(error) == "resume_parser_timeout"
    else:
        raise AssertionError("controlled parser timeout did not trigger")
    remaining = run(
        ["docker", "ps", "--all", "--filter", "name=campushire-parser-", "--format", "{{.Names}}"],
        capture=True,
    )
    assert not remaining.stdout.strip(), remaining.stdout.decode(errors="replace")
    print(
        json.dumps(
            {
                "image": args.image,
                "network": "none",
                "read_only_root": True,
                "capabilities": "dropped",
                "no_new_privileges": True,
                "credentials_present": False,
                "valid_pdf_parsed": True,
                "timeout_cleanup": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
