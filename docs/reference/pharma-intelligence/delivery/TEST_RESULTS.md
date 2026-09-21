# 软件测试结果记录

记录日期：2026-09-21。开发阶段测试基于个人仓库基线提交
`c8796e41b0cc2e3132c5514035b2e015017ead89` 加各次执行时的工作树；最终功能
提交为 `ce98725b12eb73aec1e685d46dec5b8e5c1a14d9`，已推送至 `origin/main`。
固定 DeerFlow 上游为
`29d285731b326a728a9df33d3641f73b68bbe48b`，详见
[upstream.lock.json](upstream.lock.json)。生产产物及公网部署验收分别记录。

环境：Python 3.12.3、Node.js 24.17.0、pnpm 10.26.2、PostgreSQL 16；
Playwright 1.59.1 / Chromium headless shell 147.0.7727.15。后端使用
`backend/.venv`。数据库集成只在专用 `_test` 数据库的随机 schema 内迁移和回滚，
不清空部署业务表。虚构资料、受控模型桩、官方 API 和真实模型的结果分别记录。

## 1. 已执行检查

| 编号 / 检查 | 状态与实际结果 | 证据与范围 |
| --- | --- | --- |
| B-ALL 全量离线后端 | **18,172 passed、18 failed、190 skipped、5 deselected、32 warnings**；2614.79 秒，退出码 1 | `.deer-flow/pharma/backend-final-full.log`；包含当时全部 152 项 Pharma 测试，152 项均通过；先于最后新增事件合同测试 |
| B-CONFIG 失败节点配置复验 | **17 passed、1 warning**；21.21 秒，退出码 0 | `.deer-flow/pharma/backend-final-auth-recheck.log`；只复验 16 个旧登录/注册用例及 1 个账户初始化用例，使用 example 配置副本 |
| B-BLOCK 严格阻塞 I/O | **149 passed、2 warnings**；16.76 秒，退出码 0 | `.deer-flow/pharma/backend-final-blocking.log` |
| B-DOMAIN 最终医药聚合 | **157 passed、2 live deselected、1 warning**；29.27 秒，退出码 0 | `/tmp/pharma-backend-release-gate.log`；含原 152 项及新增 5 项事件映射/真实 PG/API 合同回归 |
| B-PG 数据库/权限/版本 | **通过，包含在 B-DOMAIN 中，不重复相加** | 实际 Alembic、两工作区隔离、复合外键、不可变版本与证据、审核发布和站内投递；事件与持久化专项另有 46 项通过 |
| R-GRAPH DeerFlow 离线图探针 | **19 passed**，退出码 0；包含在 B-DOMAIN 中 | 真实上游 agent factory 和 graph，受控 `BaseChatModel`；九个领域工具、预算、取消、澄清、上下文隔离、结构/证据验证，不是第二套 Agent 循环 |
| S-CTG ClinicalTrials.gov 官方 API | **LIVE PASSED**；2 项来源联网用例中的 1 项 | `metformin` 单条 search/fetch、HTTPS 返回与 JSON Schema/字段映射；本次样本 NCT07436182 |
| S-PUB PubMed 官方 API | **LIVE PASSED**；2 项来源联网用例中的 1 项 | `metformin` 单条 ESearch/EFetch、摘要与元数据合同；本次样本 42503322；不读取全文 |
| F-ALL 前端完整单元/DOM 回归 | **224 文件、1,923 passed、0 failed**；82.711 秒，退出码 0 | `/tmp/pharma-frontend-full-tests-final.log`；受控 API/组件测试，不等同真实浏览器或模型验收 |
| F-DOMAIN 最新前端领域专项 | **5 文件、30 passed、0 failed**；6.086 秒，退出码 0 | `/tmp/pharma-frontend-domain-final.log`；含最新 Field 回归、API 客户端、研究/报告、表单与实体页面 |
| F-CHECK 前端静态检查 | **完整 `pnpm check` 通过**，退出码 0 | `/tmp/pharma-frontend-release-check.log`；ESLint + `tsc --noEmit`；生产构建是单独门槛 |
| F-BUILD 最终生产构建 | **PASSED**，退出码 0 | `/tmp/pharma-production-build-final.log`；隔离目录 Next.js `build --webpack`，含 TypeScript 检查；BUILD_ID `VCCPkjbupDUif5wuKuguZ` |
| E-DEV 开发栈真实浏览器 | **PARTIAL / 存在失败记录**，详见第 4 节 | 同源真实 API、PostgreSQL 与 worker；无 API mock；不能将各次部分结果合并称为完整 8 项通过 |
| E-PROD 最终生产产物 8 项浏览器门 | **8 passed、0 failed**；24.8 秒，退出码 0 | `/tmp/pharma-browser-production-final.log`；上述构建产物经 13027 同源代理连接真实 API、PG 和 worker；严格焦点恢复、导航和研究发布全旅程通过 |
| E-PUBLIC 部署后公网完整浏览器门 | **8 passed、0 failed**；27.3 秒，退出码 0 | `/tmp/pharma-browser-public-final.log`；同一配置直接访问 `https://pharmascount.zimagent.top`，使用正式 Gateway、Frontend、PG 和 worker |
| D-PUBLIC 公网健康与会话安全 | **PASSED** | 首页跳转 `/pharma/dashboard`；既有 `/health`、`/health/ready` 与 Pharma 两个探针均 200；Cookie 安全属性正确、错误 CSRF/Origin 均 403、有效退出 200 后原会话 401 |
| R-LIVE 真实模型 A/B/C 分支 | **BLOCKED：models=[]** | 未配置模型，未调用真实 LLM；没有真实输出质量评分或重复稳定性评测 |
| SMTP 真实/本地 SMTP 传输 | **NOT_RUN**；真实外发关闭 | 订阅/outbox/unknown/重试由内存 SMTP 替身及真实 PG 验证；不声称已通过 Mailpit 或真实邮箱投递 |

