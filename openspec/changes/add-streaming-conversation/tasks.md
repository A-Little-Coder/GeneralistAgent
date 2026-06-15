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

## 10. 端到端集成测试

- [ ] 10.1 完整问答（无反问）
- [ ] 10.2 反问 slot_fill 续跑
- [ ] 10.3 反问 replan 续跑
- [ ] 10.4 限流 429
- [ ] 10.5 客户端断开取消
- [ ] 10.6 离线续跑

## 11. 验收

- [ ] 11.1 全部测试通过
- [ ] 11.2 LangSmith 中可看到完整对话 trace（含反问、续跑、限流事件）
- [ ] 11.3 README 协议示例可被前端验证