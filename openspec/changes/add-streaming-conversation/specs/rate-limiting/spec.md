## ADDED Requirements

### Requirement: 进程级与用户级限流

系统 SHALL 实现 `RateLimiter` 中间件：
- 进程级：`asyncio.Semaphore(settings.max_concurrent_runs)`，默认 10；
- 用户级：基于内存的令牌桶（容量 5，速率 1 token/s），默认 5 QPS；
- 超限请求返回 HTTP 429 + JSON `{"error":"rate_limited", "retry_after_s": <int>}`。

#### Scenario: 超出用户级 QPS

- **WHEN** 同一 user 1 秒内发起 6 次请求
- **THEN** 第 6 次返回 429
- **AND** 响应 header `Retry-After: 1`

#### Scenario: 超出进程并发

- **WHEN** 已有 10 个 plan_run 并发，第 11 个进入
- **THEN** 第 11 个排队（默认 30 秒），超时仍返回 429

### Requirement: 限流可配置

系统 SHALL 在 Settings 暴露 `max_concurrent_runs`、`user_rate_qps`、`user_rate_burst`、`queue_max_wait_s` 字段，可通过环境变量覆盖。

#### Scenario: 环境变量覆盖

- **WHEN** 设置 `USER_RATE_QPS=10`
- **THEN** 单用户每秒可跑 10 次

### Requirement: 限流事件上报

系统 SHALL 在限流事件触发时给 LangSmith trace 添加 span `event=rate_limited`，含 `user_id`、`reason`（`user_qps`/`process_concurrency`）、`waited_ms`。

#### Scenario: 上报

- **WHEN** 触发 user_qps 限流
- **THEN** LangSmith 中可见对应 span