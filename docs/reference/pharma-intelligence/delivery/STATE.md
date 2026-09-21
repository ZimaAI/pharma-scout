# 当前实施状态

- 执行模式：end-to-end（用户明确授权后端先行、前端、提交推送、更新已有部署）。
- M0：已确认真实上游 SHA、现有 harness factory 与工具注入；实际模型未配置。
- M1–M4：源码、PostgreSQL Alembic、独立会话/RBAC、来源适配、快照观察/事件/证据、研究与SSE、版本审核/发布、排程/投递实现。
- 后端真实 PostgreSQL/API 链路：通过；最终领域聚合157通过，2项来源联网另行通过；涵盖报告历史版本权限、时间边界、事件分类和投递合同回归。
- ClinicalTrials.gov/PubMed：实际 search/fetch 成功，字段合同验证通过。
- DeerFlow：真实工厂使用受控模型桩完成领域工具循环/取消/预算/上下文测试；真实模型 A/B/C 因 models=[] 为 BLOCKED，绝不算 replay 通过。
- H：后端交接文档 `BACKEND_HANDOFF.md`；根设计规范 `design.md` 已创建。后端门通过，明确 H-complete 后开始前端。
- M5：`/pharma/*` 业务前端实现完成；完整前端检查与生产构建通过，最终生产产物8项真实API浏览器验收全部通过（24.8秒），三尺寸截图已复核。
- M6：功能提交 `ce98725b12eb73aec1e685d46dec5b8e5c1a14d9` 已推送 `origin/main`，并已更新 `https://pharmascount.zimagent.top`；公网同套8项浏览器验收全部通过（27.3秒）。Gateway、Frontend、独立PG及正式worker均运行，worker已启用开机恢复；备份与回退见 `docs/pharma-deployment-handoff.md`。
- 当前实际环境与测试详细记录见 `docs/pharma-environment-audit.md`、`docs/pharma-runtime-validation.md`、`docs/pharma-source-validation.md`。
- 后端功能测试：`make pharma-test`，只在显式 *_test 数据库的随机schema执行，生产数据不清空。
- 用户已明确选择“先完成部署，稍后配置模型”；不等待真实模型，不把 DEMO 验收当作真实 Agent 联网验收。
- 实际交付范围：DEMO_READY；后端、前端、设计规范、提交推送与公网更新均已完成。真实模型及外发邮件未配置，不标记 V1_RELEASE_READY。详细失败、复验和通过证据保留于 `TEST_RESULTS.md`。
