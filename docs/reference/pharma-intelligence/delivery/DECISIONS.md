# 实施决策记录

当前：采用 docs/15-decisions-and-risks.md 的设计基线。没有编造实施决策。

追加格式：日期 / 决策ID / 事实或阻塞 / 选择与理由 / 受影响合同及测试 / 执行者。

2026-09-21 / ADR-011 / 现有仓库已部署 DeerFlow Gateway 与 Next.js，并已有 `/api/v1/auth`。
采用 `backend/app/pharma` 的领域模块与 `/api/pharma/v1` 独立 API；Gateway 外层 ASGI 分发器仅分发该命名空间，原有通用聊天鉴权不变。沿用现有部署端口，新增私有 PostgreSQL 与任务 worker。前端使用 `/pharma/*`，原 `/workspace` 保留。用户已明确授权端到端实施、提交推送和更新已有公网部署，无需重复阶段批准。

2026-09-21 / ADR-012 / 部署没有模型配置。
真实来源适配器仍完成联网验证；真实 DeerFlow 循环只执行受控本地模型桩测试，真实模型分支验收为 BLOCKED。LIVE 缺模型明确失败，绝不回退回放。DEMO 工作区独立标识、随机账户密码保存在忽略的私有文件，不提供公开默认登录。

2026-09-21 / ADR-013 / 历史研究需要防未来资料泄漏。
研究知识截止取创建时间与请求时间窗上界的较早者。只引用截止前持久化且实体关联已审核的快照；研究中发现的新资料作为待确认候选，提示同步/确认后开启新研究。网页提示先同步再研究，不伪造抓取日期。

2026-09-21 / ADR-014 / 参考 TrialProjection 漏列日期和干预。
按 FR-003/005 将 interventions、start_date、completion_date、primary_completion_date 增补为可选字段，同时更新 OpenAPI、快照 schema、映射与测试。新增工作区配置只读接口和 DEMO 时间线推进接口；补充 membership.data_mode 与 run.clarification，便于前端准确显示模式及澄清。
