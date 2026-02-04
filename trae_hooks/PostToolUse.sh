#!/usr/bin/env bash
set -euo pipefail
export TRAE_MEM_HOME="${TRAE_MEM_HOME:-"$PWD/.trae-mem"}"
python3 -m trae_mem.hooks_bridge --event PostToolUse
