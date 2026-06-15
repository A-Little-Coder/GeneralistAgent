## 1. SSE 基础

- [ ] 1.1 安装 `sse-starlette`（清华源）
- [ ] 1.2 实现 `chatbi/conversation/sse.py::sse_stream(events_iter)`：把异步事件流转 SSE
- [ ] 1.3 心跳协程：30s 一次 SSE comment
- [ ] 1.4 单元测试：用 `httpx.AsyncClient` 消费 SSE，断言事件顺序与心跳

## 2. 标准事件 schema

- [ ] 2.1 定义 `chatbi/conversation/events.py::StandardEvent`（pydantic v2，含 type discriminator）
- [ ] 2.2 各 type 的 data 子模型
- [ ] 2.3 单元测试：每种 type 序列化往返、非法类型被拒

## 3. EventNormalizer

- [ ] 3.1 实现 `chatbi/conversation/event_normalizer.py::EventNormalizer.normalize(raw_events)`
- [ ] 3.2 LangGraph v1/v2 schema 双兼容
- [ ] 3.3 多路合并（LangGraph + AskBackHub）
- [ ] 3.4 单元测试：mock 两路事件，验证合并顺序

## 4. /api/chat/stream 路由

- [ ] 4.1 实现 `chatbi/conversation/router.py::stream_endpoint`
- [ ] 4.2 启动 plan_run、注入 AskBackHub、调用 build_planning_graph().astream_events
- [ ] 4.3 注入 trace metadata（user_id/conv_id/plan_run_id）
- [ ] 4.4 客户端断开检测 → cancel
- [ ] 4.5 集成测试：mock LangGraph，端到端跑

## 5. /api/chat/resume

- [ ] 5.1 实现 resume endpoint：从 checkpoint 取 plan_run，调用 hub.resume(answer)
- [ ] 5.2 在线续跑（原流仍存活）：写入 hub 即可
- [ ] 5.3 离线续跑：建立新 SSE，从 checkpoint 恢复 LangGraph
- [ ] 5.4 集成测试：在线 + 离线两路径

## 6. Checkpoint 持久化

- [ ] 6.1 配置 LangGraph `SqliteSaver` 或自定义 `RedisSaver`，使用 `add-memory-persistence` 后端
- [ ] 6.2 thread_id = plan_run_id
- [ ] 6.3 TTL 30 分钟与黑板一致
- [ ] 6.4 单元测试：中断后用 plan_run_id 恢复

## 7. 限流

- [ ] 7.1 实现 `chatbi/conversation/rate_limit.py::RateLimiter`
- [ ] 7.2 进程 Semaphore + 用户级令牌桶（内存字典）
- [ ] 7.3 排队上限与超时
- [ ] 7.4 LangSmith span 上报
- [ ] 7.5 单元测试：429、排队、配置覆盖

## 8. 取消

- [ ] 8.1 监听 `request.is_disconnected()`
- [ ] 8.2 task.cancel() + 释放 Teammate
- [ ] 8.3 单元测试：模拟客户端断开

## 9. FastAPI 集成

- [ ] 9.1 在 `chatbi/server/app.py` 注册新路由
- [ ] 9.2 startup：构建 graph、初始化 RateLimiter、初始化 Checkpointer
- [ ] 9.3 注入 trace context middleware（每请求设置 user_id/conv_id/plan_run_id）
- [ ] 9.4 README 章节：《SSE 协议》《前端集成示例》

## 10. 统一错误响应

- [ ] 10.1 在 `chatbi/conversation/errors.py` 定义错误码枚举（kebab-case，含 `rate_limited`/`invalid_input`/`conversation_not_found`/`plan_run_not_found`/`not_ready`/`internal_error` 等）
- [ ] 10.2 实现 `ChatBIException` 基类（含 code / message / status_code / plan_run_id）
- [ ] 10.3 注册 FastAPI `exception_handler` 处理：`ChatBIException` / `HTTPException` / `Exception`，统一输出 `{"error":{"code","message","plan_run_id"}}`
- [ ] 10.4 单元测试：4xx/5xx/未捕获异常的响应体 schema
- [ ] 10.5 注意：不引入 X-Request-Id 中间件；body 中 plan_run_id 来源于 `TraceContext`（缺失为空串）

## 11. http-surface 接口实现

- [ ] 11.1 `GET /api/capabilities`：从 `SkillRegistry.summary_table()` 读取，返回 `{"capabilities":[...]}`
- [ ] 11.2 `GET /api/ready`：依次检查 Redis ping / SQLite / LLM 工厂 / SkillRegistry，全过返回 200，否则 503 + 统一错误格式
- [ ] 11.3 `POST /api/feedback`：写入 `mem:conv:{cid}:feedback` 列表，并给 LangSmith 对应 plan_run trace 加 tag `feedback=<rating>`
- [ ] 11.4 `GET /api/conversations`：列出 user 的对话，按 `last_active_at` 倒序，支持 `limit`/`cursor` 分页
- [ ] 11.5 `GET /api/conversations/{cid}/messages`：分页拉历史消息，`limit` 默认 50 / 最大 200，`before` 游标
- [ ] 11.6 `DELETE /api/conversations/{cid}`：调 `SessionMemoryStore.clear` 删除全部 `mem:conv:{cid}:*` key
- [ ] 11.7 单元测试：每个接口的 200 / 4xx / 5xx 路径
- [ ] 11.8 OpenAPI：FastAPI 自动生成；`/docs` 在 `CHATBI_ENV=dev` 时开启，prod 关闭

## 12. 对话标题 + 元数据

- [ ] 12.1 在 `add-memory-persistence` 提供的 `SessionMemoryStore` 之上添加 `ConversationStore`（同包/同模块均可），暴露 `ensure_title(cid, first_query)`、`list_for_user(uid, limit, cursor)`、`get_meta(cid)`
- [ ] 12.2 标题截断逻辑：按字符数（`len()`）截 30，超出加 `…`
- [ ] 12.3 plan_run 完成时（在 stream_endpoint 收尾处）调用 `ensure_title`
- [ ] 12.4 `last_active_at` 在每次 plan_run 完成时更新
- [ ] 12.5 单元测试：短/长 query / 后续轮不覆盖

## 13. feedback 在 LangSmith 的关联

- [ ] 13.1 用 LangSmith client 找到 root run by `plan_run_id`，加 tag `feedback=<rating>` 与 metadata `comment`
- [ ] 13.2 失败容忍：LangSmith 不可达时仍写入本地反馈（不阻断接口）

## 14. 端到端集成测试

- [ ] 14.1 完整问答（无反问）
- [ ] 14.2 反问 slot_fill 续跑
- [ ] 14.3 反问 replan 续跑
- [ ] 14.4 限流 429
- [ ] 14.5 客户端断开取消
- [ ] 14.6 离线续跑
- [ ] 14.7 capabilities / ready / feedback 三个接口的 200 路径
- [ ] 14.8 conversations CRUD：列表 → 历史 → 删除
- [ ] 14.9 标题自动生成：首条 query 完成后 title 正确
- [ ] 14.10 错误响应统一性：故意触发 4xx/5xx 校验 schema

## 15. 验收

- [ ] 15.1 全部测试通过
- [ ] 15.2 LangSmith 中可看到完整对话 trace（含反问、续跑、限流事件、feedback tag）
- [ ] 15.3 README 协议示例可被前端验证
- [ ] 15.4 `/docs`（仅 dev）展示完整 OpenAPI，所有 http-surface 接口均含 schema