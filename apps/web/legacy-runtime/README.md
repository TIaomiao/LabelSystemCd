# Frozen legacy Viewer runtime

This directory is a byte-for-byte snapshot of the compiled CMR Viewer assets present on the LabelSystem server on 2026-07-16. The main runtime uses cache-buster `20260716-la-strain-biplane-1`; the embedded patch was refreshed at `20260716-lge-scar-toggle-1`. The original React source was not present in Git, local backups, or the archived server bundle.

These files are retained only to make a clean build and disaster recovery possible while the Viewer is incrementally replaced by maintained source under `apps/web/src/`. Do not edit the minified bundle to implement new features. When the live legacy runtime is intentionally upgraded, refresh this snapshot and record the new cache-buster in `apps/web/index.html`.
