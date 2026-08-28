from types import SimpleNamespace

import pytest

from app.modules.resumes.storage import ObjectStoreError, OciObjectStore


class FakeObjectClient:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(
        self,
        namespace: str,
        bucket: str,
        key: str,
        data: bytes,
        *,
        content_type: str,
    ) -> None:
        assert namespace == "namespace"
        assert bucket == "private-resumes"
        assert content_type == "application/pdf"
        self.objects[key] = data

    def get_object(self, namespace: str, bucket: str, key: str) -> SimpleNamespace:
        return SimpleNamespace(data=SimpleNamespace(content=self.objects[key]))

    def delete_object(self, namespace: str, bucket: str, key: str) -> None:
        self.objects.pop(key, None)


def test_oci_object_store_quarantines_promotes_reads_and_deletes_privately() -> None:
    client = FakeObjectClient()
    store = OciObjectStore("namespace", "private-resumes", client)
    quarantined = store.put_quarantined(b"%PDF-safe")
    clean = store.promote_clean(quarantined)
    assert quarantined not in client.objects
    assert clean.startswith("clean/")
    assert store.read(clean) == b"%PDF-safe"
    store.delete(clean)
    assert client.objects == {}


def test_oci_object_store_refuses_uploads_after_quota_guard() -> None:
    store = OciObjectStore(
        "namespace", "private-resumes", FakeObjectClient(), uploads_enabled=False
    )
    with pytest.raises(ObjectStoreError, match="resume_storage_quota_guard"):
        store.put_quarantined(b"%PDF-safe")


def test_oci_object_store_rejects_unsafe_keys_before_provider_access() -> None:
    store = OciObjectStore("namespace", "private-resumes", FakeObjectClient())
    with pytest.raises(ObjectStoreError, match="resume_storage_path"):
        store.read("../another-tenant.pdf")
