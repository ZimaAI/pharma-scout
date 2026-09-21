# 08｜API、错误和事件合同

机器可读合同：`contracts/openapi.yaml`（OpenAPI 3.1）。所有新增接口是本项目API，不是DeerFlow上游API。业务路径前缀 `/api/v1/workspaces/{workspace_id}`。

## 1. 通用约定
日期/时间见领域文档；ID为UUID字符串，外部ID单独字段；成功资源直接返回对象，列表返回items/next_cursor/has_more，不添加第二套data包装。
会话用HttpOnly Cookie；GET `/api/v1/auth/me`返回用户、workspace membership和CSRF token。变更操作必须X-CSRF-Token，登录也校验Origin并设置登录限流。响应带X-Request-Id。
POST创建返回201或异步202；验证错误422；身份401；权限403（资源存在可知时）；资源越权404；并发/重复参数409；限流429；外部不可用503。空列表200不意味着外部来源成功。
错误统一：`{"error":{"code":"...","message":"...","details":{},"request_id":"..."}}`。不得返回stack、密钥、原始SQL或其他workspace标识。

## 2. 幂等与乐观锁
run创建、来源sync、手动订阅触发、publish使用Idempotency-Key。保存workspace、用户、operation、key、canonical request hash和响应。相同键相同参数回原响应；相同键不同参数409 IDEMPOTENCY_CONFLICT。
幂等键至少保留7天，业务唯一约束长期存在。请求处理中返回相同job/run标识或409 IN_PROGRESS，不新建任务。
修改drug、subscription使用If-Match版本字符串，例如`"3"`；review/publish使用version_id+content_hash，不能仅传approve=true。

## 3. 端点分组
身份：login/logout/me；工作区成员：list/role update。
档案：drug list/create/detail/update/archive；alias candidate/list/decision；record link decision。
来源：source status、sync job create/detail；trial/publication list/detail；record snapshots/observations/diff；snapshot/evidence detail。
事件：event list/detail、revisions。
研究：run create/list/detail、cancel、retry、clarification、SSE；工具调用列表。
报告：list/detail、versions create/list、submit-review、reviews create、publish、retract、export。
订阅：list/create/detail/update、preview、trigger；通知：inbox/read、delivery list/detail；审计：list。
详细参数和body以OpenAPI为准，新增接口须同步合同。

## 4. SSE协议
路径GET `.../research/runs/{run_id}/events`，同源Cookie鉴权；接收Last-Event-ID。每个持久事件格式：
```text
id: 18
event: tool.completed
data: {"schema_version":"1.0","run_id":"...","seq":18,"occurred_at":"2026-09-21T08:00:00Z","type":"tool.completed","payload":{"call_id":"...","tool":"read_source_snapshot","evidence_count":2}}

```
事件类型：run.queued、run.started、plan.updated、tool.started、tool.completed、tool.failed、evidence.added、clarification.required、report.ready、run.partial、run.completed、run.failed、run.cancel_requested、run.cancelled、run.recovery_required。
仅业务事件有seq；15秒heartbeat是注释不计序号。重复/乱序投递由前端按run_id+seq去重；服务端按序回放，不能将心跳当进度。
断连不取消run。401触发重新登录；旧游标事件已过期返回410 EVENT_HISTORY_EXPIRED，前端GET run快照后从当前event_seq重新订阅；不得重新POST创建run。reverse proxy关闭缓冲并允许长连接。

## 5. 草稿版本与导出
POST versions提交结构化内容，不接受直接覆盖数据库的SQL/任意HTML。返回新的version_id及server计算content_hash。
GET report默认reader看到published版本，creator/reviewer可请求current；其他人不得由version_id绕过可见性。export支持markdown/json，服务器鉴权后流式输出或返回受控artifact，不返回本机路径。
Markdown引用URL从证据来源构建；demo://链接只打开本地证据页，不联网。

## 6. 稳定分页和过滤
limit默认20最大100；cursor不透明且绑定workspace/排序/过滤；标识搜索精确优先，其他query长度上限200。返回has_more但总数可为null。所有字段在服务端校验，不以拼接字符串构造SQL/上游查询。

## 7. 错误码最低集合
AUTH_REQUIRED, FORBIDDEN, NOT_FOUND, VALIDATION_ERROR, STALE_VERSION, IDEMPOTENCY_CONFLICT, SELF_REVIEW_FORBIDDEN, REPORT_NOT_APPROVED, EVIDENCE_INVALID, SCOPE_AMBIGUOUS, SOURCE_UNAVAILABLE, SOURCE_RATE_LIMITED, SOURCE_SCHEMA_CHANGED, BUDGET_EXCEEDED, RUNTIME_UNAVAILABLE, EVENT_HISTORY_EXPIRED, EXTERNAL_DELIVERY_UNKNOWN。

## 8. 合同验证
OpenAPI是本项目可执行结构基线；API和Web从同一schema生成类型/客户端。CI比较FastAPI生成schema与冻结合同的关键operation/字段，不允许同名字段一端snake_case另一端camelCase。开放JSON仅用于有版本的source payload、tool payload，不得把所有核心请求都写成任意object。

## 9. 部分更新与停用范围
DrugPatch/SubscriptionPatch仅更新出现字段，未出现保持原值；明确null仅允许nullable字段；空对象422。嵌套schedule出现时须完整提交并验证。成员PATCH支持role/enabled，停用只影响该workspace membership；全局账户禁用属于部署管理员CLI，不允许普通workspace admin跨组影响用户。

模型草稿中的claim_key为C1等局部标识；持久化时生成UUID claim_id并存对应关系。ReportVersion.content保持原始结构化内容，claim_ids及claim表提供ID映射，不在已签名内容内静默改写。

reader请求Report时current_version_id返回null，title来自可见的published版本；未发布报告整体不可见。creator/reviewer可见current。任何version详情仍独立检查访问权限，不能凭UUID直接读取。

## 10. 结论核验状态与增量交付范围
GET reports/{report_id}/versions/{version_id}/claims返回ClaimPage，供审核UI查看verification_status/numeric_check；仍按版本权限校验。GET reports/{report_id}/notices返回独立来源更新/撤回提示，不修改旧内容。
ResearchOutput.event_revision_ids列出本次确实覆盖并呈现的事件版本，必须是授权且在cutoff前已观察的版本。服务端核对它们与结论/证据关系；新文献原始研究但无已建事件时可为空。投递游标只能按实际覆盖列表推进，不能按本轮扫描到的所有事件推进。
