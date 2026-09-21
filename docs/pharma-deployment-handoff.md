# PharmaScount 本机部署交接

## 当前状态（2026-09-22）

用户因本机资源不足撤销了本次更新部署要求，要求只完成编码、提交推送并停止
本项目。品牌修改尚未部署；未完成的构建、检查和浏览器验收不再继续。
Gateway、Frontend、Pharma worker、项目独立 PostgreSQL 已全部停止，相关
`13026/13027/13028/15432/18001/18003` 端口均无监听。数据库与配置保留。

用户级 `pharmascope-worker`、`pharmascope-postgres` 已 disable。
系统级 `pharmascount-gateway`、`pharmascount-frontend` 当前 inactive/dead，
但仍 enabled：当前账户没有免密 sudo，systemctl 禁用被拒绝（需要交互鉴权）。
为了避免它们在下次开机恢复，需要管理员执行：

```bash
sudo systemctl disable --now pharmascount-frontend.service pharmascount-gateway.service
```

未修改共享 Nginx 或其他项目。下文为此前部署的历史交接记录；不代表本项目
目前仍在运行。历史数据库、服务和账户标识保持原名，不因品牌更名自动迁移。

此文只记录已核查的本机环境与更新步骤。业务接口和客户端联调以根目录
`BACKEND_HANDOFF.md`、`backend/app/pharma/resources/openapi.yaml` 为准。

## 环境与入口

公网沿用 `https://pharmascount.zimagent.top`。现有 Nginx 将 `/api/*` 转发到
`127.0.0.1:18001` 的 Gateway；Pharma 通过独立 ASGI 分发器接管
`/api/pharma/*`，保留原 Gateway 的其他路由及鉴权。

| 服务 | 管理器 | 本机端口 / 命令 |
| --- | --- | --- |
| 既有 Gateway | 系统 systemd：`pharmascount-gateway` | `127.0.0.1:18001` |
| 既有 Frontend | 系统 systemd：`pharmascount-frontend` | `127.0.0.1:13026` |
| Pharma PostgreSQL 16 | 用户 systemd：`pharmascope-postgres` | `127.0.0.1:15432` |
| Pharma worker | 用户 systemd：`pharmascope-worker` | `python -m app.pharma.worker`，无监听端口 |

数据库与 worker 用户服务均已经 enabled/active，正式部署时先停止了临时
worker，再启用持久用户服务。

数据库和私有环境位于 `.deer-flow/pharma/`，目录 `0700`、环境文件
`private.env` 为 `0600`。应用角色 `pharma_app` 为非超级用户，独立拥有
`pharmascope`；集成测试使用 `pharmascope_test` 内的随机临时 schema。
请勿改动系统 PostgreSQL 5432 或本机其他项目。

## 配置与账户

领域配置加载 `.deer-flow/pharma/private.env`，主要变量如下，值不进入 Git：

- `PHARMA_DATABASE_URL`、`PHARMA_TEST_DATABASE_URL`。
- `PHARMA_DATA_MODE=live`；具体 workspace 的 `settings.data_mode` 决定其资料模式。
- `PHARMA_SESSION_SECRET`。
- `PHARMA_ALLOWED_ORIGINS=https://pharmascount.zimagent.top`。
- `PHARMA_COOKIE_SECURE=true`。

既有管理员 `admin@pharmascount.zimagent.top` 已在 Pharma 建立同口令账户，
加入“PharmaScope 演示研究组”和空白的“PharmaScope 公开研发研究组”，均为
admin。原私有凭据文件仍是 `.deer-flow/deployment/admin-credentials.json`。
这里只复用本机既有账户，没有发送邮件。

独立演示分析员、审核员、管理员的随机口令仅存
`.deer-flow/pharma/accounts.json`。审核员为 `reviewer@pharmascope.invalid`；
不得用发起人账号审核其自己的报告。账号和 workspace 标识的无口令映射记录在
`.deer-flow/pharma/deployment-accounts.json`。

浏览器必须从 Pharma `auth/me` 或登录响应取得 CSRF token，再以
`X-CSRF-Token` 发送变更操作。会话 Cookie 为 HttpOnly、Secure、SameSite=Lax，
Path 为 `/api/pharma`；页面不能依赖 `document.cookie` 读取这个路径下的 token。

## 后端命令

从仓库根目录安装已锁定依赖；不要在测试进程中保留
`UV_PROJECT_ENVIRONMENT`，扩展安装测试会继承并改动其指定的环境。

```bash
.deployment-tools/bin/uv sync --project backend --locked --all-packages --extra postgres
cd backend
.venv/bin/python -m app.pharma.cli migrate
.venv/bin/python -m app.pharma.cli seed-demo --day 3 --accounts-file ../.deer-flow/pharma/accounts.json
```

独立 API 验证服务可监听一个空闲的回环端口，不必改动公网服务：

```bash
cd backend
.venv/bin/python -m uvicorn app.pharma.main:app --host 127.0.0.1 --port 18003
```

