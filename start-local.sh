#!/bin/bash
# Keep Atmos frontend + backend running locally
set -e
ROOT="/Users/adityasarna/atmos"
export PATH="$ROOT/.tools/node/bin:$PATH"
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/.tools/pw-browsers"

cd "$ROOT"
docker start atmos-mongo >/dev/null 2>&1 || docker run -d --name atmos-mongo -p 27017:27017 mongo:7 >/dev/null

# Free ports
for p in 8000 3000; do
  lsof -ti TCP:$p 2>/dev/null | xargs kill -9 2>/dev/null || true
done
pkill -f "uvicorn server:app" 2>/dev/null || true
sleep 1

# Backend
cd "$ROOT/backend"
source .venv/bin/activate
set -a
# shellcheck disable=SC1091
source .env
set +a
export CORS_ORIGINS="http://localhost:3000,http://127.0.0.1:3000"
uvicorn server:app --host 0.0.0.0 --port 8000 >> "$ROOT/.tools/backend.log" 2>&1 &
BPID=$!
echo "Backend PID $BPID"

# Frontend
cd "$ROOT/frontend"
cat > .env <<'EOF'
REACT_APP_BACKEND_URL=http://localhost:8000
REACT_APP_DISABLE_AUTH=1
PORT=3000
BROWSER=none
HOST=127.0.0.1
EOF
BROWSER=none HOST=127.0.0.1 npm start >> "$ROOT/.tools/frontend.log" 2>&1 &
FPID=$!
echo "Frontend PID $FPID"

echo "$BPID" > "$ROOT/.tools/backend.pid"
echo "$FPID" > "$ROOT/.tools/frontend.pid"

echo "Waiting for health…"
for i in $(seq 1 60); do
  A=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/ 2>/dev/null || echo 0)
  F=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/ 2>/dev/null || echo 0)
  if [ "$A" = "200" ] && [ "$F" = "200" ]; then
    echo "Atmos is up:"
    echo "  http://localhost:3000"
    echo "  http://localhost:8000/api/"
    open "http://localhost:3000/dashboard" 2>/dev/null || true
    break
  fi
  sleep 1
done

# Keep this Terminal session alive and restart children if they die
while true; do
  if ! kill -0 "$BPID" 2>/dev/null; then
    echo "$(date) backend died — restarting"
    cd "$ROOT/backend"
    source .venv/bin/activate
    set -a; source .env; set +a
    uvicorn server:app --host 0.0.0.0 --port 8000 >> "$ROOT/.tools/backend.log" 2>&1 &
    BPID=$!
    echo "$BPID" > "$ROOT/.tools/backend.pid"
  fi
  if ! kill -0 "$FPID" 2>/dev/null; then
    echo "$(date) frontend died — restarting"
    cd "$ROOT/frontend"
    BROWSER=none HOST=127.0.0.1 npm start >> "$ROOT/.tools/frontend.log" 2>&1 &
    FPID=$!
    echo "$FPID" > "$ROOT/.tools/frontend.pid"
  fi
  sleep 5
done
