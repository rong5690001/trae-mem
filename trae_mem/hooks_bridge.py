import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from .compress import ObservationLike, summarize_session, contains_private, remove_private
from .db import TraeMemDB


def _default_map_path() -> Path:
    env = os.environ.get("TRAE_MEM_SESSION_MAP")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("TRAE_MEM_HOME")
    if base:
        return Path(base).expanduser() / "session_map.json"
    return Path.cwd() / ".trae-mem" / "session_map.json"


_MAP_PATH = _default_map_path()


def _load_map() -> dict[str, Any]:
    if _MAP_PATH.exists():
        try:
            return json.loads(_MAP_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_map(data: dict[str, Any]) -> None:
    _MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    _MAP_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _ensure_session(db: TraeMemDB, trae_session_id: str, project_path: Optional[str], meta: Optional[dict[str, Any]] = None) -> str:
    mp = _load_map()
    proj_key = project_path or ""
    key = f"{proj_key}:{trae_session_id}"
    existing = mp.get(key)
    if isinstance(existing, str) and existing:
        return existing
    sid = db.new_session(project_path=project_path, meta=meta or {})
    mp[key] = sid
    _save_map(mp)
    return sid


def _lookup_session(db: TraeMemDB, trae_session_id: str, project_path: Optional[str]) -> Optional[str]:
    mp = _load_map()
    proj_key = project_path or ""
    key = f"{proj_key}:{trae_session_id}"
    sid = mp.get(key)
    if isinstance(sid, str) and sid:
        return sid
    return None


def _read_stdin_json() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _truncate(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[: max(0, n - 1)] + "…"


def _norm_text_for_log(text: str) -> tuple[str, bool]:
    if contains_private(text):
        cleaned = remove_private(text)
        if cleaned:
            return cleaned, False
        return "[PRIVATE]", True
    return text, False


def _summarize_session(db: TraeMemDB, session_id: str) -> None:
    rows = db.get_observations_by_session(session_id, limit=5000)
    obs = [
        ObservationLike(
            ts=int(r["ts"]),
            kind=str(r["kind"]),
            tool_name=str(r["tool_name"]) if r["tool_name"] else None,
            content=str(r["content"]),
        )
        for r in rows
        if int(r["private"]) == 0
    ]
    brief = summarize_session(obs, max_chars=900)
    detailed = summarize_session(obs, max_chars=3200)
    db.add_summary(session_id=session_id, level="brief", content=brief)
    db.add_summary(session_id=session_id, level="detailed", content=detailed)


def handle_session_start(payload: dict[str, Any]) -> int:
    trae_session_id = str(payload.get("session_id") or "")
    cwd = str(payload.get("cwd") or "")
    source = str(payload.get("source") or "")
    db = TraeMemDB()
    try:
        db.init_schema()
        _ensure_session(db, trae_session_id, cwd or None, meta={"source": source})
        return 0
    finally:
        db.close()

def handle_user_prompt_submit(payload: dict[str, Any]) -> int:
    trae_session_id = str(payload.get("session_id") or "")
    cwd = str(payload.get("cwd") or "")
    prompt = str(payload.get("prompt") or "")
    text, private = _norm_text_for_log(prompt.strip())
    db = TraeMemDB()
    try:
        db.init_schema()
        sid = _ensure_session(db, trae_session_id, cwd or None, meta=None)
        db.add_observation(session_id=sid, kind="user", content=text, private=private)
        return 0
    finally:
        db.close()

def handle_pre_tool_use(payload: dict[str, Any]) -> int:
    trae_session_id = str(payload.get("session_id") or "")
    cwd = str(payload.get("cwd") or "")
    tool_name = str(payload.get("tool_name") or "")
    tool_input = json.dumps(payload.get("tool_input") or {}, ensure_ascii=False)
    txt = _truncate(f"准备执行 {tool_name} 输入={tool_input}", 1800)
    db = TraeMemDB()
    try:
        db.init_schema()
        sid = _ensure_session(db, trae_session_id, cwd or None, meta=None)
        db.add_observation(session_id=sid, kind="note", tool_name=tool_name, content=txt)
        return 0
    finally:
        db.close()

def handle_post_tool_use(payload: dict[str, Any]) -> int:
    trae_session_id = str(payload.get("session_id") or "")
    cwd = str(payload.get("cwd") or "")
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input")
    tool_resp = payload.get("tool_response")
    text_in = _truncate(json.dumps(tool_input, ensure_ascii=False), 2000)
    text_out = _truncate(json.dumps(tool_resp, ensure_ascii=False), 4000)
    txt = f"输入={text_in}\n输出={text_out}"
    db = TraeMemDB()
    try:
        db.init_schema()
        sid = _ensure_session(db, trae_session_id, cwd or None, meta=None)
        db.add_observation(session_id=sid, kind="tool", tool_name=tool_name, content=txt)
        return 0
    finally:
        db.close()

def handle_stop(payload: dict[str, Any]) -> int:
    trae_session_id = str(payload.get("session_id") or "")
    cwd = str(payload.get("cwd") or "")
    reason = str(payload.get("reason") or "")
    text = _truncate(f"停止，原因={reason}", 600)
    db = TraeMemDB()
    try:
        db.init_schema()
        sid = _ensure_session(db, trae_session_id, cwd or None, meta=None)
        db.add_observation(session_id=sid, kind="note", content=text)
        return 0
    finally:
        db.close()

def handle_session_end(payload: dict[str, Any]) -> int:
    trae_session_id = str(payload.get("session_id") or "")
    cwd = str(payload.get("cwd") or "")
    transcript_path = str(payload.get("transcript_path") or "")
    reason = str(payload.get("reason") or "")
    db = TraeMemDB()
    try:
        db.init_schema()
        sid = _lookup_session(db, trae_session_id, cwd or None)
        if not sid:
            sid = _ensure_session(db, trae_session_id, cwd or None, meta=None)
        db.add_observation(session_id=sid, kind="note", content=_truncate(f"结束，原因={reason} transcript={transcript_path}", 1200))
        db.end_session(sid)
        _summarize_session(db, sid)
        return 0
    finally:
        db.close()


_HANDLERS = {
    "SessionStart": handle_session_start,
    "UserPromptSubmit": handle_user_prompt_submit,
    "PreToolUse": handle_pre_tool_use,
    "PostToolUse": handle_post_tool_use,
    "Stop": handle_stop,
    "SessionEnd": handle_session_end,
}


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--event", required=True, choices=list(_HANDLERS.keys()))
    args = p.parse_args(argv)
    payload = _read_stdin_json()
    fn = _HANDLERS[args.event]
    return int(fn(payload))


if __name__ == "__main__":
    raise SystemExit(main())
