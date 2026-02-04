# 🧠 trae-mem

**A Localized, Persistent "Second Brain" for Trae IDE.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[中文](README.md) | [English](README_EN.md)

`trae-mem` is a lightweight context management system designed to solve the "session amnesia" problem in AI programming. It persists every Trae session, tool usage, and key decision into a local SQLite database, and automatically generates compressed summaries when a session ends. In new sessions, it intelligently retrieves relevant history and generates context blocks that can be directly injected, making the AI understand you better the more you use it.

---

## ✨ Core Features

- **🔒 Local-First**: All data (sessions, observations, summaries) are stored in a local SQLite database (`~/.trae-mem`), with no cloud uploads, ensuring absolute privacy.
- **💾 Persistent Memory**: Completely records user intents, tool usage (Tool Use), and AI responses, so you never lose a flash of inspiration.
- **📝 Intelligent Summarization**: Automatically generates two layers of summaries (`Brief` and `Detailed`) at the end of a session. Supports heuristic algorithms (default) or LLM (OpenAI/Anthropic) integration for deep summarization.
- **🔍 Progressive Retrieval**:
    - **Search**: Full-text search based on FTS5.
    - **Timeline**: Reconstructs the context window of key moments.
    - **Inject**: Generates a prompt injection block containing "recent sessions" + "relevant memories" with one click.
- **🔌 MCP Protocol Support**: Native support for the Model Context Protocol (MCP), allowing it to be directly mounted as a tool in Trae IDE.

## 🚀 Quick Start (Recommended)

`trae-mem` provides a standard MCP Server implementation that can be directly configured into Trae.

### 1. Clone the Repository

```bash
git clone https://github.com/rong5690001/trae-mem.git
cd trae-mem
# Recommended: python 3.10+
```

### 2. Configure Trae

**✨ One-Click Installation (Recommended)**

Run the provided installation script to automatically write the configuration to Trae's `mcp.json`:

```bash
python3 scripts/install_mcp.py
```

**Manual Configuration**

If the script fails, you can manually edit Trae's configuration file `~/Library/Application Support/Trae/User/mcp.json` and add the following content:

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

> **Note**: Please replace `/path/to/your/trae-mem` with the actual path where you cloned the repository (e.g., `/Users/chenhuarong/workspace/trae-mem`). It is recommended to use an absolute path for the Python interpreter.

### 3. Start Using

After restarting Trae, you will see the following tools in the tool list:

- `trae_mem_search`: Search the memory bank.
- `trae_mem_inject`: Generate a context block suitable for injection into the current session.
- `trae_mem_log`: (Advanced) Manually record observation data.
- `trae_mem_start_session` / `trae_mem_end_session`: Manage session lifecycle.

In the chat, you can directly ask Trae to use these tools, for example:
> "Help me check the discussion about the player preloading strategy from last time"

## 🛠️ CLI Usage

You can also manage the memory bank directly via the CLI, which is suitable for debugging or script integration.

```bash
# Initialize
python3 -m trae_mem.cli init

# Start HTTP Service (Optional)
python3 -m trae_mem.cli serve --port 37777

# Manual Search
python3 -m trae_mem.cli search --query "preload"

# Generate Injection Block
python3 -m trae_mem.cli inject --query "player optimization"
```

## ⚙️ Advanced Configuration

Control behavior via environment variables:

| Variable Name | Description | Default Value |
| :--- | :--- | :--- |
| `TRAE_MEM_DB` | SQLite database path | `~/.trae-mem/trae_mem.sqlite3` |
| `TRAE_MEM_SUMMARIZER` | Summarizer (`heuristic`, `openai`, `anthropic`) | `heuristic` |
| `OPENAI_API_KEY` | OpenAI Key (if using openai summarizer) | - |
| `ANTHROPIC_API_KEY` | Anthropic Key (if using anthropic summarizer) | - |

## 📚 Documentation

- [Trae Integration Guide](docs/trae_integration.md)

## 📄 License

MIT
