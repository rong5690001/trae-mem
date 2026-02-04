import json
import os
import re
import textwrap
import urllib.request
from dataclasses import dataclass
from typing import Iterable, Optional


_PRIVATE_RE = re.compile(r"<private>[\s\S]*?</private>", re.IGNORECASE)


def redact_private(text: str) -> str:
    return _PRIVATE_RE.sub("[PRIVATE]", text)


def contains_private(text: str) -> bool:
    return bool(_PRIVATE_RE.search(text))


def remove_private(text: str) -> str:
    return _PRIVATE_RE.sub("", text).strip()


def _dedupe_preserve_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        k = it.strip()
        if not k:
            continue
        if k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def _clip(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[: max(0, max_len - 1)] + "…"


def _as_bullets(lines: list[str], max_chars: int) -> str:
    out_lines: list[str] = []
    remaining = max_chars
    for ln in lines:
        bullet = f"- {ln}"
        if len(bullet) + 1 > remaining:
            break
        out_lines.append(bullet)
        remaining -= len(bullet) + 1
    return "\n".join(out_lines).strip()


@dataclass(frozen=True)
class ObservationLike:
    ts: int
    kind: str
    tool_name: Optional[str]
    content: str


def heuristic_session_summary(observations: list[ObservationLike], max_chars: int) -> str:
    user_msgs: list[str] = []
    tool_actions: list[str] = []
    decisions: list[str] = []
    errors: list[str] = []

    for o in observations:
        c = remove_private(o.content)
        if not c:
            continue

        if o.kind == "user":
            user_msgs.append(_clip(re.sub(r"\s+", " ", c), 180))
            continue

        if o.kind == "tool":
            base = o.tool_name or "tool"
            one_line = _clip(re.sub(r"\s+", " ", c), 220)
            tool_actions.append(f"{base}: {one_line}")
            continue

        if o.kind in ("decision", "note"):
            decisions.append(_clip(re.sub(r"\s+", " ", c), 220))
            continue

        if o.kind in ("error", "exception"):
            errors.append(_clip(re.sub(r"\s+", " ", c), 220))
            continue

    user_msgs = _dedupe_preserve_order(user_msgs)
    tool_actions = _dedupe_preserve_order(tool_actions)
    decisions = _dedupe_preserve_order(decisions)
    errors = _dedupe_preserve_order(errors)

    lines: list[str] = []
    if user_msgs:
        lines.append("用户意图/输入")
        for m in (user_msgs[:3] + (["…"] if len(user_msgs) > 3 else [])):
            lines.append(f"  {m}")
    if decisions:
        lines.append("关键结论/决策")
        for d in decisions[:6]:
            lines.append(f"  {d}")
    if tool_actions:
        lines.append("工具动作/线索")
        for a in tool_actions[:8]:
            lines.append(f"  {a}")
    if errors:
        lines.append("错误/风险")
        for e in errors[:6]:
            lines.append(f"  {e}")

    flat = _dedupe_preserve_order(lines)
    return _as_bullets([ln.rstrip() for ln in flat], max_chars=max_chars)


def _llm_provider() -> str:
    return (os.environ.get("TRAE_MEM_SUMMARIZER") or "none").strip().lower()


def _anthropic_summarize(prompt: str, max_tokens: int) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    model = os.environ.get("TRAE_MEM_ANTHROPIC_MODEL") or "claude-3-5-sonnet-latest"
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    content = payload.get("content") or []
    texts = [c.get("text", "") for c in content if isinstance(c, dict)]
    return "\n".join(t for t in texts if t).strip()


def _openai_summarize(prompt: str, max_tokens: int) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    model = os.environ.get("TRAE_MEM_OPENAI_MODEL") or "gpt-4.1-mini"
    body = {
        "model": model,
        "max_output_tokens": max_tokens,
        "input": prompt,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json", "authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    out = payload.get("output") or []
    texts: list[str] = []
    for item in out:
        if not isinstance(item, dict):
            continue
        for c in item.get("content") or []:
            if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                if c.get("text"):
                    texts.append(c["text"])
    return "\n".join(texts).strip()


def llm_session_summary(observations: list[ObservationLike], max_chars: int) -> str:
    provider = _llm_provider()
    raw = "\n\n".join(
        f"[{o.ts}] {o.kind}{'/' + o.tool_name if o.tool_name else ''}\n{remove_private(o.content)}"
        for o in observations
        if remove_private(o.content)
    )
    prompt = textwrap.dedent(
        f"""
        你是一个“会话记忆压缩器”。请把下面的会话日志压缩成可注入到下次会话的上下文，要求：
        1) 使用中文；2) 只输出要点；3) 不要包含任何 <private> 内容；4) 总长度尽量不超过 {max_chars} 字符。

        输出格式：
        - 用户目标：
        - 已完成：
        - 未解决/风险：
        - 下一步建议：

        会话日志：
        {raw}
        """
    ).strip()

    if provider == "anthropic":
        return _clip(_anthropic_summarize(prompt, max_tokens=800), max_chars)
    if provider == "openai":
        return _clip(_openai_summarize(prompt, max_tokens=800), max_chars)
    raise RuntimeError(f"Unsupported summarizer provider: {provider}")


def summarize_session(observations: list[ObservationLike], max_chars: int) -> str:
    provider = _llm_provider()
    if provider == "none":
        return heuristic_session_summary(observations, max_chars=max_chars)
    try:
        return llm_session_summary(observations, max_chars=max_chars)
    except Exception:
        return heuristic_session_summary(observations, max_chars=max_chars)

