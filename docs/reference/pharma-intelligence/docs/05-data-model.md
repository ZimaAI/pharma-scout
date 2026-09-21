# 05｜数据库设计与持久化约定

## 1. 设计原则
使用UUID作为内部标识、UTC timestamptz、JSONB保留原始和版本化结构。所有业务表含workspace_id；子对象使用(workspace_id,parent_id)复合外键。`database/schema.sql` 为初始参考，未在真实数据库执行，实施时必须转换迁移并运行约束测试。

## 2. 表分组
| 模块 | 表 |
|---|---|
| 身份 | app_user, workspace, membership, app_session |
| 实体 | drug, drug_alias, entity_link |
| 来源 | source_record, source_snapshot, source_observation, source_sync_state |
| 证据/事件 | evidence, intelligence_event, event_revision |
| 任务 | job, research_run, run_event, tool_call |
| 报告 | report, report_version, claim, claim_evidence, review, report_notice |
| 订阅 | subscription, schedule_occurrence, subscription_cursor |
| 交付 | delivery, delivery_attempt |
| 系统 | artifact, audit_log, idempotency_record |

Trial/Publication的V1当前读模型存在 `source_record.current_projection` JSONB，trial_id/publication_id即各自source_record.id，不额外维护两套彼此漂移的实体表。source_record.kind区分trial/publication；API校验kind。热点字段有status/phase等表达式索引可按实测新增。

## 3. 关键字段与含义
### source_record
source=ctgov/pubmed；external_id在同workspace与source唯一；kind=trial/publication；canonical_url来自来源适配器；current_snapshot_id为最近成功观察内容，不保证内容时间单调；current_observation_id记录当前位置。latest source date不覆盖历史。
### source_snapshot
record_id、content_hash、raw_payload、normalized、normalizer_version、source_updated(SourceDate)、first_observed_at。hash基于规范化原始有效负载，去除传输时间，不能用标题hash替代全文内容hash。
### source_observation
每次record抓取一行；observation_seq按record锁后递增；outcome=changed/unchanged/baseline/unavailable/failed；snapshot_id可空。失败不推进record的current成功观察；404不是删除证据。
### evidence
snapshot_id、locator(json_pointer/text_range)、quoted_text、snippet_hash、original_language、translation_text、extractor_version。创建后不可变；quote必须由快照提取校验，不能接受模型随意撰写。
### entity_link
record_id/drug_id/relation/status/reviewed_by；关系是可撤销的业务记录，不删除历史快照。
### event_revision
before_observation_id、after_observation_id、changes[]、evidence_ids[]、severity=info/important/correction；severity只表示研究关注优先级，不代表临床风险等级。
### research_run
created_by、status、question、frozen_request、runtime_mode、upstream_ref、model_ref、prompt_version、budget、usage、checkpoint_ref、attempt、stop_reason、next_event_seq。JSON中的外部ID先授权解析成内部ID。
### report/report_version
report保存current/published指针与工作流状态；version保存content_json、content_hash、version_no、created_by。report_version不可变；审核、发布、撤回单独留痕。report_run一对一，追问为新run。
### claim/claim_evidence
claim归属具体report_version；supports/contradicts/context关系保存多条证据。claim.status为语义核验状态，不作为临床认证。报告JSON的claim_id集合必须与表记录一致。
### delivery
version_id、recipient_user_id、channel、idempotency_key、state、lease、last_error。state=queued/sending/accepted/unknown/failed/cancelled；站内accepted代表创建成功，email accepted只代表SMTP接收。read_at是独立用户动作。

## 4. SQL层与服务层各保证什么
SQL层：非空、枚举CHECK、唯一键、同workspace外键、正数/上限基础约束、JSON类型基础检查。
服务层：角色、草稿可见性、源ID和kind一致、所有JSON evidence_ids是否同workspace、审稿哈希、日期精度、前后观察属于同record、不得把DEMO外部ID发给live源。
插入引用必须在同一事务内校验并落库，不能先审查后换内容。数据库服务账户不允许直接更新immutable表；迁移管理员单独保管。

## 5. 幂等与并发
- source_record唯一(workspace,source,external_id)；首次竞态使用ON CONFLICT后锁记录。
- source_snapshot唯一(workspace,record,content_hash,normalizer_version)。内容回退可复用旧snapshot，但新的observation必然存在。
- event_revision唯一(workspace,event,before_observation,after_observation)，首次baseline不建变化revision。
- run_event唯一(workspace,run,seq)。锁run自增分配序号并同事务写入事件，不用进程局部计数。
- review依赖version/hash；发布锁report，在事务中再次验证。
- delivery唯一(workspace,version,recipient,channel)，重试增加attempt而不建新逻辑投递。
- schedule_occurrence唯一(workspace,subscription,scheduled_at)，编辑后的revision冻结在发生记录，不能重复触发相同绝对时刻。

## 6. 索引与分页
常见索引：记录(source,external_id)、快照(record,first_observed_at)、观察(record,seq)、事件(subject,updated_at)、run(created_by,created_at,id)、job(state,available_at)、delivery(state,next_attempt_at)。
列表使用keyset cursor（created_at,id）或（observed_at,id），不以OFFSET承诺在持续写入时稳定分页。cursor包括过滤指纹和workspace，必须验证与当前请求匹配；cursor不是权限凭证。

## 7. 删除与保留
V1不提供用户可调用的物理删除来源快照/发布报告；实体archive、关联revoke、报告retract。会话过期清理；运行详细日志默认90天、审计180天，发布证据随报告保留。以上是本项目可配置运营默认值，不是法律保留期。
资料授权撤销/侵权移除必须由管理员走特殊流程，保留撤下标记、哈希及引用失效说明，不继续散发原文。备份恢复需同时恢复DB和文件，不能只恢复一个导致引用悬空。

## 8. 人工核验与不可变内容
claim保存生成该报告版本时的最终自动核验结果，人工review在review表。复核导致结论、核验结论或证据变化时创建新report_version及claim，不直接UPDATE immutable claim。报告published/current指针必须归属同一report，DB只保证workspace，服务层需在事务里额外检查。

## 9. 发布后的资料变更提示
新增report_notice表保存与旧报告版本分离的提示，type=source_updated或report_retracted，引用触发的event_revision。来源更新只提示“资料已有新版本，旧结论需重新核对”，不自动宣称旧结论已被证伪。用稳定notice_key去重，GET报告时读取可见版本对应提示。
