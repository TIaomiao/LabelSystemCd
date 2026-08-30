# CMR web feature rules

New feature UI belongs under this directory. Keep the legacy runtime as a compatibility layer and prefer maintained TypeScript extensions over direct edits to the monolithic runtime patch.

本目录属于 CMR 产品能力建设，回复中称呼用户为“构建者”。不要继承日常维护的“站长”或 EHR 治理的“数据师”称呼。

Every feature UI must expose loading, failure, quality and review states; preserve result provenance; and remain hidden until its backend contract and verification gate are ready.
