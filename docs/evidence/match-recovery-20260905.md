# Match explanation recovery — 2026-09-05

## Cause and change

`semantic_match` returned any existing fingerprint result immediately, including failed provider
attempts. A transient failure therefore prevented recovery for unchanged inputs. The dashboard
correctly reflected that persisted unavailable result; hiding its warning would not fix the cause.

The configured Gemini provider passed a synthetic connectivity probe (3072 dimensions). The
first restricted-shell probe could not connect; the permitted network probe succeeded. This does
not establish the cause of the original historical provider failure.

Failed results now allow a retry after 60 seconds. Existing failed rows are locked during recovery,
then refreshed without deleting records or changing source versions. Successful cached results
are preserved. Continued failures restart the cooldown. No API schema, configuration, frontend,
eligibility, application snapshot, or migration change was needed for this fix.

## Actual local browser verification

- Signed into the existing synthetic student account through normal demo authentication.
- Before recovery, the dashboard showed the warning and Northstar's match as pending.
- Opened the Graduate Software Engineer / Northstar Labs opportunity through its normal link.
- The existing authenticated, CSRF-protected match endpoint returned **85% match**, `match-v1`,
  and explanations including 100% published skill coverage.
- Formal eligibility remained **Eligible** and the application remained **shortlisted**.
- Returned through Home; the dashboard showed **85% match** for Northstar with no unavailable
  warning. The other displayed match results remained 88% and 85%.
- Local API restarted with the patched code on port 8000; frontend remained on port 3001.

## Automated evidence

- Added two regression tests; both failed against the original permanent-cache behavior.
- Focused intelligence suite after the fix: **5 passed**.
- Ruff: passed. MyPy: **108 source files**, no issues.
- Full backend suite with permitted temporary-directory access: **184 passed, 1 skipped**
  in 61.15 seconds. Two existing dependency deprecation warnings remain. Initial sandbox
  run produced 174 passed, 1 skipped, and 10 temporary-fixture setup errors; these were not
  treated as passing tests and the permitted rerun completed successfully.

The retry lock uses PostgreSQL row locking. SQLite unit tests cover cooldown/recovery behavior,
not multi-process PostgreSQL contention. No load capacity, staging, security-qualification, or
external approval result is claimed. Prior release status/evidence is not promoted by this fix.
