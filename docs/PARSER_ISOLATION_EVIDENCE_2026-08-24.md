# PDF parser isolation evidence — 2026-08-24

## Candidate and environment

- Source baseline: backend `f3a9fcb293642edb720a8725b539d49ad8b4b234` plus the Phase 7A change.
- Docker Engine: 29.5.3 using the Desktop Linux builder.
- Parser base image: `python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a`.
- Parser test image ID: `sha256:0c91679fcd38fdf2bf689d99d0c2abb9032fd663321585989d25d96ee6792160` (70,457,421 bytes).
- Backend verification image ID: `sha256:c986f1ab07561bdf073289eb856d4941a22bc14b1e24ac238831a6565936eb64` (149,464,823 bytes).
- Test data: generated synthetic PDFs only; no student data.

## Executed evidence

1. `docker build --file Dockerfile.parser --tag campushire-pdf-parser:test .` passed.
2. `RUN_PARSER_CONTAINER_TESTS=1 pytest tests/test_resume_parser.py` passed all seven parser tests.
3. `python scripts/verify_parser_sandbox.py --image campushire-pdf-parser:test` passed live inspection, valid parsing, forced timeout, and container cleanup.
4. A production backend image was built and deterministic PDF generation from reviewed structured fields passed inside it.
5. A source regression test proved the privileged worker and upload-processing pipeline contain no `pymupdf` import or `parse_pdf()` call.
6. Focused resume/pipeline tests preserved valid upload, review, suggestion, ownership, retry, generation, and download behavior.

Live inspection proved: network mode `none`; read-only root; all capabilities dropped; `no-new-privileges`; non-root UID/GID; fixed CPU, memory/swap, PID, wall-time, tmpfs, and output-file limits; no application credential variables; no input/application mounts; one isolated disposable output mount. The valid control retained selectable text. Non-PDF, malformed, encrypted, oversized, and over-page-limit inputs returned only bounded safe codes. A forced timeout removed its container and produced `resume_parser_timeout`.

## Disposition

The original source-to-sink path—scanned attacker PDF to `pymupdf.open()` inside the privileged worker—no longer exists. Native parsing of uploaded bytes is confined to the credential-free parser image. The application retains the same library only for deterministic output generation from reviewed structured fields, preserving legitimate behavior without reopening the hostile parsing path. The same runtime policy must still be demonstrated on the selected managed staging launcher in Phase 7C; local Docker evidence does not approve a hosting topology or real student data.