B-ALL 的 18 个失败不能直接抹去：17 项在独立配置复验后通过；唯一仍失败的是
`test_client_langfuse_metadata.py::test_stream_abandoned_generator_cleanup_stays_inside_trace_binding`。
该异步生成器 trace binding 清理问题在开发前基线已复现，相关 harness client、
factory 和该测试文件没有本次改动。没有为本次领域功能修改无关上游行为。
因此原有全量测试**不是全部通过**。此前因继承临时配置路径或缺少 uv PATH 导致的
59 个旧环境失败，在 B-ALL 的清洁环境运行中未再出现。

## 2. 后端命令与隔离条件

本机实际执行的私有 runner（脚本和原始日志均不提交）：

```bash
backend/.venv/bin/python .deer-flow/pharma/run_backend_regression.py
backend/.venv/bin/python .deer-flow/pharma/recheck_backend_auth.py
```

第一个 runner 安全读取 `.deer-flow/pharma/private.env` 中的测试数据库 URL，
只传入子进程环境；移除 `UV_PROJECT_ENVIRONMENT`、`UV_NO_SYNC`、
`DEER_FLOW_CONFIG_PATH` 和 `DEER_FLOW_RUN_LIVE_TESTS`，在 PATH 加入本仓库
`.deployment-tools/bin` 和 `backend/.venv/bin`，然后从 `backend/` 执行：

```bash
PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
  .venv/bin/python -m pytest -m 'not live' --ignore=tests/blocking_io tests/ -v
PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
  .venv/bin/python -m pytest tests/blocking_io -q --tb=short
```

范围与 backend `make test` / `make test-blocking-io` 一致。直接调用已同步的解释器，
避免 `uv run` 在已部署环境重新同步并裁剪可选运行依赖。全量耗时包含主机资源竞争，
不作为性能基准。

第二个 runner 从完整日志选出上述 17 个确切失败 node ID，复制
`config.example.yaml` 到私有临时文件，仅为该复验子进程设置
`DEER_FLOW_CONFIG_PATH`，执行 `.venv/bin/python -m pytest <17个失败node ID> -q --tb=short`。
没有开启生产公开注册，没有修改原断言，也没有让其他子进程测试继承此配置覆盖。

最终领域聚合和事件专项的底层命令为：

```bash
# 从仓库根目录；测试数据库 URL 已由私有环境加载器传入，不打印连接串。
make pharma-test
PYTHONPATH=backend backend/.venv/bin/python -m pytest \
  backend/tests/test_pharma_events.py backend/tests/test_pharma_persistence.py -q
```

来源适配器当次执行了整个来源文件：**32 passed**（30 离线 + 2 live），退出码 0。
这不是 32 次真实联网验收。完整命令和小规模联网方式为：

