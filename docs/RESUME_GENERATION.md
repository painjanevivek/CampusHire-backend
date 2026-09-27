# Local resume generation

CampusHire generates a student resume as a private, versioned PDF from profile details the student has reviewed. The API checks required fields and queues a durable `pdf_generation` job. The local worker compiles the checked-in `campushire-modern` LaTeX template and stores the validated PDF in the existing private resume store. PDF generation does not call an AI provider or an external service.

## AI Resume Studio drafting

AI Resume Studio can draft optional wording before the same local PDF workflow. It uses the
`gemini-3.5-flash-lite` model by default because its documented free tier supports structured JSON
outputs. The free tier has account-dependent limits and Google states that submitted data may be used
to improve its products. Do not treat a free API key as a real-data release approval. See the
[Gemini model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite),
[pricing and data-use terms](https://ai.google.dev/gemini-api/docs/pricing), and
[rate limits](https://ai.google.dev/gemini-api/docs/rate-limits).

To use Studio in local development, configure `GEMINI_API_KEY`, `GEMINI_RESUME_MODEL`,
`AI_GENERATION=true`, `AI_RESUME_STUDIO=true`, a bounded AI budget, and the institution's
`ai_generation` and `ai_resume_studio` feature flags. The student must select profile evidence and
explicitly consent to send it to Google Gemini for each draft. The structured name, email, and phone
fields are not added to the model prompt, but selected free-text evidence may contain personal
information, so the UI displays the exact evidence text before consent. Every generated claim cites
selected evidence, is checked against
unsupported facts and invented metrics, and must be reviewed before acceptance. If selected profile
evidence changes, the student must generate and review a new proposal.

Accepted AI wording is combined with saved profile titles, dates, links, education, and credentials
using the manual builder's line format. Both paths create a `ResumeContent` and queue the same local
`campushire-modern` PDF renderer. The AI model never generates a PDF or bypasses the resume worker.
The current release status still prohibits production/real-data promotion until its separate gates
are closed.

## Local prerequisites

Install a local TeX distribution with XeLaTeX and the template dependencies before starting the API worker. The current development machine was verified with MiKTeX 24.1. MiKTeX Console should finish installing the required packages before worker startup. Compiler auto-install is disabled during each job so a missing package produces a controlled retryable error instead of an unplanned network request.

The template uses `fontspec`, `geometry`, `hyperref` (including `stringenc`), `enumitem`, `tabularx`, `xcolor`, `array`, `needspace`, `xurl`, and Latin Modern Roman. `fontspec` requires XeLaTeX. To use a TeX Live installation, set `RESUME_LATEX_DISTRIBUTION=texlive` and retain `RESUME_LATEX_ENGINE=xelatex`.

On Windows, install or update those packages in MiKTeX Console before running the worker. On Debian-based Linux, the worker image installs them with `fonts-lmodern`, `texlive-latex-extra`, and `texlive-xetex`.

Relevant environment settings (defaults are shown):

```dotenv
RESUME_LATEX_ENGINE=xelatex
RESUME_LATEX_DISTRIBUTION=miktex
RESUME_LATEX_TIMEOUT_SECONDS=20
RESUME_GENERATED_MAX_BYTES=5242880
RESUME_GENERATED_MAX_PAGES=5
```

Run the API and worker as separate local processes:

```powershell
python -m uvicorn app.main:app --reload
python -m app.worker
```

Keep the worker running alongside the API. The API only queues PDF jobs; it does not compile
them. If AI Resume Studio says a PDF is waiting for the worker for more than 30 seconds, check
that `python -m app.worker` is running and can access the same database, private store, and
XeLaTeX installation as the API. Restarting the frontend or asking Gemini for another draft
will not advance an already-queued PDF. The accepted proposal and queued resume version remain
saved while the worker is unavailable.

The worker must run in an account that can execute the configured TeX binary and write its temporary build directory. No student content is printed to compiler logs or application logs. Temporary `.tex`, `.log`, and intermediate files are removed after compilation.

## Data and validation

Profile and onboarding fields are prefilled into the manual Resume Generator. Students can edit the generated document's inputs without changing their saved profile. Full name, a valid email, and at least one education entry are required. Skills, experience, projects, links, research, publications, certifications, positions, extracurricular activities, and achievements are optional. Unknown or unsupported fields are rejected by request validation; optional sections are omitted from the PDF when empty.

The API records the accepted structured content and its evidence digest in a new immutable version, then returns `202 Accepted`. The worker uses the versioned LaTeX template, restricts links to normalized HTTP(S) URLs, escapes text as LaTeX data, runs without shell escape, and applies bounded time, page-count, and output-size checks. It validates the resulting PDF before storage promotion. The compiler is never given access to the database or object-store credentials beyond the worker process environment; the compiler subprocess receives a filtered environment and no shell.

Generation failures keep the structured version and report a safe error code. Transient compiler errors are retried within the configured job attempt limit. A user can retry eligible failed generations from the version history. A content/template digest prevents identical submissions from creating duplicate generated versions. Changes to the template should increment `TEMPLATE_VERSION` and use a new template resource so prior generated versions remain attributable to their original renderer.

## Verification

Run the focused resume generator and workflow checks from `Backend/`:

```powershell
python -m pytest tests/test_resume_builder.py tests/test_resume_readiness.py tests/test_profile_resume_pipeline.py
ruff check app/modules/resumes app/api/v1/routes/resumes.py tests/test_resume_builder.py tests/test_resume_readiness.py tests/test_profile_resume_pipeline.py
```

The renderer tests verify content escaping, safe links, section ordering and omission, metadata, and pagination. Workflow tests verify queued job state, worker completion, ownership, retries, and private downloads. A compiler smoke check can be run with:

```powershell
python -c "from app.modules.resumes.builder import ResumeContent, generate_pdf; print(len(generate_pdf(ResumeContent(full_name='Test Student', email='test@example.edu'))))"
```

Keep generated PDFs, student data, compiler logs, and local environment files out of Git. Use synthetic accounts and profile information for development and CI.
