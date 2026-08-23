# Resume processing pipeline

Resume files are non-authoritative until the student completes review. The API validates the upload envelope, stores the bytes under an opaque quarantine key, creates an immutable version plus a PostgreSQL job, and returns `202`. A separately supervised `python -m app.worker` process claims jobs with row locks.

The worker performs these ordered gates:

1. Read the quarantined object and run the configured malware scanner.
2. Promote only clean objects to the private `clean/` namespace.
3. Parse bounded PDF pages and store proposed structured extraction.
4. Create conservative wording suggestions that add no metrics or outcomes.
5. Expose the version as `review_required`; never update profile or matching facts automatically.

Job states are `queued`, `processing`, `completed`, and `failed`. Storage/scanner outages retry with bounded backoff; malformed, encrypted, oversized, or infected files fail closed. Repeated processing is idempotent because each upload checksum and each version job are unique.

Development uses `LocalObjectStore` and `MarkerScanner`. Before staging, provide an S3-compatible adapter behind the `ObjectStore` protocol and set `MALWARE_SCANNER=clamav`. Downloads require ownership, a clean scan, private no-store caching, and safe `Content-Disposition` metadata.
