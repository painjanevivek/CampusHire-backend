# Resume upload retirement

New resume ingestion is disabled: the public collection route is GET-only, applications accept
reviewed `source=generated` versions, and semantic matching starts from reviewed profile evidence.
Existing uploaded versions remain read-only so historical application snapshots and downloads do
not break.

Run the following in each environment before removing the remaining legacy parser, scanner,
quarantine storage readers, or worker code:

```powershell
python scripts/audit_resume_uploads.py
```

The legacy pipeline may be removed only when `legacy_pipeline_removable` is `true` and Product/Data
Retention approves `[FILL: environment cleanup approval]`. When uploads remain, drain or terminate
nonterminal jobs under that approval, preserve referenced records until retention/deletion completes,
and rerun the audit. The script reports counts only; it does not expose filenames, users, or resume
content and never mutates data.
