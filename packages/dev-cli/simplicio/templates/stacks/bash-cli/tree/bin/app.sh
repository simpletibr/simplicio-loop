#!/usr/bin/env bash
set -euo pipefail

main() {
  case "${1:-}" in
    --help|-h)
      printf '%s\n' "{project_name}: {goal}"
      ;;
    *)
      printf '%s\n' "ok"
      ;;
  esac
}

main "$@"
