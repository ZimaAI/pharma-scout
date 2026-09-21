# 18｜实现者交付清单与跨会话续接

## 必须交付文件
源码、依赖锁、Alembic迁移、Dockerfile/Compose、.env.example、初始化账户CLI、demo loader、OpenAPI及生成客户端、单元/集成/E2E测试、应用README、BACKEND_HANDOFF.md、测试报告、许可证/改动说明、已知限制。

## 后端交接模板
- commit与依赖环境；启动/停止/迁移/重置命令。
- 实际端口与Cookie/CSRF策略；demo用户如何创建。
- 每个operation的通过状态、实际请求响应位置。
- run状态与SSE错误恢复；版本并发与审核失败例子。
- source adapters：fixture通过、live通过/阻塞分别记录。
- DeerFlow：固定SHA、工具注册、上下文、恢复、取消探针结果。
- 未完成能力和不能上线的风险；禁止用“基本完成”省略。

## STATE更新规则
写明当前阶段、已完成任务ID、正在修改的文件、下一条可执行任务、阻塞条件、上次测试命令与退出码。新会话以Git/文件和测试报告核实，不把对话中的“我做了”当事实。

## 项目成果表达
保留“基于DeerFlow二次开发”标注；描述自己实现的实体映射/快照版本/证据/审核投递，不把上游Agent Loop与MCP支持说成自研。演示/合成数据结果标明环境，不写真实药企上线或临床准确率。
