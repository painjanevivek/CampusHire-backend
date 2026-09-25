# Platform drive reports

The Platform Admin Reports page groups institution-owned drives by normalized company name,
normalized drive title, and opening year. This is a reporting view: it does not merge drives,
applications, role rules, or institution ownership. “Ongoing” means a published drive whose opening
time has passed and whose deadline has not passed. “All drives” includes drafts and closed records.

The admin can inspect each institution's drive count, distinct student count, and application count.
An applicant row represents one application to one role; one student can therefore appear more than
once. Applicant detail reads the immutable submission snapshots for profile, resume selection,
student facts, eligibility result, application form definition, and acknowledgment. The displayed
PRN comes from the student's current verified institutional profile, not the submission snapshot.
If no verified PRN is present, the UI states that clearly.

`/platform/reports/drive-groups` requires `platform.reports.read`. Applicant lists and evidence
details also require `platform.records.read`. CSV export additionally requires
`platform.reports.export`, which is granted only to the singleton Platform Admin. CSV can cover the
matching group, one institution, or one specific drive within that institution. It escapes cells
that spreadsheet software might interpret as formulas, streams rows in pages, and records an export
audit event. These endpoints are read-only with respect to recruitment decisions.

Custom application disclosure answers remain encrypted and restricted to authorized institutional
compliance readers. The platform report exposes the submitted form definition and disclosure status,
not those answers. No database migration or new student identity field is required.

Authenticator setup is idempotent while a setup is pending: repeated setup requests for the same
account return the same pending secret, so a scanned QR code remains valid for confirmation. The
existing six-digit TOTP verification and recent reauthentication rules remain in force.
