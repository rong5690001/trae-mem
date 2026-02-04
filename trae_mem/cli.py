import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from .api import serve as serve_http
from .compress import ObservationLike, contains_private, remove_private, summarize_session
from .db import TraeMemDB


def _read_text_arg(text: Optional[str]) -> str:
    if text is not None:
        return text
    return sys.stdin.read()


def cmd_init(db: TraeMemDB, _args: argparse.Namespace) -> int:
    db.init_schema()
    print(str(db.db_path))
    return 0


def cmd_start_session(db: TraeMemDB, args: argparse.Namespace) -> int:
    meta = {}
    if args.meta_json:
        meta = json.loads(args.meta_json)
    session_id = db.new_session(project_path=args.project, meta=meta)
    print(session_id)
    return 0


def cmd_end_session(db: TraeMemDB, args: argparse.Namespace) -> int:
    session_id = args.session
    db.end_session(session_id)

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

    print(session_id)
    return 0


def cmd_log(db: TraeMemDB, args: argparse.Namespace) -> int:
    raw = _read_text_arg(args.text).strip()
    if not raw:
        return 0

    has_priv = contains_private(raw)
    content = remove_private(raw) if has_priv else raw
    private = bool(has_priv and not content)
    if not content and private:
        content = "[PRIVATE]"

    tags = {}
    if args.tags_json:
        tags = json.loads(args.tags_json)

    obs_id = db.add_observation(
        session_id=args.session,
        kind=args.kind,
        tool_name=args.tool_name,
        content=content,
        tags=tags,
        private=private,
    )
    print(obs_id)
    return 0


def cmd_search(db: TraeMemDB, args: argparse.Namespace) -> int:
    hits = db.search(args.query, limit=args.limit)
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
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_timeline(db: TraeMemDB, args: argparse.Namespace) -> int:
    rows = db.timeline(args.observation_id, window=args.window)
    payload = [{k: r[k] for k in r.keys()} for r in rows]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_get_observations(db: TraeMemDB, args: argparse.Namespace) -> int:
    rows = db.get_observations(args.ids)
    payload = [{k: r[k] for k in r.keys()} for r in rows]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_inject(db: TraeMemDB, args: argparse.Namespace) -> int:
    from .api import build_injection_block

    text = build_injection_block(db, query=args.query, limit=args.limit, project_path=args.project)
    print(text)
    return 0


def cmd_serve(_db: TraeMemDB, args: argparse.Namespace) -> int:
    serve_http(db_path=args.db, host=args.host, port=args.port)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="trae-mem")
    parser.add_argument("--db", default=None, help="SQLite db path (default: ~/.trae-mem/trae_mem.sqlite3 or $TRAE_MEM_DB)")

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init")
    p_init.set_defaults(fn=cmd_init)

    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=37777)
    p_serve.set_defaults(fn=cmd_serve)

    p_start = sub.add_parser("start-session")
    p_start.add_argument("--project", default=None)
    p_start.add_argument("--meta-json", dest="meta_json", default=None)
    p_start.set_defaults(fn=cmd_start_session)

    p_log = sub.add_parser("log")
    p_log.add_argument("--session", required=True)
    p_log.add_argument("--kind", required=True, choices=["user", "tool", "note", "decision", "error"])
    p_log.add_argument("--tool-name", dest="tool_name", default=None)
    p_log.add_argument("--text", default=None)
    p_log.add_argument("--tags-json", dest="tags_json", default=None)
    p_log.set_defaults(fn=cmd_log)

    p_end = sub.add_parser("end-session")
    p_end.add_argument("--session", required=True)
    p_end.set_defaults(fn=cmd_end_session)

    p_search = sub.add_parser("search")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--limit", type=int, default=20)
    p_search.set_defaults(fn=cmd_search)

    p_tl = sub.add_parser("timeline")
    p_tl.add_argument("--observation-id", required=True)
    p_tl.add_argument("--window", type=int, default=10)
    p_tl.set_defaults(fn=cmd_timeline)

    p_get = sub.add_parser("get-observations")
    p_get.add_argument("ids", nargs="+")
    p_get.set_defaults(fn=cmd_get_observations)

    p_inject = sub.add_parser("inject")
    p_inject.add_argument("--query", required=True)
    p_inject.add_argument("--limit", type=int, default=12)
    p_inject.add_argument("--project", default=None)
    p_inject.set_defaults(fn=cmd_inject)

    args = parser.parse_args(argv)

    db_path = None
    if args.db:
        db_path = Path(args.db).expanduser()

    db = TraeMemDB(db_path=db_path)
    try:
        db.init_schema()
        return int(args.fn(db, args))
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

