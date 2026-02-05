# 🧠 trae-mem

**为 Trae IDE 打造的本地化、持久化“第二大脑”。**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[中文](README.md) | [English](README_EN.md)

`trae-mem` 是一个轻量级的上下文管理系统，旨在解决 AI 编程过程中的“会话遗忘”问题。它将你的每一次 Trae 会话、工具调用、关键决策持久化到本地 SQLite 数据库，并在会话结束时自动生成压缩摘要。在新的会话中，它能智能检索相关历史，并生成可直接注入的上下文块，让 AI 越用越懂你。

---

## ✨ 核心特性

- **🔒 本地优先 (Local-First)**: 所有数据（会话、观测、摘要）均存储在本地 SQLite (`~/.trae-mem`)，无需上传云端，隐私绝对安全。
- **💾 持久化记忆**: 完整记录用户意图、工具调用 (Tool Use) 和 AI 响应，不再丢失任何一次灵感。
- **📝 智能摘要**: 会话结束时自动生成 `Brief` (简报) 和 `Detailed` (详报) 两层摘要。支持启发式算法（默认）或接入 LLM (OpenAI/Anthropic) 进行深度总结。
- **🔍 渐进式检索**:
    - **Search**: 基于 FTS5 的全文检索。
    - **Timeline**: 还原关键时刻的时间窗口上下文。
    - **Inject**: 一键生成包含“最近会话”+“相关记忆”的 Prompt 注入块。
- **🔌 MCP 协议支持**: 原生支持 Model Context Protocol (MCP)，可直接作为工具挂载到 Trae IDE。

## 🚀 快速接入 (推荐)

`trae-mem` 提供了标准的 MCP Server 实现，可以直接配置到 Trae 中。

### 1. 克隆仓库

```bash
git clone https://github.com/rong5690001/trae-mem.git
cd trae-mem
# 推荐使用 python 3.10+
```

### 2. 配置 Trae

**✨ 一键安装（推荐）**

直接运行提供的安装脚本，自动将配置写入 Trae 的 `mcp.json`：

```bash
python3 scripts/install_mcp.py
```

**手动配置**

如果脚本执行失败，你也可以手动编辑 Trae 的配置文件 `~/Library/Application Support/Trae/User/mcp.json`，添加以下内容：

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

> **注意**: 请将 `/path/to/your/trae-mem` 替换为你实际克隆的仓库路径（例如 `/Users/yourname/workspace/trae-mem`）。建议使用绝对路径的 Python 解释器。

### 3. 开始使用

重启 Trae 后，你将在工具列表中看到以下工具：

- `trae_mem_search`: 搜索记忆库。
- `trae_mem_inject`: 生成适合注入当前会话的上下文块。
- `trae_mem_log`: (高级) 手动记录观测数据。
- `trae_mem_start_session` / `trae_mem_end_session`: 管理会话生命周期。

在对话中，你可以直接让 Trae 使用这些工具，例如：
> "帮我查一下上次关于播放器预加载策略的讨论"

## 🛠️ 命令行使用 (CLI)

你也可以通过 CLI 直接管理记忆库，适合调试或脚本集成。

```bash
# 初始化
python3 -m trae_mem.cli init

# 启动 HTTP 服务 (可选)
python3 -m trae_mem.cli serve --port 37777

# 手动搜索
python3 -m trae_mem.cli search --query "预加载"

# 生成注入块
python3 -m trae_mem.cli inject --query "播放器优化"
```

## ⚙️ 高级配置

通过环境变量控制行为：

| 变量名 | 描述 | 默认值 |
| :--- | :--- | :--- |
| `TRAE_MEM_DB` | SQLite 数据库路径 | `~/.trae-mem/trae_mem.sqlite3` |
| `TRAE_MEM_SUMMARIZER` | 摘要生成器 (`heuristic`, `openai`, `anthropic`) | `heuristic` |
| `OPENAI_API_KEY` | OpenAI Key (如果使用 openai 摘要) | - |
| `ANTHROPIC_API_KEY` | Anthropic Key (如果使用 anthropic 摘要) | - |

## 📚 文档

- [Trae 集成指南](docs/trae_integration.md)
- [技术博客总览：深度解析 Trae-Mem](blog/trae-mem-tech-deep-dive.md)

## 📄 License

MIT
