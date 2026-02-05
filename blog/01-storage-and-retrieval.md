# 01｜存储与检索：用 SQLite + FTS5 搭一个“可带走”的记忆库

你可以把 `trae-mem` 的持久化层理解为：**把“对话/工具输出/关键结论”按时间线落盘，然后用全文检索把它们在毫秒级捞出来**。这一层做得足够“克制”，才支撑了整个系统的轻量化与本地化。

本文聚焦 `trae-mem` 的第一块核心能力：**Memory Storage & Retrieval（记忆存储与检索）**。

---

## 1. 设计目标：为什么是 SQLite？

`trae-mem` 选择 SQLite 的核心原因不是“复古”，而是它正好满足记忆层的三个硬指标：

- **零运维**：一个文件就是全部数据；迁移、备份、同步都简单。
- **足够快**：WAL + 索引 + FTS5，10 万级别记录仍能快速检索。
- **可扩展**：用 JSON 字段存 tags/meta，未来要加字段、加策略都不痛苦。

实现集中在 [db.py](../trae_mem/db.py) 的 `TraeMemDB`。

---

## 2. 数据模型：Session / Observation / Summary

整个数据库围绕三个实体建模：

- **sessions**：一次“连续工作”的时间段（可理解为 IDE 的一个对话会话）。
- **observations**：会话内发生的一切“可回放事件”（用户输入、工具调用、note/decision/error 等）。
- **summaries**：会话结束时生成的“压缩结果”（brief/detailed 两层）。

在 [db.py](../trae_mem/db.py#L61-L102) 里，`init_schema()` 创建了这三张表：

```sql
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  started_at INTEGER NOT NULL,
  ended_at INTEGER,
  project_path TEXT,
  meta_json TEXT
);

CREATE TABLE IF NOT EXISTS observations (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  ts INTEGER NOT NULL,
  kind TEXT NOT NULL,
  tool_name TEXT,
  content TEXT NOT NULL,
  private INTEGER NOT NULL DEFAULT 0,
  tags_json TEXT,
  FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS summaries (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  level TEXT NOT NULL,
  content TEXT NOT NULL,
  FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
```

这里有几个点非常关键：

- **observations 是“事件溯源”的载体**：它不是存最终状态，而是存“发生了什么”。这让你能用 Timeline 还原当时的思维链。
- **private 标记决定是否进入索引**：敏感内容不参与检索，降低泄漏风险。
- **tags_json/meta_json 用 JSON 字符串**：避免过度结构化导致 schema 快速膨胀。

---

## 3. 写入路径：Observation 是如何落盘的？

写入的核心 API 是 [TraeMemDB.add_observation](../trae_mem/db.py#L155-L185)：

1. 生成 `obs_id`
2. 插入 `observations`
3. 如果 `private=False`，再插入 `observations_fts`

```python
obs_id = uuid.uuid4().hex
self._conn.execute(
    "INSERT INTO observations(...) VALUES (?, ?, ...)",
    (...),
)
if not private:
    self._conn.execute(
        "INSERT INTO observations_fts(id, session_id, kind, tool_name, content) VALUES (?, ?, ?, ?, ?)",
        (obs_id, session_id, kind, tool_name or "", content),
    )
self._conn.commit()
```

这里的设计取舍很明确：**FTS 只服务“可检索内容”**，隐私内容即使落盘也不会被搜索命中。

---

## 4. 索引：FTS5 + BM25 + snippet 是怎么工作的？

`trae-mem` 的检索优先走 FTS5。建表在 [init_schema()](../trae_mem/db.py#L103-L138)：

- 优先使用 `tokenize='trigram'`：对中文更友好（更像“按 3 字符切片”的模糊匹配）
- 如果 SQLite 环境不支持 trigram，则回落到 `unicode61`

搜索逻辑在 [TraeMemDB.search](../trae_mem/db.py#L260-L327)：

```sql
SELECT
  o.id AS id,
  o.ts AS ts,
  o.kind AS kind,
  o.tool_name AS tool_name,
  o.session_id AS session_id,
  snippet(observations_fts, 4, '[', ']', '…', 12) AS snip,
  bm25(observations_fts) AS score
FROM observations_fts
JOIN observations o ON o.id = observations_fts.id
WHERE observations_fts MATCH ?
ORDER BY score
LIMIT ?
```

三件事在这里发生：

- **MATCH**：倒排索引检索命中项（非常快）
- **snippet**：从内容中截取“可读片段”，用于 UI 展示
- **bm25**：给每条命中一个相关性分数（越小越相关）

如果 FTS5 查询不可用（例如某些环境缺少模块），它会 fallback 到 `LIKE`（能用但性能差一些）。

---

## 5. 复盘：Timeline 为什么比“只 search”更重要？

你在 IDE 里搜到一条记录，往往想知道“它前后发生了什么”。所以 `trae-mem` 提供了 Timeline 查询：

实现位于 [TraeMemDB.timeline](../trae_mem/db.py#L329-L348)：

- 先通过 `observation_id` 找到 `session_id` 和 `ts`
- 再查询 `ts ± window*60` 的所有 observations

```sql
SELECT * FROM observations
WHERE session_id=?
  AND ts BETWEEN ? AND ?
ORDER BY ts ASC
```

这让“点检索”升级为“点面结合”：先用 search 找到针，再用 timeline 拉出那一小段“思维现场”。

---

## 6. 性能与可靠性：WAL、索引与容错

`TraeMemDB` 在连接时做了三件对性能很关键的事情（见 [db.py](../trae_mem/db.py#L52-L57)）：

- `PRAGMA journal_mode=WAL`：写入更快，读写并发更友好
- `PRAGMA synchronous=NORMAL`：在安全与性能之间做平衡
- `CREATE INDEX idx_observations_session_ts`：按会话 + 时间排序快速

容错上也很“实用主义”：

- FTS 不可用就降级 LIKE
- trigram 不可用就降级 unicode61

---

## 7. 你可以怎么扩展？

如果你要继续把“存储与检索”这层打磨得更强，典型方向有：

- **更好的分词**：中文检索可考虑引入自定义 tokenizer（但会牺牲“零依赖”）
- **结构化 tags**：把 tags_json 拆为专门字段并建立索引，支持更强的筛选（kind/tool_name/项目/时间）
- **向量检索**：在 observations 上增加 embedding 字段与 ANN 索引（这会引入新依赖，谨慎）

下一篇我们拆解 “生命周期挂钩”：数据从哪里来、如何稳定地把 IDE 的行为转成 Observation。
