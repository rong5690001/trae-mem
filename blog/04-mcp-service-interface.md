# 04｜MCP 服务接口：让本地能力变成 Agent 可调用的 Tools

到目前为止，你已经知道：

- 数据如何存（SQLite）
- 事件如何来（生命周期挂钩）
- 日志如何变薄（摘要压缩）

但少了一个关键环节：**Agent 到底怎么“摸到”这些本地能力？**

答案就是：**MCP（Model Context Protocol）**。`trae-mem` 通过实现一个 MCP Server，把本地 Python 逻辑包装成一组“工具（Tools）”，让 Trae 的 Agent 能像调用内置工具一样调用它们。

本文聚焦第四块核心能力：**MCP Service Interface（MCP 服务接口）**，核心实现位于 [mcp_server.py](../trae_mem/mcp_server.py)。

---

## 1. 角色划分：Trae / Agent / MCP Server

你可以用一句话把三者关系讲清楚：

- **Trae（客户端/宿主）**：负责启动 MCP Server，并把“工具菜单”暴露给 Agent
- **Agent（模型）**：负责理解用户意图，决定调用哪个工具、用什么参数调用
- **MCP Server（服务端）**：负责实现工具，接收 JSON-RPC 请求并返回结果

这也是 MCP 的核心价值：**把“理解（AI）”与“执行（本地能力）”解耦**。

如果你想看更完整的“三角协同”讲解，可配合阅读 [mcp-architecture-deep-dive.md](./mcp-architecture-deep-dive.md)。

---

## 2. 传输层：为什么是 stdio？

`trae-mem` 选择 stdio（标准输入/输出）作为 MCP 传输方式：

- Trae 启动 server 进程
- Trae 通过 stdin 写入一行行 JSON（请求）
- Server 通过 stdout 回写一行行 JSON（响应）

优点非常“工程”：

- 不需要监听端口（减少配置与安全风险）
- 跨平台稳定（macOS/Linux/Windows）
- 进程生命周期由宿主控制，方便自动重启

实现入口是 [serve_stdio()](../trae_mem/mcp_server.py#L251-L311)。

---

## 3. 协议层：JSON-RPC 的最小实现

在 `serve_stdio()` 中，server 做了一个极简的 JSON-RPC 循环：

1) `initialize`：握手，声明能力  
2) `tools/list`：返回工具清单  
3) `tools/call`：执行某个工具并返回结果  

对应代码片段在 [mcp_server.py](../trae_mem/mcp_server.py#L270-L305)：

```python
if method == "initialize":
    _write(_result(id_value, {...capabilities...}))
    continue

if method == "tools/list":
    _write(_result(id_value, {"tools": _tools()}))
    continue

if method == "tools/call":
    name = str(params.get("name") or "")
    args = params.get("arguments") or {}
    res = _handle_tool_call(name, args)
    _write(_result(id_value, res))
    continue
```

注意：这里没有引入任何第三方库，完全靠 Python 标准库就能跑通。

---

## 4. 工具发现：tools/list 为什么这么重要？

Agent 能调用哪些能力，取决于 `tools/list` 返回的“工具描述（Schema）”。在 [mcp_server.py](../trae_mem/mcp_server.py#L33-L129) 的 `_tools()` 里，`trae-mem` 定义了 7 个工具：

- `trae_mem_search`：全文检索
- `trae_mem_timeline`：按 observation_id 拉时间窗
- `trae_mem_get_observations`：按 ID 批量取详情
- `trae_mem_inject`：生成可注入上下文块
- `trae_mem_start_session`：创建 session
- `trae_mem_log`：写入 observation
- `trae_mem_end_session`：结束 session 并生成摘要
- `trae_mem_hook_event`：适配生命周期事件（把 Trae 事件写进 DB）

每个工具都有：

- `name`
- `description`：给模型读的说明
- `inputSchema`：参数结构（类型、必填字段、枚举值）

这是“模型可调用工具”的关键：**description + schema 就是模型的说明书**。

---

## 5. 工具执行：tools/call 如何路由到真实逻辑？

当 Trae 收到 Agent 输出的“调用某工具”的意图，它会发送 `tools/call` 给 server。server 在 `_handle_tool_call()` 内做路由（见 [mcp_server.py](../trae_mem/mcp_server.py#L131-L249)）：

### 5.1 示例：trae_mem_inject（上下文注入）

- 参数：`query/limit/project`
- 逻辑：调用 [build_injection_block](../trae_mem/api.py#L98-L141) 拼一段文本块

```python
if name == "trae_mem_inject":
    text = build_injection_block(db, query=query, limit=limit, project_path=...)
    return _tool_text_result(text, structured={"context": text})
```

返回值是 MCP 约定的 ToolResult 结构：`content: [{type:"text", text:"..."}]`。

### 5.2 示例：trae_mem_log（写 observation）

它会：

- 处理 `<private>` 脱敏（必要时将整段标记为 private）
- 调用 `db.add_observation(...)`
- 返回 `observation_id`

见 [mcp_server.py](../trae_mem/mcp_server.py#L181-L208)。

---

## 6. 关键桥梁：trae_mem_hook_event 怎么把 Trae 生命周期“灌进来”？

`trae_mem_hook_event` 是 `trae-mem` 的“适配器工具”。它把 Trae 的生命周期事件（SessionStart / PreToolUse 等）转换成 `hooks_bridge.py` 能处理的形式。

实现位于 [mcp_server.py](../trae_mem/mcp_server.py#L229-L245)：

核心技巧只有一个：**伪造 stdin，复用 hooks_bridge 的 main()**。

```python
buf = json.dumps(payload, ensure_ascii=False)
proc_argv = ["--event", event]
stdin_backup = sys.stdin
try:
    sys.stdin = io.StringIO(buf)
    rc = int(hooks_bridge_main(proc_argv))
finally:
    sys.stdin = stdin_backup
```

这带来两个好处：

- hooks_bridge 可以继续保持“命令行风格”（stdin + argv），测试/调试都很方便
- MCP server 不需要重复写一遍事件处理逻辑

---

## 7. 备用接口：HTTP API 为什么存在？

除了 MCP，`trae-mem` 还提供了一个极简 HTTP API（见 [api.py](../trae_mem/api.py)）。它的价值是：

- 不依赖 IDE：脚本/浏览器也能查
- 便于外部集成：比如你写一个 Android Studio 插件，也能直接请求 `/inject`

常用端点：

- `/search?q=...`
- `/timeline?observation_id=...`
- `/inject?q=...&project=...`

---

## 8. 你可以怎么扩展？

如果你想让 MCP 层更强，常见方向有：

- **更强的 structuredContent**：不仅返回 text，还返回结构化 JSON，便于 Trae 或未来的 UI 做渲染
- **权限/能力分级**：按项目白名单、按 tool 分类限制，进一步减少误调用风险
- **资源（Resources）接口**：把 DB 中的 summaries 作为资源暴露，让 IDE 直接浏览

至此，四篇模块拆解完成。你可以回到总览文章，从“整体架构”视角串起四块能力，并按需深入。
