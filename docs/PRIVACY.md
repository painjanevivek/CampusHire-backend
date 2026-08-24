# CampusHire privacy baseline

Institution-facing approval drafts and current gaps are maintained in `docs/GOVERNANCE_PRIVACY_NOTICE.md`, `docs/DATA_RIGHTS_RETENTION.md`, and `docs/GOVERNANCE_IMPLEMENTATION_CROSSCHECK.md`. They remain drafts until the roles in `docs/GOVERNANCE_SIGNOFF_REGISTER.md` record authorized decisions.

CampusHire collects only data needed to operate institutional recruitment, explain eligibility, support resumes, calculate versioned match evidence, and personalize approved roadmaps. Age and date of birth are excluded from normal onboarding. Protected or sensitive attributes must never enter match embeddings.

Students may request correction, export, or deactivation through their TNP team. An authenticated student may delete eligible data through `POST /api/v1/privacy/deletion-requests` after entering the exact irreversible confirmation. The transaction removes the account, sessions, profile, resumes and suggestions, roadmap progress, notifications, saved roles, eligibility evaluations, and semantic-match evidence. Private resume files are handed to a durable worker record and retried without retaining filenames, email addresses, or resume content.

An existing application creates an explicit retention hold because its immutable decision snapshots and audit evidence can be institutionally required. The API returns a conflict rather than implying that all data was deleted. An institution must approve the applicable retention periods, legal basis, contact path, export format, and appeal process before real student data is used. This implementation is a technical control, not a compliance claim.

CampusHire does not currently persist vectors in Qdrant. If the Qdrant adapter is enabled, deployment approval is blocked until tenant- and student-filtered vector deletion is implemented and verified. Cleanup records retain only pseudonymous UUIDs, opaque object keys, safe error codes, and operational timestamps; completed object keys are cleared.

Gemini receives only the minimum delimited content required by a workflow. Raw passwords, session tokens, phone numbers, and unrelated profile data must never be included. AI may assist; it never becomes the authority for formal eligibility.
