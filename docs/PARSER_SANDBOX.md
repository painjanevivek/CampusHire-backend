# Credential-Free PDF Parser Sandbox

## Security boundary

The API accepts only a bounded PDF envelope and stores it under an opaque quarantine key. The privileged worker reads the object and requires a clean malware result, but it never imports or invokes PyMuPDF. It streams the scanned bytes to one ephemeral parser container and accepts only a versioned, size-bounded JSON result.

The parser image contains only Python, pinned PyMuPDF, and `parser_runtime/main.py`. It contains no CampusHire application package, database driver, Redis/Qdrant/Gemini client, object-store adapter, session code, or application credentials. The privileged upload-processing path never imports or calls the native parser. Resume PDFs are generated from reviewed structured fields by the separately configured, local LaTeX renderer; PyMuPDF is used by the application to validate generated output and read its page count.

## Runtime policy

Every parse uses these fixed controls:

- non-root UID/GID `65532:65532`;
- `--network none`, with no published ports;
- read-only root filesystem;
- all Linux capabilities dropped and `no-new-privileges` enabled;
- 0.5 CPU, 256 MiB memory/swap, 32 PIDs, and a 20-second wall-time default;
- a 16 MiB `noexec,nosuid,nodev` temporary filesystem;
- a strict 192 KiB parent-side result limit with anonymous worker-local capture;
- PDF bytes delivered through stdin, never a host input mount;
- no host, application, database, or storage mounts; the single result is streamed over the
  authenticated launcher API into an anonymous worker-local temporary file;
- fixed output path, strict protocol v1 schema, 192 KiB parent read limit, 100,000-character text limit, and maximum page revalidation.

Container creation, start, result validation, and forced removal use argv arrays without a shell. A timeout kills and removes the container. Missing runtime, crash, or timeout produces a safe parser code and follows the bounded job retry policy. Malformed, encrypted, oversized, and over-page-limit documents fail terminally.

## Environment modes

`RESUME_PARSER_BACKEND=subprocess` is limited to development and tests. It executes the isolated runtime script with a minimized environment but shares the developer operating-system account, so staging and production configuration rejects it.

Staging and production require:

```text
MALWARE_SCANNER=clamav
RESUME_PARSER_BACKEND=docker
RESUME_PARSER_IMAGE=<immutable approved parser image reference>
```

The worker must run on a dedicated host or workload with an approved rootless container-launch facility. Do not mount a rootful Docker socket into the public API container. Record the parser image digest, launcher identity, resource policy, and verification output in each release dossier.

## Build and verification

```powershell
docker build --file Dockerfile.parser --tag campushire-pdf-parser:test .
$env:RUN_PARSER_CONTAINER_TESTS = "1"
python -m pytest tests/test_resume_parser.py
python scripts/verify_parser_sandbox.py --image campushire-pdf-parser:test
docker build --tag campushire-backend:test .
docker run --rm --entrypoint python campushire-backend:test -c "from app.modules.resumes.builder import ResumeContent; assert ResumeContent(full_name='Test Student', email='test@example.edu').full_name == 'Test Student'"
```

The XeLaTeX smoke check must run in the backend worker environment where the local TeX distribution is installed; see `docs/RESUME_GENERATION.md`.

CI runs the same image, container-policy, functional, timeout-cleanup, and dependency-separation checks.
