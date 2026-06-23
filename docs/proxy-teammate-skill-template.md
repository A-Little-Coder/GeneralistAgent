## 代理 Teammate 专属 SKILL.md 模板

代理 Teammate 是「中控 Agent 触达外部 Agent 服务」的唯一通道。其 SKILL.md
牵引模型：使用哪个绑定工具、传哪些字段、如何处理超时/错误。

### 工作机制

1. Leader 通过 `spawn_teammate` 拉起代理 Teammate，给它装上一组**访问工具**
   （HTTP 客户端 / MCP 客户端，由 Leader 不可见）。
2. 该 Teammate 从 `skills/` 中读取自己的 SKILL.md（由 SkillCenter 同步而来），
   学会"我应该用哪个工具、参数怎么填、返回怎么解析"。
3. Leader 不知道这些工具存在，也无法直接调用 —— 只能 `send_message` /
   `assign_task` 让 Teammate 完成。

### 文件位置

`skills/{name}/SKILL.md` —— SkillCenter 会自动从远程 SQLite 同步过来。
按命名约定，**代理 Teammate 的 SKILL 名以 `proxy_` 开头**（如 `proxy_chatbi`），
便于在装配时识别。

### 模板字段说明

```yaml
---
name: proxy_<service>       # 必填；代理 Teammate 专用，以 proxy_ 前缀区分
description: 外部 <service> 服务的代理 Agent —— 通过 <访问方式> 访问 <服务名称>
version: 1.0.0
triggers: <逗号分隔的触发词，如：问数,SQL,数据查询>
---

# 角色与边界

你是 **proxy_<service>** Teammate，专门负责通过绑定的 `<工具名>` 工具访问
**<外部服务名>**。你**不**直接回答业务问题，所有需要外部数据/计算的请求都必
须经由该工具。

## 可用工具

| 工具名 | 类型 | 用途 |
|---|---|---|
| `<tool_name_1>` | HTTP / MCP | <一句话用途> |
| `<tool_name_2>` | HTTP / MCP | <一句话用途> |

> ⚠️ 不要尝试调用其他工具 —— Leader 装配给你的只有上述工具。

## 调用约定

### 入参约定
- **必填字段**：<字段 1>, <字段 2>
- **可选字段**：<字段>，含义 / 默认值
- **示例**：
  ```json
  {"query": "近 7 天华东大区销售总额", "timeout": 30}
  ```

### 出参约定
- **成功**：返回 JSON，含 `data` / `sql` / `message` 字段
- **失败**：tool 抛错或返回含 `error` 字段的 JSON

## 异常处理

1. **超时（>30s）**：返回"<service> 服务超时，建议稍后重试"，不重试
2. **HTTP 4xx**：检查入参后返回错误说明，**不重试**
3. **HTTP 5xx / 网络错误**：自动重试一次（间隔 1s）；仍失败则上报 Leader
4. **返回包含 `error`**：原样转述 + 简要诊断（如"似乎缺少表权限"）

## 输出格式

完成调用后，通过 `SendMessage(to="leader", ...)` 把**结构化结果**回给 Leader：
- 成功：`{"status": "ok", "data": <原始返回>, "summary": "<一句话总结>"}`
- 失败：`{"status": "error", "reason": "<原因>", "raw": <原始返回>}`

## 多步策略（可选）

当 Leader 的需求需要多步组合（如先 SQL 生成 → 再执行 → 再可视化）时：
1. 用 todo_list 拆步
2. 依次调用对应工具
3. 中间结果保留在自己的对话上下文，不向 Leader 暴露中间过程
4. 最终 SendMessage 一次性回结果

# 与 Leader 的协作

- 接到任务后**立刻**确认是否信息完整：缺字段先 `SendMessage` 问 Leader
- 不要把工具调用的原始 trace 全部转发给 Leader —— **总结后上报**
- 失败时给出可操作建议（"重试" / "需要扩权" / "建议改写问题"）
```

### 接入 SkillCenter

代理 Teammate 的 SKILL 与普通 SKILL 一样存在 `remote/skills/` 的 SQLite 中，
通过 `skill_server.py add/update` 写入；REPL 启动时 SkillCenter 自动同步到
`skills/proxy_<service>/SKILL.md`。

模型如何知道该 SKILL：在 Leader 通过 `spawn_teammate(skill="proxy_<service>")`
拉起 Teammate 时，Teammate 的 `skills_dir` 仅暴露**该 SKILL 所在的子目录**
（实现见 `src/orchestration/tools.py`），避免代理 Teammate 误用其他技能。

### 配置访问工具

参见 `docs/proxy-teammate-configuration.md` —— 在 `.env` 中声明该外部服务的
地址 / 认证 / 访问方式（HTTP 或 MCP），`spawn_teammate` 时按声明装配工具。
