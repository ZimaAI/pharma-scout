# 09｜页面与交互规格

## 1. 全局信息架构
侧栏：工作台、药物档案、临床试验、研究文献、研究任务、报告中心、我的订阅、通知；reviewer追加审核中心，admin追加设置。顶部：workspace切换、全局对象搜索、模式、用户菜单。
全局搜索只搜索当前workspace中已摄入且可访问对象；“到官方来源检索”是单独的明确动作，不能假装本地搜索覆盖全网。

## 2. 页面规格
| 路由 | 核心内容 | 主要操作 | API |
|---|---|---|---|
| /dashboard | 工作区观测概览、最近变化、本人任务、待审 | 新研究/建关注 | dashboard, events, runs |
| /drugs | 档案、代号、关联资料数、更新鲜度 | 建档、筛选 | drugs |
| /drugs/:id | 基本身份、关联试验/文献、事件时间线 | 发起研究/订阅/别名 | drugs/{id}, trials, publications, events |
| /trials | trial表格、status/phase/has_results筛选 | 详情/比较 | trials |
| /trials/:id | 原始字段、关联药物角色、快照/观察 | 选择前后观察、研究变化 | trials/{id}, records/{id}/observations, diff |
| /literature | 标题、来源、日期精度、摘要可用性 | 详情/引用 | publications |
| /literature/:id | 元数据、原文摘要、更正关系 | 打开证据/来源 | publications/{id} |
| /events/:id | 版本时间线、变化前后、证据 | 研究此变化 | events/{id}, revisions |
| /research/new | 问题、对象、窗口、来源、预算 | 开始 | runs create |
| /research/:id | 行动轨迹、工具/资料覆盖、草稿、证据 | 澄清/取消/重试 | run detail, events SSE, tool-calls |
| /reports | 当前/发布状态、作者/审核者、截止时间 | 阅读/版本 | reports |
| /reports/:id | 报告、引用、版本、限制与审核 | 编辑/送审/批准/发布/导出 | report versions/reviews/publish/export |
| /subscriptions | 本人订阅、下次时间、渠道、last outcome | 建立/暂停/修改/触发 | subscriptions |
| /inbox | 站内通知与简报投递状态 | 标已读/查看版本 | inbox |
| /review | 映射候选和报告待审 | 批准/驳回/退回 | aliases/links/reports |
| /settings | 成员角色、数据源状态、同步任务、审计 | 启停/同步/成员调整 | members/sources/jobs/audit |

## 3. 工作台线框
```text
[侧栏] [workspace]                              [DEMO/LIVE] [账户]
       研究什么？ [输入问题........................] [新建研究]
       [关注药物] [近7天观察变化] [待审报告] [来源健康]
       [重要变化列表  2/3宽]             [本人运行/需澄清]
       [最近发布简报]                     [同步失败/资料范围]
```
卡片数量必须来自后端聚合；没有资料显示引导建档/同步。不要展示原型图中的真实药物疗效比较。

## 4. 研究详情线框
```text
研究标题  资料截至…  [部分完成/运行中]   [取消] [重试]
[范围与预算条]
[行动轨迹 40%]            [报告草稿/结论 60%]
  搜索试验                结论A [证据1] [证据2]
  读取S2                  结论B：资料不足
  发现冲突                未完成问题/来源覆盖
[工具详情折叠]            [右侧EvidenceDrawer按需打开]
```
工具返回内容先脱敏和限长；不能把LLM内部思考逐字作为可解释性成果。run完成后自动出现报告链接，而不是强制新开窗口。

## 5. 差异页面
比较的是before_observation与after_observation，展示两个观察时间和对应snapshot；允许回退复用旧snapshot。字段级标签added/removed/changed；保留raw和规范化值；关键日期带precision；没变的字段可折叠。
查看120→160时只描述入组目标调整，不附“疗效提升”的智能标签。无变化显示“内容未变化；本次抓取已记录”。

## 6. 审核页面
显示当前版本号和摘要hash，点击引用打开证据。检查清单：范围、资料时间、试验角色、关键数字、冲突/缺口、措辞不越界。批准/退回都要note。若当前版本变动，409提示刷新，不自动把旧批准套到新版本。
阅读者看到已发布版本，审核员可切current/published。撤回报告显示横幅和原因，禁止“重新发送旧内容”按钮。

## 7. 订阅编辑
每周显示星期；每日不显示无意义星期字段。选择IANA时区，预览未来5次绝对时间；夏令时规则旁有说明。email不可用时禁用渠道并解释配置缺失；不能假装已发送。
“立即生成”返回queued任务，默认仍需人工审核；“暂停订阅”不代表当前任务已取消，分别呈现。

## 8. 五类边界状态
empty：尚未同步→引导；filtered_empty：调整筛选；error：可重试并有request_id；partial：展示已成功来源和失败来源；forbidden：不泄漏被拒对象内容。
日期未知、无摘要、无结果、不支持字段、历史不足均有专门文案。不出现假数字0、虚假趋势、无限spinner、按钮点击无反应。

## 9. 前端技术约定
TanStack Query管理服务器状态，局部表单/抽屉使用React状态；不要把所有API复制到全局store。Zod等校验需与OpenAPI一致；生成客户端统一Cookie/CSRF/error处理。Markdown禁止原始HTML；外链noopener，来源是否外部明确提示。
URL保存筛选和选中tab；SSE更新只影响对应run的cache，不能覆写其他任务。列表乐观更新仅用于可回滚的轻操作，审核发布以服务端返回为准。

## 10. 关注与报告提示
V1不另做收藏模块。“关注”打开订阅编辑，保存订阅后生效；工作台watched_drugs表示当前用户enabled订阅中不同药物数量，卡片标题用“我的关注”。reader仅只读已发布内容，不显示可用的订阅新增按钮。报告通过claims端点读取核验状态，通过notices读取旧版本来源更新提示；来源有变化不等于旧结论已经错误。
