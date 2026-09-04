import sys
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import Settings
from app.modules.resumes.storage import ObjectStoreError, OciObjectStore, build_object_store


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


def test_oci_object_store_supports_api_key_auth_without_a_key_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_signer(**kwargs: Any) -> object:
        captured["signer"] = kwargs
        return object()

    def fake_client(*, config: dict[str, str | None], signer: object) -> FakeObjectClient:
        captured["client"] = {"config": config, "signer": signer}
        return FakeObjectClient()

    fake_oci = SimpleNamespace(
        signer=SimpleNamespace(Signer=fake_signer),
        auth=SimpleNamespace(
            signers=SimpleNamespace(InstancePrincipalsSecurityTokenSigner=lambda: object())
        ),
        object_storage=SimpleNamespace(ObjectStorageClient=fake_client),
    )
    monkeypatch.setitem(sys.modules, "oci", fake_oci)
    settings = Settings(
        _env_file=None,
        resume_storage_backend="oci",
        oci_auth_mode="api_key",
        oci_object_namespace="namespace",
        oci_object_bucket="private-resumes",
        oci_tenancy_ocid="ocid1.tenancy.oc1..example",
        oci_user_ocid="ocid1.user.oc1..example",
        oci_key_fingerprint="00:11:22:33",
        oci_region="ap-mumbai-1",
        oci_private_key="private-key-material",
    )

    store = build_object_store(settings)

    assert isinstance(store, OciObjectStore)
    assert captured["signer"] == {
        "tenancy": "ocid1.tenancy.oc1..example",
        "user": "ocid1.user.oc1..example",
        "fingerprint": "00:11:22:33",
        "private_key_file_location": None,
        "private_key_content": "private-key-material",
        "pass_phrase": None,
    }
    client_config = captured["client"]
    assert isinstance(client_config, dict)
    assert client_config["config"] == {"region": "ap-mumbai-1"}
