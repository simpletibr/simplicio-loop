#!/usr/bin/env bash
set -euo pipefail

source_path="${BASH_SOURCE[0]}"
while [[ -L "${source_path}" ]]; do
  source_dir="$(cd "$(dirname "${source_path}")" && pwd)"
  target_path="$(readlink "${source_path}")"
  if [[ "${target_path}" == /* ]]; then
    source_path="${target_path}"
  else
    source_path="${source_dir}/${target_path}"
  fi
done

script_dir="$(cd "$(dirname "${source_path}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
python_bin="${SIMPLICIO_PYTHON_BIN:-/opt/homebrew/opt/python@3.14/bin/python3.14}"

if [[ -n "${PYTHONPATH:-}" ]]; then
  export PYTHONPATH="${repo_root}:${PYTHONPATH}"
else
  export PYTHONPATH="${repo_root}"
fi

exec "${python_bin}" -m simplicio.cli "$@"
