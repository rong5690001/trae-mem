#!/usr/bin/env bash
set -euo pipefail

DB="${TRAE_MEM_DB:-/tmp/trae_mem_demo.sqlite3}"
export TRAE_MEM_DB="$DB"

python3 -m trae_mem.cli init >/dev/null

SESSION_ID="$(python3 -m trae_mem.cli start-session --project "/tmp/demo-project")"
python3 -m trae_mem.cli log --session "$SESSION_ID" --kind user --text "我要实现一个音视频应用的预加载策略"
python3 -m trae_mem.cli log --session "$SESSION_ID" --kind tool --tool-name Grep --text "在 player/ 里搜索 preload 相关实现"
python3 -m trae_mem.cli log --session "$SESSION_ID" --kind decision --text "优先基于 ExoPlayer 的 MediaSource 预创建 + 缓存池"
python3 -m trae_mem.cli end-session --session "$SESSION_ID" >/dev/null

python3 -m trae_mem.cli search --query "预加载" --limit 5
python3 -m trae_mem.cli inject --query "预加载策略" --project "/tmp/demo-project"

