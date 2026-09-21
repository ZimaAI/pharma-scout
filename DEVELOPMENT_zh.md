# Pharma Scout 二次开发指南

本项目基于 [DeerFlow](https://github.com/bytedance/deer-flow)，保留上游提交历史。
初始上游基线：`29d285731b326a728a9df33d3641f73b68bbe48b`。

## 仓库与分支

- `origin`：`https://github.com/ZimaAI/pharma-scout.git`，自己的开发成果推送到这里。
- `upstream`：可选远程 `https://github.com/bytedance/deer-flow.git`，用于获取官方更新。
- `main`：本个人项目唯一的工作分支，开发、修复、验证和发布均在此进行。

直接在 `main` 提交并推送，无需创建功能分支或走分支间 PR 合并流程。

```bash
git switch main
git pull --ff-only origin main
# 修改代码并运行相关检查
git add <本次修改的文件>
git commit -m "feat: add drug search"
git push origin main
```

自己的业务代码只推送到 `origin/main`。不要向 `upstream` 推送业务代码。

## 本地启动

本地模式需要 Node.js 22+、pnpm（项目固定为 10.26.2）、uv、Nginx；
后端要求 Python 3.12+。先运行 `make check` 确认工具是否齐全。

首次拉取后的配置流程：

```bash
# 仅在 config.yaml 不存在时运行；已有配置时此命令会退出
make config
# 当前配置脚本不会复制扩展模板，需要时补齐
test -f extensions_config.json || cp extensions_config.example.json extensions_config.json
```

本次初始化已在本机生成 `config.yaml`、`extensions_config.json`、`.env` 和
`frontend/.env`。它们均被 Git 忽略，不会随仓库推送，其他机器需要重新生成。

编辑 `config.yaml`：在 `models` 下选择并启用至少一个模型示例，填写服务地址、
模型标识和对应能力。API Key 使用环境变量引用，并在根目录 `.env` 中配置对应值。
按需要调整 `sandbox`、工具和搜索服务配置。

工具齐全且模型配置完成后，在项目根目录运行：

```bash
make install
make doctor
make dev
```

浏览器访问 `http://localhost:2026`；停止服务使用 `make stop`。
Docker 开发方式参见 [README_zh.md](README_zh.md)：配置好模型并确保 Docker 可用后，
运行 `make docker-init`、`make docker-start`。

## 从哪里修改

| 需求 | 主要入口 |
| --- | --- |
| 页面、路由、品牌界面 | `frontend/src/app/`、`frontend/src/components/` |
| 前端请求与会话逻辑 | `frontend/src/core/` |
| HTTP API、业务接口 | `backend/app/gateway/` |
| 主 Agent 的提示词、编排 | `backend/packages/harness/deerflow/agents/lead_agent/` |
| 工具能力 | `backend/packages/harness/deerflow/tools/` |
| 模型适配 | `backend/packages/harness/deerflow/models/` |
| MCP 工具配置 | 根目录 `extensions_config.json`，模板为 `extensions_config.example.json` |
| 可复用业务扩展 | `examples/deerflow-extension-example/`，根目录 `config.yaml` 的 `plugins` 配置 |
| 技能 | `skills/public/`；`skills/custom/` 默认被 Git 忽略 |

修改模块前先阅读根目录及对应目录的 `AGENTS.md`。建议将药品检索、数据源接入等
业务逻辑封装为工具、MCP 服务或独立扩展，接口与界面按需求增加；需要变更 Agent
底层行为时再修改框架代码。准备随仓库分发的技能应放在受版本控制的目录。

新增配置项时同步更新示例配置和说明，真实密钥只放在本地环境中。
保留仓库原有 `LICENSE` 和版权声明。

## 提交前验证

根据修改范围运行检查。功能或修复应增加有意义的相关测试。

```bash
# 后端修改
cd backend
make format
make lint
make test

# 前端修改（从根目录进入）
cd frontend
pnpm check
pnpm test
```

上述两个代码段中的目录命令分别从项目根目录执行；如果刚完成后端检查，
请先 `cd ..` 回到根目录，再进入 `frontend`。

## 同步官方更新

先提交本地改动并确保工作区干净，在 `main` 上合并官方更新。
首次同步前，如尚未配置 `upstream`，运行
`git remote add upstream https://github.com/bytedance/deer-flow.git`。

```bash
git switch main
git pull --ff-only origin main
git fetch upstream
git merge upstream/main
# 如有冲突：处理文件，git add <已处理文件>，然后 git commit
# 检查配置迁移和 CHANGELOG，运行相关测试
git push origin main
```

验证通过后直接推送 `main`。本地配置需要更新时，先备份再运行
`make config-upgrade` 并检查结果。保留提交历史，避免强制推送。

## 换机器继续开发

```bash
git clone https://github.com/ZimaAI/pharma-scout.git
cd pharma-scout
git remote add upstream https://github.com/bytedance/deer-flow.git
git switch main
```

随后按“本地启动”重新生成配置、安装依赖并填写模型凭据。
