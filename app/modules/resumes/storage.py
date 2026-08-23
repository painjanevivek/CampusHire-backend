from pathlib import Path
from typing import Protocol
from uuid import uuid4


class ObjectStoreError(RuntimeError):
    pass


class ObjectStore(Protocol):
    def put_quarantined(self, data: bytes) -> str: ...

    def promote_clean(self, key: str) -> str: ...

    def read(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...


class LocalObjectStore:
    """Private local adapter for development and tests.

    Keys are opaque and resolved beneath a dedicated root. The same interface is
    intentionally small so staging can provide an S3-compatible adapter without
    changing domain services.
    """

    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        if not key or Path(key).is_absolute() or ".." in Path(key).parts:
            raise ObjectStoreError("resume_storage_path")
        target = (self.root / key).resolve()
        if self.root not in target.parents or target.suffix != ".pdf":
            raise ObjectStoreError("resume_storage_path")
        return target

    def put_quarantined(self, data: bytes) -> str:
        key = f"quarantine/{uuid4()}.pdf"
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_bytes(data)
        except OSError as error:
            raise ObjectStoreError("resume_storage_unavailable") from error
        return key

    def promote_clean(self, key: str) -> str:
        source = self._resolve(key)
        clean_key = f"clean/{uuid4()}.pdf"
        target = self._resolve(clean_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            source.replace(target)
        except OSError as error:
            raise ObjectStoreError("resume_storage_unavailable") from error
        return clean_key

    def read(self, key: str) -> bytes:
        try:
            return self._resolve(key).read_bytes()
        except OSError as error:
            raise ObjectStoreError("resume_storage_unavailable") from error

    def delete(self, key: str) -> None:
        try:
            self._resolve(key).unlink(missing_ok=True)
        except OSError as error:
            raise ObjectStoreError("resume_storage_unavailable") from error
