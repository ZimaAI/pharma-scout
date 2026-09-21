# 订阅、交付与后台任务验证

2026-09-21 完成后端验证。所有自动化数据为 synthetic/DEMO；SMTP 测试使用内存替身，没有向真实邮箱发送邮件。

实现：`backend/app/pharma/subscriptions.py`、`worker.py`。测试：`backend/tests/test_pharma_subscriptions.py`、`test_pharma_worker.py`。PostgreSQL 测试通过 `tests/support/pharma.py` 在专用 `_test` 数据库建立随机 schema，执行 Alembic 迁移并在结束时删除该 schema；每个测试事务回滚，不清理真实部署业务表。

## 实测结果

```bash
# PHARMA_TEST_DATABASE_URL 由本机 private.env 安全传入子进程，不打印连接串。
cd backend
.venv/bin/python -m pytest tests/test_pharma_worker.py tests/test_pharma_subscriptions.py -q
```

结果：30 passed，退出码 0。其中 9 项纯日期排程测试、21 项后台执行/数据库测试。Ruff 格式和静态检查通过。

验证覆盖：

- Asia/Shanghai 的 UTC/当地时间转换；America/Los_Angeles 春季不存在时刻顺延到第一个合法分钟，秋季重复时刻只选第一次；星期使用 ISO 1–7。
- 同一订阅/绝对 scheduled_at 唯一；任务冻结订阅 revision、批准别名、药物、来源、渠道和知识截止时间；编辑/暂停不改变已创建 occurrence。
- 宕机只补最近一次到期发生，保存略过窗口；失效成员不能创建研究任务。
- 站内 accepted 与对应 event/channel 游标同事务更新，重复扫描不产生重复投递，accepted 不等于 read。
- 只按已被各渠道接受的 event revision 去重。未建立初次基线的渠道仍生成初报；来源失败/截断不能误报 no_change。
- 明确连接失败最多五次退避重试；SMTP 结果不明或 sending 租约过期进入 unknown，不自动重发、不推进游标；过期执行者不能写回结果。
- 已撤回报告不再进入新投递；投递只读取指定版本，不重跑研究。
- 失效租约、取消任务、停用成员、停用来源在响应落库前再次检查；过期心跳不能重新取得租约；旧研究 job 的失败不能覆盖新的 run attempt。
- 按条保存成功响应，后续查询失败保留已成功数据。已知来源记录 404/失败保留失败 observation，但不替换当前有效快照。重复观察仍允许关联第二个药物候选。
- 研究正在执行时，独立调度/交付协程继续扫描；所有协程同属一个拥有 PostgreSQL leader lock 的工作进程，TaskGroup 负责退出清理。

## 对接接口

- `preview_schedule(schedule, after=None, count=5)`：返回 UTC、当地时间及 DST 调整标志。
- `create_subscription(repo, owner_id, payload)` / `update_subscription(repo, id, owner_id, payload, expected_revision)`：短事务业务操作。
- `trigger_subscription(repo, id, owner_id, create_run=callback, ...)`：创建冻结 occurrence，回调为 `create_run(repo, owner_id, ResearchInput)`。
- `scan_subscriptions(repo, create_run, at=None)`：使用行锁、advisory lock 和唯一键扫描到期任务。
- `pending_event_revision_ids(repo, run_id, ids)` / `finalize_occurrence(repo, run_id, coverage, ids)`：真实来源核查后筛选增量并决定 generated/no_change/partial；不推进交付游标。
- `process_deliveries(workspace_id, batch_size=20)`：自身管理短事务，外部 SMTP 请求在事务外。异步调用方用 `asyncio.to_thread` 调用。

## 邮件配置

默认关闭。仅 `PHARMA_SMTP_ENABLED=1` 且配置 `PHARMA_SMTP_HOST`、`PHARMA_SMTP_FROM` 才允许本地 Mailpit/loopback SMTP；其他主机另需 `PHARMA_SMTP_ALLOW_EXTERNAL=1`。可选 `PHARMA_SMTP_PORT`、`PHARMA_SMTP_STARTTLS`、`PHARMA_SMTP_USERNAME`、`PHARMA_SMTP_PASSWORD` 均来自服务器环境，绝不接受模型提供的收件人或服务器地址。

收件人取管理员创建的账户邮箱，并在首次领取时冻结。邮件只有 SMTP accepted 语义；本实现没有供应商回执集成，因此不会声称已送达或已阅读。unknown 留待管理员核对，本次没有启用外部 SMTP。
