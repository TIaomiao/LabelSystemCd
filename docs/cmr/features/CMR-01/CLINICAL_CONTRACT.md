# CMR-01 clinical and review contract

## Confirmed decisions

- CMR-01 carries technical result metadata; it does not define metric formulas,
  normal ranges, diagnoses or treatment implications.
- A result's metric unit is mandatory and uses UCUM notation.
- Quality assessment and human review are independent.
- A technically valid result may remain `not_reviewed`.
- A physician review decision binds to an exact result fingerprint.
- Reviewer identity and timestamp remain in the access-controlled platform
  audit layer; the shared envelope stores only an opaque review event reference.
- No patient identity, accession number, DICOM UID, server path or free-text
  clinical report belongs in the shared envelope.

## Human review states

| State | Meaning |
|---|---|
| `not_reviewed` | no result-level review has begun |
| `pending` | queued or actively awaiting review |
| `reviewed` | reviewer accepted this exact result revision |
| `rejected` | reviewer rejected this exact result revision |
| `changes_requested` | reviewer requested a new result revision |

Editing a value, source, ROI, geometry, algorithm input or quality-bearing
result content changes `result_fingerprint`. A decided review whose stored
fingerprint differs is invalid and must not be displayed as current review.
The fingerprint is computed from deterministic JSON after removing only the
fingerprint field itself and the review object.

## Quality semantics

- `not_run` plus `not_assessed` means no quality evaluation was executed.
- `completed` plus `pass` means no warning/error/blocking flag was found.
- `completed` plus `warn` requires non-blocking flags.
- `completed` plus `fail` requires an error or an explicit blocker.
- Block targets are `display`, `export` and `report`; integrations decide how
  to enforce them but may not silently drop the information.

## Not yet decided

- The full UCUM vocabulary allowed for each module metric.
- Inline contour and ROI geometry schemas, closure rules and DICOM frame links.
- Platform audit retention, reviewer roles and electronic-signature policy.
- Which quality flags are required for each clinical algorithm.
- How legacy saved results map into v1 without fabricating provenance.

These open items block clinical adoption, not the synthetic technical contract
test. They require module owners and physician/product review.
