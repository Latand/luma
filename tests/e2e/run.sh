#!/usr/bin/env bash
# Build the demo if needed, serve it over http, run the end-to-end suites. Requires bun (or node) + playwright, ffmpeg, Python with numpy/soundfile.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=${LUMA_PY:-.venv/bin/python}; [ -x "$PY" ] || PY=python3
[ -f examples/demo/Demo/target.json ] || "$PY" examples/make_demo.py
"$PY" studio/build_html.py examples/demo/Demo -o examples/demo/Luma_Demo.html >/dev/null   # always embed the current app/ parts
PORT=${LUMA_TEST_PORT:-8791}
python3 -m http.server "$PORT" --bind 127.0.0.1 --directory examples/demo >/dev/null 2>&1 &
SRV=$!; trap 'kill $SRV 2>/dev/null || true' EXIT; sleep 1
export LUMA_URL="http://127.0.0.1:$PORT/Luma_Demo.html"
RUN=${LUMA_JS:-bun}; command -v "$RUN" >/dev/null || RUN=node
status=0
for t in scoring audio; do echo "== $t"; LUMA_SHOT="tests/e2e/shot_$t.png" "$RUN" "tests/e2e/$t.mjs" || status=1; done
exit $status
