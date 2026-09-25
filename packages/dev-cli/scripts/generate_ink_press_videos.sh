#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${ROOT}/assets/video"
REMOTION_PROJECT="${SIMPLICIO_REMOTION_PROJECT:-${ROOT}/../simplicio-remotion/videos/simplicio-dev-cli-ink-press}"
RENDER_DIR="${REMOTION_PROJECT}/out/localized"

for command_name in npm ffmpeg ffprobe; do
  command -v "${command_name}" >/dev/null || {
    printf 'Missing required command: %s\n' "${command_name}" >&2
    exit 1
  }
done

test -f "${REMOTION_PROJECT}/package.json" || {
  printf 'Missing Remotion production: %s\n' "${REMOTION_PROJECT}" >&2
  printf 'Set SIMPLICIO_REMOTION_PROJECT to its local path.\n' >&2
  exit 1
}

npm --prefix "${REMOTION_PROJECT}" run validate:locales
npm --prefix "${REMOTION_PROJECT}" run render:locales
npm --prefix "${REMOTION_PROJECT}" run validate:renders

mkdir -p "${OUT_DIR}"
cp \
  "${RENDER_DIR}/simplicio-dev-cli-ink-press.en.mp4" \
  "${OUT_DIR}/simplicio-ink-press-en-v1.mp4"
cp \
  "${RENDER_DIR}/simplicio-dev-cli-ink-press.pt-BR.mp4" \
  "${OUT_DIR}/simplicio-ink-press-pt-br-v1.mp4"

printf 'Generated and validated:\n'
find "${OUT_DIR}" -maxdepth 1 -type f -name 'simplicio-ink-press-*.mp4' -print | sort
