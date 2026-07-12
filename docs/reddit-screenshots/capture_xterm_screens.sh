#!/usr/bin/env bash
set -euo pipefail
cd /home/deadgirl/Projects/Software/ffmpeg-ai
out=/home/deadgirl/Projects/Software/ffmpeg-ai/docs/reddit-screenshots
mkdir -p "$out"

capture() {
  local name="$1"
  local cols="$2"
  local rows="$3"
  local wait_s="$4"
  local cmd="$5"
  local title="ffmpeg-ai ${name}"
  xterm \
    -title "$title" \
    -geometry "${cols}x${rows}" \
    -fa "DejaVu Sans Mono" \
    -fs 10 \
    -bg '#05070a' \
    -fg '#e6edf3' \
    -cr '#00d4ff' \
    -bd '#05070a' \
    -xrm 'XTerm*scrollBar: false' \
    -e bash -lc "cd /home/deadgirl/Projects/Software/ffmpeg-ai; export TERM=xterm-256color COLUMNS=${cols} FORCE_COLOR=1; clear; printf '\033[38;5;81m$ %s\033[0m\n' \"$cmd\"; $cmd; printf '\n\033[38;5;244m[screenshot captured]\033[0m'; sleep 20" &
  local pid=$!
  local wid=''
  for _ in {1..40}; do
    wid=$(xdotool search --pid "$pid" 2>/dev/null | tail -n 1 || true)
    [[ -n "$wid" ]] && break
    sleep 0.25
  done
  if [[ -z "$wid" ]]; then
    echo "no window for $name" >&2
    return 1
  fi
  sleep "$wait_s"
  import -window "$wid" "$out/${name}.png"
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}

capture help 104 34 2 "uv run ffmpeg-ai --help"
capture providers 104 28 2 "uv run ffmpeg-ai providers"
capture dry-run 112 38 7 "uv run ffmpeg-ai generate 'why command line tools are coming back' --script docs/reddit-screenshots/demo-script.json --dry-run --style dramatic --caption-style bold-center --fresh"
