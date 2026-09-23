# CampusHire agentic AI pilot

CampusHire implements two bounded workflows: `prepare_opportunity` for students and
`prepare_drive` for T&P. PostgreSQL owns run state, sanitized events, immutable usage attempts,
source versions, consent, and reviewable artifacts. LangGraph chooses whether to clarify or draft;
only typed read tools and proposal creation are available. Existing recruitment services remain
authoritative for eligibility and drive mutations.

Each run reserves 30,000 micro-dollars and shares a lifetime ceiling of four model calls, six tool
calls, one validated correction, and 90 active seconds. Waiting for review does not consume active
time, and resuming retains all counters. Provider attempts are written before dispatch so uncertain
billing is visible and is never retried automatically. A stale lease with a dispatched attempt is
stopped with `provider_outcome_review_required`; an operator must review it instead of allowing a
replacement worker to replay the request. Because the exact provider charge is unknown, the run's
full reserved amount remains counted against the tenant budget. Worker execution is fenced by the claimed lease owner,
so a late worker cannot overwrite or clear a safely recovered claim.

Every run and artifact records the model release, workflow version, source-projection version, and
optional frozen evaluation-run identifier. Production refuses to start agent runs unless
`AI_REAL_DATA_ENABLED=true` has been set after the separate provider/privacy release gate. The
default remains false, and `AGENT_RUNS` remains the global operational kill switch.

Enable the global `AGENT_RUNS` switch and the institution `agent_runs` flag only after model,
pricing, monthly allowance, API, and worker configuration are present. `LIVE_SOURCES` and the
institution `live_sources` flag enable ESCO lookup and source registration. Add every permitted
official-career domain to `SOURCE_ALLOWED_DOMAINS`; NPTEL and SWAYAM are the defaults. URL checks
require HTTPS, an allowlisted hostname, a public resolved address, no redirect, and bounded metadata.
Changed metadata creates a pending version for human review. Campus policy always has higher
authority than external career information.

Student runs are owner-scoped. T&P drive runs and artifacts are institution and drive scoped for
authorized reviewers. Applying accepted fields additionally requires `recruitment.manage` and both
artifact and drive revisions. During review, students may edit only the plan summary and T&P may
edit only the announcement draft; eligibility, citations, blockers, and proposed drive fields stay
bound to validated generation evidence. Decided artifacts are immutable. Practice conversations
and answers never enter shared indexes.
Practice aggregate consent records purpose, version, grant, and revocation; the pilot stores no
derived assessment contribution until a qualified assessment workflow exists. Students can delete
cancelled, failed, rejected, or otherwise unaccepted private tasks. Active tasks must first be
cancelled, and accepted plans follow the destination record's retention rules.

The benchmark manifest contains 20 reviewed scenario templates with five deterministic variants,
balanced into 50 student and 50 T&P scenarios. Run each expanded scenario three times and report
per-attempt and all-repeats success. Qualification is calculated independently for both workflows:
at least 90% task completion, 95% supported factual claims, 98% valid citations, and zero observed
private disclosure or unauthorized state change. Automated grading assists review; it does not
replace the reviewed reference judgment.

Schema-valid output is only a candidate. The runner separately validates deterministic eligibility,
source resolution, source support, student-evidence state, selected drive fields, and planned effort.
Failures receive at most one bounded correction. Any material that still lacks support is withheld
and the run ends with a safe error.

## Synthetic interview-practice pilot

Interview practice is a separate Student Copilot intent, backed by the configured Gemini structured
generator. It uses only the published role title/skills and a minimized conversation transcript; it
does not load the student's profile or resume. Each conversation is limited to 12 model turns and
the route retains its 20-requests-per-minute tenant/user limit. The feature is restricted in settings
to development and test, requires both `AI_GENERATION=true` and `STUDENT_COPILOT=true`, and also
requires the institution's matching feature flags. `INTERVIEW_PRACTICE_PILOT=true` enables it only
when `COPILOT_GENERATION_PROVIDER=gemini` and
`GEMINI_GENERATION_MODEL=gemini-3.8-flash`.

The free-tier provider may use prompts to improve its products. The interface warns students to use
synthetic answers and avoid personal or confidential information. Do not enable this pilot for real
student data or production; provider privacy, institutional approval, usage limits, and budget policy
must be reviewed first. The agent gives practice feedback only and never assesses eligibility or
hiring outcomes.
