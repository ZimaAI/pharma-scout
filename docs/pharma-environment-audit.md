# PharmaScope 环境与部署审计

核查日期：2026-09-21。实施前代码提交为
`c8796e41b0cc2e3132c5514035b2e015017ead89`；本地 `main` 与当时的
`origin/main` 一致。业务变更只提交和推送至 `origin/main`。

## 既有公网服务

- 公网入口：`https://pharmascount.zimagent.top`，由主机 Nginx 提供 HTTPS。
- `pharmascount-gateway.service`：系统级 systemd 服务，运行用户 `zima`，
  本仓库 `backend/.venv/bin/python`，监听 `127.0.0.1:18001`。
- `pharmascount-frontend.service`：系统级 systemd 服务，运行用户 `zima`，
  Next.js production，监听 `127.0.0.1:13026`。
- Nginx 已将 `/api/*` 交给 Gateway，其他页面交给 Frontend；SSE 缓冲已关闭。
  因而新增 `/api/pharma/v1/*` 可沿用现有路由，无需新开公网端口。
- 初查 Gateway `/health` 与公网首页均返回 HTTP 200。
- 两个服务使用 `Restart=on-failure`；服务文件和 Nginx 配置均归 root 所有。
  当前会话 `sudo -n` 返回“需要密码”，不能假称具备管理系统服务的权限。
- 现有数据库为本仓库 `.deer-flow/data/deerflow.db`，原管理员和登录配置保留。

本机还有其他项目，不能用全机 `pkill`、停止 Nginx 或改动其他项目数据库来更新本项目。

## 隔离的领域数据库

系统 PostgreSQL 16 已供本机使用，当前用户没有可用的 peer 登录角色。
没有尝试修改该集群权限或读取其他项目的凭据。利用已安装的 PostgreSQL 16
程序建立本项目独立集群：

- 数据目录：`.deer-flow/pharma/postgres`；父目录权限 `0700`。
- 只监听 `127.0.0.1:15432`；Unix socket 也在该私有父目录中。
- 用户服务：`pharmascope-postgres.service`，已启用；用户 systemd 的 linger 已开启。
- 应用角色 `pharma_app` 不具备 superuser 权限；拥有业务数据库
  `pharmascope` 和独立测试数据库 `pharmascope_test`。
- TCP 采用 SCRAM 口令认证；应用随机口令只在
  `.deer-flow/pharma/private.env` 中，文件权限 `0600`，被 Git 忽略。
- 私有配置包含 `PHARMA_DATABASE_URL`、`PHARMA_TEST_DATABASE_URL`、
  `PHARMA_DATA_MODE=live`、`PHARMA_SESSION_SECRET`，本文不记录值。
- 数据库初始化后 `pg_isready -h 127.0.0.1 -p 15432` 通过。

演示 workspace 必须显著显示 demo/replay，使用独立随机账户；不得向公网提供
文档中的默认演示口令。官方来源失败也不能静默切换到演示资料。

## 依赖与验证环境

- Python `3.12.3`、Node.js `24.17.0`、pnpm `10.26.2`。
- 既有 uv 在 `.deployment-tools/bin/uv`，版本 `0.12.17`，默认 PATH 没有它。
- 生产 `backend/.venv` 初查未安装 pytest、ruff 和 PostgreSQL 驱动。
  为避免改变运行中的服务依赖，新建 `.deer-flow/venv-pharma`，按既有锁文件执行
  `uv sync --frozen --all-packages --extra postgres`，退出码 0。
- 后续同步及测试设置
  `UV_PROJECT_ENVIRONMENT=/home/zima/Develop/Projects/pharma-scount/.deer-flow/venv-pharma`。
  最初运行基线测试时还设置 `UV_NO_SYNC=1`。随后发现扩展安装测试会继承
  `UV_PROJECT_ENVIRONMENT`，把测试扩展安装到该隔离环境并移除其他依赖，因此
  该次全量运行已中断，不能作为代码回归结果。后续测试不继承这两个变量，直接
  使用已同步完整依赖的 `backend/.venv/bin/python -m pytest`。
