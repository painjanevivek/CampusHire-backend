# Student placement access policy

CampusHire checks placement access as a deterministic backend capability. This policy controls entry to the student placement workspace; it does not replace the deterministic, role-specific eligibility checks used for each opportunity.

## PRN and study year

The PRN is stored on the authenticated student's `StudentProfile`. The current institutional convention is a three-digit prefix followed by one or more letters or digits, for example `123B1B287`. Only the first three digits are used: for a prefix beginning with `1`, the final two digits encode the admission year (`123` → 2023). The backend validates this format during onboarding and profile updates. A syntactically valid PRN is not treated as verified just because the student entered it.

Only an institution `institution.manage` role can mark a student's PRN verified through `POST /institutions/{institution_id}/students/{student_id}/prn-verification`. The staff member confirms the PRN against institutional records and supplies an audit reason; the full PRN is not copied into the audit details. Updating the PRN clears verification and requires another staff review. Where an institutional email convention already ties the batch year to the PRN, onboarding also checks that consistency.

The `Institution.academic_year_start_month` value determines when that institution's year rolls over; the migration defaults existing institutions to June. The academic-year start year is calculated from the current date in that institution's configured timezone, so it advances each year without storing a stale student year. Institutions with another academic calendar should set their own start month.

For the configured four-year B.Tech program:

```text
study_year = academic_year_start - admission_year + 1
placement_access = study_year in {3, 4}
```

Study years 1 and 2 are denied. Study year 5 and beyond are also denied. A future admission year or invalid PRN cannot produce access. The policy does not persist mutable `is_third_year` or `is_final_year` fields.

## Enforcement and boundaries

`GET /auth/me` returns the derived `placement_access` state for the frontend, including whether institution verification is pending. Protected student placement routes additionally run `require_student_placement_access` using the existing authenticated principal and institution membership. The backend derives the institution from that session and queries the matching student profile; client-supplied tenant or year values are not used. A blocked student can still authenticate, complete or correct their profile, and use account and privacy functions.

The guard applies to student dashboards, opportunity discovery and actions, applications and application packets, preparation and roadmap workflows, student Copilot and agentic preparation, and role-tailored resume creation. Existing T&P and Platform Admin permission dependencies remain unchanged.

Once placement access is granted, role-specific branch, CGPA, skill, backlog, and other published requirements continue through the existing deterministic eligibility engine. PRNs are not sent to AI providers, and this policy does not use AI.
