from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from app.core.config import Settings


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


class OciObjectStore:
    """Private OCI bucket adapter authenticated by a configured OCI signer."""

    def __init__(
        self,
        namespace: str,
        bucket: str,
        client: Any,
        *,
        uploads_enabled: bool = True,
    ) -> None:
        self.namespace = namespace
        self.bucket = bucket
        self.client = client
        self.uploads_enabled = uploads_enabled

    @staticmethod
    def _validate_key(key: str) -> str:
        path = Path(key)
        if not key or path.is_absolute() or ".." in path.parts or path.suffix != ".pdf":
            raise ObjectStoreError("resume_storage_path")
        return key

    def _put(self, key: str, data: bytes) -> None:
        if not self.uploads_enabled:
            raise ObjectStoreError("resume_storage_quota_guard")
        try:
            self.client.put_object(
                self.namespace,
                self.bucket,
                key,
                data,
                content_type="application/pdf",
            )
        except Exception as error:
            raise ObjectStoreError("resume_storage_unavailable") from error

    def put_quarantined(self, data: bytes) -> str:
        key = f"quarantine/{uuid4()}.pdf"
        self._put(key, data)
        return key

    def promote_clean(self, key: str) -> str:
        source = self._validate_key(key)
        clean_key = f"clean/{uuid4()}.pdf"
        try:
            response = self.client.get_object(self.namespace, self.bucket, source)
            self._put(clean_key, bytes(response.data.content))
            self.client.delete_object(self.namespace, self.bucket, source)
        except ObjectStoreError:
            raise
        except Exception as error:
            raise ObjectStoreError("resume_storage_unavailable") from error
        return clean_key

    def read(self, key: str) -> bytes:
        try:
            response = self.client.get_object(
                self.namespace, self.bucket, self._validate_key(key)
            )
            return bytes(response.data.content)
        except ObjectStoreError:
            raise
        except Exception as error:
            raise ObjectStoreError("resume_storage_unavailable") from error

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(
                self.namespace, self.bucket, self._validate_key(key)
            )
        except ObjectStoreError:
            raise
        except Exception as error:
            raise ObjectStoreError("resume_storage_unavailable") from error


def build_object_store(settings: Settings) -> ObjectStore:
    if settings.resume_storage_backend == "local":
        return LocalObjectStore(settings.resume_storage_path)
    if not settings.oci_object_namespace or not settings.oci_object_bucket:
        raise ObjectStoreError("resume_storage_configuration")
    try:
        import oci  # type: ignore[import-untyped]

        if settings.oci_auth_mode == "api_key":
            identity = (
                settings.oci_tenancy_ocid,
                settings.oci_user_ocid,
                settings.oci_key_fingerprint,
                settings.oci_region,
            )
            private_key = settings.oci_private_key
            if (
                any(not value or not value.strip() for value in identity)
                or private_key is None
                or not private_key.get_secret_value().strip()
            ):
                raise ObjectStoreError("resume_storage_configuration")
            passphrase = settings.oci_private_key_passphrase
            signer = oci.signer.Signer(
                tenancy=settings.oci_tenancy_ocid,
                user=settings.oci_user_ocid,
                fingerprint=settings.oci_key_fingerprint,
                private_key_file_location=None,
                private_key_content=private_key.get_secret_value(),
                pass_phrase=passphrase.get_secret_value() if passphrase else None,
            )
            client = oci.object_storage.ObjectStorageClient(
                config={"region": settings.oci_region}, signer=signer
            )
        else:
            signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
            client = oci.object_storage.ObjectStorageClient(config={}, signer=signer)
    except Exception as error:
        raise ObjectStoreError("resume_storage_configuration") from error
    return OciObjectStore(
        settings.oci_object_namespace,
        settings.oci_object_bucket,
        client,
        uploads_enabled=settings.oci_object_uploads_enabled,
    )
