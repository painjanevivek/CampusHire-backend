# Private student profile photos

Profile photos are optional account personalization. They are not collected for recruitment decisions and are not included in profile revisions, readiness, eligibility, resume snapshots, or application snapshots. Only the signed-in student can read or modify their own photo; these routes do not accept a user or institution identifier.

## Contract and persistence

- `GET /api/v1/profile/photo`: `{ "data_url": null }` when absent, otherwise a normalized JPEG data URL.
- `PUT /api/v1/profile/photo`: multipart `file`; authenticated student plus session-bound CSRF and allowed Origin required.
- `DELETE /api/v1/profile/photo`: removes only the current student's optional photo, with the same authorization/CSRF protection.
- Responses are `private, no-store`. The frontend keeps the small image in account-lifetime memory, not local storage.
- Migration `20260905_0023` adds one `profile_photos` row per user with a cascading user foreign key. This uses the existing PostgreSQL database and requires no additional hosting service.
- Account-wide data cleanup also includes this table; no account-deletion UI is introduced.

## Upload boundary

JPEG and PNG only; extension, declared MIME, decoder format, contents, byte size (2 MiB), pixel count (8 million), and single-frame restrictions are checked. Multipart request limits apply before spooling, including PUT. Image work runs outside the event loop. The existing rate-limit infrastructure limits uploads to ten per account per minute.

Only a new JPEG of at most 512 × 512 pixels is saved. Original bytes, EXIF/GPS, comments, embedded profiles, and trailing content are discarded. SVG and animated images are not supported. Photos are never fetched from user-provided external URLs or served as executable content.

The image decoder is pinned to [Pillow 12.3.0](https://pypi.org/project/pillow/12.3.0/). Its optional NumPy type imports are skipped in MyPy because this application only uses PIL images/bytes and the installed NumPy stubs target newer syntax than the application's Python 3.11 type-check target; application code remains strictly checked.

## Local verification (2026-09-05)

- Photo unit/API tests: 9 passed, covering normalization, corruption, MIME/extension mismatch, byte/pixel limits, persistence, replacement, removal, unchanged profile revision, unauthenticated/administrator denial, CSRF rejection, and cross-student/institution read isolation.
- Full backend: 193 passed, 1 skipped; Ruff passed; MyPy passed for 109 source files.
- OpenAPI exported to both repositories; snapshots match.
- Applied additive migration to `localhost/campushire`; `alembic current` reports `20260905_0023 (head)`.
- `alembic check` does **not** pass: it reports older unique-constraint/index representation differences plus existing audit/drive constraints in unrelated tables. No difference was reported for `profile_photos`; unrelated schema was not changed.
- Browser upload, header refresh, persistence after reload, and removal verified with a temporary synthetic one-pixel photo. The photo was removed after verification.

For another environment, install updated backend dependencies and apply the additive migration before deploying the consuming frontend. No production deployment, capacity qualification, multi-process photo contention test, or external approval is claimed.
