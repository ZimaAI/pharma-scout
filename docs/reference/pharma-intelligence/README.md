# PharmaScope｜医药研发情报与临床试验进展研究平台

**版本：1.0.0 · 文档基线日期：2026-09-21 · 类型：供编码 Agent 实现的产品与工程 Context Pack**

> 本包是需求、实现合同、设计和验收资料，不是已经完成的软件。没有执行真实模型、外部数据源或数据库集成测试。所有演示药物、试验和结论均为虚构。前一轮生成的原型图只提供布局参考，图中真实药物名称对应的日期、结果及比较数据不得复制到产品。

## 1. 产品一句话
面向药企研发信息分析人员，将公开药物与试验资料整理为**可跟踪版本、可核对证据、可人工审核、可订阅交付**的研究报告。系统辅助研究，不提供患者诊疗、处方、剂量建议或药物有效性认证。

## 2. 已选择的实现方案
- 前端：Next.js + React + TypeScript；Tailwind CSS + shadcn/ui；TanStack Query；桌面优先、中文界面。
- 后端：Python + FastAPI + Pydantic + SQLAlchemy + Alembic；模块化单体，而非微服务拼盘。
- Agent：固定提交版本的 DeerFlow 2.x harness；由项目的 `DeerFlowRuntimeAdapter` 隔离上游变化。仅一套 Agent Loop。
- 持久化：PostgreSQL；本地私有文件卷保存授权原文片段与产物。V1 不强制 Redis、向量数据库、消息中间件、ToolUniverse 或 GPU。
- 数据：V1 必须实现 ClinicalTrials.gov + PubMed 两个受控适配器；openFDA 标签、ToolUniverse/MCP、全文 PDF 摄入为 V1.1，默认关闭。
- 部署：Docker Compose；API、worker、Web、数据库、反向代理；开发环境 Mailpit。实际镜像/依赖版本在 M0 锁定，不使用 `latest`。

以上是本项目设计选择，不是对某一上游版本的已验证兼容性声明。上游说明与外部事实见 [来源记录](docs/16-sources-and-verification.md)。

## 3. 首版必须闭环
登录 → 建立药物档案/确认别名 → 同步试验与文献 → 浏览变化与原始证据 → 发起研究 → 查看工具执行和资料缺口 → 生成草稿 → 独立审核人审核指定版本 → 发布 → 站内通知/邮件投递 → 下一次只报告新增信息。

## 4. 阅读顺序
1. 编码 Agent：先读 `AGENTS.md`、`docs/00-baseline.md`、`docs/14-implementation-plan.md`、`delivery/STATE.md`。
2. 产品范围：`docs/01-prd.md`、`docs/02-domain-model.md`、`docs/03-functional-spec.md`。
3. 后端：`docs/04-architecture.md` 至 `docs/08-api-contract.md`、`docs/10-security.md`、`docs/11-reliability.md`。
4. 前端：根目录 `design.md`、`docs/09-ui-spec.md`、`contracts/openapi.yaml`。
5. 验收：`docs/12-test-and-evaluation.md`、`acceptance/acceptance.feature`、`docs/17-demo-guide.md`。

[完整文档索引](docs/INDEX.md) · [直接给 Codex 的启动提示词](CODEX_START.md) · [版本与交付状态](delivery/STATE.md)

## 5. 两种运行配置，不能混称
| 配置 | 数据 | Agent | 可以证明什么 |
|---|---|---|---|
| `demo` | `fixtures/` 虚构时间线 | `replay` 确定性回放 | 页面、状态、契约、权限和故障场景；不能证明真实模型能力 |
| `live` | 受控官方适配器 | `deerflow` + 已配置模型 | 实际资料检索与工具循环；须单独出具联网验收记录 |

前端每页显示模式，报告携带模式和数据截止时间。live 配置缺失时显式失败，禁止悄悄回退成假数据。demo 默认只访问本机；不得把默认种子账户暴露公网。

## 6. 实现与变更原则
后端先行并交付接口与测试证据，再实现前端；每次改页面必须实际读取 `design.md`。可以逐阶段验收，也可以使用 `CODEX_START.md` 中的端到端授权指令。生产部署、对外发信、付费服务、涉及真实个人敏感信息的接入，均不包含在默认实现授权内。

`contracts/` 是字段与协议合同；`database/schema.sql` 是 PostgreSQL 初始结构参考，须转成并执行 Alembic 迁移。规范冲突遵守 `AGENTS.md` 中的优先级，不能静默选择有利于少做功能的解释。
