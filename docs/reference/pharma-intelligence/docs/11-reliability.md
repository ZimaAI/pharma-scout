# 11｜任务、订阅、发布与可靠交付

## 1. 双层状态而不是双套Agent
job为业务执行外壳：queued→running→succeeded；可转retry_wait/failed/cancelled。
research_run为领域状态：queued→running→awaiting_input→running→verifying→completed|partial；可转cancelling→cancelled、failed、recovery_required。attempt/工具调用/检查点用于恢复，同一业务run不因浏览器刷新重建。
report工作流：draft→in_review→approved→published；退回changes_requested后编辑新版本→draft。老published版本不因新draft而消失。

## 2. 领取与租约
worker用短事务 `SELECT ... FOR UPDATE SKIP LOCKED` 领取可用job，写owner_token、lease_expires_at、attempt；执行外部调用前提交事务。定期heartbeat；状态写回必须匹配owner_token，过期worker不能覆盖新owner结果。
单机也保留这些字段以便演示恢复；扩容前必须测试并发领取和全局限制。lease超时不是外部调用一定停止，重复执行风险另行处理。

## 3. 幂等动作
读来源：稳定record identity和内容hash复用，观察记录按attempt/请求operation key去重，恢复不造两个相同业务观察。
保存草稿：`run_id + candidate_no + candidate_hash`唯一；report一个run一份。重复结果不能创建不同内容的同号version。
发布：有效review+version hash+事务唯一delivery；投递失败不重跑研究。

## 4. 恢复矩阵
| 故障位置 | 恢复策略 |
|---|---|
| 拉到HTTP响应但未保存 | 可重新拉取；记录新抓取日期，结果不保证与第一次相同 |
| snapshot已存、事件未存 | 同事务提交或回滚；重试对比正确观察链 |
| 模型调用完成但用量/草稿未存 | 可重跑有限attempt，记录可能重复费用，不承诺exactly-once |
| checkpoint缺失/损坏 | recovery_required；保留有效证据；显式重跑，不假装继续同一步 |
| 发布事务提交后worker宕机 | durable delivery仍在，独立投递器继续 |
| SMTP接收后本地未记成功 | unknown；人工/提供商回执核对，不自动无限重发 |
| 发信明确未连接成功 | 退避重试，仍使用同逻辑delivery |

报告引用只依赖已持久化snapshot/evidence，不依赖已经回收的Agent临时工作区。

## 5. 订阅与水位
每个occurrence保存订阅revision、scheduled_at、药物/别名/来源配置快照、知识截止时间。编辑订阅只影响未来occurrence。
三类水位区分：来源同步水位（成功读到哪）、报告覆盖水位（报告包含哪些event revision）、用户已交付水位（哪条投递已被渠道接受）。不要把任务开始时间写成已交付进度。
`subscription_cursor`按subscription+event+channel记录last_accepted_revision_id。发信unknown不推进。新报告包含集合而非单一timestamp，避免迟到事件按老时间被漏掉。
无新增且所有必需来源成功：occurrence=no_change，不发重复简报；必需来源失败：partial或failed，通知任务状态，不能推进完整水位。

## 6. 排程
项目调度进程周期扫描next_run_at，使用行锁和occurrence唯一键避免重复。V1只一个活动scheduler；多进程启动需DB advisory lock保证扫描领导者。
计算以IANA timezone和实际时区数据库为准；存UTC scheduled_at与本地展示。夏令时不存在时刻顺延，重复时刻选较早那个；测试用America/Los_Angeles和Asia/Shanghai。
补跑：宕机后默认只补最近一次漏掉的occurrence，记录skipped窗口；不是把一个月全部邮件一次发出。具体策略可管理员配置但必须审计。

## 7. 交付状态
delivery：queued→sending→accepted；明确临时失败回queued并next_attempt_at；无法判定结果unknown；永久错误failed；撤回/取消cancelled。
站内通知accepted即可更新对应游标；email accepted仅说明SMTP接受。送达/退信仅有有效回执才补充；read_at只来自用户阅读动作。不提供伪造“已阅读率”。
重试最大5次，指数退避+抖动；消息内容固定version，模板和收件人记录版本。管理员手动重发unknown必须提示重复风险并生成独立审计，不偷偷视作首次发送。

## 8. SSE与运行事件
事件先持久化后发送；seq在run行锁内分配。连接断开不改变run状态；恢复从Last-Event-ID读取。终态事件出现后仍可通过GET完整查看，不依赖客户端缓存。
run事件默认90天清理，但报告及关键审计按保留策略留存。历史丢失返回410，不返回空数组假装任务没执行。

## 9. 运维指标
job_queue_age、lease_expired_count、run_terminal_count{status}、source_requests{outcome}、source_coverage、delivery_unknown、delivery_duplicate_prevented、report_review_lag、evidence_invalid_count、llm_tokens_known/estimated。来源失败率与零结果率分别统计。

## 10. 待审提醒与手动触发
订阅只自动生成待审稿，发布仍需独立reviewer。V1待审提醒由审核中心队列呈现，不借用已发布报告delivery冒充已交付；没有审核员时任务保留待审并显示阻塞。手动trigger使用服务端实际触发时刻作为scheduled_at，Idempotency-Key复用同次触发；自动排程唯一性依赖绝对scheduled_at。
