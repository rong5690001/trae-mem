# 给 AI 装个“海马体”：Trae-Mem 本地记忆系统技术内幕

> **摘要**：你是否遇到过这样的场景：在 Trae IDE 里和 AI 聊得火热，解决了 A 模块的 Bug，转头去改 B 模块，再问 A 模块时 AI 却“失忆”了？或者第二天打开新会话，不得不把昨天的背景重说一遍？本文将带你深入 `trae-mem` 的技术实现，看我们如何用不到 1000 行 Python 代码，基于 SQLite 和 MCP 协议，为 Trae IDE 打造一个**本地化、持久化、隐私安全**的“第二大脑”。

---

## 1. 为什么我们需要一个“外挂大脑”？

在大模型编程（AI-Assisted Coding）的日常中，我们面临着两个核心矛盾：

1.  **Context Window（上下文窗口）的限制**：虽然模型窗口越来越大，但在 IDE 中无限堆叠历史对话会导致 Token 消耗激增，响应变慢，且“大海捞针”效应（Lost in the Middle）会导致注意力分散。
2.  **Session Isolation（会话隔离）**：IDE 通常以“会话”为单位隔离上下文。一旦你点击“New Chat”或重启 IDE，之前的思维链条就断了。

`trae-mem` 的诞生就是为了解决这个问题。它不像传统的 RAG（检索增强生成）那样依赖庞大的向量数据库和云端服务，而是**反其道而行之**，选择了一条**极简、本地化**的技术路线。

---

## 2. 技术栈选型：少即是多

为了让每个开发者都能零负担地跑起来，我们在技术选型上极其克制：

*   **编程语言**: **Python 3.10+**
    *   *理由*：标准库强大，无需编译，胶水能力强，方便后续接入本地 LLM 推理库。
*   **存储引擎**: **SQLite (with FTS5 & JSON)**
    *   *理由*：单文件数据库，部署极其简单（Zero Configuration）。FTS5 提供了足够好用的全文检索能力，JSON 列则让我们能灵活存储非结构化的元数据（Metadata）。
*   **通信协议**: **MCP (Model Context Protocol)**
    *   *理由*：Anthropic 推出的开放标准，Trae IDE 原生支持。通过 MCP，我们可以像开发“插件”一样，把本地 Python 服务挂载为 AI 的一个 Tool。
*   **可视化**: **Mermaid**
    *   *理由*：代码即图表，易于维护和版本控制。

---

## 3. 核心架构与实现原理

`trae-mem` 的工作流可以概括为：**记录 (Log) -> 沉淀 (Summarize) -> 唤起 (Inject)**。

下面这张架构图展示了数据是如何在 Trae IDE 和本地数据库之间流转的：

