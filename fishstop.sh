#!/bin/bash
# MicroFish stopper — kills backend + frontend.
# Installed as alias `fishstop`.

echo "🐟 Stopping MicroFish..."

# Kill by port
for port in 5001 3000; do
  pids=$(lsof -ti:$port 2>/dev/null)
  if [ -n "$pids" ]; then
    echo "   Killing port $port (pid: $(echo $pids | tr '\n' ' '))"
    echo "$pids" | xargs kill 2>/dev/null
  fi
done

# Also kill any lingering python run.py / vite processes
pkill -f "python.*run.py" 2>/dev/null
pkill -f "vite.*3000" 2>/dev/null
sleep 1

# Verify
backend=$(lsof -ti:5001 2>/dev/null)
frontend=$(lsof -ti:3000 2>/dev/null)

if [ -z "$backend" ] && [ -z "$frontend" ]; then
  echo "   ✅ Everything stopped"
else
  echo "   ⚠️  Some processes may still be running — try: kill -9 $backend $frontend"
fi

echo "🐟 MicroFish stopped."
