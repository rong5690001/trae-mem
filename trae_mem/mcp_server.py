import json
import os
import sys
import traceback
from typing import Any, Optional

from .api import build_injection_block
from .compress import ObservationLike, summarize_session
from .hooks_bridge import main as hooks_bridge_main
from .db import TraeMemDB


def _write(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _error(id_value: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_value, "error": {"code": code, "message": message}}


def _result(id_value: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_value, "result": payload}


def _tool_text_result(text: str, is_error: bool = False, structured: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": bool(is_error)}
    if structured is not None:
        out["structuredContent"] = structured
    return out


def _tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "trae_mem_search",
            "description": "在持久化记忆中搜索（轻量索引）。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["query"],
            },
        },
        {
            "name": "trae_mem_timeline",
            "description": "给定 observation_id，返回同一会话的时间窗口上下文。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "observation_id": {"type": "string"},
                    "window": {"type": "integer", "default": 10},
                },
                "required": ["observation_id"],
            },
        },
        {
            "name": "trae_mem_get_observations",
            "description": "按 ID 批量获取 observations 详情。",
            "inputSchema": {
                "type": "object",
                "properties": {"ids": {"type": "array", "items": {"type": "string"}}},
                "required": ["ids"],
            },
        },
        {
            "name": "trae_mem_inject",
            "description": "生成可注入到新会话的上下文块（含最近会话摘要与相关观测）。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 12},
                    "project": {"type": "string"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "trae_mem_start_session",
            "description": "创建一个持久化会话。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "meta": {"type": "object"},
                },
                "required": [],
            },
        },
        {
            "name": "trae_mem_log",
            "description": "写入一条观测（用户输入/工具调用/决策/错误）。支持 <private> 片段不入库。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session": {"type": "string"},
                    "kind": {"type": "string", "enum": ["user", "tool", "note", "decision", "error"]},
                    "tool_name": {"type": "string"},
                    "text": {"type": "string"},
                    "tags": {"type": "object"},
                },
                "required": ["session", "kind", "text"],
            },
        },
        {
            "name": "trae_mem_end_session",
            "description": "结束会话并生成 brief/detailed 两层摘要。",
            "inputSchema": {"type": "object", "properties": {"session": {"type": "string"}}, "required": ["session"]},
        },
        {
            "name": "trae_mem_hook_event",
            "description": "适配“生命周期事件”输入（stdin JSON 同构），写入记忆。event 支持 SessionStart/UserPromptSubmit/PreToolUse/PostToolUse/Stop/SessionEnd。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "event": {
                        "type": "string",
                        "enum": ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SessionEnd"],
                    },
                    "payload": {"type": "object"},
                },
                "required": ["event", "payload"],
            },
        },
    ]


