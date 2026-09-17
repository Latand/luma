#!/usr/bin/env bash
# Build the demo if needed, serve it over http, run the end-to-end suites. Requires bun (or node) + playwright, ffmpeg, Python with numpy/soundfile.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=${LUMA_PY:-.venv/bin/python}; [ -x "$PY" ] || PY=python3
export LUMA_PY="$PY"
[ -f examples/demo/Demo/target.json ] || "$PY" examples/make_demo.py
"$PY" studio/build_html.py examples/demo/Demo -o examples/demo/Luma_Demo.html >/dev/null   # always embed the current app/ parts
PORT=${LUMA_TEST_PORT:-8791}
python3 -m http.server "$PORT" --bind 127.0.0.1 --directory examples/demo >/dev/null 2>&1 &
SRV=$!
STUDIO_PORT=${LUMA_TEST_STUDIO_PORT:-8793}
TEST_LIBRARY=$(mktemp -d -t luma-studio-test-XXXXXX)
"$PY" studio/studio_server.py --port "$STUDIO_PORT" --songs "$TEST_LIBRARY" >/dev/null 2>&1 &
STUDIO_SRV=$!
trap 'kill $SRV $STUDIO_SRV 2>/dev/null || true; rm -rf "$TEST_LIBRARY"' EXIT
sleep 1
export LUMA_URL="http://127.0.0.1:$PORT/Luma_Demo.html"
export LUMA_STUDIO_URL="http://127.0.0.1:$STUDIO_PORT/"
export LUMA_TEST_LIBRARY="$TEST_LIBRARY"   # lessons.mjs generates the built-in lessons into this empty library
RUN=${LUMA_JS:-bun}; command -v "$RUN" >/dev/null || RUN=node
status=0
for t in scoring audio ux studio scale lessons history progress; do echo "== $t"; LUMA_SHOT="tests/e2e/shot_$t.png" "$RUN" "tests/e2e/$t.mjs" || status=1; done
"$PY" tests/studio_test.py || status=1
"$PY" tests/lyrics_text_test.py || status=1
"$PY" tests/lyrics_align_test.py || status=1
"$PY" tests/retranscribe_song_test.py || status=1
"$PY" tests/audio_stems_test.py || status=1   # last: it rebuilds the demo, so it must not race the suites served from it
exit $status
