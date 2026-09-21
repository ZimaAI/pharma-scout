# PharmaScope｜设计规范 v1.0

定位：专业、清晰、现代的研发情报工作台。浅色背景，蓝色主操作，紧凑但不拥挤。视觉优先传达资料范围、版本、证据和审核状态，而不是“AI非常聪明”。
每次新增或修改页面前，必须实际读取本文和现有共享组件。原型图仅参考布局，图中药物事实、数据、趋势与名称不作为实现内容。

## 1. 色彩Token
| Token | 色值 | 用途 |
|---|---|---|
| background | #F6F8FC | 主背景 |
| surface | #FFFFFF | 卡片/弹窗 |
| surface-muted | #F0F3F9 | 分区/表头 |
| primary | #315EFB | 主按钮/选中态 |
| primary-hover | #254BDC | 悬停 |
| primary-soft | #EEF2FF | 选中背景 |
| accent | #6D5AE6 | AI研究辅助标识，不能替代状态色 |
| text-primary | #17243B | 正文/标题 |
| text-secondary | #52617A | 辅助文本 |
| text-muted | #6B7890 | 次要信息 |
| border | #DDE4EF | 边界 |
| success | #157347 | 成功/已发布 |
| warning | #9A5700 | 资料不足/待核对 |
| danger | #BC2D3E | 错误/撤回 |
| info | #225AA7 | 一般提示 |
| sidebar | #142138 | 深色侧栏 |
| sidebar-text | #E6ECF7 | 侧栏文字 |

状态必须有文字和图标，不能只靠颜色。普通文字对比度目标4.5:1，大字/关键非文字组件目标3:1；实现时用自动化/人工核查，不因指定色值而宣称全部合格。

## 2. 字体
系统字体栈：Inter, -apple-system, BlinkMacSystemFont, Segoe UI, PingFang SC, Microsoft YaHei, sans-serif；未提供Inter资源时用系统字体，禁止把容器字体文件打包。
页面标题28px/700/1.35；分区20px/600/1.4；卡片标题16px/600/1.45；正文14px/400/1.6；辅助12px/400/1.5；报告正文15px/1.8。数字使用tabular-nums；长标识等宽13px，不以缩小到10px解决拥挤。

## 3. 布局与间距
4px基础栅格：4/8/12/16/24/32/48。侧栏232px，折叠72px；顶栏64px；主区域24px边距；内容最大1440px居中。
>=1280px使用12列；1024～1279侧栏折叠；768～1023单列主内容+抽屉辅助；<768移动导航抽屉。复杂表格保留表头横向滚动，不能挤成不可读的微型文字。
详情页主栏约2/3+资料侧栏1/3；研究页左右两栏，左运行轨迹/问题，右报告与证据；小屏改为tab，不要求全部同屏。

## 4. 圆角、边框和阴影
按钮8px；输入8px；卡片12px；抽屉/弹窗16px；徽章6px或pill。卡片默认1px border，无强阴影；弹窗`0 16px 48px rgba(23,36,59,.14)`；聚焦环2px primary+2px偏移。不要每个区块都叠渐变/发光/玻璃效果。

## 5. 共享组件
AppShell、PageHeader、ModeBanner、SourceBadge、SourceCoverage、FreshnessLabel、DrugIdentity、StatusBadge、MetricCard、FilterBar、DataTable、DatePrecisionText、DiffViewer、EventTimeline、EvidenceDrawer、ClaimCard、RunTimeline、BudgetMeter、ReviewPanel、EmptyState、ErrorState、PermissionState。
组件需覆盖default/hover/focus/disabled/loading/error/empty/no_permission。数据由API供应，禁止复制页面内部多套实体/状态定义。

## 6. 按钮/表单
主按钮高度36px（触控场景40～44）；次级边框按钮；危险操作使用危险色+明确动作名。提交中锁重复提交但保留原文字+spinner；不能把整个页面变不可交互。
label永久显示；placeholder不是label；必填说明与字段错误相邻；服务端错误映射字段；离开未保存表单有提醒。药物多选最多5个；时间窗含timezone；预算超限在提交前提示。

## 7. 表格/筛选/分页
表头40px、行48～56px；可排序列有明确箭头；筛选chips可清除；空列表区分“尚未同步”与“筛选无结果”。先用cursor前后分页，不展示无法可靠计算的第N页总数。长名称两行+tooltip；外部ID可复制；整行点击不吞掉行内按钮的键盘事件。
批次/试验状态只显示源状态，不能把completed用庆祝图标表达成“研发成功”。

