# 02｜生命周期挂钩：把“对话/工具调用”变成可回放的事件流

如果把 `trae-mem` 比作一层记忆系统，那么 **生命周期挂钩（Lifecycle Hooks）** 就是它的“神经末梢”——决定了我们能捕捉到什么、以什么颗粒度捕捉、以及捕捉是否稳定。

本文聚焦第二块核心能力：**Session Lifecycle Hook（会话生命周期挂钩）**，对应实现主要在 [hooks_bridge.py](../trae_mem/hooks_bridge.py)。

---

## 1. 目标：我们到底想“挂钩”什么？

在 IDE 里，真正有记忆价值的事件其实很少，基本可以归结为三类：

- **用户输入**：用户的目标、约束、偏好
- **工具调用**：读了哪些文件、搜了哪些关键字、拿到了哪些输出
- **关键结论/决策**：最终达成的结论、下一步计划、风险点

对应到 `trae-mem` 的数据结构，就是把这些东西写成 `observations`：

- `kind="user"`：用户输入
- `kind="tool"`：工具输入/输出
- `kind="note"/"decision"/"error"`：过程中的关键节点

---

## 2. 总体思路：事件驱动 + 映射会话 ID

### 2.1 为什么需要“映射会话 ID”？

Trae（或类似 IDE）通常会给每个对话生成一个**临时 session_id**。但本地数据库里我们希望：

- **同一个项目**的连续会话能串起来（便于“最近会话”检索）
- 不依赖 IDE 内部实现细节（IDE 重启也不丢）

所以 `trae-mem` 采用了一个很朴素但好用的做法：用一个本地 JSON 文件做映射表。

映射文件路径由 [hooks_bridge.py](../trae_mem/hooks_bridge.py#L11-L21) 决定：

- `TRAE_MEM_SESSION_MAP`（环境变量指定）
- 否则 `TRAE_MEM_HOME/session_map.json`
- 再否则落到当前目录的 `.trae-mem/session_map.json`

### 2.2 映射逻辑如何工作？

核心函数是 [_ensure_session](../trae_mem/hooks_bridge.py#L38-L48)：

- 以 `"{project_path}:{trae_session_id}"` 作为 key
- 如果 map 里已经有数据库 session_id，就复用
- 否则创建新 session 并写回 map

```python
proj_key = project_path or ""
key = f"{proj_key}:{trae_session_id}"
existing = mp.get(key)
if isinstance(existing, str) and existing:
    return existing
sid = db.new_session(project_path=project_path, meta=meta or {})
mp[key] = sid
_save_map(mp)
return sid
```

这个设计很像 Android 里做“账号体系”的 mapping：外部系统一个 id，本地系统另一个 id，中间一张映射表解耦。

---

## 3. hooks_bridge.py：它到底是怎么被调用的？

你可以把 [hooks_bridge.py](../trae_mem/hooks_bridge.py) 理解为一个“事件分发器”：

1. 外部传入 `--event=SessionStart`（或别的事件名）
2. 事件 payload 通过 stdin 传入（JSON）
3. 分发器将事件路由到对应 handler

入口函数在 [main()](../trae_mem/hooks_bridge.py#L206-L214)：

```python
p.add_argument("--event", required=True, choices=list(_HANDLERS.keys()))
args = p.parse_args(argv)
payload = _read_stdin_json()
fn = _HANDLERS[args.event]
return int(fn(payload))
```

事件到 handler 的映射表在 [_HANDLERS](../trae_mem/hooks_bridge.py#L196-L203)：

- `SessionStart`
- `UserPromptSubmit`
- `PreToolUse`
- `PostToolUse`
- `Stop`
- `SessionEnd`

---

## 4. 六个生命周期事件：逐个拆开看

下面按“你写 Android App 的埋点”那种视角，把每个事件的意义讲清楚。

### 4.1 SessionStart：会话开始

对应 [handle_session_start](../trae_mem/hooks_bridge.py#L104-L115)：

- 从 payload 里取 `session_id / cwd / source`
- 初始化 DB schema
- `_ensure_session()` 建立 Trae 会话到本地会话的映射

这一步不写 observation，原因很简单：**它只是建立“容器”，真正的内容从下一条用户输入开始。**

### 4.2 UserPromptSubmit：用户输入

对应 [handle_user_prompt_submit](../trae_mem/hooks_bridge.py#L116-L129)：

- 将 prompt 归一化（处理 `<private>` 标签）
- 写入 `kind="user"`

关键在 [_norm_text_for_log](../trae_mem/hooks_bridge.py#L77-L84)：

- 如果包含 `<private>...</private>`，会移除敏感段
- 如果移除后变成空文本，则写入 `[PRIVATE]` 并标记 `private=True`

这等价于“日志脱敏 + 不可索引”的双保险。

### 4.3 PreToolUse：工具调用前

对应 [handle_pre_tool_use](../trae_mem/hooks_bridge.py#L130-L144)：

- 写入一条 `kind="note"` 的 observation
- 内容形如：`准备执行 {tool_name} 输入={tool_input}`
- 做了截断，避免过长内容影响库体积

它的意义是：**你不仅能知道工具输出了什么，还能知道当时模型“准备做什么”。**

### 4.4 PostToolUse：工具调用后

对应 [handle_post_tool_use](../trae_mem/hooks_bridge.py#L145-L162)：

- 写入 `kind="tool"` 的 observation
- 将 `tool_input`、`tool_response` 都记录下来
- 对入参/出参分别截断（2000 / 4000）

这是整个记忆系统最“含金量高”的数据来源：很多时候你要复盘的不是一句话，而是“当时读到了哪段代码/哪条日志”。

### 4.5 Stop：中止

对应 [handle_stop](../trae_mem/hooks_bridge.py#L163-L175)：

- 写入一条 note：`停止，原因=...`

它更像一次“事件打点”，用于解释为什么会话中断。

### 4.6 SessionEnd：会话结束 + 触发压缩

对应 [handle_session_end](../trae_mem/hooks_bridge.py#L177-L193)：

它做两件事：

1) 写入“结束” note，并把 session 标记为 ended  
2) 调用 [_summarize_session](../trae_mem/hooks_bridge.py#L86-L102) 生成 brief/detailed 摘要并落盘

```python
db.end_session(sid)
_summarize_session(db, sid)
```

这一点非常关键：**压缩不是后台定时任务，而是“事件驱动”的同步触发**，因此你能保证摘要总是与该会话一致。

---

## 5. MCP 是怎么把事件送进来的？

生命周期事件最终要从 IDE 进入本地 DB，需要一个“入口”。`trae-mem` 的入口是 MCP 工具 `trae_mem_hook_event`，实现位于 [mcp_server.py](../trae_mem/mcp_server.py#L229-L245)：

- Trae（客户端）通过 MCP `tools/call` 把 `{event, payload}` 发给 server
- server 内部把 payload 转成 JSON 文本，伪造 stdin，调用 `hooks_bridge_main(["--event", event])`

这样 `hooks_bridge.py` 就像“被命令行调用了一次”一样执行对应 handler。

---

## 6. 你可以怎么扩展？

生命周期挂钩层扩展点非常多，典型方向：

- **增加事件类型**：例如 `ModelResponse`（记录模型最终回答）、`FileChanged`（监听文件变化）
- **更细粒度的 tool 采样**：针对大输出工具做摘要/采样，减少噪声
- **跨窗口的会话策略**：用 project_path + 日期滚动会话、或按 Git 分支隔离

下一篇我们拆解“压缩与摘要”：为什么需要 brief/detailed 两层，以及启发式压缩/LLM 压缩的取舍。
