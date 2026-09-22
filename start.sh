#!/bin/bash
# MicroFish Startup Script

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="/tmp/microfish.log"

echo "=== MicroFish Starting ==="

# Create required directories if they don't exist
mkdir -p "$PROJECT_DIR/backend/app/uploads/projects"
mkdir -p "$PROJECT_DIR/backend/app/uploads/simulations"

# Kill any existing processes
pkill -f "python.*run.py" 2>/dev/null || true
pkill -f "vite.*host" 2>/dev/null || true
sleep 1

# Check if backend is already running
if lsof -ti:5001 > /dev/null 2>&1; then
    echo "Backend already running on port 5001"
else
    echo "Starting backend on port 5001..."
    cd "$PROJECT_DIR/backend" && uv run python run.py > "$LOG_FILE" 2>&1 &
    sleep 3
    if lsof -ti:5001 > /dev/null 2>&1; then
        echo "Backend started successfully"
    else
        echo "Failed to start backend. Check logs: tail -f $LOG_FILE"
    fi
fi

# Check if frontend is already running
if lsof -ti:3000 > /dev/null 2>&1; then
    echo "Frontend already running on port 3000"
else
    echo "Starting frontend on port 3000..."
    cd "$PROJECT_DIR/frontend" && npm run dev > "$LOG_FILE" 2>&1 &
    sleep 3
    if lsof -ti:3000 > /dev/null 2>&1; then
        echo "Frontend started successfully"
    else
        echo "Failed to start frontend. Check logs: tail -f $LOG_FILE"
    fi
fi

echo ""
echo "=== MicroFish Status ==="
echo "Frontend: http://localhost:3000"
echo "Backend:  http://localhost:5001"
echo "Logs:     tail -f $LOG_FILE"
echo ""

# Auto-open frontend in browser
open http://localhost:3000

echo ""
echo "Use 'microfish-stop' to shutdown"
