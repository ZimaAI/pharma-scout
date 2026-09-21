# 02｜领域词典、对象关系与业务不变量

## 1. 领域对象
| 对象 | 定义与边界 |
|---|---|
| Drug | 内部研究对象；名称与研发代号不等于已获批准药品 |
| DrugAlias | 带来源与审核状态的别名；同一文字允许关联多个候选药物，不全局强行唯一 |
| Trial | 一条试验注册记录；以来源+外部ID识别，关联药物可多对多 |
| Publication | 文献元数据/摘要；PMID、DOI是不同命名空间的标识 |
| SourceRecord | 外部逻辑记录；来源和external_id形成稳定身份 |
| SourceSnapshot | 该记录某次内容版本；不可修改原文/哈希/规范化内容 |
| SourceObservation | 一次抓取观察，包括未改变、失败、404等；不等于新版本 |
| Evidence | 从具体快照定位出的可核对片段或结构化字段 |
| IntelligenceEvent | 围绕同一对象及事件类型的持续事件，例如某试验招募状态变化 |
| EventRevision | 一次有意义变化；包含前后值、观察时间、来源更新日期与支持证据 |
| Claim | 研究结论；必须有适用范围、证据关系与核验状态 |
| ReportVersion | 不可变报告内容；草稿编辑产生新版本 |
| Review | 对一个版本及其哈希的决策；不是对报告永远有效的许可 |
| Subscription | 一个用户关注的对象、资料范围、排程与交付配置 |
| Delivery | 一个确定版本向一个确定用户/渠道的逻辑投递 |

## 2. 时间与日期精度
平台时间统一UTC存 `timestamptz`；UI按用户IANA时区显示。来源日期使用对象：
```json
{"value":"2026-08","precision":"month","kind":"source_reported"}
```
value为空时precision必须unknown；day格式YYYY-MM-DD、month格式YYYY-MM、year格式YYYY。不确定哪一天，不补成月1日；source_updated不是trial实际完成日期；fetched_at不是事件发生时间。
关键时间：`source_updated_at`（原始来源报告）、`observed_at`（系统首次观察）、`published_at`（本平台发布）、`knowledge_cutoff`（本次研究资料截止）、`effective_at`（确有依据时才赋值）。

## 3. 药物对齐规则
外部稳定ID且命名空间一致可作为强候选；批准别名+明确试验intervention线索可用于召回。仅标题相似/模型自信不自动合并；盐型、复方、制剂、不同发行名称不能无依据等同。
临床试验关联有 `investigational/comparator/background/unspecified`，不能因为某药是对照组就认定其正在开展对应新适应证研发。
V1提供候选确认/驳回，不做自动永久合并；人工错误关联以撤销关系+审计修正，原快照不改。

## 4. 试验业务解释
状态集合由外部适配器映射为内部 `NOT_YET_RECRUITING/RECRUITING/ENROLLING_BY_INVITATION/ACTIVE_NOT_RECRUITING/SUSPENDED/TERMINATED/COMPLETED/WITHDRAWN/UNKNOWN/OTHER`，保留raw值。
不能假设状态只向前推进；重新招募是合法变化；未知不转换为完成。phase保留数组/原文，不强制为单个整数。观察性研究等情况可无phase。
`has_results` 表示来源是否出现结果结构，不等于结果积极；没有结果不能改写为无效。注册记录出现不代表批准或已经验证安全性。
研究阶段按试验/适应证/辖区记录；V1药物页不显示一个缺依据的统一“已上市”标签。

## 5. 证据与结论
证据定位必须是快照内JSON Pointer，或规范化文本上的[start,end)码点偏移。保存提取器版本、片段sha256、原始语言、translation_text(可空)。翻译不是新的独立证据。
关系：supports / contradicts / context。`verification_status` 为 unverified/supported/conflicted/insufficient，另有 numeric_check 等确定性检查结果；不把模型语义判断当数学证明。
核心事实句必须引用至少一条证据；无依据的解释只允许作为明确假设或资料缺口，不可进入“已确认事实”。

## 6. 版本规则
S1→S2产生新快照；反复观察S2仍只有一个S2快照，多条observation；之后回退S1内容时复用原内容快照，但产生新的observation，并以“前次观察内容→当前观察内容”生成回退事件。不能只按content_hash全局去重而漏掉回退。
事件fingerprint=`source_record_id + change_category`；revision identity=`event_id + before_observation_id + after_observation_id`，区别反复发生的状态变化。
报告由不可变版本组成；published指针可指向新批准版本，旧版本永久可见（若合法保留），不被静默修改。证据撤回/更正时给旧报告加独立更正提示，不重写旧文。

## 7. 隔离与可见性
V1所有资料及业务对象按workspace落库，即使资料公开也不跨workspace复用用户搜索/历史。每条外键的workspace必须相同。
公开资料页workspace内共享；run、草稿仅创建者和reviewer/admin可见；已发布报告workspace成员可见；订阅和收件箱仅本人及具备明确运维权限的管理员。

## 8. 不变量
INV-01：没有来源不能成为受支持事实。INV-02：快照和报告版本不可变。
INV-03：身份与权限不来自模型。INV-04：外部失败不等于零结果。
INV-05：研究成功不等于来源完整。INV-06：人工批准只作用于批准哈希。
INV-07：模型不直接发信/改订阅。INV-08：发布与投递重试不得重跑研究。
INV-09：demo与live不混用，真实来源ID不从假数据构造。INV-10：每次任务记录模型/工具/Prompt/数据版本。
