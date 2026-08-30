# CMR web feature rules

New feature UI belongs under this directory. Keep the legacy runtime as a compatibility layer and prefer maintained TypeScript extensions over direct edits to the monolithic runtime patch.

Every feature UI must expose loading, failure, quality and review states; preserve result provenance; and remain hidden until its backend contract and verification gate are ready.
