# Embedded CMR Viewer source recovery

The original React/Vite Viewer source is absent from Git and all known server backups. `legacy-runtime/` contains a versioned snapshot of the currently deployed compiled runtime so a clean checkout can still produce a complete workstation bundle. It is not presented as recovered source code. Existing files in `dist/` remain the live frozen runtime so current contouring, propagation, measurements, and reporting keep working.

`src/curvature-manual-v1.ts` is a separately maintained TypeScript extension for the manual IVS/free-wall curvature workflow. It mounts on the existing Function/SAX viewer without replacing the legacy application.

Commands:

```bash
npm --prefix apps/web run typecheck
npm --prefix apps/web test
npm --prefix apps/web run build
```

The normal build writes a complete bundle to the ignored `apps/web/.vite-build/` staging directory and does not change the currently served bundle. After review, `npm --prefix apps/web run build:install` first rebuilds and verifies staging, then copies the verified index and curvature assets into `apps/web/dist/`. Existing legacy assets are never overwritten; on a clean checkout only missing legacy files are supplied from `legacy-runtime/`. Build-time index synchronization preserves the currently served bootstrap and cache-buster instead of rolling an active server back. Installing changes the page served by the running LabelSystem instance and therefore requires an explicit deployment decision.

To rehearse only the copy/install step without touching the served bundle, set `CVI_WORKSTATION_INSTALL_ROOT` to a disposable directory before running `node apps/web/scripts/install-staging.mjs`. When the variable is absent, the target remains `apps/web/dist/`.
