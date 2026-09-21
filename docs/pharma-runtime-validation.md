# PharmaScount 运行时适配验证

验证日期：2026-09-21。此记录区分真实 DeerFlow 图的离线兼容性探针与真实模型验收。

## 已读取与锁定的上游

当前个人仓库在集成开始时为 `c8796e41b0cc2e3132c5514035b2e015017ead89`；与 `upstream/main` 的共同提交为 `29d285731b326a728a9df33d3641f73b68bbe48b`。已读取 README、依赖清单、`deerflow/client.py`、`agents/factory.py`、模型工厂、工具装配及运行上下文说明；上述三个核心源文件与固定上游提交相比无本项目改动。锁信息和源码哈希见 `docs/reference/pharma-intelligence/delivery/upstream.lock.json`。

`DeerFlowClient` 自动装配通用工具、skills 和 middleware，构造器没有显式领域工具列表，因此本项目不修改其私有缓存。实际采用上游已经存在的 `create_deerflow_agent(model, tools, system_prompt=..., middleware=...)` 纯参数工厂。它最终使用上游同一 LangChain/LangGraph agent loop；应用没有编写第二套 ReAct 循环。

## 实现边界

- `backend/app/pharma/runtime.py` 为每次运行创建独立图与闭包上下文；workspace/user/run 来自服务端，工具参数严格按已有 JSON Schema 拒绝额外字段。
- 完整接管 middleware，并且只传入九个领域工具。不装配 sandbox、Bash、Python、任意网页抓取、MCP、文件、记忆或子 Agent 工具。
- 自定义 middleware 在上游模型调用前预留输入估计和最大输出 token，限制模型、工具、外部记录和壁钟预算。无 provider usage 时明确使用估计值；未配置单价时金额为 `null`。
- 外部资料只进入低优先级用户/工具数据，不进入系统 Prompt；事件只含工具名、证据引用与状态，不透传隐藏推理、完整模型响应或可能包含凭据的异常信息。
- 草稿先校验结构、冻结范围、来源覆盖和本次工具已发出的证据 ID，再交给业务服务验证数据库权限、快照哈希、定位、时间和数字。工具只能提交候选草稿，无法审核、发布或发信。
- 取消会取消并等待执行中的 graph/tool 任务退出。网络供应商已经接收的请求不能承诺物理撤销或零费用。
- **没有启用持久化 checkpoint 恢复**。`capabilities()` 明确返回 `checkpoint_recovery=false`，`recover()` 返回 `recovery_required`；worker 重启后需显式创建新 attempt，不能冒充无损续跑。稳定 thread ID 只是隔离键，不是授权依据。
- `ReplayRuntimeAdapter` 显式标记 `runtime_mode=replay`，也经过证据工具和草稿验证。真实模型失败绝不回落到 replay。
- 工具 Schema 和 Prompt 在 `backend/app/pharma/resources/` 随 backend 镜像部署，自动化测试与参考资料检查字节一致。

## 实际执行记录

环境：Python 3.12.3，Node 24.17.0；隔离开发环境 `.deer-flow/venv-pharma`；依赖版本见 upstream lock。

| 命令或探针 | 结果 |
| --- | --- |
| `git merge-base HEAD upstream/main` | 返回上述完整固定 SHA |
| `git diff <固定 SHA> HEAD -- .../factory.py .../client.py .../models/factory.py` | 三个核心文件没有差异 |
| `.deer-flow/venv-pharma/bin/python -m pytest backend/tests/test_pharma_runtime.py -q` | 19 passed，退出码 0 |
| `.deer-flow/venv-pharma/bin/ruff check backend/app/pharma/runtime.py backend/tests/test_pharma_runtime.py` | 通过，退出码 0 |
| `.deer-flow/venv-pharma/bin/ruff format backend/app/pharma/runtime.py backend/tests/test_pharma_runtime.py` | 完成格式化，退出码 0 |
| 真实配置 `get_app_config().models`（仅查看模型标识，不输出凭据） | `[]`；没有配置模型 |

离线测试使用脚本化 `BaseChatModel`，但真实构建并执行 DeerFlow graph，覆盖：自定义领域工具、同进程并发上下文隔离、危险工具排除、注入参数、工具结果提示注入、未发出证据、事实缺少支持、取消与任务回收、澄清终止、工具/模型/token/记录/时间预算、真实 usage 与未知金额、live 配置缺失和显式 replay。

