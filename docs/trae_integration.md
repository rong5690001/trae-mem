# Trae 生命周期接入

Trae 是基于 VS Code 内核的 IDE，目前最稳定、可配置的“扩展点”是 MCP Server（`mcp.json`）以及可执行脚本能力（如果你的 Trae/AI 运行时提供了类似生命周期 Hook 的机制）。

本仓库提供两条接入路径：

1) **MCP 接入（推荐）**：Trae 可直接调用 `trae-mem` 的工具完成记忆检索/注入/记录
2) **Hook 接入（自动记录）**：如果 Trae 的 AI 生命周期能在事件点执行脚本，并把事件 JSON 通过 stdin 传入，则可做到“自动落库 + 会话结束自动摘要”

## 1) MCP 接入（推荐）

### 1.1 启动方式

#### 方法 A：直接配置（推荐）

在 Trae 的 `mcp.json` (通常位于 `~/Library/Application Support/Trae/User/mcp.json`) 中添加如下配置。
**注意**：必须在 `env` 中设置 `PYTHONPATH` 为本仓库的根目录，否则会报 `ModuleNotFoundError`。

```json
{
  "mcpServers": {
    "trae-mem": {
      "command": "/usr/bin/python3", 
      "args": ["-m", "trae_mem.mcp_server"],
      "env": {
        "PYTHONPATH": "/path/to/your/trae-mem",
        "TRAE_MEM_HOME": "/Users/yourname/.trae-mem"
      }
    }
  }
}
```

> **提示**：
> 1. 请将 `/path/to/your/trae-mem` 替换为你实际的仓库克隆路径。
> 2. `command` 建议使用绝对路径（如 `/usr/bin/python3` 或 `/opt/homebrew/bin/python3`），以确保环境一致。

### 1.3 可用工具

- `trae_mem_search`：索引级搜索
- `trae_mem_timeline`：时间窗口上下文
- `trae_mem_get_observations`：批量拉取细节
- `trae_mem_inject`：生成“可注入上下文块”
- `trae_mem_start_session` / `trae_mem_log` / `trae_mem_end_session`：可选，手动管理会话
- `trae_mem_hook_event`：把“生命周期事件 payload”喂给桥接层（见下一节）

## 2) Hook 接入（自动记录）

如果你的 Trae/AI 运行时能在以下事件点执行脚本，并将 JSON payload 通过 stdin 传入（字段名同本仓库桥接器约定），则可以做到全自动采集：

- `SessionStart`：会话启动
- `UserPromptSubmit`：用户提交 prompt
- `PreToolUse`：工具调用前
- `PostToolUse`：工具调用后
- `Stop`：一次回复完成
- `SessionEnd`：会话结束（生成摘要）

本仓库提供桥接器：

```bash
python3 -m trae_mem.hooks_bridge --event SessionStart
```

以及一组便于配置的脚本（目录：`trae_hooks/`）：

- `trae_hooks/SessionStart.sh`
- `trae_hooks/UserPromptSubmit.sh`
- `trae_hooks/PreToolUse.sh`
- `trae_hooks/PostToolUse.sh`
- `trae_hooks/Stop.sh`
- `trae_hooks/SessionEnd.sh`

### 2.1 stdin payload 约定（最小集合）

不同事件会读取不同字段，但最小需要：

- `session_id`: Trae 侧会话 ID（用来映射到 trae-mem 的 session）
- `cwd`: 项目路径（用于区分项目与分组检索）

示例：

```json
{ "session_id": "sess-123", "cwd": "/path/to/project", "prompt": "我要实现预加载策略" }
```

## 3) 验证

你可以在终端手动模拟一个事件序列：

```bash
export TRAE_MEM_HOME=/tmp/trae-mem
echo '{"session_id":"sess-1","cwd":"/tmp/p","source":"startup"}' | python3 -m trae_mem.hooks_bridge --event SessionStart
echo '{"session_id":"sess-1","cwd":"/tmp/p","prompt":"我要优化缓冲"}' | python3 -m trae_mem.hooks_bridge --event UserPromptSubmit
echo '{"session_id":"sess-1","cwd":"/tmp/p","reason":"exit","transcript_path":"/tmp/t.jsonl"}' | python3 -m trae_mem.hooks_bridge --event SessionEnd
python3 -m trae_mem.cli inject --query "缓冲" --project "/tmp/p"
```

