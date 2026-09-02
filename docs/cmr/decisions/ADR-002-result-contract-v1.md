# ADR-002: Canonical CMR result envelope v1

- Status: Proposed
- Date: 2026-09-02
- Decision owner: CMR product program
- Review required: architecture review before acceptance

## Context

CMR-10, CMR-11, CMR-20, CMR-30, CMR-40 and CMR-50 need a shared way to
exchange measurements without allowing each module to invent an incompatible
result, provenance, quality or review structure. The repository previously had
runtime-specific contour and measurement dictionaries, but no versioned public
result contract.

This decision defines a technical contract only. It does not define a clinical
metric, normal range, diagnostic threshold or physician acceptance state.

## Decision

### One normative source

`contracts/cmr/result-envelope.schema.json` is the single normative source.
Backend validation reads it directly. Frontend TypeScript declarations are
generated from it, carry its SHA-256 digest and are checked for exact drift in
tests. Hand-maintained module result interfaces are not public contracts.

### Version and extension policy

The envelope uses semantic versions:

- incompatible changes increment the major version;
- unknown major versions fail closed;
- compatible v1 additions use the existing namespaced `extensions` object;
- the v1 root remains closed, so a minor version cannot silently redefine a
  common field;
- deprecations are documented for at least one minor line and removal requires
  a new major.

An extension key is a dotted lowercase namespace such as
`cine_function.summary`. Common consumers preserve the extension object but do
not infer clinical meaning from unknown extension payloads.

### Values and units

Version 1 supports:

- a computed scalar;
- a computed immutable artifact reference for a curve, parameter map, vector
  field, table or another versioned payload;
- explicit `missing`, `not_computed`, `failed` and `not_applicable` states.

Every state carries the metric's UCUM unit. Dimensionless values use `1` and
percentages use `%`; an empty string is invalid. A state is never represented
by an unexplained `null`.

### Sources, selectors, ROI and geometry

Source series are opaque identifiers with immutable versions. Slice and phase
selectors support `all`, explicit index sets and inclusive ranges, and may span
multiple series.

ROI and geometry contexts use an explicit union:

- `referenced` with one or more immutable references; or
- `not_applicable` with a machine-readable reason.

Version 1 does not inline coordinate arrays. Every geometry reference includes
one coordinate frame:

| Frame | Axis order | Length unit |
|---|---|---|
| `pixel_index_2d` | `column`, `row` | `px` |
| `image_physical_2d` | `x`, `y` | `mm` |
| `patient_lps_3d` | `left`, `posterior`, `superior` | `mm` |

Contour closure, 2D/3D storage and slice/phase attachment belong to the
versioned geometry artifact contract. They may not be guessed from a bare
array. A later inline geometry contract requires a separate ADR or a compatible
versioned artifact schema.

### Algorithm provenance and staleness

Results record algorithm identity, algorithm version and either inline
parameters or a versioned parameter-manifest reference. Lineage records the
algorithm plus every source series, ROI and geometry identity/version used. A shared comparison
entry point marks a result stale when a current input is missing or has a
different version.

### Quality and human review

Quality is machine readable and distinguishes `not_run` from a completed
assessment with no issues. Flags have a namespaced code, severity, scope and
explicit display/export/report blockers. An overall disposition is required.

Human review is a separate result-level state:
`not_reviewed`, `pending`, `reviewed`, `rejected` or `changes_requested`.
Quality never upgrades review. A decided review binds to the result fingerprint;
an edit that changes the fingerprint invalidates the old review until the
workflow resets or repeats review.
The canonical fingerprint is SHA-256 over deterministic JSON after removing
`result_fingerprint` and `review`. Quality remains in the digest.

Reviewer identity and timestamp are platform audit data. The common envelope
contains only an opaque `review_event_ref`; the platform stores reviewer and
time under its own access-control and retention policy.

## Alternatives considered

1. Backend and frontend hand-maintain separate models. Rejected because drift
   would remain possible even if each side has local tests.
2. Make current runtime dictionaries the public schema. Rejected because they
   omit stable versions, coordinate semantics and independent review state.
3. Inline all curves and geometry in v1. Rejected because this prematurely
   fixes module payload shapes and makes large vector/map results part of every
   consumer's common boundary.
4. Use quality pass as physician review. Rejected because technical QC and
   human acceptance answer different questions.

## Strongest counterexamples and limits

- A valid UCUM-looking string may still be semantically wrong for a metric;
  schema validation cannot prove the clinical unit.
- Opaque version references detect change only if the owning repository creates
  a new immutable version after edits.
- An artifact digest proves bytes, not that the curve/map is clinically valid.
- The first contract does not define an inline contour representation, DICOM
  frame of reference, or a persistence transaction.
- Passing synthetic tests does not prove compatibility with legacy saved
  results or any physician workflow.

## Consequences

- All modules can share one envelope without adopting a specific algorithm.
- Schema and generated frontend type changes are reviewable and testable.
- Module adapters must translate legacy dictionaries explicitly.
- Database persistence, legacy migration and production rollout remain outside
  CMR-01.

This ADR remains Proposed until an authorized architecture reviewer accepts it.
