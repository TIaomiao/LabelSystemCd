# Shared CMR API core rules

This directory owns shared contracts and foundations only. Feature-specific formulas and UI behavior belong in `apps/api/modules/<feature>/`.

本目录属于 CMR 产品能力建设，回复中称呼用户为“构建者”。不要继承日常维护的“站长”或 EHR 治理的“数据师”称呼。

- Changes affecting two or more modules require an architecture decision and cross-module tests.
- Preserve coordinate systems, units, provenance and quality flags explicitly.
- Database schema changes require migration, rollback and production-risk review.
- Do not add patient data, runtime paths, credentials or model weights.
