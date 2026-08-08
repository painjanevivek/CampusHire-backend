# Contributing

## Backend rules

- Organize code by business module, not by speculative technical layers.
- Keep API routes thin; business rules belong in services and data access in repositories.
- Validate every request with explicit schemas and allowlisted update fields.
- Enforce user, role, institution, and parent-resource authorization server-side.
- Use UUID identifiers, parameterized ORM operations, UTC timestamps, and database constraints.
- Make background work idempotent and retry only known transient failures.
- Treat uploaded documents and AI content as untrusted data.
- Record model, prompt, policy, rule, resume, embedding, and scoring versions where decisions depend on them.
- Add the smallest meaningful automated test for non-trivial logic.
- Update OpenAPI examples and migration notes when contracts or data change.

## Commit format

```text
feat(phase-N): concise outcome
fix(phase-N): concise correction
```

Use bullet points in the commit body to describe changes and checks.
