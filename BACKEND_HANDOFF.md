# PharmaScount 后端交接

2026-09-21。H 后端交接已完成：在后端接口及真实 PostgreSQL 闭环验证通过后，
明确 H-complete，再开始业务前端。根目录 [design.md](design.md) 已沉淀为实现规范，
`/pharma` 页面使用共享组件和生成合同联调。最终生产构建、完整浏览器门和部署状态
由交付记录更新，不由本交接文档推定。

测试基于个人仓库 `c8796e41b0cc2e3132c5514035b2e015017ead89` 加当时工作树；
固定 DeerFlow 上游为 `29d285731b326a728a9df33d3641f73b68bbe48b`。
使用已有 `create_deerflow_agent` 工厂和 Agent loop，不创建第二套循环。

## 运行与规范接口

- `backend/app/pharma/` 为独立领域模块。Gateway 通过 `PharmaDispatcher` 只分发
  `/api/pharma/*`，其他路由保留原通用助手鉴权。
- 业务 HTTP `/api/pharma/v1`；规范 OpenAPI `/api/pharma/openapi.json`；
  交互文档 `/api/pharma/docs`；存活 `/api/pharma/healthz`；数据库就绪 `/api/pharma/readyz`。
- OpenAPI 使用 `contract.specification()` 返回的完整合同，`app.openapi` 明确绑定该函数，
  不是动态注册路由后自动推断出的空白或宽松合同。它将规范路径映射到实际
  `/api/pharma/v1` 与健康检查前缀，服务基址为同源 `/`。
- 规范源 `docs/reference/pharma-intelligence/contracts/openapi.yaml` 与部署镜像
  `backend/app/pharma/resources/openapi.yaml` 同步；前端
  `frontend/src/core/pharma/contracts.ts` 由 `scripts/generate_pharma_contracts.py` 生成，
  不手写另一套字段。运行时严格校验请求，响应按合同投影，数据库内部字段不直接外泄。
- PostgreSQL 为事实源；SQLAlchemy Core 执行带工作区约束的查询；Alembic 独立迁移，
  数据库触发器保护不可变版本。worker 使用 PostgreSQL advisory leader lock、
  单研究执行槽及带 owner token 的租约；排程/投递协程仍可推进。
- 根命令：`make migrate`、`make seed-demo`、`make pharma-worker`、`make pharma-test`、
  `make verify-docs`。原有 `make setup/dev` 保持全栈职责。
- 本机私有环境为 `.deer-flow/pharma/private.env`；容器配置参考
  `docker/pharma.env.example` 与 Compose overlay。密钥、账户口令、备份和原始日志不提交。

## 会话与权限

登录 `POST /auth/login {email,password}`；`GET /auth/me` 返回 user、memberships
（含工作区 data_mode）及 csrf_token。以下业务路径均相对 `/api/pharma/v1`。

Cookie `pharma_session` 为 HttpOnly/Secure/SameSite=Lax，Path=/api/pharma；
前端从登录或 me JSON 取得 CSRF，并在变更请求发送 `X-CSRF-Token`，不读取
`document.cookie`。工作区由 URL 指定后重新验证 membership；reader/analyst/reviewer/admin
独立于通用助手角色。草稿和运行仅创建者或 reviewer/admin 可操作，发布报告按权限共享；
账户/成员停用会在后续请求及后台写入前重新生效。

Pharma 不提供在线注册，使用 CLI 建号。原部署管理员继续使用本机私有登录信息；
独立演示审核员口令存于 `.deer-flow/pharma/accounts.json`，网页不公开默认凭据。
审核发起人和当前版本编辑人均不能自审。

## 客户端协议

所有资源字段为 snake_case；分页为 items/next_cursor/has_more。列表使用合同中的
`query`（不是 `q`）及结构化筛选；药物搜索包括已批准别名。cursor 绑定工作区和筛选，
筛选改变应回到第一页。日期按实际精度返回，未知值为 null，不补造年月日。

药物与订阅修改发送 `If-Match: "revision"`。研究、同步、发布、订阅触发和研究重试
发送 8–200 字符 `Idempotency-Key`；同键参数不同返回 409。
错误为 `{error:{code,message,details,request_id}}`：401 重新登录，403 显示权限，
404 不透露对象，409 重新读取并保留编辑内容，422 显示字段错误。

SSE `/workspaces/{workspace_id}/research/runs/{run_id}/events` 按持久化 seq 发出，
支持 `Last-Event-ID` 和 `after`。客户端按 run_id+seq 去重，心跳不算进度，断线不创建新任务。
410 后先读任务详情；历史 clarification.required 帧不能关闭已经恢复的研究事件流。
澄清提交到 `/research/runs/{run_id}/clarifications`，携带 question_id 和 answer。
取消区分请求与终态，排队/待输入任务可直接取消；重试创建新 attempt，不冒充 checkpoint 恢复。

