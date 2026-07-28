#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${ROOT}/assets/video"
FFMPEG="${FFMPEG:-ffmpeg}"
MAGICK="${INK_PRESS_MAGICK:-magick}"
FONT="${INK_PRESS_FONT:-/System/Library/Fonts/HelveticaNeue.ttc}"
HERO="${ROOT}/output/imagegen/simplicio-cli-readme-hero.png"
PROOF="${ROOT}/output/imagegen/simplicio-cli-proof-receipt.png"

for command_name in "${FFMPEG}" "${MAGICK}" ffprobe; do
  command -v "${command_name}" >/dev/null || {
    printf 'Missing required command: %s\n' "${command_name}" >&2
    exit 1
  }
done
for asset in "${HERO}" "${PROOF}" "${FONT}"; do
  test -f "${asset}" || {
    printf 'Missing Ink Press source asset: %s\n' "${asset}" >&2
    exit 1
  }
done

mkdir -p "${OUT_DIR}"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "${WORK_DIR}"' EXIT

encode_scene() {
  local image="$1"
  local destination="$2"

  "${FFMPEG}" -hide_banner -loglevel error -y \
    -loop 1 -framerate 30 -i "${image}" -t 6 \
    -vf "format=yuv420p" -an -c:v libx264 -profile:v high -preset medium -crf 20 \
    -movflags +faststart "${destination}"
}

render_video() {
  local language="$1"
  local output_name="$2"
  local title="$3"
  local subtitle="$4"
  local feature_line="$5"
  local closing="$6"
  local url_line="$7"
  local scene_dir="${WORK_DIR}/${language}"
  mkdir -p "${scene_dir}"

  "${MAGICK}" "${HERO}" -resize '1920x1080^' -gravity northwest -crop 1920x1080+0+0 +repage \
    -fill '#06111ddd' -draw 'rectangle 64,610 1194,940' \
    -font "${FONT}" -fill '#ffc878' -pointsize 34 -annotate +104+660 'INK PRESS' \
    -fill white -pointsize 78 -annotate +100+720 "${title}" \
    -fill '#d9e7f5' -pointsize 34 -annotate +104+830 "${subtitle}" \
    "${scene_dir}/01.png"

  "${MAGICK}" "${PROOF}" -resize '1920x1080^' -gravity northwest -crop 1920x1080+0+0 +repage \
    -fill '#06111ddd' -draw 'rectangle 70,70 1290,320' \
    -font "${FONT}" -fill white -pointsize 62 -annotate +110+150 "${feature_line}" \
    -fill '#ffc878' -pointsize 34 -annotate +112+240 'simplicio-dev-cli' \
    "${scene_dir}/02.png"

  "${MAGICK}" -size 1920x1080 "xc:#06111f" \
    -fill '#0b1d32' -draw 'rectangle 80,170 1840,870' \
    -fill '#53d5ff' -draw 'rectangle 112,202 124,838' \
    -font "${FONT}" -fill white -pointsize 70 -annotate +180+370 "${closing}" \
    -fill '#ffc878' -pointsize 36 -annotate +184+610 "${url_line}" \
    -fill '#d9e7f5' -pointsize 30 -annotate +184+720 'context  /  diff  /  tests  /  evidence' \
    "${scene_dir}/03.png"

  encode_scene "${scene_dir}/01.png" "${scene_dir}/01.mp4"
  encode_scene "${scene_dir}/02.png" "${scene_dir}/02.mp4"
  encode_scene "${scene_dir}/03.png" "${scene_dir}/03.mp4"

  "${FFMPEG}" -hide_banner -loglevel error -y \
    -i "${scene_dir}/01.mp4" -i "${scene_dir}/02.mp4" -i "${scene_dir}/03.mp4" \
    -filter_complex "[0:v][1:v][2:v]concat=n=3:v=1:a=0,format=yuv420p[v]" \
    -map "[v]" -an -c:v libx264 -profile:v high -preset medium -crf 20 \
    -movflags +faststart "${OUT_DIR}/${output_name}"
}

render_video \
  "en" \
  "simplicio-ink-press-en-v1.mp4" \
  "Ship code with proof." \
  "A focused operator for trustworthy changes." \
  "Context. Diff. Tests. Evidence." \
  "One line in. Verified change out." \
  "github.com/wesleysimplicio/simplicio-dev-cli"

render_video \
  "pt-br" \
  "simplicio-ink-press-pt-br-v1.mp4" \
  "Entregue código com prova." \
  "Um operador focado para mudanças confiáveis." \
  "Contexto. Diff. Testes. Evidência." \
  "Uma linha entra. Uma mudança verificada sai." \
  "github.com/wesleysimplicio/simplicio-dev-cli"

printf 'Generated:\n'
find "${OUT_DIR}" -maxdepth 1 -type f -name 'simplicio-ink-press-*.mp4' -print | sort
