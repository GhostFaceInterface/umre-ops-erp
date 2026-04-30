#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

PYTHON_BIN="${CODE_INTEL_PYTHON:-${REPO_ROOT}/.venv-code-intel/bin/python}"
if [ ! -x "${PYTHON_BIN}" ]; then
  PYTHON_BIN="${CODE_INTEL_PYTHON:-python3}"
fi

if [ -z "${CODEBASE_ROOT:-}" ] || [ "${CODEBASE_ROOT}" = "." ]; then
  export CODEBASE_ROOT="${REPO_ROOT}"
else
  CODEBASE_ROOT="$(cd "${CODEBASE_ROOT}" && pwd)"
  export CODEBASE_ROOT
fi

exec "${PYTHON_BIN}" "${REPO_ROOT}/scripts/mcp_server.py"
