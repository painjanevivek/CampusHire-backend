from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

CONFIGURATION_PATHS: Final = (
    ("backend", ".env.example"),
    ("backend", "Dockerfile"),
    ("backend", "Dockerfile.parser"),
    ("backend", "deploy/staging/Caddyfile"),
    ("backend", "deploy/staging/compose.yaml"),
    ("frontend", ".env.example"),
    ("frontend", "Dockerfile"),
    ("frontend", "next.config.ts"),
)


@dataclass(frozen=True)
class ConfigurationFile:
    path: str
    bytes: int
    sha256: str


def hash_release_configuration(
    backend: Path, frontend: Path
) -> tuple[str, list[ConfigurationFile]]:
    roots = {"backend": backend.resolve(strict=True), "frontend": frontend.resolve(strict=True)}
    digest = hashlib.sha256()
    files: list[ConfigurationFile] = []
    for repository, relative_path in CONFIGURATION_PATHS:
        path = roots[repository] / relative_path
        content = path.read_bytes()
        label = f"{repository}/{relative_path}"
        encoded_label = label.encode("utf-8")
        digest.update(len(encoded_label).to_bytes(4, "big"))
        digest.update(encoded_label)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
        files.append(
            ConfigurationFile(
                path=label,
                bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )
    return digest.hexdigest(), files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hash the committed CampusHire deployment configuration bundle."
    )
    parser.add_argument("--backend", type=Path, default=Path("."))
    parser.add_argument("--frontend", type=Path, default=Path("../Frontend"))
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    digest, files = hash_release_configuration(args.backend, args.frontend)
    payload = {
        "schema_version": 1,
        "configuration_sha256": digest,
        "files": [asdict(item) for item in files],
    }
    rendered = json.dumps(payload, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
