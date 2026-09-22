#!/bin/bash
# MicroFish Shutdown Script

echo "=== MicroFish Stopping ==="

# Stop backend (port 5001)
if lsof -ti:5001 > /dev/null 2>&1; then
    echo "Stopping backend on port 5001..."
    kill $(lsof -ti:5001) 2>/dev/null || pkill -f "python.*run.py" 2>/dev/null
    sleep 1
    if ! lsof -ti:5001 > /dev/null 2>&1; then
        echo "Backend stopped"
    else
        echo "Warning: Backend may still be running"
    fi
else
    echo "Backend not running"
fi

# Stop frontend (port 3000)
if lsof -ti:3000 > /dev/null 2>&1; then
    echo "Stopping frontend on port 3000..."
    kill $(lsof -ti:3000) 2>/dev/null || pkill -f "vite" 2>/dev/null
    sleep 1
    if ! lsof -ti:3000 > /dev/null 2>&1; then
        echo "Frontend stopped"
    else
        echo "Warning: Frontend may still be running"
    fi
else
    echo "Frontend not running"
fi

# Clean up any remaining processes
pkill -f "microfish" 2>/dev/null

echo ""
echo "=== MicroFish Stopped ==="
