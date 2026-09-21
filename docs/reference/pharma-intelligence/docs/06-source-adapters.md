# 06｜外部数据源与增量摄入

## 1. 统一接口（本项目定义）
`search(query: SourceQuery, cursor: str|None) -> SourcePage`
`fetch(external_id: str) -> SourceEnvelope`
`health() -> SourceHealth`
返回source、external_id、raw_payload、normalized、source_updated、fetched_at、coverage、next_cursor、request_meta。错误用结构化code区分timeout/rate_limited/auth/schema_changed/not_found/unavailable。
所有网络访问走服务端适配器。模型只能选择查询意图/源标识，不直接提供URL、Cookie、API Key或SQL。

## 2. ClinicalTrials.gov：V1必需
官方提供API v2入口。[S06] 本次文档调研未成功读取实时schema/具体study样本，以下是目标映射，实施者必须在M0/M2读取当时官方schema并进行真实响应contract测试，遇到字段变动修改版本化适配器，而不是硬造响应。

| 内部字段 | 预期v2路径/来源 |
|---|---|
| external_id | protocolSection.identificationModule.nctId |
| title | protocolSection.identificationModule.briefTitle |
| status/raw_status | protocolSection.statusModule.overallStatus |
| source_updated | protocolSection.statusModule.lastUpdatePostDateStruct.date |
| conditions | protocolSection.conditionsModule.conditions |
| phases | protocolSection.designModule.phases |
| enrollment/count,type | protocolSection.designModule.enrollmentInfo |
| interventions | protocolSection.armsInterventionsModule.interventions |
| sponsor | protocolSection.sponsorCollaboratorsModule.leadSponsor |
| primary_outcomes | protocolSection.outcomesModule.primaryOutcomes |
| has_results | 顶层hasResults；不能仅凭该布尔推导疗效 |

目标HTTP路径是`/api/v2/studies`和`/api/v2/studies/{NCT_ID}`；使用官方分页token按次序遍历，不能猜page编号。NCT校验`^NCT[0-9]{8}$`，DEMO模式另走fixture适配器不发送请求。
第一轮按批准别名召回，再人工确认record-drug关系；后续定时重抓已关联ID，另做有限窗口发现。V1不依赖未经核实的“变更Webhook”或免费历史全量API。
本平台版本历史从首次采集开始；上游历史不能自动等同本平台历史。设小于外部允许上限的保守全局速率，默认1请求/秒（项目预算，不是官方配额）。429按Retry-After及抖动退避。

## 3. PubMed：V1必需
NCBI E-utilities提供PubMed检索与记录读取；V1用ESearch取ID，再用EFetch/ESummary批量读取元数据与可获得摘要，不抓取未授权全文。[S07]
目标base=`https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`；`esearch.fcgi?db=pubmed` 与 `efetch.fcgi?db=pubmed`，具体可用参数在集成测试确认。tool/email配置使用开发者联系方式，不把终端用户邮箱发给上游。
V1工作量限制每次最多200候选，超过标truncated并要求缩小主题/日期；不得把截断结果声称全集。定期重抓已跟踪PMID以识别更正，不能只用发表日期过滤而遗漏旧文章更新。
PMID、DOI、PMCID分开保存；参考链接由已验证标识构建。文献日期保留精度，摘要缺失不当作空结论；retraction/correction关系只有来源明确提供时记录。
NCBI标准用量为无key每秒不超过3次、有key默认10次；本项目默认无key每秒2次、有key每秒5次，仍需考虑相同出口IP/相同key的其他使用方并遵守当时规则。[S08]

## 4. openFDA标签：V1.1
默认disabled，界面不承诺可用。后续按SPL set_id/id/version映射并核对实际字段，不把标签出现自动解释为FDA批准。官方说明标签信息可能并非当前流通产品标签或完全等同批准标签，不应用于医疗决策。[S09]
未来live启用要求显式配置API key并验证配额，尽管文档同时列出无key额度，不在本项目假定无key永久可用。[S10]
不良事件分析不进入首版；不能用报告数量推断发生率或因果关系。[S11]

## 5. 摄入算法
1. 创建带截止时间、批准别名版本、来源、页数上限的sync job。
2. 分页读取；每页结果先持久化/校验，再保存next_cursor；失败保持上一个已提交cursor。
3. 对每条记录规范化并计算hash；锁source_record，取得上次成功observation。
4. 复用已有内容snapshot或创建新snapshot；始终写新的observation。
5. 比较前次成功观察与本次内容；变化写事件revision和结构化证据；仅更新日期无业务变化不写重要事件。
6. 所有分页成功才推进该发现查询的完整水位；partial和truncated保持覆盖警告。重叠窗口用于发现迟到资料，窗口是可配置启发式，不保证捕捉无限迟到记录。
7. 定期重抓已跟踪ID与执行重对账，避免仅依赖更新时间水位。

## 6. 规范化与差异
去除传输meta/抓取时刻；字段排序确定化；集合语义数组可排序，顺序有业务意义的字段不能排序。原始payload原样保留，normalized带版本。
忽略纯空白/大小写只适用于明确定义字段；名称/单位/终点文本不做过度清洗。删除字段、null、空数组和“未提供”区分；从estimated到actual即使数字不变也属于变化。
抽取器升级先影子重算，不能把normalizer变化全部推成研究新事件。回填记录不删除历史观察；在事件中注明修复来源。

## 7. 超时与重试默认值（项目设定）
连接10秒、单请求读取30秒、总外部请求60秒；最多3次尝试；尊重Retry-After并添加抖动；429和临时5xx可重试，非法参数/结构变化不盲重试。请求/响应体大小和页数受限。
缓存TTL针对一次查询结果而非immutable snapshot；缓存命中仍记录cache_hit和原fetched_at，不能显示成刚从来源更新。来源故障时可用旧证据，但明确stale和时间。

## 8. 授权与版权
API可访问不代表所有内容可任意再分发；保存metadata和任务所需短片段，全文摄入需许可证依据。报告引用保留来源，下载受workspace权限；不绕过验证码/付费墙。数据使用条款的最终上线检查由部署方承担并记录。[S12]
