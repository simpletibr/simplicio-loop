#!/usr/bin/env bash
set -euo pipefail

FRONTEND_COMMAND="${FRONTEND_COMMAND:-<FRONTEND_START_COMMAND>}"
BACKEND_COMMAND="${BACKEND_COMMAND:-<BACKEND_START_COMMAND>}"

echo "Starting <APP_NAME> local services"
echo "Frontend URL: <FRONTEND_URL>"
echo "Backend URL: <BACKEND_URL>"

if [[ "$FRONTEND_COMMAND" == \<* || "$BACKEND_COMMAND" == \<* ]]; then
  echo "Update scripts/start.sh with the real project commands before using it."
  exit 1
fi

echo "Run frontend command:"
echo "$FRONTEND_COMMAND"

echo "Run backend command:"
echo "$BACKEND_COMMAND"