- Playwright 测试包及 Chromium `1223` 已安装；可用现有
  `PLAYWRIGHT_BASE_URL` / `PLAYWRIGHT_SKIP_WEB_SERVER` 指向验证服务。
- 主机内存约 8 GiB，初查剩余可用约 3.5 GiB，没有 swap。前端构建需控制内存，
  不可直接覆盖仍在运行的 `.next` 目录；应在隔离构建目录完成后切换。

## 实施前测试

第一次直接执行两个 backend make 目标均因 `uv: not found` 退出 2；这是环境
PATH 问题，不是测试失败结论。修正工具路径并使用隔离环境后：

| 命令 | 结果 | 日志 |
| --- | --- | --- |
| `make test-blocking-io` | 149 passed，18.47 秒，退出码 0 | `/tmp/pharma-baseline-blocking.log` |
| `make test` 首次收集 | 并行新增的 Pharma TDD 测试尚无实现，2 个 import 错误 | `/tmp/pharma-baseline-tests.log` |
| 仅既有测试，继承隔离环境变量 | 扩展测试改变依赖环境，已中断；不是可靠回归基线 | `/tmp/pharma-baseline-existing-tests.log` |
| 仅既有测试，直接 Python 与模板配置 | 17,977 passed、190 skipped、61 failed、3 deselected，862.44 秒，退出码 1 | `/tmp/pharma-baseline-clean-tests.log` |
| Pharma PostgreSQL 与认证集成 | 41 passed，5.14 秒，退出码 0 | `/tmp/pharma-persistence-tests.log` |
| 既有环境敏感文件复验 | 273 passed、2 skipped、1 failed，56.95 秒 | `/tmp/pharma-baseline-sensitive-recheck.log` |
| 扩展依赖同步复验 | 23 passed，2.98 秒 | `/tmp/pharma-baseline-extension-sync-recheck.log` |
| Agent 指引清单补录后复验 | 13 passed，1.80 秒 | `/tmp/pharma-guidance-tests.log` |

清洁基线使用 `/tmp/pharma-baseline-config.yaml`（复制自 `config.example.yaml`），
避免从公网部署配置继承“禁止公开注册”，后者会让既有注册测试预期的 201 变成
403。单项复验已确认模板配置下该测试通过。

全量运行的 61 个失败中，59 个是子进程继承临时配置路径或未取得 uv PATH 的
环境问题；取消该变量并补齐工具 PATH 后，对应配置迁移、部署、扩展安装、
扩展依赖同步及 sandbox 文件全部通过。另一个失败是既有指引清单遗漏已提交的
`docs/reference/pharma-intelligence/AGENTS.md`，已补录并验证。
最后一个可复现的既有问题是
`test_client_langfuse_metadata.py::test_stream_abandoned_generator_cleanup_stays_inside_trace_binding`：
被提前丢弃的异步生成器清理时 trace binding 为 `None`。相关 harness 源文件未在
本次领域开发中修改；这里如实记录失败，不声称原有全量测试全绿。

全量评估命令（从 `backend/` 执行）：

```bash
env -u UV_PROJECT_ENVIRONMENT -u UV_NO_SYNC \
  DEER_FLOW_CONFIG_PATH=/tmp/pharma-baseline-config.yaml PYTHONPATH=. \
  .venv/bin/python -m pytest -m 'not live' --ignore=tests/blocking_io \
  '--ignore-glob=tests/test_pharma*.py' tests/ -v
```

环境敏感文件复验使用同一个解释器，取消 `DEER_FLOW_CONFIG_PATH`，在 PATH 前加入
本仓库 `.deployment-tools/bin` 和 `backend/.venv/bin`。这样子进程测试可选择自己的
临时配置，而不读取本机部署配置或全量评估的模板配置。