def _handle_tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    db = TraeMemDB()
    try:
        db.init_schema()
        if name == "trae_mem_search":
            hits = db.search(str(args.get("query") or ""), limit=int(args.get("limit") or 20))
            payload = [
                {
                    "id": h.id,
                    "ts": h.ts,
                    "kind": h.kind,
                    "tool_name": h.tool_name,
                    "session_id": h.session_id,
                    "snippet": h.snippet,
                    "score": h.score,
                }
                for h in hits
            ]
            return _tool_text_result(json.dumps(payload, ensure_ascii=False, indent=2), structured={"results": payload})

        if name == "trae_mem_timeline":
            obs_id = str(args.get("observation_id") or "")
            window = int(args.get("window") or 10)
            rows = db.timeline(obs_id, window=window)
            items = [{k: r[k] for k in r.keys()} for r in rows]
            return _tool_text_result(json.dumps(items, ensure_ascii=False, indent=2), structured={"items": items})

        if name == "trae_mem_get_observations":
            ids = args.get("ids") or []
            if not isinstance(ids, list):
                return _tool_text_result("ids 必须是数组", is_error=True)
            rows = db.get_observations([str(i) for i in ids])
            items = [{k: r[k] for k in r.keys()} for r in rows]
            return _tool_text_result(json.dumps(items, ensure_ascii=False, indent=2), structured={"items": items})

        if name == "trae_mem_inject":
            query = str(args.get("query") or "")
            limit = int(args.get("limit") or 12)
            project = args.get("project")
            text = build_injection_block(db, query=query, limit=limit, project_path=str(project) if project else None)
            return _tool_text_result(text, structured={"context": text})

        if name == "trae_mem_start_session":
            project = args.get("project")
            meta = args.get("meta")
            if meta is not None and not isinstance(meta, dict):
                meta = {}
            sid = db.new_session(project_path=str(project) if project else None, meta=meta or {})
            return _tool_text_result(sid, structured={"session_id": sid})

        if name == "trae_mem_log":
            session = str(args.get("session") or "")
            kind = str(args.get("kind") or "")
            tool_name = args.get("tool_name")
            text = str(args.get("text") or "")
            tags = args.get("tags")
            if tags is not None and not isinstance(tags, dict):
                tags = {}
            from .compress import contains_private, remove_private

            private = False
            if contains_private(text):
                cleaned = remove_private(text)
                if cleaned:
                    text = cleaned
                else:
                    text = "[PRIVATE]"
                    private = True
            obs_id = db.add_observation(
                session_id=session,
                kind=kind,
                tool_name=str(tool_name) if tool_name else None,
                content=text,
                tags=tags or {},
                private=private,
            )
            return _tool_text_result(obs_id, structured={"observation_id": obs_id})

        if name == "trae_mem_end_session":
            session = str(args.get("session") or "")
            db.end_session(session)
            rows = db.get_observations_by_session(session, limit=5000)
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
            db.add_summary(session_id=session, level="brief", content=brief)
            db.add_summary(session_id=session, level="detailed", content=detailed)
            return _tool_text_result(session, structured={"session_id": session})

        if name == "trae_mem_hook_event":
            event = str(args.get("event") or "")
            payload = args.get("payload") or {}
            if not isinstance(payload, dict):
                payload = {}
            buf = json.dumps(payload, ensure_ascii=False)
            proc_argv = ["--event", event]
            stdin_backup = sys.stdin
            try:
                sys.stdin = __import__("io").StringIO(buf)
                rc = int(hooks_bridge_main(proc_argv))
            finally:
                sys.stdin = stdin_backup
            if rc != 0:
                return _tool_text_result(f"hook 处理失败 rc={rc}", is_error=True)
            return _tool_text_result("ok", structured={"ok": True})

        return _tool_text_result(f"未知工具: {name}", is_error=True)
    finally:
        db.close()


def serve_stdio() -> None:
    initialized = False
    server_info = {"name": "trae-mem", "version": "0.1.0"}
    while True:
        line = sys.stdin.readline()
        if not line:
            return
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue

        method = msg.get("method")
        id_value = msg.get("id")
        params = msg.get("params") or {}

        try:
            if method == "initialize":
                initialized = True
                protocol_version = params.get("protocolVersion") or "2025-11-25"
                _write(
                    _result(
                        id_value,
                        {
                            "protocolVersion": protocol_version,
                            "capabilities": {"tools": {}},
                            "serverInfo": server_info,
                        },
                    )
                )
                continue

            if method == "notifications/initialized":
                continue

            if not initialized:
                _write(_error(id_value, -32002, "not_initialized"))
                continue

            if method == "tools/list":
                _write(_result(id_value, {"tools": _tools()}))
                continue

            if method == "tools/call":
                name = str(params.get("name") or "")
                args = params.get("arguments") or {}
                if not isinstance(args, dict):
                    args = {}
                res = _handle_tool_call(name, args)
                _write(_result(id_value, res))
                continue

            _write(_error(id_value, -32601, f"method_not_found: {method}"))
        except Exception as e:
            if os.environ.get("TRAE_MEM_MCP_DEBUG") == "1":
                traceback.print_exc()
            _write(_error(id_value, -32000, f"server_error: {e}"))


def main() -> None:
    serve_stdio()


if __name__ == "__main__":
    main()
