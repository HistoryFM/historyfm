#!/usr/bin/env bash
# Stop the novel generation daemon.
set -euo pipefail

PID_FILE="/Users/dhrumilparekh/NovelGen/logs/novel_daemon.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping daemon (PID $PID)..."
        kill "$PID"
        rm -f "$PID_FILE"
        echo "Daemon stopped."
    else
        echo "PID $PID not running. Cleaning up stale PID file."
        rm -f "$PID_FILE"
    fi
else
    echo "No PID file found. Attempting to kill by process name..."
    pkill -f "novel_daemon.py" 2>/dev/null && echo "Killed." || echo "No daemon process found."
fi
