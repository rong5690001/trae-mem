# trae-mem

为 Trae 打造的“持久化内存压缩系统”原型：把一次次会话中的上下文（用户意图、工具调用、关键输出、决策）落到本地 SQLite，并在会话结束时生成分层压缩摘要；新会话可按需检索并输出“可注入的上下文块”。

本仓库不依赖 Bun/Node 插件机制，默认以本地 Python 服务 + CLI 形式运行，方便后续接入 Trae 的生命周期钩子或自定义脚本。

## 核心能力

- 持久化：会话、观测（observations）、摘要（summaries）写入本地 SQLite
- 压缩：会话结束后自动生成 brief / detailed 两层摘要（默认启发式压缩；可选通过环境变量接入 LLM）
- 渐进式检索：search（轻量索引）→ timeline（上下文窗口）→ get_observations（全量细节）
- 隐私控制：支持 `<private>...</private>` 片段不入库
- 上下文注入：根据查询与最近活动生成可直接粘贴到下一会话的上下文块

## 快速开始（本地）

```bash
python3 -m trae_mem.cli init
python3 -m trae_mem.cli serve --port 37777
```

另开一个终端，模拟一次会话写入与检索：

```bash
python3 -m trae_mem.cli start-session --project /path/to/your/project
python3 -m trae_mem.cli log --session <SESSION_ID> --kind user --text "我要实现一个播放器预加载策略"
python3 -m trae_mem.cli log --session <SESSION_ID> --kind tool --tool_name Grep --text "在 player/ 里搜索 preload"
python3 -m trae_mem.cli end-session --session <SESSION_ID>

python3 -m trae_mem.cli search --query "预加载"
python3 -m trae_mem.cli inject --query "预加载策略"
```

## 可选：LLM 压缩（默认关闭）

默认使用启发式压缩（不依赖任何外部服务）。如需用 LLM 压缩，可设置：

- `TRAE_MEM_SUMMARIZER=anthropic` 并提供 `ANTHROPIC_API_KEY`
- `TRAE_MEM_SUMMARIZER=openai` 并提供 `OPENAI_API_KEY`

这些配置仅影响“生成摘要”步骤；不影响落库与检索。

## HTTP API

服务启动后默认提供：

- `GET /health`
- `GET /search?q=...&limit=...`
- `GET /timeline?observation_id=...&window=...`
- `POST /get_observations` body: `{ "ids": ["...","..."] }`
- `GET /inject?q=...&limit=...`

## Trae 接入

见 [trae_integration.md](file:///Users/chenhuarong/workspace/trae-mem/docs/trae_integration.md)。
