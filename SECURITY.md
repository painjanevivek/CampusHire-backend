# Security policy

Do not publish vulnerabilities, secrets, credentials, or student information in a public issue. Report security concerns privately to the project maintainers.

The backend security baseline includes least privilege, institution isolation, Argon2id password hashing, revocable sessions, CSRF protection, strict CORS, server-side validation, parameterized database access, safe errors, rate limits, secure file upload, PII redaction, and bounded AI workflows.

No user-controlled URL is fetched by the server in the MVP. Uploaded files are stored outside the web root and are never served without authorization.