## 事件与投递的最终合同

公开 Event 分类由 API 读取投影统一，内部历史分组标识保持稳定：

| 内部分组 | 公开 category | 展示含义 |
| --- | --- | --- |
| status | status_change | 来源试验状态变化 |
| enrollment | enrollment_change | 入组信息变化 |
| endpoints | outcome_definition_change | 终点定义变化 |
| results | results_available | 结果结构变化，不表示结果积极或临床成功 |
| dates | date_change | 日期字段变化，保留来源精度 |
| correction | correction | 来源提供的更正关系 |
| literature / record | other | 其他资料字段变化 |

事件列表和详情都返回同一公开枚举。旧自动英文分类标题在读取时转换为中文，
新事件直接使用中文标题；不回写、重编号或合并旧事件，尤其不能因两个旧分组都投影为
other 而合并身份。event_revision、source_observation、source_snapshot 和 evidence
保持不可变，无需历史数据迁移。文献首次抓取建立 baseline，不伪造前一观察或
publication_added revision；摘要变化和更正关系分别表达。五项新回归覆盖真实 PG、
API JSON Schema、多对一分类和读取前后的不可变记录比较。

`Delivery` 现在同时返回 **report_id** 与 **report_version_id**。report_id 由服务端读取
已绑定版本所属报告得出，无需新增数据库列。通知链接使用
`/pharma/reports/{report_id}?version={report_version_id}`，打开实际投递的不可变版本，
不能默认跳到后来修改的草稿。版本读取和导出仍由后端鉴权。

## 研究、审核和交付闭环

1. 建立药物、提出别名、reviewer 确认；来源同步返回 202 job。成功抓取形成快照和观察，
   官方召回的候选实体关联需明确确认。
2. 创建研究时冻结问题、药物、批准别名、来源、预算及资料截止时间。
   knowledge_cutoff 为创建时刻与 end_exclusive 的较早者，并排除恰好位于结束边界的观察。
   当前状态按截止前最新成功 observation 选择，内容回退仍能指向较旧快照；不按快照首次出现时间猜测。
3. 新抓取资料若晚于冻结 cutoff，保留真实观察时间并提示先确认关联后创建新研究；
   不回填时间。模型仅能调用九个领域工具，可信闭包限定 user/workspace/run，不能运行任意代码、
   读写文件、访问任意网址、安装 MCP、批准、发布或发信。
4. DEMO 使用 `ReplayRuntimeAdapter` 并始终标记 replay/虚构资料；LIVE 缺模型明确失败，
   不退回 DEMO。取消、预算和任务写入经过租约检查；不支持持久化 checkpoint 无损恢复。
5. 编辑报告产生新的 report_version，校验范围、证据定位/哈希和事件覆盖；结构/数字匹配
   不代表语义成立，语义保留人工核对。阅读界面保留来源覆盖、资料截止、限制与引用。
6. submit-review / reviews / publish 都绑定 version_id/content_hash；独立 reviewer 批准，
   发布时再次事务检查。自审为 403；旧版本或旧哈希为 409；编辑后必须重新审核。
7. publish 原子写发布指针和 delivery outbox。worker 独立投递指定版本，不重新研究。
   站内 accepted 表示成功写入通知；邮件 accepted 仅表示 SMTP 接受，unknown 不自动重发。
   只有实际覆盖且对应渠道已经接受的事件才推进订阅游标。来源失败或截断不能伪装为 no_change。

## 验证与交付边界

最终领域聚合 **157 passed、2 live deselected**，含新增事件合同回归；此前原有全量运行
中的 152 项 Pharma 测试全部通过。严格阻塞 I/O **149 passed**。全量旧后端
**18,172 passed、18 failed**，其中 17 个关闭公开注册导致的环境用例在 example 配置下
全部通过，剩余一个与开发前一致的上游 trace binding 清理失败。不能声称旧后端全量全绿。

ClinicalTrials.gov/PubMed 两项真实 search/fetch 合同用例通过；真实模型 A/B/C 仍因
models=[] 为 **BLOCKED**。用户明确授权“先部署、后配置模型”，不需要等待模型配置，
也不能将本次标记为 `V1_RELEASE_READY`。SMTP 真实外发保持关闭，网络 SMTP 未实测。

前端已完成 design.md 规范和业务对接；完整组件回归 **1,923 passed**，最后一轮领域专项
**30 passed**，完整 `pnpm check` 通过。开发栈浏览器存在已记录的失败与修复，
最终生产产物的完整 8 项浏览器验收及公网更新仍由部署门确认。

详细命令、原始日志位置和未通过项见
[测试结果](docs/reference/pharma-intelligence/delivery/TEST_RESULTS.md)、
[运行时验证](docs/pharma-runtime-validation.md)、
[官方来源验证](docs/pharma-source-validation.md)、
[部署与回滚交接](docs/pharma-deployment-handoff.md)。