初次命令 `backend/.venv/bin/python -m pytest ...` 因部署环境没有 pytest 失败；未计为测试通过。随后在隔离开发环境执行。第一次业务断言发现 fixture 本身带未回答问题，应为 `insufficient_evidence`，已校正断言；最终结果为上表所示。

## 用户确认的部署范围与真实模型待验项

用户已明确选择“先部署项目，真实模型稍后配置”。因此可以更新平台、来源浏览、审核发布和明确标识的 DEMO 流程，但不能将本次交付标记为真实模型质量验收完成，也不能为满足阶段门擅自配置或调用模型。

真实模型的 A（证据充分提前结束）、B（同名歧义澄清）、C（来源失败或冲突后补查并 partial）三种分支均为 **BLOCKED：未配置模型**。本轮没有真实 LLM 调用、没有真实模型输出质量评分、没有三次重复稳定性评测，也不宣称医学语义支持已经通过。配置可用模型后必须补跑并记录工具轨迹，才能考虑 `V1_RELEASE_READY`；离线图探针不替代这一门槛。

## 业务运行与 API 集成补充

后续完成 `backend/app/pharma/research.py`：服务端冻结研究对象、批准别名、来源、预算和 `min(创建时刻, 时间范围结束时刻)` 的资料截止时间；事件序号在数据库行锁内分配。每个领域工具、草稿保存与结束写回都检查 job owner token、租约和 run/job 关联，工具还重新检查当前账户及成员角色。澄清继续使用原 run 剩余总预算；显式重试创建新 attempt。

本次新联网快照的真实抓取时间若晚于冻结 cutoff，会保留为待确认实体关联的资料，明确告知需要新研究任务，不能回填观察时间绕过历史范围。业务流程为“同步来源并审核关联 → 发起研究”。历史窗口同时排除 `end_exclusive` 及之后的快照。

订阅调用读取 occurrence 冻结的别名和非交互标记；已投递事件按所有冻结渠道的游标过滤。`finalize_occurrence` 在报告写入前检查资料覆盖，确认没有可交付新版本时不创建重复报告。未批准的实体关联、未来快照、未向本次模型发出的证据均不能进入报告。

实际补充运行：

- `backend/.venv/bin/python -m pytest backend/tests/test_pharma_runtime.py backend/tests/test_pharma_research.py backend/tests/test_pharma_research_db.py backend/tests/test_pharma_api.py -q`，配置独立 `PHARMA_TEST_DATABASE_URL`：**32 passed，8.46 秒，退出码 0**（增加来源停用回归之前）。数据库测试每个模块执行真实 Alembic 迁移，使用随机独立 schema，测试结束删除该 schema，不清空部署数据库。
- 上述 32 项包括 19 个运行时探针、7 个研究边界测试、4 个实际 PostgreSQL 研究测试和 2 个真实 FastAPI 登录/完整业务旅程测试。API 测试覆盖幂等创建、回放研究、草稿修改、发起人自审拦截、旧批准失效、内容哈希校验、独立审核发布、站内投递、重复发布、读者草稿隔离、跨 workspace、失效证据、CSRF 与 SSE 重连。
- 额外增加“停用来源必须返回失败覆盖，而非成功空结果；回放也保留失败覆盖”测试；单独研究测试文件 **8 passed，退出码 0**。
- 唯一测试警告为上游 Starlette TestClient 的 httpx 弃用提示，不是测试失败。
- 检查通过：runtime/research 及上述测试文件的 `ruff check` 和 `ruff format`。

此业务 API 验证仍使用明确标识的虚构资料与 replay；没有把它记录为真实模型三分支验收。

后端阶段门补充回归：上述四个测试文件合并执行现为 **41 passed，12.24 秒，退出码 0**。新增覆盖合同 `query` 筛选、批准别名、试验 `observed_since`、研究状态筛选、排队取消立即终态、分页游标跨筛选/工作区限制及非法时间戳。测试先发现 PostgreSQL 日期筛选与合法游标返回 503，API 将时间戳及 UUID 转成对应类型后全部通过。

