---
name: general
description: 通用技能
version: 1.0.0
triggers: 文件,代码,整理,总结,创建
---

## 通用任务处理指南

### 文件操作
- 创建文件时使用 write_file 工具
- 编辑已有文件时使用 edit_file 工具
- 读取文件内容时使用 read_file 工具

### 任务规划
- 多步骤任务先使用 write_todos 拆解为子任务
- 按优先级逐步执行，并及时更新 todo 进度

### 命令执行
- 使用 execute 执行 shell 命令
- 命令执行结果会返回给用户