```bash
PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests/test_pharma_sources.py -q
PYTHONPATH=backend DEER_FLOW_RUN_LIVE_TESTS=1 backend/.venv/bin/python \
  -m pytest backend/tests/test_pharma_sources.py -q
backend/.venv/bin/ruff check backend/app/pharma/sources.py backend/tests/test_pharma_sources.py
```

两个 live 用例均使用生产适配器 search/fetch，每源仅取一个样本；截断明确记录，
不宣称来源全集、持续可用性或医学语义正确。响应时间、规范化版本和内容哈希见
[官方来源验证](../../../pharma-source-validation.md)，本机摘要为忽略文件
`.deer-flow/pharma-source-probe.json`。

## 3. 前端命令与证据

在 `frontend/` 执行：

```bash
pnpm exec rstest run
pnpm exec rstest run tests/unit/core/pharma tests/unit/pharma
pnpm check
```

完整 1,923 项运行发生在最后一个 Field 用例之前；最新 30 项领域专项已经包含该用例。
二者为不同批次，不相加宣称 1,953 个独立用例。研究/报告专项的 10 项包括：
SSE 去重与异任务隔离、历史澄清重放、LIVE 缺模型禁用、时区/预算提交和重复点击锁、
独立版本/哈希审核、自审/旧版本禁用、409 保留编辑、读者发布视图与引用、
通知历史版本参数及作者降级后的动作隐藏。

开发中的构建曾因测试类型错误失败，已修复并通过 F-CHECK；主机内存竞争也导致过
检查中断。失败和中断不记为生产构建通过；其后的最终 F-BUILD 与 E-PROD 均已通过。

## 4. 浏览器实测与最终生产产物验收

测试位置 `frontend/tests/e2e-pharma/`；开发栈使用真实 API、数据库、worker 和私有账户，
只在 DEMO 工作区追加验收资料。以下记录是不同尝试，不能合并成完整通过：

| 实际尝试 | 结果 | 原始证据 |
| --- | --- | --- |
| 三视口布局 | **3 passed，30.1 秒**；1440×900、1024×768、390×844 的工作台/药物/试验/报告无页面溢出 | `/tmp/pharma-browser-layout.log`；当时主机 CJK 字体缺失，其后已补齐 Noto 并于 E-PROD/E-PUBLIC 重采截图 |
| 真实登录和主路由 | 登录专项通过；11 个主页面及药物/试验详情曾实际渲染；合并场景曾因测试误设 D3 已有文献而失败，已修正为 D4 首次文献 | 不将路由观察替代完整场景通过 |
| LIVE 无模型提示 | 独立用例通过（4.7 秒） | 原工作流日志已被后续重跑覆盖；不伪造可恢复日志 |
| 订阅预览/创建/暂停切换 | 独立真实工作流通过（5.5 秒） | `/tmp/pharma-browser-workflows.log` |
| 研究回放至报告发布/导出 | 真实 SSE、引用、独立审核、发布、JSON/Markdown 导出与版本哈希核对均实际执行；该次最终因浮点宽度 `390.00003 > 390` 断言失败 | `/tmp/pharma-browser-research.log`；已改为合理的 1px 容差，最终完整重跑见 E-PROD/E-PUBLIC |
| 引用抽屉键盘焦点 | 严格回归曾因 Escape 后焦点未回到引用按钮而真实失败；已补显式焦点恢复 | `/tmp/pharma-browser-research-focus.log`；保留严格断言，其后 E-PROD/E-PUBLIC 均通过 |
| 最近一次开发栈完整 8 项尝试 | **1 passed、1 failed、6 未运行**；导航加载超时中止，导航等待已调整 | `/tmp/pharma-browser-dev-final.log`；开发 HMR/资源竞争不能替代最终生产门 |

在 `frontend/` 的完整与专项命令：

```bash
PHARMA_E2E_BASE_URL=http://127.0.0.1:13027 \
  pnpm exec playwright test --config=playwright.pharma.config.ts
PHARMA_E2E_BASE_URL=http://127.0.0.1:13027 \
  pnpm exec playwright test --config=playwright.pharma.config.ts \
  --grep 'demo layouts' --max-failures=1
```