存活与数据库检查：`/api/pharma/healthz`、`/api/pharma/readyz`。
运行时 OpenAPI：`/api/pharma/openapi.json`；交互文档：`/api/pharma/docs`。
数据库就绪不等于真实模型或来源联网验收通过。

后端验收后，启用独立 worker：

```bash
systemctl --user enable --now pharmascope-worker.service
systemctl --user status pharmascope-postgres.service pharmascope-worker.service
journalctl --user -u pharmascope-worker -n 50 --no-pager
```

## 更新与回退

原 Gateway SQLite 已用 SQLite backup API 一致性备份，领域 PostgreSQL 已用
`pg_dump -Fc --no-owner --no-acl` 备份，保存在私有目录
`.deer-flow/pharma/backups/20260921T105027Z-before-update/`，含 SHA-256 清单。
原私有配置仍保留在其原路径。完成后续重要变更后应再制作备份。

前端必须使用相同的 `DEER_FLOW_INTERNAL_GATEWAY_BASE_URL=http://127.0.0.1:18001`
构建。可以复制源文件到忽略目录 `.deer-flow/build-frontend/`，排除 `.next`
和 `node_modules`，复用已安装依赖，在隔离目录执行 `build --webpack`。先用
独立回环端口验证产物，再替换正式 `.next`，保留旧产物用于回退；不要在正在
服务的 `.next` 目录直接构建。

当前会话没有免密 sudo。通常可由运维执行
`sudo systemctl restart pharmascount-gateway pharmascount-frontend`；本次更新
也可在核对 MainPID、用户、cwd 与端口后，向本项目自有进程发送失败退出信号，
让现有 `Restart=on-failure` 策略恢复。`SIGTERM` 属于正常退出，不能依赖该
策略重启；不能使用匹配整台机器的 `pkill`。选择哪条路径，以最终交付记录的
实际执行结果为准。

每次切换后复查公网 HTTPS、Pharma 就绪探针、既有 `/health/ready`、管理员登录、
CSRF 变更请求与研究事件流；失败时恢复上一份产物，并检查本项目日志。
不要重启整个 Nginx 或影响其他站点。

本次用户明确选择先部署，后配置真实模型。当前主机未配置真实模型。
demo/replay 可用于流程验收，live workspace 应明确
报告 `RUNTIME_UNAVAILABLE`，不得回退演示结果。真实外发邮件仍保持关闭，
独立审核与站内投递不会授权向真实邮箱发送邮件。

## 真实浏览器验收与隔离预发布

`frontend/playwright.pharma.config.ts` 是专用真实后端验收配置；测试位于
`frontend/tests/e2e-pharma/`，不使用 `page.route()` 替换 API，也不自动启动或
重建生产服务。默认入口 `http://127.0.0.1:13027`，可用
`PHARMA_E2E_BASE_URL` 显式覆盖。测试读取上述本机私有账号文件；其他环境可
通过 `PHARMA_E2E_ADMIN_FILE` 和 `PHARMA_E2E_ACCOUNTS_FILE` 指定同结构文件。
缺少账号或 DEMO 工作区时明确失败，不创建默认口令，不清空数据库。

本机预发布使用三个回环端口，正式产物始终按 `18001` Gateway 构建一次：

| 端口 | 预发布角色 |
| --- | --- |
| `13027` | 临时同源代理：`/api/pharma/*` 转发 `18003`，其他请求转发 `13028` |
| `13028` | 隔离目录中的正式 Next.js 构建产物 |
| `18003` | 独立 Pharma ASGI 实例，连接既有领域数据库 |

预发布 API 的启动进程单独设置
`PHARMA_ALLOWED_ORIGINS=http://127.0.0.1:13027,http://localhost:13027` 和
`PHARMA_COOKIE_SECURE=false`，只允许回环 HTTP 验收；私有环境文件中的公网
HTTPS、Secure Cookie 配置保持启用。临时 worker 与正式 worker 使用同一
数据库领导锁，切换时先停止临时 worker，再启动用户服务，不能并行执行。

2026-09-21 已启动的临时进程及命令记录于
`.deer-flow/pharma/e2e/processes.json`，日志在同目录。停止前逐项核对 PID 的
命令、工作目录与所有者，仅向记录的本项目进程发送信号。临时代理脚本仅存
忽略目录，不参与公网路由配置。

在 `frontend/` 目录执行：

```bash
pnpm exec playwright install chromium --only-shell
PHARMA_E2E_BASE_URL=http://127.0.0.1:13027 pnpm exec playwright test --config=playwright.pharma.config.ts
```

也可在根目录执行 `make test-e2e`。安装浏览器必须与锁定的 Playwright 版本
匹配，已安装其他修订版本不能替代对应的 headless shell。