![Trae-mem 架构图（深色主题）](https://mermaid.ink/img/JSV7aW5pdDogeyJ0aGVtZSI6ICJkYXJrIiwgInRoZW1lVmFyaWFibGVzIjogeyAiZm9udFNpemUiOiAiMTZweCIsICJmb250RmFtaWx5IjogImFyaWFsIiwgImxpbmVXaWR0aCI6ICIycHgifX19JSUKZ3JhcGggVEQKICAgICUlIOagt-W8j-WumuS5iQogICAgY2xhc3NEZWYgY2xpZW50IGZpbGw6IzJkMzQzNixzdHJva2U6I2RmZTZlOSxzdHJva2Utd2lkdGg6MnB4LGNvbG9yOiNmZmY7CiAgICBjbGFzc0RlZiBicmlkZ2UgZmlsbDojMDk4NGUzLHN0cm9rZTojNzRiOWZmLHN0cm9rZS13aWR0aDoycHgsY29sb3I6I2ZmZjsKICAgIGNsYXNzRGVmIGNvcmUgZmlsbDojNmM1Y2U3LHN0cm9rZTojYTI5YmZlLHN0cm9rZS13aWR0aDoycHgsY29sb3I6I2ZmZjsKICAgIGNsYXNzRGVmIHN0b3JhZ2UgZmlsbDojMDBiODk0LHN0cm9rZTojNTVlZmM0LHN0cm9rZS13aWR0aDoycHgsY29sb3I6I2ZmZjsKCiAgICBzdWJncmFwaCBDbGllbnRfTGF5ZXIgW--_ve-_ve-4jyBUcmFlIElERSAvIENsaWVudCBTaWRlXQogICAgICAgIGRpcmVjdGlvbiBUQgogICAgICAgIFVzZXJbVXNlciBQcm9tcHRdOjo6Y2xpZW50CiAgICAgICAgVG9vbHNbVG9vbCBFeGVjdXRpb25zXTo6OmNsaWVudAogICAgICAgIE1DUF9DbGllbnRbTUNQIENsaWVudCBNb2R1bGVdOjo6Y2xpZW50CiAgICBlbmQKCiAgICBzdWJncmFwaCBCcmlkZ2VfTGF5ZXIgW_CfjIkgTUNQIFNlcnZlciBJbnRlcmZhY2VdCiAgICAgICAgZGlyZWN0aW9uIFRCCiAgICAgICAgU3RkaW9bU3RkaW8gVHJhbnNwb3J0XTo6OmJyaWRnZQogICAgICAgIERpc3BhdGNoZXJbUmVxdWVzdCBEaXNwYXRjaGVyXTo6OmJyaWRnZQogICAgZW5kCgogICAgc3ViZ3JhcGggQ29yZV9Mb2dpYyBb8J-noCBDb3JlIExvZ2ljIExheWVyXQogICAgICAgIGRpcmVjdGlvbiBUQgogICAgICAgIFNlc3Npb25NZ3JbU2Vzc2lvbiBNYW5hZ2VyXTo6OmNvcmUKICAgICAgICBTdW1tYXJpemVyW1N1bW1hcml6ZXIgRW5naW5lXTo6OmNvcmUKICAgICAgICBTZWFyY2hFbmdbRlRTNSBTZWFyY2ggRW5naW5lXTo6OmNvcmUKICAgICAgICBJbmplY3RHZW5bQ29udGV4dCBJbmplY3Rvcl06Ojpjb3JlCiAgICBlbmQKCiAgICBzdWJncmFwaCBTdG9yYWdlX0xheWVyIFvvv73vv70gUGVyc2lzdGVuY2UgTGF5ZXJdCiAgICAgICAgZGlyZWN0aW9uIFRCCiAgICAgICAgREJbKFNRTGl0ZSBEQlxufi8udHJhZS1tZW0pXTo6OnN0b3JhZ2UKICAgICAgICBUYWJsZXNbU2Vzc2lvbnMgfCBPYnNlcnZhdGlvbnMgfCBTdW1tYXJpZXNdOjo6c3RvcmFnZQogICAgZW5kCgogICAgJSUg6LCD55So5rWBCiAgICBVc2VyIC0tPnwxLiBTdWJtaXR8IE1DUF9DbGllbnQKICAgIFRvb2xzIC0tPnwyLiBSZXN1bHR8IE1DUF9DbGllbnQKICAgIE1DUF9DbGllbnQgPT0-fDMuIEpTT04tUlBDIChzdGRpbi9zdGRvdXQpfCBTdGRpbwogICAgU3RkaW8gLS0-IERpc3BhdGNoZXIKCiAgICBEaXNwYXRjaGVyIC0tPnxXcml0ZSBMb2d8IFNlc3Npb25NZ3IKICAgIERpc3BhdGNoZXIgLS0-fFF1ZXJ5fCBTZWFyY2hFbmcKICAgIERpc3BhdGNoZXIgLS0-fEdldCBDb250ZXh0fCBJbmplY3RHZW4KCiAgICBTZXNzaW9uTWdyIC0tPnxJbnNlcnR8IERCCiAgICBTZXNzaW9uTWdyIC0tPnxUcmlnZ2VyfCBTdW1tYXJpemVyCiAgICBTdW1tYXJpemVyIC0tPnxVcGRhdGV8IERCCgogICAgU2VhcmNoRW5nIDwtLT58U2VsZWN0IChCTTI1KXwgREIKICAgIEluamVjdEdlbiA8LS0-fEZldGNoIFJlY2VudHwgREIKCiAgICAlJSDluIPlsYDosIPmlbQKICAgIERCIC0tLSBUYWJsZXMKCiAgICAlJSDms6jph4ror7TmmI4KICAgIGxpbmtTdHlsZSBkZWZhdWx0IHN0cm9rZTojYjJiZWMzLHN0cm9rZS13aWR0aDoycHg7)

<details>
<summary>架构图源码（Mermaid）</summary>

```mermaid
%%{init: {'theme': 'dark', 'themeVariables': { 'fontSize': '16px', 'fontFamily': 'arial', 'lineWidth': '2px'}}}%%
graph TD
    %% 样式定义
    classDef client fill:#2d3436,stroke:#dfe6e9,stroke-width:2px,color:#fff;
    classDef bridge fill:#0984e3,stroke:#74b9ff,stroke-width:2px,color:#fff;
    classDef core fill:#6c5ce7,stroke:#a29bfe,stroke-width:2px,color:#fff;
    classDef storage fill:#00b894,stroke:#55efc4,stroke-width:2px,color:#fff;

    subgraph Client_Layer [🖥️ Trae IDE / Client Side]
        direction TB
        User[User Prompt]:::client
        Tools[Tool Executions]:::client
        MCP_Client[MCP Client Module]:::client
    end

    subgraph Bridge_Layer [🌉 MCP Server Interface]
        direction TB
        Stdio[Stdio Transport]:::bridge
        Dispatcher[Request Dispatcher]:::bridge
    end

    subgraph Core_Logic [🧠 Core Logic Layer]
        direction TB
        SessionMgr[Session Manager]:::core
        Summarizer[Summarizer Engine]:::core
        SearchEng[FTS5 Search Engine]:::core
        InjectGen[Context Injector]:::core
    end

    subgraph Storage_Layer [💾 Persistence Layer]
        direction TB
        DB[(SQLite DB\n~/.trae-mem)]:::storage
        Tables[Sessions | Observations | Summaries]:::storage
    end

    %% 调用流
    User -->|1. Submit| MCP_Client
    Tools -->|2. Result| MCP_Client
    MCP_Client ==>|3. JSON-RPC (stdin/stdout)| Stdio
    Stdio --> Dispatcher
    
    Dispatcher -->|Write Log| SessionMgr
    Dispatcher -->|Query| SearchEng
    Dispatcher -->|Get Context| InjectGen
    
    SessionMgr -->|Insert| DB
    SessionMgr -->|Trigger| Summarizer
    Summarizer -->|Update| DB
    
    SearchEng <-->|Select (BM25)| DB
    InjectGen <-->|Fetch Recent| DB
    
    %% 布局调整
    DB --- Tables

    %% 注释说明
    linkStyle default stroke:#b2bec3,stroke-width:2px;
```

</details>

### 3.1 持久化层：不仅仅是 Log

我们定义了一个通用的数据单元：**Observation (观测)**。
无论是用户的提问、AI 的回复，还是工具（如 `Grep`、`Read File`）的执行结果，都被视为一次 Observation。

```python
@dataclass
class Observation:
    id: str
    session_id: str
    kind: str      # user | tool | model | note
    content: str   # 实际内容
    private: bool  # 隐私标记
    # ...
```

在 SQLite 中，我们利用 **FTS5 (Full-Text Search 5)** 扩展模块建立了倒排索引。这意味着，即使你存了 10 万条对话记录，通过关键词（如“预加载策略”）检索，也能在毫秒级返回结果。

### 3.2 隐私安全：`<private>` 标签

在设计之初，我们就把隐私放在第一位。开发者经常会在代码里贴 API Key 或内部 IP。
`trae-mem` 实现了一个简单的过滤器：

```python
def remove_private(text: str) -> str:
    # 匹配 <private>...</private> 并替换为占位符
    return re.sub(r"<private>.*?</private>", "[PRIVATE HIDDEN]", text, flags=re.DOTALL)
```

当检测到 `<private>` 标签时，原始内容会被清洗，**不会**进入 FTS 索引，也不会被存储在明文字段中（或者只存储脱敏后的版本，取决于配置）。

### 3.3 渐进式检索：Search -> Timeline

单纯的关键词搜索往往丢失上下文。`trae-mem` 引入了 **Timeline (时间线)** 的概念。
当你搜到一条关于“报错日志”的记录时，你往往想看它**前后 5 分钟**发生了什么。

1.  **Search**: `SELECT ... FROM observations_fts WHERE ...` 找到命中点。
2.  **Timeline**: 拿到命中点的 `session_id` 和 `timestamp`，查询 `timestamp ± window` 范围内的所有记录。

这种“点面结合”的检索方式，能极其精准地还原当时的思维现场。

### 3.4 上下文注入 (Injection)

这是最酷的部分。当你在新会话中需要用到之前的知识时，`trae-mem` 会生成一个结构化的 Context Block：

```text
【trae-mem 注入上下文】
查询：播放器优化

最近会话摘要：
- [Session A] 讨论了 ExoPlayer 的缓存配置
- [Session B] 尝试了 PreloadManager 但失败了

相关观测细节：
- [User] 我要优化 Android 播放器的预加载策略...
- [Grep] player/config.kt ...
```

这个 Block 可以通过 MCP 工具直接喂给 Trae 的当前会话，让 AI 瞬间“想起”之前的上下文。

---

## 4. 技术总结与思考

开发 `trae-mem` 的过程，其实是对 **AI 记忆机制**的一次微型探索。

*   **本地化是趋势**：随着 IDE 越来越智能，大量的上下文数据产生在本地。将记忆留在本地，既是隐私的需求，也是性能的需求（零网络延迟）。
*   **结构化 vs 非结构化**：单纯存 Log 是不够的，必须有 **Summarization (摘要)**。目前的版本使用了启发式摘要（Heuristic），未来接入本地 LLM（如 Ollama）进行语义摘要将是巨大的提升点。
*   **MCP 的潜力**：Model Context Protocol 让工具的开发变得异常简单。它解耦了 IDE 和工具，让我们能用 Python 随心所欲地扩展 IDE 的能力。

---

### 📸 效果演示

*(此处预留演示 GIF：展示在 Trae 中输入 @trae-mem 搜索并注入上下文的过程)*
![Trae-Mem Demo Placeholder](https://via.placeholder.com/800x400?text=Trae-Mem+Demo+GIF)

---

> **项目开源地址**：[https://github.com/rong5690001/trae-mem](https://github.com/rong5690001/trae-mem)
> 欢迎 Star ⭐️ 和 PR，一起打造更聪明的 AI 编程助手！
