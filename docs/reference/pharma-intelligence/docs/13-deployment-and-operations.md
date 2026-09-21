# 13｜部署、配置与运维手册（实现目标）

本文件定义实现者应交付的运行方式；当前文档包不含已构建的软件镜像。以下make命令必须在实施阶段创建并运行验证。

## 1. 本地拓扑
反向代理统一localhost:8080，Web内部3000，API内部8000，Postgres内部5432；dev Mailpit可仅绑定localhost:8025。除统一入口与开发邮箱面板外不暴露其他端口。
数据卷：pgdata、evidence-data、artifact-data、runtime-state。默认不挂载Docker socket，不挂载宿主家目录。V1领域研究无代码执行，不需要任意可执行沙箱。
推荐起点为8GB～16GB内存开发环境，这是本项目资源规划假设，实际构建/运行需求按测量记录；不承诺小机器性能。

## 2. 命令合同
```bash
cp .env.example .env        # 填随机会话密钥；不要直接部署example值
make setup                 # 检查锁/依赖/Docker配置
make migrate               # Alembic升级，必须可重复运行
make seed-demo             # 仅demo数据库；不得破坏live数据
make dev                   # 启动本地服务
make test                  # 不联网单元+集成
make test-e2e              # 浏览器端到端，使用demo账户
make test-live             # 显式启用，可能消耗模型额度
make verify-docs           # 合同/类型/链接/fixtures一致性
make stop
```
如果当前机器缺少依赖，输出准确缺失信息和已完成部分，不假称启动成功。demo reset要求再次确认数据库模式，命令禁止对live执行。

## 3. 配置原则
`.env.example`仅含变量名与安全默认值；真实key不提交Git。配置分APP_DATA_MODE、AGENT_RUNTIME两个维度，合法组合demo+replay、live+deerflow；开发实验组合需明确标志且不用于release。
M0锁Python/Node/数据库/上游SHA；`uv.lock`、包管理lock、容器digest进入仓库；不在容器启动时临时解析最新版依赖。
模型必须支持工具调用和所需结构化输出；不绑定某一商业模型名称/价格，配置记录model_id与上限。ToolUniverse/openFDA旗标关闭时不显示可用能力。

## 4. 启动检查
API /healthz仅存活；/readyz检查DB迁移、存储可写、配置有效；live还显示runtime/provider配置状态，但不在每次健康检查中付费调用模型。source连通测试由显式管理任务执行。
前端展示模式、来源最近成功时间和必要配置缺口。live不能因来源不可用回退到假数据。

## 5. 备份与恢复
备份数据库、证据/产物卷、必要runtime checkpoint和密钥配置版本；秘密单独加密备份。恢复到隔离环境验证引用、快照hash、报告版本和权限，不直接恢复后自动补发全部积压邮件。
恢复时delivery=unknown保留待核对；生产SMTP默认暂停。来源同步先做小范围重对账。

## 6. 升级/回滚
升级前备份并记录schema+upstream SHA；先在demo/暂存环境迁移；不兼容变更使用expand-contract。不可逆迁移不承诺自动downgrade；回滚按备份和兼容代码计划执行。
normalizer和Prompt升级独立版本，旧报告继续指向旧证据。版本升级引起的重算不能假装源数据新增。

## 7. 监控告警
来源连续失败、队列积压、过期lease、研究超预算、硬证据校验失败、投递unknown、磁盘不足和数据库不可用。告警只含脱敏ID，不复制研究全文。
日志保留按05约定，清理不能删已发布报告唯一证据；artifact引用计数/保留标记在清理前校验。

## 8. 首版生产外部署限制
默认交付本地/受控开发环境，不自动创建云资源、公网域名或给真实用户发信。真实上线需补HTTPS、备份演练、秘密管理、用户运维、来源条款、模型数据处理政策及人工审核责任。
