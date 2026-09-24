# Resume processing pipeline

Resume versions are private, immutable records. Uploaded files remain non-authoritative until the student completes review. The API validates an upload envelope, stores the bytes under an opaque quarantine key, creates a version plus a PostgreSQL job, and returns `202`. Generated resumes also return `202`; the API validates readiness and stores the reviewed structured content in a version before queueing PDF generation. A separately supervised `python -m app.worker` process claims both job types with row locks.

For `upload_processing` jobs, the worker performs these ordered gates:

1. Read the quarantined object and run the configured malware scanner.
2. Stream clean bytes to the credential-free parser sandbox described in `docs/PARSER_SANDBOX.md`.
3. Validate the bounded protocol result, then promote only clean, successfully parsed objects to the private `clean/` namespace and store proposed structured extraction.
4. Create conservative wording suggestions that add no metrics or outcomes.
5. Expose the version as `review_required`; never update profile or matching facts automatically.

For `pdf_generation` jobs, the worker validates the persisted structured content, renders the versioned CampusHire LaTeX template with the configured local `xelatex` or `pdflatex` engine, disables shell escape and compiler-side package installation, enforces a timeout and output-size limit, validates the resulting PDF and page count, then promotes it to private clean storage. Failed attempts keep the accepted content and use bounded job retries; no profile or matching facts are changed. Compiler setup and the supported template inputs are documented in `docs/RESUME_GENERATION.md`.

Job states are `queued`, `processing`, `cancellation_requested`, `completed`, `failed`, and `cancelled`. Claims carry a random worker identity and bounded lease; storage/scanner boundaries refresh the heartbeat. Expired leases requeue within the retry budget and become inspectable terminal failures after exhaustion. Storage/scanner outages retry with bounded backoff; malformed, encrypted, oversized, or infected files fail closed. Repeated processing is idempotent because each upload checksum and each version job are unique.

Development uses `LocalObjectStore`, `MarkerScanner`, and the subprocess parser adapter. Staging and production reject this parser mode and require `MALWARE_SCANNER=clamav`, `RESUME_PARSER_BACKEND=docker`, an immutable parser image, and an approved rootless launcher. Provide an S3-compatible adapter behind the `ObjectStore` protocol. Downloads require ownership, a clean scan, private no-store caching, and safe `Content-Disposition` metadata.
