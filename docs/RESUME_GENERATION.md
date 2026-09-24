# Local resume generation

CampusHire generates a student resume as a private, versioned PDF from profile details the student has reviewed. The API checks required fields and queues a durable `pdf_generation` job. The local worker compiles the checked-in `campushire-modern` LaTeX template and stores the validated PDF in the existing private resume store. PDF generation does not call an AI provider or an external service.

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
