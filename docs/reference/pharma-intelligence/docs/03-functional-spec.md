# 03｜功能规格（SRS）

关键词 MUST 表示V1验收必需，SHOULD表示有理由可延期；所有状态保存于后端。UI隐藏按钮不能替代鉴权。

## 1. FR-001 会话与成员
登录输入email/password，服务端校验后写HttpOnly会话Cookie；CSRF token独立返回并对变更操作校验。Cookie在HTTPS下Secure、SameSite=Lax；demo仅localhost允许HTTP。连续失败限制按账号+IP，错误不泄漏账号是否存在。
登出撤销会话。变更成员角色/禁用账户后下一次请求失效，长SSE连接定期重验。workspace切换通过URL中的workspace_id并校验membership；禁止仅信任前端传来的角色。
管理员可列成员、修改角色/禁用；不能删除最后一名admin。V1账号开通采用CLI初始化/创建，邮件邀请与找回密码留后续。

## 2. FR-002 药物和映射
建档字段：display_name、development_code可空、description可空、indications[]、targets[]；后两者是研究标签，不自动代表已批准适应证或机制证实。
编辑用If-Match避免覆盖他人修改。别名候选含namespace、alias、drug_id、evidence_id或人工说明、proposed_by。允许同名不同对象，列表展示歧义。确认/驳回必须填写理由；确认不自动合并药物。
药物关联试验和文献必须可查看来源依据；reader只读；archive只停止后续自动跟踪，不删除历史引用。

## 3. FR-003 试验和文献
列表支持对象、状态、来源更新时间/观察时间、是否有结果、关联状态等过滤；选择的时间字段必须在UI清楚显示。缺失值用“来源未提供”，不能填0或推断。
试验详情展示外部标识、标题、干预/对照关联、phase、招募状态、条件、申办者、入组数量及actual/estimated、主要终点描述、日期精度、当前来源快照。
文献详情展示标题、作者、期刊、DOI/PMID、文献类型、原始摘要、关联药物、撤稿/更正关系（来源提供时）。全文不可用显示“仅元数据/摘要”，不自动抓取付费全文。

## 4. FR-004 同步与来源健康
来源同步为异步job；提交返回202和job_id。参数仅允许药物ID、已批准别名、已知外部ID、时间窗与上限，不接受任意URL。
每条外部请求记录结果、尝试次数、响应码、用量、耗时、批次和cursor。job状态与单来源覆盖分开；部分来源失败可保存已成功的结果，界面标partial。总条数未知则为null，不编造100%进度。
手动重试同Idempotency-Key复用任务，参数变更返回409。超出页数上限标truncated，不能“同步完成=完整覆盖”。数据源状态页仅显示密钥是否配置，不返回秘密。

## 5. FR-005 快照、差异与事件
以来源+external_id识别逻辑记录。规范化失败仍保留受限原始响应与解析错误，不覆盖当前有效读模型。
首次抓取标baseline；有意义字段变化生成revision；抓取日期、JSON字段顺序、无意义空白变化不生成业务事件。实际业务字段缺失与空字符串区别保留，字段消失生成removed而不默认0。
试验状态、入组目标、关键日期、终点描述、结果出现分别独立分类。禁止把一次变化自动解释成有效性结果。列表显示event_type和“来源声称的时间/系统发现时间”。
事件详情默认按observed_at排序；可切换有据的事件日期，未知日期单列。回退内容、撤回、更正均保持原观察链。

## 6. FR-006/007 研究任务
请求包含question(10～4000字符)、drug_ids(1～5)、time_range、source_allowlist、budget、optional parent_run_id。parent引用必须可访问；追问创建新run并引用前次报告，不修改旧run。
输入检查：病例、剂量、个体治疗建议等转成范围提示，拒绝对应个体决策任务；保留“研究公开资料”的可用入口。
研究流程非固定顺序：模型可选择发现资料、读取快照、对比、补查或结束。统一工具网关验证预算/权限。研究状态明确queued/running/awaiting_input/verifying/completed/partial/failed/cancelling/cancelled/recovery_required。
澄清只针对实体歧义、时间或范围缺失；后台订阅不能等待无限交互，转partial并通知订阅所有者。预算不足交partial，说明未完成问题。
取消是异步请求：先cancelling，worker协作停止并在不可停止的外部读请求完成后丢弃结果，最终cancelled；界面不即时谎报已终止外部请求。

## 7. FR-008 证据与报告生成
工具返回evidence_id/snapshot_id及受控片段；模型生成structured report，服务器核验引用存在、workspace、版本、定位和数字。只有通过结构/引用硬校验才生成可送审版本。
语义核验结果单独展示：supported、conflicted、insufficient、unverified。自动supported表示已过配置的核验过程，不是医学事实认证；需要人工审核发布。
冲突内容可以放入“争议与限制”节，经审核发布，但不得同时以确定事实呈现。无来源关键疗效/批准结论不得通过人工忽略直接发布；需要补证据或删除该结论。
报告结构：范围与截止时间、执行摘要、试验变化、文献变化、结论与证据、冲突/缺口、方法和来源覆盖、版本与审核记录。不是所有研究都必须含所有变化；无内容的节写明无已证实新增信息。

## 8. FR-009 审核与发布
报告有current_version和published_version两个指针。草稿编辑保存全量新版本，版本内容不可修改。提交审核绑定current_version；reviewer的approve提交version_id + content_hash + decision + note。
自审、对象越权、过期版本、哈希不匹配返回403/404/409。approve不自动发信，publish在事务里重新验证当前版本和有效批准、写published指针和delivery outbox。
有旧发布版本时允许创建新草稿；读者默认仍看到旧发布版本，审核员看到新稿待审标签。retract不是删除：留原版本、原因和更正提示；已撤回内容禁止新外发。V1撤回由reviewer/admin执行。

## 9. FR-010 订阅与投递
订阅字段：name、drug_ids、source_allowlist、daily/weekly、local_time、weekday(weekly时)、timezone、channels(in_app/email)、enabled。初始last_delivered_revision为空；首次报告明确初次建立基线。
排程预览未来5次UTC和本地时刻。时区夏令时重复时刻只触发第一次；不存在的本地时刻顺延到当日下一个合法时刻；规则在测试中固定。
订阅所有者邮箱来自已验证账户/管理员配置，不接受模型传入的收件人。email未配置时仅in_app；live外发需管理员开关。
暂停阻止新occurrence；不默默取消已运行任务，界面单独询问是否取消当前任务。编辑只影响未来触发，运行中的配置保持冻结。
站内投递以插入收件箱记录为成功；SMTP只有accepted，不等同已送达/已读。结果未知进入unknown待核对，避免自动重复外发。

## 10. FR-011 管理与观测
dashboard聚合当前workspace的关注对象数、过去7天观测到的事件、待审报告、来源健康、本人任务；不把本系统采样计数标为全球研发热度。
run详情显示工具调用摘要、返回证据数、耗时、Token已知值/未知、预算、停止原因、source coverage。不得展示模型隐含思维链，显示行动摘要和证据即可。
审计覆盖登录失败、角色变更、映射审核、任务取消/重试、报告审核发布/撤回、订阅修改、来源启停。日志脱敏。
