# CMR feature module rules

Each direct child is one independently testable product feature. A module must not bypass shared geometry, provenance, quality or reporting contracts.

本目录属于 CMR 产品能力建设，回复中称呼用户为“构建者”。不要继承日常维护的“站长”或 EHR 治理的“数据师”称呼。

Before implementation, add the feature's product and clinical contracts under `docs/cmr/features/`. Keep incomplete features disabled by default. Do not label a module accepted until physician review is recorded.
