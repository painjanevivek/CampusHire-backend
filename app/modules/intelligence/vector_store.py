from typing import Any


def tenant_vector_payload(
    *, institution_id: str, owner_id: str, source_id: str, model: str, version: str
) -> dict[str, str]:
    """Build the only payload shape accepted for tenant-owned embeddings."""
    if not all((institution_id, owner_id, source_id, model, version)):
        raise ValueError("Vector metadata must be complete")
    return {
        "institution_id": institution_id,
        "owner_id": owner_id,
        "source_id": source_id,
        "embedding_model": model,
        "embedding_version": version,
    }


def tenant_query_filter(institution_id: str) -> dict[str, Any]:
    """Return an explicit Qdrant-compatible mandatory tenant filter."""
    if not institution_id:
        raise ValueError("Institution scope is required")
    return {
        "must": [
            {
                "key": "institution_id",
                "match": {"value": institution_id},
            }
        ]
    }
