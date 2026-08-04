# Isolated CMR Workstation demo profile

This profile runs the complete repository code against isolated runtime state. It does not copy or simplify the application source.

## Data boundary

Place only 2–5 de-identified demonstration cases under `.labelsystem-demo/cases/`. Do not symlink production roots into this directory. The demo profile exposes only this root to the workstation catalogue and uses separate LabelSystem and CVI databases, generated files, ports, and logs.

Repository investigations remain read-only. A finding that depends on a missing production case, directory permission, Link mapping, or production database state must be marked `production_data_required`.

## Start

Build the main frontend once:

```bash
cd frontend
npm run build
cd ..
```

Then run:

```bash
deployment/demo/start_demo.sh
```

Open `http://127.0.0.1:15173`. Press Ctrl-C in the launch terminal to stop the demo services.

The default isolated runtime directory is `.labelsystem-demo/` and is ignored by Git. Override it with `LABELSYSTEM_DEMO_RUNTIME_DIR` when needed.

## Safety boundary

- Full repository source is available to the embedded Codex investigator in read-only mode.
- Demo services cannot discover the configured production case roots through the catalogue.
- The Demo profile does not authorize code modification, deployment, or access to production DICOM data.
- Modification and release remain separate: an approved plan should later be implemented in a temporary Git worktree and reviewed before deployment.
