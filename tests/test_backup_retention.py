import json
from subprocess import CompletedProcess
from typing import Any

import pytest

from scripts import prune_oci_backups


def test_backup_pruner_removes_oldest_pairs_and_preserves_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    names = [
        "backups/daily/campushire-2026-09-01T000000Z.tar.age",
        "backups/daily/campushire-2026-09-02T000000Z.tar.age",
        "backups/daily/campushire-2026-09-03T000000Z.tar.age",
    ]

    def fake_run(command: list[str], **_: Any) -> CompletedProcess[str]:
        calls.append(command)
        if "list" in command:
            return CompletedProcess(
                command,
                0,
                stdout=json.dumps({"data": [{"name": name} for name in names]}),
                stderr="",
            )
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(prune_oci_backups.subprocess, "run", fake_run)

    removed = prune_oci_backups.prune(
        "namespace", "bucket", "backups/daily/", 2, executable="oci"
    )

    assert removed == [names[0]]
    delete_targets = [
        command[command.index("--object-name") + 1]
        for command in calls
        if "delete" in command
    ]
    assert delete_targets == [names[0], f"{names[0]}.sha256"]


def test_backup_pruner_rejects_zero_retention() -> None:
    with pytest.raises(ValueError, match="at least one"):
        prune_oci_backups.prune(
            "namespace", "bucket", "backups/daily/", 0, executable="oci"
        )