本地截图及报告输出位于忽略目录 `.deer-flow/pharma/e2e/`。不保存登录 trace、录像、
Cookie/storageState 或未掩码认证错误截图。原始日志保留在 `/tmp` 或忽略目录，
不提交可能含环境细节的文件；三个最终后端日志权限为 0600。
十份最终构建、检查、本机及公网测试日志另已归档至私有目录
`.deer-flow/pharma/verification/20260921/`，附 `sha256.json`，避免仅依赖临时目录。

最终生产产物单次完整运行 **8 passed（24.8 秒）**：真实登录、11 个主路由及
实体详情、LIVE 缺模型提示、订阅预览/创建/暂停、三种视口布局，以及分析员研究
回放 → 独立审核 → 指定版本发布 → 站内投递/导出。该次采用 Next.js 正式构建，
不使用开发 HMR，也没有放宽引用和移动菜单 Escape 后焦点恢复的断言。
最终 18 张截图已覆盖三个视口的工作台、药物、试验、报告列表、发布报告和证据
抽屉；主机补齐 Noto CJK 后中文可正常显示，人工复查桌面与手机工作台及手机
证据抽屉。字体仅安装在验收主机，没有打包进应用。

部署切换后以 `PHARMA_E2E_BASE_URL=https://pharmascount.zimagent.top` 执行
同一套完整配置，**8 passed（27.3 秒）**。这是相同 8 个用例的第二个环境运行，
不是额外 8 个独立场景。公网使用正式 systemd 服务和同一 BUILD_ID，包含真实
DEMO 事件流、独立审核、发布和站内投递。原 `/workspace` 在未登录时仍按既有
逻辑跳转 `/login`；使用原管理员登录后到达 `/workspace/chats/new`，返回 200。
会话 Cookie 的 Secure、HttpOnly、SameSite=Lax 与
Path=/api/pharma 均实际检查，错误 CSRF 与 Origin 被拒绝。

## 5. 发布范围与未验证项

用户已明确选择“先部署项目，真实模型稍后配置”，允许继续生产构建和部署更新。
这不取消真实模型 A/B/C 三分支及稳定性验收：它们仍为 **BLOCKED**，
不能用受控模型桩、replay、官方 API 连接或截图代替。LIVE 模型缺失显式失败，
不自动回退 DEMO；当前不得标记 `V1_RELEASE_READY`。

真实 SMTP 未启用，未向真实邮箱发信；开发 SMTP 网络传输也未执行。
accepted/read/unknown 等 outbox 行为已通过替身和数据库验证，但不等于真实邮件送达。
最终生产构建、本机及公网完整浏览器门、服务切换与公网健康检查均已通过。
Gateway/Frontend 已加载功能提交 `ce98725b`，独立 PostgreSQL 与 worker 用户服务
均启用；更新前的数据库、SQLite、私有配置与旧前端产物保存在
`.deer-flow/pharma/backups/20260921T130035Z-release-ce98725b/`。
实际部署与回退步骤见 [部署交接](../../../pharma-deployment-handoff.md)。
文档包 JSON/引用/合同检查见 [CONTEXT_VALIDATION.md](CONTEXT_VALIDATION.md)，
其结果不能替代本记录的运行时或浏览器验收。
# 2026-09-22 品牌更名验证补记

用户要求停止测试、构建和部署后，未再执行此类操作。以下是收到停止指令前
工具输出已经确认的结果，不代表最终完整验收通过：

- Pharma 后端聚合：159 passed、2 deselected（含品牌兼容回归）。
- Pharma 前端及备案组件单元测试：31 passed。
- 后端 blocking-I/O：修改前 149 passed，修改后 149 passed。
- 后端全量离线：修改前已出现 DeerFlow 注册/登录失败，停止时
  1839 passed、16 failed；修改后以首个失败停止，1437 passed、1 failed。
  两次共有失败为 `test_api_login_success_no_token_in_body`（401，预期 200）。
- 后端格式化：通过，1602 files left unchanged。
- 前端完整 check：启动过，但未取得最终通过结果；不标为通过。
- 生产构建：首次因 Nextra 从错误工作目录解析而失败；调整目录后的构建
  未完成。本次没有切换正式产物。
- 新增品牌/备案浏览器回归与原业务 E2E：NOT_RUN。
- 最终版本不再重跑测试；后续如需验证，请在资源充足的环境单独执行。
