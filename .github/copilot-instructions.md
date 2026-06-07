---
description: "Workspace instructions for the CMR Labeling & Analysis System. Use when working on backend Python, frontend React/TypeScript, deployment scripts, or docs in this repo."
---

# Workspace Instructions for LabelSystem

## Project overview
This repository is a medical imaging labeling and analysis platform with:
- `frontend/`: React 18 + TypeScript + Vite UI, Ant Design components, Cornerstone.js DICOM viewers
- `backend/`: Flask Python server, SQLite/SQLAlchemy, image processing, AI model integration
- `README.md` and `README_RESTART.md`: primary documentation and startup commands
- `start_background.sh`: helper to run/stop backend and frontend together

## Common tasks

### Run locally
- Backend: `conda run -n label_sys python backend/app.py` or `python backend/app.py` if the environment is already active
- Frontend: `cd frontend && npm run dev`
- React build: `cd frontend && npm run build`

### Dependencies
- Backend: `backend/requirements.txt`
- Frontend: `frontend/package.json`

## Code organization
- `frontend/src/`: pages, components, hooks, api clients, utilities
- `frontend/src/i18n*`: localization bundles
- `backend/`: Flask app, routes, models, extensions, diagnosis and hospital browser modules
- `backend/src/`: internal AI/segmentation support code and related docs
- `backend/checkpoints/`: model weights
- `backend/instance/`: runtime database files

## Agent guidance
- Preserve existing structure and naming conventions in `frontend/src` and `backend/`
- Prefer minimal edits and keep Chinese comments/context intact when editing domain-specific medical or imaging code
- Use `README_RESTART.md` for startup guidance and `start_background.sh` for background run scripts
- When changing API behavior, update both backend routes and frontend calls if applicable
- When modifying the UI, follow existing React/TypeScript patterns and use Ant Design components consistently

## When not to change
- Do not remove or rewrite `backend/checkpoints/` weights
- Do not change environment-specific paths in documentation like hardcoded local conda paths unless the user asks to generalize them
- Do not break `frontend/package-lock.json` without a matching `npm install` / lockfile update plan

## Quick reference
- `README.md`: system overview and architecture
- `README_RESTART.md`: restart/run commands in Chinese/English
- `start_background.sh`: start/stop helper for backend and frontend
- `frontend/package.json`: frontend scripts and dependencies
- `backend/requirements.txt`: backend Python dependencies
- `backend/routes.py`: main Flask API routes
- `backend/app.py`: Flask app entrypoint

## Useful prompts
- "Help me debug the backend Flask route for patient uploads in `backend/routes.py`."
- "Refactor the React page at `frontend/src/pages/Cardiac/Diagnosis.tsx` to simplify conditional rendering."
- "Add a new API endpoint in Flask and wire it to the frontend Vite dev server proxy."
