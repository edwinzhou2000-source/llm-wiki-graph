#!/bin/bash
# gbrain-sidecar management script with auto-restart
# Usage: ./sidecar.sh {start|stop|status|restart|daemon}

set -e

SIDECAR_DIR="$(cd "$(dirname "$0")" && pwd)"
SIDECAR_SCRIPT="$SIDECAR_DIR/gbrain-sidecar.ts"
PORT=9876
PID_FILE="$SIDECAR_DIR/.sidecar.pid"
LOCK_DIR="$HOME/.gbrain-llm-wiki/.gbrain/brain.pglite/.gbrain-lock"
PID_SOCK="$HOME/.gbrain-llm-wiki/.gbrain/brain.pglite/postmaster.pid"

_cleanup_locks() {
    # Remove stale PGLite lock files from crashed sidecar instances
    if [ -d "$LOCK_DIR" ]; then
        local pid=$(cat "$LOCK_DIR/postmaster.pid" 2>/dev/null || echo "")
        if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
            echo "🧹 Cleaning stale PGLite lock (pid $pid is dead)..."
            rm -rf "$LOCK_DIR" 2>/dev/null || true
        fi
    fi
    rm -f "$PID_SOCK" 2>/dev/null || true
}

_start_once() {
    _cleanup_locks
    
    if lsof -ti :$PORT >/dev/null 2>&1; then
        return 1  # already running
    fi
    
    cd "$SIDECAR_DIR"
    /opt/homebrew/bin/bun run "$SIDECAR_SCRIPT" &
    local pid=$!
    echo $pid > "$PID_FILE"
    
    # Wait for health check
    for i in $(seq 1 30); do
        if curl -s "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
            echo "✅ Sidecar ready (pid: $pid)"
            return 0
        fi
        sleep 1
    done
    echo "❌ Sidecar failed to start within 30s"
    return 1
}

_start() {
    if _start_once; then
        return 0
    fi
    # Already running
    local pid=$(lsof -ti :$PORT | head -1)
    echo "⚠️  Sidecar already running (pid: $pid)"
    return 1
}

_daemon() {
    # Auto-restart loop: if sidecar crashes, restart it
    echo "🔄 Sidecar daemon mode (auto-restart on crash)"
    while true; do
        if ! lsof -ti :$PORT >/dev/null 2>&1; then
            echo "$(date '+%H:%M:%S') 🔄 Restarting sidecar..."
            _start_once || true
        fi
        sleep 5
    done
}

_stop() {
    local pid=$(lsof -ti :$PORT 2>/dev/null | head -1)
    if [ -z "$pid" ]; then
        echo "Sidecar is not running."
        rm -f "$PID_FILE"
        _cleanup_locks
        return 0
    fi
    echo "🛑 Stopping sidecar (pid: $pid)..."
    kill "$pid" 2>/dev/null || true
    sleep 2
    if lsof -ti :$PORT >/dev/null 2>&1; then
        kill -9 "$pid" 2>/dev/null || true
        sleep 1
    fi
    rm -f "$PID_FILE"
    _cleanup_locks
    echo "✅ Stopped."
}

_status() {
    if lsof -ti :$PORT >/dev/null 2>&1; then
        local pid=$(lsof -ti :$PORT | head -1)
        local health=$(curl -s "http://127.0.0.1:$PORT/health" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"uptime={d.get('uptime',0):.0f}s\")" 2>/dev/null || echo "unknown")
        echo "✅ Sidecar running (pid: $pid, $health)"
    else
        echo "❌ Sidecar not running."
        return 1
    fi
}

case "${1:-status}" in
    start)   _start ;;
    daemon)  _daemon ;;  # auto-restart loop
    stop)    _stop ;;
    restart) _stop; sleep 1; _start ;;
    status)  _status ;;
    *)       echo "Usage: $0 {start|stop|status|restart|daemon}"; exit 1 ;;
esac
