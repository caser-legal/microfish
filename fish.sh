#!/bin/bash
# MicroFish launcher — starts backend + frontend and opens the browser.
# Installed as alias `fish`.

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="/tmp/microfish_fish.log"

export PATH="$HOME/.local/bin:$PATH"

echo "🐟 Starting MicroFish..."

# Create required directories
mkdir -p "$PROJECT_DIR/backend/app/uploads/projects"
mkdir -p "$PROJECT_DIR/backend/app/uploads/simulations"

# Kill anything already running on our ports
lsof -ti:5001 2>/dev/null | xargs kill 2>/dev/null
lsof -ti:3000 2>/dev/null | xargs kill 2>/dev/null
sleep 1

# Start backend (Flask on :5001)
echo "   Starting backend (:5001)..."
cd "$PROJECT_DIR/backend" && \
  FLASK_DEBUG=True FLASK_HOST=0.0.0.0 FLASK_PORT=5001 \
  .venv/bin/python run.py > "$LOG_FILE" 2>&1 &

# Wait for backend
for i in $(seq 1 15); do
  if curl -s http://127.0.0.1:5001/health | grep -q "ok"; then
    echo "   ✅ Backend is up"
    break
  fi
  sleep 1
done

# Start frontend (Vite dev server on :3000)
echo "   Starting frontend (:3000)..."
cd "$PROJECT_DIR/frontend" && npx vite --host --port 3000 >> "$LOG_FILE" 2>&1 &

# Wait for frontend
for i in $(seq 1 10); do
  if curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 | grep -q "200"; then
    echo "   ✅ Frontend is up"
    break
  fi
  sleep 1
done

echo ""
echo "🐟  MicroFish is running!"
echo "   UI:      http://localhost:3000"
echo "   Backend: http://localhost:5001"
echo "   Logs:    tail -f $LOG_FILE"
echo "   Stop:    fishstop"
echo ""

# Open in browser
open http://localhost:3000