Pharma 集成测试在显式 `PHARMA_TEST_DATABASE_URL` 中新建随机临时 schema，
迁移两次、每条用例回滚、结束仅删除本次 schema，未清空业务或共享测试数据。
覆盖 D1—D5、两工作区、复合外键、版本和审核不可变、证据篡改/未来日期、会话
撤销、服务端角色、CSRF/Origin 及安全 Cookie。没有数据库变量时会明确跳过，
不能把跳过算作通过。

## 更新程序与验收限制

后端、数据库迁移、worker 和全链路验证先完成，再进行前端业务开发。后端领域
应用通过 Gateway 最外层 ASGI 分发器承接精确 `/api/pharma/` 命名空间，自行验证
会话和 CSRF；其余 Gateway 路径继续使用原鉴权链。业务 API 也应可独立启动。

发布前备份 PostgreSQL、SQLite（使用 SQLite backup API）和私有配置；配置备份
保持私有权限。前端在隔离目录构建，验证成功后切换；只更新本项目进程。
系统服务若通过用户持有的进程信号触发恢复，须仅作用于核对过 executable、
cwd 和监听端口的本项目 PID；`SIGTERM` 是正常退出，不能依赖
`Restart=on-failure` 自动恢复。部署时必须记录实际采取的更新方式和健康探测。

初查 `config.yaml` 未配置任何模型，因此真实 DeerFlow 研究分支尚不能验收；
没有模型配置时只可报告离线闭环及真实来源适配器的实测结果。SMTP 默认不对真实
收件人发送；缺少模型或 live 验收不能标记为 `V1_RELEASE_READY`。

验收需区分 replay、官方 API、模型 live、数据库约束、浏览器三视口和投递状态；
原型图仅用于版式参考，真实药物名称、疗效比例与批准日期不能继承为产品事实。

## 浏览器预发布准备

前端锁定 Playwright 1.59.1，对应 Chromium 修订 `1217`；原缓存中的 `1223`
不能直接作为该锁定版本的默认浏览器。已从 Playwright 官方 CDN 下载匹配的
headless shell，并真实启动验证浏览器版本 `147.0.7727.15`。

独立配置 `frontend/playwright.pharma.config.ts` 可发现 8 条真实后端测试，
配置和测试文件通过 ESLint。临时回环 API、worker 与同源代理已经启动；
四种已配置账户均通过真实登录、工作区配置读取、CSRF 退出验证。
预发布 `/api/pharma/readyz` 为 200；公网主页和旧 `/health` 保持 200，旧 Gateway
尚未重启，因此公网 Pharma 路由仍返回旧鉴权的 401。这些是准备状态，不代表
业务浏览器测试已通过。

后续最终生产产物真实浏览器验收已完成：2026-09-21，**8 passed，24.8 秒，
退出码 0**；日志 `/tmp/pharma-browser-production-final.log`。产物 BUILD_ID 为
`VCCPkjbupDUif5wuKuguZ`，从 `.deer-flow/build-frontend/` 在回环 `13028` 运行。
测试覆盖实际登录、11 个主页面及来源详情、LIVE 缺模型状态、订阅预览和
暂停/恢复、分析员研究与事件流、独立审核、发布、导出和站内投递。引用抽屉及
移动菜单的焦点恢复断言全部通过，三视口无水平溢出。

18 张最终中文截图在 `.deer-flow/pharma/e2e/screenshots/`，均掩码账号区域；
宿主 Noto CJK 字体来自可信发行版软件包，没有加入前端资产。未记录浏览器
Cookie、storageState、trace 或视频。本轮只追加 DEMO 验收资料，未重置数据库。
用户明确选择先部署、后配置模型；该验收不能视为模型 LIVE 验收或
`V1_RELEASE_READY`。此时正式服务仍未切换；实际更新及回退记录见
`docs/pharma-deployment-handoff.md`。
