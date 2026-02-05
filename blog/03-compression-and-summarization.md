# 03｜压缩与摘要：让“会话日志”变成可注入的短记忆

存储一切并不等于拥有记忆。对 IDE 的 AI 而言，“记忆”的本质是：**在有限的上下文窗口里，用尽可能少的 token 复现过去的关键事实**。

所以 `trae-mem` 把 “Log（原始观测）” 和 “Summary（压缩记忆）” 明确分层：日志负责可追溯，摘要负责可注入。

本文聚焦第三块核心能力：**Compression & Summarization（压缩与摘要）**，核心实现位于 [compress.py](../trae_mem/compress.py)。

---

## 1. 压缩目标：我们要压缩成什么样？

`trae-mem` 的摘要不是写作文，而是生成“下一次会话可直接贴进 Prompt”的内容。你可以把它理解为 Android 里的：

- **崩溃日志**：原始的 stacktrace（可追溯）
- **Crash Summary**：一句话结论 + 复现路径 + 修复建议（可行动）

项目里默认会生成两层摘要（在会话结束时写入 summaries 表）：

- **brief**：更短（默认上限约 900 字符），适合频繁注入
- **detailed**：更长（默认上限约 3200 字符），适合需要背景时注入

这些上限由调用方控制，例如在 [hooks_bridge.py](../trae_mem/hooks_bridge.py#L98-L101)：

```python
brief = summarize_session(obs, max_chars=900)
detailed = summarize_session(obs, max_chars=3200)
```

---

## 2. 数据入口：摘要吃什么？ObservationLike

摘要函数不直接依赖数据库 Row，而是使用一个轻量的结构 [ObservationLike](../trae_mem/compress.py#L57-L63)：

```python
@dataclass(frozen=True)
class ObservationLike:
    ts: int
    kind: str
    tool_name: Optional[str]
    content: str
```

调用方会从 DB 拉取当前 session 的 observations，然后过滤掉 `private=1` 的记录，再转成 `ObservationLike` 列表（见 [hooks_bridge.py](../trae_mem/hooks_bridge.py#L86-L97)）。

这一步很重要：**敏感内容从源头就不进入摘要**。

---

## 3. 隐私策略：<private> 标签是如何处理的？

隐私处理有两层：

### 3.1 文本级脱敏：正则清洗

在 [compress.py](../trae_mem/compress.py#L10-L23)：

- `<private>...</private>` 会被识别
- 支持 `contains_private/remove_private/redact_private`

```python
_PRIVATE_RE = re.compile(r"<private>[\s\S]*?</private>", re.IGNORECASE)

def remove_private(text: str) -> str:
    return _PRIVATE_RE.sub("", text).strip()
```

### 3.2 存储级隔离：private=1 不入索引

写库时如果 `private=True`，不会写入 FTS 表（见 [db.py](../trae_mem/db.py#L176-L184)）。这保证了“隐私内容既不可被检索命中，也不会在摘要中被带出来”。

---

## 4. 两种摘要器：启发式 vs LLM（可选）

`trae-mem` 的摘要器是可插拔的：默认无外部依赖（启发式），也可以通过环境变量切到 LLM。

分发逻辑在 [summarize_session()](../trae_mem/compress.py#L212-L219)：

```python
provider = _llm_provider()
if provider == "none":
    return heuristic_session_summary(...)
try:
    return llm_session_summary(...)
except Exception:
    return heuristic_session_summary(...)
```

这里的关键取舍是：**LLM 失败不能影响整个系统**。所以无论网络、Key、限流等任何异常，都会 fallback 回启发式摘要。

### 4.1 启发式摘要：把日志“归类 + 去重 + 截断”

启发式摘要的实现是 [heuristic_session_summary()](../trae_mem/compress.py#L65-L119)：

它做了四件事：

1) 按 kind 分类：`user/tool/decision/error`  
2) 每条内容做一行化（合并空白）并截断  
3) 去重（保持顺序）  
4) 输出为 bullet list，并限制总字符数（`max_chars`）

```python
if o.kind == "user":
    user_msgs.append(_clip(re.sub(r"\s+", " ", c), 180))
...
return _as_bullets([...], max_chars=max_chars)
```

这种摘要的优点是：

- 完全离线、可预测
- 不会产生“幻觉”
- 性能稳定

缺点也很明显：它更像“压缩日志”，而不是“理解语义”。

### 4.2 LLM 摘要：生成更可注入的结构化要点（可选）

当你设置环境变量 `TRAE_MEM_SUMMARIZER=anthropic/openai` 时，会走 [llm_session_summary()](../trae_mem/compress.py#L182-L210)：

- 先把每条 observation 渲染成统一格式的文本
- 拼一个固定结构 prompt
- 请求对应的云端模型

prompt 在 [compress.py](../trae_mem/compress.py#L189-L203) 里定义，要求输出格式固定为：

```
- 用户目标：
- 已完成：
- 未解决/风险：
- 下一步建议：
```

这也是一个非常工程化的取舍：**输出结构固定，便于注入、便于未来做 UI 展示。**

---

## 5. 什么时候生成摘要？谁触发？

`trae-mem` 默认是“事件驱动生成摘要”。

两条典型触发路径：

- **生命周期挂钩**：`SessionEnd` 事件触发 `_summarize_session()`（见 [hooks_bridge.py](../trae_mem/hooks_bridge.py#L177-L193)）
- **手动结束会话**：MCP 工具 `trae_mem_end_session` 结束会话并生成摘要（见 [mcp_server.py](../trae_mem/mcp_server.py#L209-L227)）

这种设计让摘要“可控且一致”：只要会话结束，摘要一定存在。

---

## 6. 你可以怎么扩展？

压缩层是最适合做“智能增强”的地方，典型方向：

- **按工具类型定制压缩**：例如 read_file 输出只保留文件路径 + 关键 diff 片段
- **引入“关键信息提取器”**：从工具输出中提取函数名/类名/错误码，作为 tags，提高检索命中率
- **本地 LLM 摘要**：通过 Ollama 等本地推理实现完全离线的语义压缩

下一篇我们拆解 MCP 服务接口：工具是如何被 Trae 发现、被 Agent 调用、并返回结果的。
