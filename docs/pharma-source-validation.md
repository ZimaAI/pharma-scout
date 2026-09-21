# 官方来源适配器验证

验证日期：2026-09-21。此记录只证明当次小规模 API 访问与字段合同，不证明来源完整、临床结论或长期服务可靠性。

实现位于 `backend/app/pharma/sources.py`。`PharmaSources.search(source, query, limit=20, cursor=None)` 返回 `items`、`coverage`、`next_cursor`、`request_meta`；`fetch(source, external_id)` 返回不可变快照入库所需的来源 envelope。来源限于 `ctgov` / `pubmed`，workspace、记录 ID 和观察 ID 由可信摄入服务添加。HTTP 错误不会转换为零结果或演示资料。

## 已核对官方资料

- [ClinicalTrials.gov API 说明](https://clinicaltrials.gov/data-about-studies/learn-about-api) 与 [API 迁移说明](https://clinicaltrials.gov/data-about-studies/api-migration)：API v2 与 study JSON 结构。实际 `GET /api/v2/version` 返回 API `2.0.5`、`dataTimestamp=2026-09-18T09:00:04`；`GET /api/v2/studies/metadata` 返回 HTTP 200 / 175633 字节，核对 `protocolSection` 的字段层级。说明页引用的 `/api/oas/v2/ctg-oas-v2.yaml` 在本次环境返回 404，因此未声称已取得该 YAML 合同。
- [NLM E-utilities 参数文档](https://www.nlm.nih.gov/dataguide/eutilities/utilities.html)：使用 ESearch 与批量 EFetch 获取 PubMed 元数据、摘要；不访问全文。
- [NCBI 用量限制说明](https://support.nlm.nih.gov/kbArticle/?pn=KA-05510)：本实现采用比官方默认限制更保守的请求间隔；开发者 tool/email 和可选 API key 由服务端配置。

## 实际联网证据

以 `metformin` 检索、每源只取一条，再按返回 ID 读取单条。两个操作都经生产适配器、JSON Schema 投影校验和实际 HTTPS 调用。此次 `coverage=truncated` 是预期结果：没有将一条样本冒充完整结果。

| 来源 | 单条 ID | UTC 抓取时间 | 搜索总数 / 本次条数 | 搜索与读取哈希一致 |
| --- | --- | --- | --- | --- |
| ClinicalTrials.gov | NCT07436182 | 2026-09-21T10:34:34.952192Z | 3457 / 1 | 是 |
| PubMed | 42503322 | 2026-09-21T10:34:36.988978Z | 38093 / 1 | 是 |

CT.gov 内容 SHA-256：`2d165abb238d53de73bc72ca593f824d4c817f77d4bf347049af80c9e39284b0`，normalizer=`ctgov-v2-1`。来源更新时间为 `2026-02-27`，精度 day。

PubMed 内容 SHA-256：`8a642cf6a1da66b9b4cb37a7e0075b39f137428e36366f7ac3c0e96cc386ec45`，normalizer=`pubmed-xml-1`。来源 `DateRevised` 为 `2026-08-10`，精度 day。此时间没有当作论文发表时间或临床事件时间。

未提交完整上游响应、摘要或敏感请求信息；本机探针摘要在 gitignored `.deer-flow/pharma-source-probe.json`。检索排序与总数以后可能变化，不用于固定离线断言。

## 自动化验证

从仓库根目录执行：

```bash
PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests/test_pharma_sources.py -q
PYTHONPATH=backend DEER_FLOW_RUN_LIVE_TESTS=1 backend/.venv/bin/python -m pytest backend/tests/test_pharma_sources.py -q
backend/.venv/bin/ruff check backend/app/pharma/sources.py backend/tests/test_pharma_sources.py
```

离线：30 个测试（另两项 live 测试默认跳过）。显式联网：32 passed，退出码 0。Ruff 检查通过。初次 31 项验证后新增关键日期/干预映射测试，并重新执行全部 32 项。

覆盖日期精度、未知状态、缺失摘要、撤稿/更正关系、混合 XML 文本、内容哈希、200 候选上限、分页 token、缺失记录 partial、外部失败、超长响应、Retry-After、重定向拒绝、XML 实体拒绝、ID 不匹配、DEMO 标识禁止外发。离线 payload 全部显式 synthetic。

`TrialProjection` 额外保留 `interventions`、`start_date`、`primary_completion_date`、`completion_date`。三个日期分别来自相应 `*DateStruct`，保留来源 ESTIMATED/ACTUAL 类型与年/月/日精度；干预保留原始 arm labels，不能由此自动认定 investigational/comparator 关联。参考 OpenAPI、运行时 OpenAPI 和 source-snapshot JSON Schema 同步为可选字段，已有演示快照继续表达其实际拥有的资料。

## 运行边界

事件公开分类由 API 投影统一到 OpenAPI 枚举：内部 `status/enrollment/endpoints/results/dates` 分别输出 `status_change/enrollment_change/outcome_definition_change/results_available/date_change`，`literature/record` 输出 `other`，`correction` 保持不变。数据库分组键、唯一约束、事件 ID 与不可变 revision 均保留；两种内部组投影为同一公开分类时，不合并历史事件。旧自动生成的英文分类标题在读取时转换为中文，新事件直接生成中文标题。`results_available` 的说明采用“结果结构变化”，不推断结果积极或临床成功。

所有试验/文献投影字段根都有明确分类；文献发表日期属于日期变化，摘要变化与来源提供的更正关系分开处理。依照 FR-005 和数据模型首次观测约定，文献与试验均先建立 baseline，不伪造前一观察或 `publication_added` 变化 revision。`test_pharma_events.py` 通过真实 PostgreSQL、API 响应 JSON Schema、旧分类多对一投影和不可变记录前后比对验证此边界；无需数据迁移。

固定 HTTPS 主机，不接收用户 URL、不跟随重定向、不从环境自动读取代理；连接 10 秒、读取 30 秒、总请求预算 60 秒、最多三次尝试，响应最多 8 MiB。默认 CT.gov 每秒 1 次，PubMed 无 key 每秒 2 次、有 key 每秒 5 次；限制共享于单 Gateway 进程。多进程部署须提供共享出口限流，不能将这些值误称跨进程全局限额。

PubMed 的 book record 具有另一种 XML 结构，当前显式返回 `schema_changed`，不会丢弃记录后声称完整。不配置实际发信、外部模型或数据摄入授权。来源失败不会退回演示 fixture。