独立审查另发现 D5 内容回退会被错误当成 D4：旧实现按 snapshot 首次观察时间选“最新”，返回目标入组 150，实际 D5 最新 observation 指回旧快照 120。新增真实 PostgreSQL 测试先失败后修复；查询现按截止时间内的成功 observation_seq 选快照，历史 D3 返回 160。再次单独检查结束边界，复用旧快照的 D5 observation 若恰好位于 `end_exclusive`，搜索和比较工具均排除它，不能因旧内容哈希存在而泄漏未来观察。


## 前端运行与审核边界

`frontend/src/components/pharma/research-pages.tsx` 通过实际领域 API 实现研究创建、预算与时区校验、SSE 行动轨迹、取消/澄清/新尝试、版本化报告编辑、独立审核和发布。事件按 run/seq 去重，浏览器重连使用 Last-Event-ID；历史澄清事件不会关闭已恢复研究的事件流。报告只显示服务端结构化内容与证据按钮，审核请求携带当前显示的 version/hash，冲突返回保留未保存的修改。LIVE 未配置模型时明确禁用新研究；DEMO 始终显示虚构资料和回放标签。

自动化 DOM 验证与真实浏览器验收分开记录。DOM 用实际组件验证边界但模拟网络，并不替代 PostgreSQL/API/worker 联调；后者由 `frontend/tests/e2e-pharma/` 在隔离预发布栈运行，最终结果见部署交接记录。

2026-09-21 前端组件验证：`pnpm exec rstest run tests/unit/pharma/research-pages.dom.test.tsx`，**10 passed，2.60 秒，退出码 0**。覆盖事件排序/重复与异任务隔离、历史澄清回放、LIVE 缺模型禁用、时间与预算提交/重复点击锁、指定版本/哈希审核、自审与旧版本禁用、409 后保留修改、读者发布视图和证据按钮、通知的历史版本参数、作者降级后的动作隐藏。浏览器数据库联调结果由独立验收记录。


## 最终全量回归（2026-09-21）

在相同工作区完成所有医药功能后，执行与 backend `make test` 相同范围的直接 Python 命令，以避免 `uv run` 在已部署解释器上重新同步并裁剪可选运行依赖。父进程移除 `UV_PROJECT_ENVIRONMENT`、`UV_NO_SYNC`、`DEER_FLOW_CONFIG_PATH` 和 live opt-in，PATH 加入本仓库 uv 与 backend 虚拟环境；测试数据库 URL 从私有环境文件加载到子进程环境，不进入命令行或输出。

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest -m 'not live' --ignore=tests/blocking_io tests/ -v
PYTHONPATH=. .venv/bin/python -m pytest tests/blocking_io -q --tb=short
```

| 检查 | 实际结果 |
| --- | --- |
| 全量离线后端 | **18,172 passed、18 failed、190 skipped、5 deselected、32 warnings**；2614.79 秒，退出码 1 |
| 全量运行中的医药模块 | **152 passed，0 failed，0 skipped** |
| 严格阻塞 I/O | **149 passed、2 warnings**；16.76 秒，退出码 0 |
| 17 个部署配置相关失败的独立复验 | **17 passed、1 warning**；21.21 秒，退出码 0 |

17 个配置相关失败为 `test_auth_type_system.py` 的 16 个注册/登录/cookie 用例，以及 `test_initialize_admin.py::test_initialize_existing_regular_user_email_reports_email_conflict`。这些既有测试直接读取本机关闭公开注册的生产配置；单独对子进程指定 `config.example.yaml` 的临时副本后，原失败节点全部通过。未更改生产注册配置，也未修改测试断言来掩盖差异。全量测试不继承临时配置路径，避免影响其他测试的子进程隔离。

唯一仍失败的是 `test_client_langfuse_metadata.py::test_stream_abandoned_generator_cleanup_stays_inside_trace_binding`，与开发前基线相同，涉及被丢弃异步生成器的 trace binding 清理。相关 `deerflow/client.py`、agent factory 和该测试文件没有本次改动。本轮未修复无关的上游问题，不能将原有全量测试声称为全部通过。此前 59 个配置路径/uv PATH 环境失败在最终清洁环境全量运行中均未复现。

完整输出保存在忽略目录下的 `backend-final-full.log`、`backend-final-blocking.log`、`backend-final-auth-recheck.log`（均位于 `.deer-flow/pharma/`，权限 0600）；文档仅记录结果，不提交潜在包含环境细节的原始日志。全量运行期间与前端验收竞争过主机资源，实测耗时不能用作性能基准。
