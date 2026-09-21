# 19｜需求到实现与验收的追踪矩阵

| 需求ID | 领域模块 | API组 | 核心场景 |
|---|---|---|---|
| FR-001 | auth/membership | auth, members | T14,T25,T26 |
| FR-002 | entities | drugs, aliases, entity-links | T08,T09 |
| FR-003 | sources projection | trials, publications | T04,T06,T07 |
| FR-004 | ingestion | sources, source-syncs, jobs | T11,T12,T24 |
| FR-005 | snapshots/events | records, snapshots, events | T01,T02,T03,T05,T10 |
| FR-006 | agent runtime/tools | research/runs | T08,T09,T11,T15,T22,T23 |
| FR-007 | run lifecycle | runs cancel/retry/clarifications/events | T20,T21,T22 |
| FR-008 | evidence/claims | evidence, report versions | T07,T10,T13,T23 |
| FR-009 | reports/reviews | submit-review, reviews, publish, retract | T13,T16,T17,T25 |
| FR-010 | subscriptions/delivery | subscriptions, inbox, deliveries | T18,T19,T26 |
| FR-011 | observability/audit | dashboard, sources, tool-calls, audit | T11,T15,T18,T21 |
| FR-012 | fixtures/replay | all demo routes | T01—T26 +独立live门槛 |

界面路由和API的对应关系见09。实现者新增或删除需求时同步此表、OpenAPI、状态机、fixtures与测试，不能只改页面文案。
