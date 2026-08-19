# ADR-009 — Supplier profile detection and structural drift

Status: Accepted

Date: 2026-08-20

Related requirements: `FR-SVC-009`, `FR-SVC-010`, `TASK-011`.

## Context

The service must rank active supplier profile versions from a previously built
`RawWorkbook`. A weak aggregate score alone cannot distinguish an unknown supplier from a
known supplier whose template changed, and it does not provide enough evidence for an
operator or manager to review the result.

The detector must remain framework-neutral and must not open files, mutate raw cells, run
normalization, or duplicate reader validation.

## Decision

Each profile file rule is represented by an immutable `ProfileFingerprint` containing:

- filename pattern;
- extensions;
- media types;
- normalized expected sheet names;
- normalized declared column names.

The detector constructs this fingerprint from the active profile version and uses the same
object for every component comparison. Filename matching is case-insensitive glob with the
existing safe regex fallback. Extension and media type comparisons are case-insensitive;
media type parameters are ignored. Sheet and column comparisons use trim, casefold, and
collapsed whitespace.

Candidate scoring remains normalized over declared features with a positive configured
weight. Every candidate exposes `totalScore` on a `0..100` scale and a `scoreComponents`
map. Each component contains awarded `score` points and maximum `weight` points. The sum of
component scores is validated against `totalScore`.

Detection has four domain statuses:

- `MATCHED` — one profile clears the selection threshold and ambiguity policy;
- `PROFILE_NOT_FOUND` — no supplier identity or adequate candidate is found;
- `AMBIGUOUS_PROFILE` — leading candidates differ by less than the configured margin;
- `TEMPLATE_CHANGED` — the supplier identity is recognized from filename plus declared file
  format signals, while structural compatibility is below the configured threshold.

Structural compatibility is the weighted result of declared sheet and column signals. The
default threshold is `0.50`. This makes the known supplier example with the expected
`price*` filename and `.xlsx` format, but renamed sheet and replaced columns, blocking
`TEMPLATE_CHANGED` rather than `PROFILE_NOT_FOUND`.

Automatic selection uses a default `0.50` score threshold and a `0.05` ambiguity margin.
Confidence thresholds are `HIGH >= 0.80`, `MEDIUM >= 0.50`, otherwise `LOW`. A result without
`selectedProfile` is never `HIGH`; an unresolved high-scoring result is capped at `MEDIUM`.

## Consequences

- `FR-SVC-010` is represented explicitly and blocks automatic publication through a
  machine-readable status and issue.
- UI and approval workflows can render ranked evidence without reproducing scoring logic.
- Profile drift policy is deterministic, configurable, and testable without touching readers.
- Header aliases, semantic normalization, and profile-version authoring remain outside
  `TASK-011`.