验收包含真实登录、工作区切换、十一个主页面与来源详情、分析员发起 DEMO 研究、
独立审核员批准指定版本、发布与站内投递，以及订阅预览和暂停。写操作先检查
工作区确为 DEMO，只追加可追溯
验收任务与报告，不重置现有资料。测试不开启 trace、录像、失败自动截图或未掩码
的错误页面快照，
不保存 cookies/storageState；明确执行的登录后截图掩盖账号区域，保存在
`.deer-flow/pharma/e2e/screenshots/`，覆盖 `1440×900`、`1024×768`、`390×844`
三个视口。截图仅展示虚构资料，不代替真实模型或来源联通验收。

2026-09-21 最终隔离生产产物验收完成：**8 passed，24.8 秒，退出码 0**。
测试产物位于 `.deer-flow/build-frontend/`，BUILD_ID 为
`VCCPkjbupDUif5wuKuguZ`；源文件与最终 `frontend/src` 一致。
命令为上面的 `pnpm exec playwright test --config=playwright.pharma.config.ts`，
日志为 `/tmp/pharma-browser-production-final.log`。

通过内容包括真实登录、全部主路由、缺少模型的 LIVE 工作区限制、订阅五次执行
预览与暂停/恢复、分析员发起研究及事件流、独立审核员审批指定版本、发布、
JSON/Markdown 导出与不可变哈希、站内通知打开指定版本。引用抽屉在三个视口
关闭后均恢复原引用焦点；移动菜单 Escape 恢复触发按钮焦点且导航可用。

18 张实际截图已更新至上述私有截图目录，文件名为
`dashboard-*`、`drugs-*`、`trials-*`、`reports-*`、`published-report-*`、
`evidence-drawer-*`，各覆盖三个视口。浏览器宿主安装可信发行版的 Noto CJK
字体后重新截图，中文正常；字体未打包进前端。此结果证明隔离生产产物及
真实本机后端验收通过；随后的公网切换与复验记录如下。

## 本次正式更新记录

2026-09-21 21:04（Asia/Shanghai，13:04 UTC）完成正式切换，部署的功能提交为
`ce98725b12eb73aec1e685d46dec5b8e5c1a14d9`，已先推送 `origin/main`。
正式 `frontend/.next/BUILD_ID` 为 `VCCPkjbupDUif5wuKuguZ`。

切换前的新鲜一致性备份位于
`.deer-flow/pharma/backups/20260921T130035Z-release-ce98725b/`：
`pharmascope.dump`、`deerflow.sqlite`、私有配置副本、旧前端 `frontend-next/`、
`release.json` 和 `sha256.json`。目录权限为 `0700`，配置和数据库备份为
`0600`。私有发布元数据另存 `.deer-flow/pharma/release-current.json`。

实际重启方式是核对系统服务的 MainPID、UID、cwd、可执行文件和回环监听端口
后，仅向两个已核实的主进程发送 `SIGKILL`，由现有 systemd
`Restart=on-failure` 恢复；未修改 Nginx 或其他项目。前端通过目录重命名切换
已经验证的产物，旧目录保留在备份内。本次没有触发回退。

| 服务 | 更新后 MainPID | 验收时状态 |
| --- | --- | --- |
| `pharmascount-gateway` | `1870958` | 系统服务 active/running |
| `pharmascount-frontend` | `1870957` | 系统服务 active/running |
| `pharmascope-postgres` | `1691739` | 用户服务 enabled/active |
| `pharmascope-worker` | `1871529` | 用户服务 enabled/active |

PID 仅为本次记录，后续操作必须重新核验。临时 API `18003`、代理 `13027`、
Next `13028` 和临时 worker 已按登记的所有者、cwd、命令逐项确认并停止；
这些临时端口已释放，PostgreSQL 和正式 worker 保持运行。

公网 `https://pharmascount.zimagent.top` 使用同一套真实浏览器测试复验：
**8 passed，27.3 秒，退出码 0**。日志为
`/tmp/pharma-browser-public-final.log`，并归档到
`.deer-flow/pharma/verification/20260921/pharma-browser-public-final.log`；
该目录 `sha256.json` 保留此前九份记录并加入这份公网日志。
三尺寸截图也已由公网复验刷新。DEMO 研究通过正式 worker 完成事件流、独立审核、
发布、导出和站内通知；LIVE 仍显示真实的缺模型状态，没有外发邮件。

额外 HTTPS 检查通过：`/` 跳转 `/pharma/dashboard`；原管理员通过原登录接口
访问 `/workspace`，最终到达 `/workspace/chats/new`，返回 200；原 `/health`、
`/health/ready` 与 Pharma `healthz`、`readyz` 均为 200。Pharma 会话 Cookie
包含 Secure、HttpOnly、SameSite=Lax 和 `/api/pharma` 路径；缺少必填 CSRF
头在契约层返回 422，错误 token 或 Origin 返回 403，有效退出返回 200，退出后
`auth/me` 返回 401。脱敏检查记录在 `.deer-flow/pharma/public-smoke.json`。
