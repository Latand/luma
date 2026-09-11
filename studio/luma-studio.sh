#!/usr/bin/env bash
# Start Luma Studio (local converter + library) and open it in the browser. Creates the Python environment on first run.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT=${LUMA_STUDIO_PORT:-8792}
if [ ! -x .venv/bin/python ]; then
  echo "Creating .venv and installing dependencies (first run; PyTorch is large)…"
  if command -v uv >/dev/null; then uv venv --python 3.11 .venv >/dev/null; uv pip install --python .venv/bin/python -r requirements.txt
  else python3 -m venv .venv; .venv/bin/python -m pip install -r requirements.txt; fi
fi
# Built-in lessons live in the library like any other trainer. Synthesizing all three takes a few seconds and only
# happens when they are missing or when lessons/ or app/ changed; otherwise this is a no-op.
.venv/bin/python lessons/build_lessons.py --songs songs || echo "Уроки зібрати не вдалося; Studio запуститься без них."
if ! curl -fsS "http://127.0.0.1:$PORT/status" >/dev/null 2>&1; then
  mkdir -p songs/logs
  LUMA_STUDIO_PORT=$PORT setsid nohup .venv/bin/python studio/studio_server.py --port "$PORT" ${LUMA_COPY_TO:+--copy-to "$LUMA_COPY_TO"} > songs/logs/studio.log 2>&1 < /dev/null &
  for _ in $(seq 1 40); do curl -fsS "http://127.0.0.1:$PORT/status" >/dev/null 2>&1 && break; sleep 0.25; done
fi
echo "Luma Studio: http://127.0.0.1:$PORT/"
command -v xdg-open >/dev/null && xdg-open "http://127.0.0.1:$PORT/" >/dev/null 2>&1 || true
