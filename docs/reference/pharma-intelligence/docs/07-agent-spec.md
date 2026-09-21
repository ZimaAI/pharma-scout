# 07｜Agent设计、工具合同与研究策略

## 1. 职责分工
DeerFlow负责真实模型工具循环；本项目负责领域上下文、工具、证据、业务状态与安全。模型可选择下一步，但不直接授权、确认药物映射、发布、发邮件或修改真实来源。
任务开始固定workspace、发起人、药物ID及别名版本、时间范围、来源白名单、模型/Prompt版本、预算和已知资料。用户偏好是订阅配置，不把全部论文事实塞进长期记忆。

## 2. 内部ResearchState
包含 run_id、scope、question、subquestions[]、evidence_ids[]、claim_candidates[]、coverage、unresolved[]、performed_queries[]、budget_reserved/spent、stop_reason。大型正文留在snapshot，状态只保留引用和少量摘要。
每个subquestion有id、问题、status(open/resolved/conflicted/insufficient)、required_evidence、depends_on。计划是模型提议，服务端校验深度与任务数量，避免循环依赖。

## 3. V1工具集（均为项目新增领域工具）
| 工具 | 参数 | 返回 | 权限/边界 |
|---|---|---|---|
| resolve_drug | text, limit | approved candidates + ambiguous | 不允许自行确认映射 |
| search_trials | drug_id, filters, limit | record_refs, coverage, cursor | 仅已批准别名/官方适配器 |
| search_publications | drug_id, terms, date_range, limit | record_refs, coverage | 检索文本长度/来源限制 |
| read_source_snapshot | snapshot_id, sections | excerpt/evidence refs | 先验证workspace与快照 |
| compare_trial_observations | trial_id, before_id, after_id | typed changes + evidence | 不仅按日期找“最新” |
| search_workspace_evidence | query, drug_ids, cutoff, limit | evidence matches | 强制scope过滤 |
| inspect_evidence | evidence_ids | 原始片段/定位/版本 | 上限10条/次 |
| request_clarification | question, options | 暂停卡片或background缺口 | 不获取治疗资料 |
| submit_research_draft | structured_report | draft_candidate_id, checks | 仅草稿候选，不发布/发信 |

所有工具返回 `ok/data/error/coverage/provenance` 统一结构；empty是正常ok且items为空，失败必须ok=false。返回的事实不得只有一段不可追踪自然语言。
工具参数不含workspace_id/user_id/recipient/凭据；这些从RuntimeContext注入。即使模型强行加参数也拒绝，不采用字段忽略策略掩盖越权。

## 4. Agent循环与停止
可执行序列示例，不是硬编码顺序：解析对象→查试验→发现状态变化→读取前后快照→检索关联文献→发现摘要不足→补查明确来源→提交草稿。
已有充足证据时不强制再次联网；遇到冲突时改变查询方向；连续3次调用无新增有效证据可建议停止。程序强制预算/深度停止，模型可以更早完成。
停止原因：answered、no_verified_change、insufficient_evidence、source_unavailable、budget_exhausted、user_cancelled、runtime_error。no_verified_change必须附来源覆盖，不能等同普遍无进展。

## 5. 预算（本项目默认值，可配置）
单run工具调用最多30次、模型调用最多12次、外部记录最多200、全流程壁钟上限10分钟；单模型输出上限依据提供商和配置；可选子Agent最多2个，总预算共享。
模型调用前预留输入估计+max_output；调用后按provider usage结算。provider未返回usage时保存estimated且不要记为0。货币成本只有配置币种一致及有效单价时计算，否则null。
并行任务在DB事务中预留，原子限制总预算；不可每个子Agent复制完整预算。达到阈值后生成partial并列未完成问题。

## 6. 结构化草稿与校验
见 `contracts/research-output.schema.json`。最重要字段：scope、coverage、sections、claims、evidence_ids、limitations。模型只引用系统发给它的证据ID。
硬校验：JSON结构、最大长度、已授权ID、locator能定位、snapshot hash、明确数值能从证据提取并按单位重算、期望研究范围与输出范围一致。
语义核验：是否超出摘要、把相关性当因果、把招募变更当疗效、把间接比较写成优越性。模型核验只作建议；最终人工审核。无证据的关键结论不可进入发布路径。
数值不是都可自动判真。数字无法确定性关联时标manual_check_required；不能把“解析不到”当通过。

## 7. 报告与原文隔离
原文包裹为untrusted_source，模型输出结构只允许引用证据，不允许内嵌script、任意HTML或调用链接作为执行指令。来源里的“忽略限制”等视为文本。输出Markdown由白名单渲染器清洗。
流式UI不显示隐藏思维链或原始debug。展示“正在读取试验记录”“发现目标入组数变更”等行动摘要，以及实际工具调用结果。

## 8. 子Agent策略
首版允许一个主研究Agent；有独立问题时再拆两个子任务，例如“试验记录变化”和“相关文献新增”。每个子任务交付结构化证据包，不是冗长作文。
子任务复用run scope并限定工具子集；上游支持的子Agent机制不算独立研发成果。应通过单Agent与有限并行的固定集对比后决定是否默认开启。

## 9. 工具发现与MCP
V1直接注册少量上述领域工具，不将ToolUniverse全量工具schema塞进上下文。V1.1按能力组加载经过审核工具；MCP配置仅管理员部署时配置。来源工具执行仍经网关与来源策略。[S04][S05]

## 10. 回放与live契约
ReplayRuntimeAdapter按fixture脚本输出DomainRunEvent，不调用模型，必须runtime_mode=replay。DeerFlowRuntimeAdapter使用同一接口但调用真实模型。
验收至少三种live路线：证据足够提前结束、同名歧义请求澄清、来源失败/冲突后补查并返回partial。不能只验证一个固定happy path。

## 11. 已覆盖事件与游标
提交结构中event_revision_ids仅包含本报告实际呈现且有证据的已知事件版本；查到但未能研究的事件不得列入。服务端验证列表和结论，不根据模型自报直接推进订阅游标；只有发布并相应渠道accepted后更新。
