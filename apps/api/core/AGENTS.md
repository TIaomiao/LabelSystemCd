# Shared CMR API core rules

This directory owns shared contracts and foundations only. Feature-specific formulas and UI behavior belong in `apps/api/modules/<feature>/`.

- Changes affecting two or more modules require an architecture decision and cross-module tests.
- Preserve coordinate systems, units, provenance and quality flags explicitly.
- Database schema changes require migration, rollback and production-risk review.
- Do not add patient data, runtime paths, credentials or model weights.
