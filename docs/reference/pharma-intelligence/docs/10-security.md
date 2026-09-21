# 10｜安全、隐私与研究边界

## 1. 威胁模型
资产：账户/会话、workspace资料、模型/来源密钥、研究提问、证据、审核记录、报告、收件人。攻击面：用户输入、外部文献、模型工具参数、SSE、Markdown、artifact路径、任务重试与管理接口。
主要风险：跨workspace读取、提示注入、SSRF、证据伪造、审批重放、隐藏外发、会话劫持、日志泄密、外部未知投递与敏感信息误接入。

## 2. 身份与授权
会话token仅保存hash；随机token至少256位；密码使用成熟Argon2id库并按实测设参数。HTTPS Secure Cookie + HttpOnly + SameSite，变更操作CSRF/Origin检查。管理员创建用户不发送明文密码，demo凭据仅本地文档显示。
每个API和worker工具以membership解析角色；数据库查询必须包含workspace；DB复合FK只是防错，不能替代鉴权。draft/run按creator或reviewer/admin限制，通知按recipient限制。
run重试、artifact下载、evidence详情、SSE回放、分页cursor全部重复鉴权。禁用账户后新请求/流重新鉴权时终止。

## 3. 不接入患者数据
V1没有病历上传/患者档案/入组匹配表，也不提供上传任意医学PDF入口。识别到个体诊断、剂量选择等请求时解释研究用途并拒绝该动作；不因合法文献提到“患者”就机械拒绝正常研发研究。
提示可能含敏感信息时在调用外部模型前中止并提示移除。管理员明确配置使用何种外部模型服务及允许传出的内容类型；只发送任务必要资料和短片段。
不声称已满足HIPAA、GxP、21 CFR Part 11等认证或监管要求。真实机构上线需另行评估法务、医疗、安全和采购要求；本包不代替该评估。

## 4. 提示注入与工具权限
仅开放批准领域工具，禁用任意shell、代码执行、任意网络/文件工具、动态安装MCP。系统Prompt和Guardrails只是多层中的一层；执行层对每次调用核验。
source文本不进入高优先级指令。工具参数additionalProperties=false；identity/secret/recipient不可由模型设置。子Agent继承相同或更小权限，不扩权。[S04]
报告只能保存草稿候选，publish/email由服务端业务动作处理，不提供给LLM作为可调用工具。任务上下文隔离测试覆盖主Agent、子Agent与恢复attempt。

## 5. 网络与SSRF
V1仅调用静态base URL的官方API，不开放用户任意URL抓取。ID/参数由HTTP客户端编码，禁止拼接URL。重定向需重新校验host、协议、端口和实际解析IP；拒绝loopback、private、link-local和云metadata等目标。配合网络层出站策略，不只靠正则。[S13]
模型base_url仅部署管理员配置并审核；客户端不能修改。代理配置只来自受信配置。外部API凭据放secret store/环境变量，不出现在记录query字符串或错误日志。

## 6. 文件与前端输出
文件key由服务端生成，数据库保存相对key，不接受客户端路径。通过授权下载服务访问；不暴露文件卷、不执行产物。HTML/JS/SVG等主动内容不可内联渲染。Markdown转HTML用白名单sanitize并配置CSP；原文摘录作为纯文本显示。
截图与演示数据全部虚构；live和demo有分离workspace/数据库配置。DEMO标识不得在导出、打印、邮件中消失。

## 7. 证据与审批完整性
每条证据定位到不可变快照；hash仅检验内容一致，不证明事实可信。snapshot/report_version/claim等在服务层和DB触发器防更新。
审批保存reviewer、version_id、hash、decision、时间和理由。发布前锁当前报告重新验证；自审禁止；过期批准失效。撤回保留原因，停止尚未发送投递；已外发内容不能假装自动从外部邮箱收回。

## 8. 日志与可观测性
默认不记录整段用户问题/医学原文/模型消息，日志记录引用ID和摘要。诊断详细trace需管理员显式开启、保留期有限、workspace鉴权，不能外发到未知第三方。禁止展示隐藏思维链；提供工具行动和证据记录。
审计不是无条件不可篡改证据，数据库管理员权限仍需治理；不声称“有hash所以满足监管”。

## 9. 安全测试必需
跨workspace对象/游标/SSE；他人草稿；CSRF；Prompt注入要求读环境/发邮件；工具参数注入；快照quote篡改；旧版审核重放；路径穿越；URL重定向到私网；禁止公开demo账户；从未验证来源抽取临床成功结论应被拦截。
硬边界场景必须100%通过才发布本地演示包的对应能力；这只代表测试集结果，不代表绝对安全。
