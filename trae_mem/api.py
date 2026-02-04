import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional

from .db import TraeMemDB


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json; charset=utf-8")
    handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> Any:
    length = int(handler.headers.get("content-length", "0") or "0")
    raw = handler.rfile.read(length) if length > 0 else b"{}"
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _row_to_dict(row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


class _Handler(BaseHTTPRequestHandler):
    db: TraeMemDB

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/health":
            return _json_response(self, 200, {"ok": True})

        if path == "/search":
            q = (qs.get("q") or [""])[0]
            limit = int((qs.get("limit") or ["20"])[0])
            hits = self.db.search(q, limit=limit)
            return _json_response(
                self,
                200,
                {
                    "query": q,
                    "results": [
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
                    ],
                },
            )

        if path == "/timeline":
            observation_id = (qs.get("observation_id") or [""])[0]
            window = int((qs.get("window") or ["10"])[0])
            rows = self.db.timeline(observation_id, window=window)
            return _json_response(self, 200, {"observation_id": observation_id, "items": [_row_to_dict(r) for r in rows]})

        if path == "/inject":
            q = (qs.get("q") or [""])[0]
            limit = int((qs.get("limit") or ["12"])[0])
            project = (qs.get("project") or [None])[0]
            text = build_injection_block(self.db, query=q, limit=limit, project_path=project)
            return _json_response(self, 200, {"query": q, "context": text})

        return _json_response(self, 404, {"error": "not_found"})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/get_observations":
            body = _read_json(self)
            ids = body.get("ids") or []
            if not isinstance(ids, list):
                return _json_response(self, 400, {"error": "ids must be a list"})
            rows = self.db.get_observations([str(i) for i in ids])
            return _json_response(self, 200, {"items": [_row_to_dict(r) for r in rows]})

        return _json_response(self, 404, {"error": "not_found"})


def build_injection_block(db: TraeMemDB, query: str, limit: int = 12, project_path: Optional[str] = None) -> str:
    hits = db.search(query, limit=limit) if query.strip() else []
    ids = [h.id for h in hits]
    obs_rows = db.get_observations(ids)
    sessions = db.get_recent_sessions(project_path=project_path, limit=5)

    lines: list[str] = []
    lines.append("【trae-mem 注入上下文】")

    if query.strip():
        lines.append(f"查询：{query.strip()}")

    if sessions:
        lines.append("")
        lines.append("最近会话：")
        for s in sessions[:5]:
            started = s["started_at"]
            ended = s["ended_at"]
            lines.append(f"- session={s['id']} started_at={started} ended_at={ended}")
            summary = db.get_latest_summary(session_id=s["id"], level="brief")
            if summary and summary["content"]:
                content = str(summary["content"]).strip()
                if len(content) > 800:
                    content = content[:799] + "…"
                lines.append(f"  摘要：{content}")

    if hits:
        lines.append("")
        lines.append("相关观测（索引级）：")
        for h in hits:
            tn = f"/{h.tool_name}" if h.tool_name else ""
            lines.append(f"- {h.id} [{h.kind}{tn}] {h.snippet}")

    if obs_rows:
        lines.append("")
        lines.append("相关观测（细节级，截断）：")
        for r in obs_rows[: min(len(obs_rows), 20)]:
            tool = f"/{r['tool_name']}" if r["tool_name"] else ""
            content = (r["content"] or "").strip()
            if len(content) > 500:
                content = content[:499] + "…"
            lines.append(f"- {r['id']} [{r['kind']}{tool}] {content}")

    return "\n".join(lines).strip()


def serve(db_path: Optional[str], host: str, port: int) -> None:
    db = TraeMemDB(None if db_path is None else __import__("pathlib").Path(db_path))
    db.init_schema()

    class Handler(_Handler):
        pass

    Handler.db = db
    httpd = HTTPServer((host, port), Handler)
    try:
        httpd.serve_forever()
    finally:
        db.close()


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=37777)
    p.add_argument("--db", default=None)
    args = p.parse_args()
    serve(db_path=args.db, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