## 8. 证据抽屉
宽度480～560px；头部显示来源、外部ID、快照版本、抓取时间、原文语言；原文片段突出相关范围，下方可查看完整已授权快照和字段路径。翻译可切换并标机器辅助；引用支持/反驳/背景关系明确展示。不要直接打开新网页代替证据抽屉。

## 9. 报告与审核
阅读宽度720～880px；段落短、数字可追溯；引用为可键盘激活按钮。固定显示DEMO/LIVE、知识截止、来源覆盖和审核状态。
审核面板有version/hash摘要、硬校验、待核查结论、审批/退回理由；自审禁用并解释。批准后编辑产生新版本，顶部醒目提示需重新审核。原版本不会被静默改动。

## 10. 运行状态与反馈
任务显示阶段/真实工具调用，不显示虚构98%进度；时间、调用数和预算有真实值才显示。partial用“部分完成”，不是绿色成功。source failure用持久横幅，toast只提示操作结果不承载唯一错误信息。
SSE重连时显示“连接恢复中，任务仍在后台运行”；取消区分“请求取消”和“已取消”。工具错误允许展开脱敏详情。

## 11. 弹窗/下拉/导航
普通确认用Dialog，有初始焦点、Tab锁、Escape关闭；未保存/危险状态按明确规则确认。Evidence侧抽屉保留背景上下文。下拉支持键盘/搜索/空结果；底层使用可访问组件，不手写不可聚焦div列表。
导航显示当前workspace，草稿/通知的角色与用户范围一致；admin模块不对reader呈现可点击入口，但后端仍鉴权。

## 12. 图表
仅绘制后端可重算的本工作区观测统计。标题如“本工作区近30天新增试验记录”，不能写“全球药物热度”。显示时间维度、数据缺口、样本数、截止时间；缺数据不绘制假折线。颜色最多3～4种，提供数据表替代。

## 13. 动效与无障碍
动效120～180ms；遵循prefers-reduced-motion。图标提供文本标签；状态aria-live适度播报，避免每个token打断阅读。键盘完成研究提交、引用阅读和审核。小屏按钮触控区域至少约44px。

## 14. 前端交付检查
先实现 `/pharma/design-preview`，展示上述基础组件和五种失败/空状态。完成业务页后以1440x900、1024x768、390x844三种视口检查溢出、抽屉、表格、焦点与长英文名称。所有截图使用虚构资料，截图不等于API验收。

参考色彩变量见 [tokens.css](docs/reference/pharma-intelligence/assets/tokens.css)，落地样式见 [pharma.css](frontend/src/styles/pharma.css)。设计规范变更先更新本文，再更新组件和页面，禁止单页私自引入另一种风格。

## 15. 本仓库落地规范（2026-09-21）

产品名称 **PharmaScope / 医药研发情报**，注明基于 DeerFlow。业务界面统一位于 `/pharma` 下，保留原有 `/workspace` 通用研究助手入口。首页进入医药工作台；未登录显示专用登录页。医药工作区具有独立账户会话与角色，API 命名空间为 `/api/pharma/v1`。

视觉延续原型的深蓝侧栏、白色资料卡、蓝色主按钮和双栏详情，去掉装饰性架构图与无来源趋势。工作台用大标题“让每一条研发进展，都有据可循。”搭配轻量网格背景；工作流信息优先。品牌图形使用 SVG/CSS 的分子节点几何，不引入照片或未经核验的药物包装。

应用 CSS 统一以 `.pharma-app` 和 `--ph-*` 命名，局部浅色主题不影响原有聊天界面。业务页使用共享 `PharmaShell`、`PageHeader`、`Panel`、`Badge`、`Empty`、`ErrorPanel`、`EvidenceDrawer`、`DataTable` 和 `Coverage`。图标采用现有 lucide-react；按钮保持可见中文标签。

列表页由标题/说明/主要操作、筛选条、真实数据表组成。详情页使用面包屑、对象身份、正文与资料侧栏。任务页左侧为可恢复的事件轨迹，右侧为报告入口与来源覆盖。审核动作只显示角色可执行操作，并保留服务端错误信息。表单使用永久标签、就地校验和可读反馈；药物建档、别名确认、订阅创建均提供可完成的交互。

常驻底部边界文案及 DEMO/LIVE 标识。空白 live 工作区显示“建立首个药物档案 → 确认别名 → 同步官方来源 → 发起研究”；缺模型时显示配置缺口，不能切换为演示数据。演示账户密码不在网页公开。
