#!/bin/bash

# Define paths
PROJECT_ROOT="/home/Larry/code/Ziqiu/LabelSystem"
BACKEND_DIR="$PROJECT_ROOT"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
SHOWCASE_DIR="/home/Larry/code/Ziqiu/MRIAgent/CardioAgentWeb"
FRP_DIR="$PROJECT_ROOT/frp_0.52.3_linux_amd64"
LOG_DIR="$PROJECT_ROOT/logs"

# Create logs directory
mkdir -p "$LOG_DIR"

CONDA_ENV="label_sys"
CONDA_SH="$HOME/miniconda3/etc/profile.d/conda.sh"

kill_by_cwd_and_cmd() {
    local cwd="$1"
    local pattern="$2"

    for pid in $(pgrep -f "$pattern" || true); do
        if [ "$(readlink "/proc/$pid/cwd" 2>/dev/null)" = "$cwd" ]; then
            kill "$pid" 2>/dev/null || true
        fi
    done
}

echo "Stopping existing LabelSystem processes..."
kill_by_cwd_and_cmd "$BACKEND_DIR" "backend/app.py"
kill_by_cwd_and_cmd "$BACKEND_DIR" "apps.api.main"
kill_by_cwd_and_cmd "$FRONTEND_DIR" "vite"
kill_by_cwd_and_cmd "$FRONTEND_DIR" "npm run dev"
kill_by_cwd_and_cmd "$SHOWCASE_DIR" "next dev"
kill_by_cwd_and_cmd "$SHOWCASE_DIR" "npm run dev"
# Be careful not to kill CardiacLabUID's FRP if it shares the name, but here we target specific config if possible or just rely on process name unique enough? 
# frpc usually looks same. Let's kill by config file if possible, or just kill all frpc for LabelSystem path.
# For simplicity and safety given previous context, let's try to kill specific PIDs or just 'pkill -f frpc' might be too aggressive if Cardiac is running.
# However, user only asked for LabelSystem. But standard pkill -f "frpc -c frpc.ini" might match.
kill_by_cwd_and_cmd "$FRP_DIR" "frpc"

echo "Starting LabelSystem Backend..."
cd "$BACKEND_DIR"
setsid bash -lc "exec '$HOME/miniconda3/bin/python' backend/app.py" > "$LOG_DIR/backend.log" 2>&1 < /dev/null &
echo "Backend PID: $!"

echo "Starting CVI Workstation API..."
cd "$BACKEND_DIR"
setsid bash -lc "source '$CONDA_SH' && conda activate '$CONDA_ENV' && exec deployment/linux/start_api.sh" > "$LOG_DIR/cvi-api.log" 2>&1 < /dev/null &
echo "CVI API PID: $!"

echo "Starting LabelSystem Frontend..."
cd "$FRONTEND_DIR"
setsid bash -lc "source '$CONDA_SH' && conda activate '$CONDA_ENV' && exec npm run dev" > "$LOG_DIR/frontend.log" 2>&1 < /dev/null &
echo "Frontend PID: $!"

echo "Starting Showcase Web..."
cd "$SHOWCASE_DIR"
setsid bash -lc "exec npm run dev" > "$LOG_DIR/showcase-web.log" 2>&1 < /dev/null &
echo "Showcase Web PID: $!"

echo "Starting LabelSystem FRP..."
cd "$FRP_DIR"
setsid env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY ./frpc -c frpc_public_frontend_only.ini > "$LOG_DIR/frp-public.log" 2>&1 < /dev/null &
echo "FRP PID: $!"

echo "LabelSystem services started in background."
