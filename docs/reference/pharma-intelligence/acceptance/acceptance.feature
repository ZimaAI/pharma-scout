Feature: PharmaScount V1 research intelligence acceptance

  @T01
  Scenario: 首次抓取仅建立基线
    Given 没有历史观察的DEMO-CT-001
    When 同步D1
    Then 只建立baseline而不宣称今天启动试验

  @T02
  Scenario: 相同内容不重复报进展
    Given 已经成功保存D1
    When 同步内容相同的D2
    Then 新增observation但不新增内容snapshot或业务事件

  @T03
  Scenario: 识别目标和状态变化
    Given 已经保存D2
    When 同步D3
    Then 生成status与enrollment两个差异并绑定前后证据

  @T04
  Scenario: estimated与actual不同
    Given 两条人数相同但count_type不同的记录
    When 执行差异比较
    Then 识别语义变化且不把目标人数称为实际入组

  @T05
  Scenario: 内容回退仍是新观察
    Given 当前观察为D4对应S3
    When 同步回退到S1的D5
    Then 复用S1内容并产生新观察与回退事件

  @T06
  Scenario: 字段缺失不补零
    Given 来源删除一个终点或入组数字字段
    When 规范化和生成草稿
    Then 显示来源未提供而不是0或已无该终点

  @T07
  Scenario: 日期精度不伪造
    Given 文献日期只有2026-09
    When 显示和导出日期
    Then 保留month精度且不填2026-09-01

  @T08
  Scenario: 同名药物需确认
    Given 一个别名关联两个候选对象
    When 发起范围不明确的研究
    Then 请求澄清或partial而不自动永久合并

  @T09
  Scenario: 对照药不误认研究对象
    Given trial-drug关系标记comparator
    When 生成药物进展草稿
    Then 保留对照角色且不声称新增该药适应证研发

  @T10
  Scenario: 更正不重写旧报告
    Given D3报告已发布且D4资料更正
    When 生成新报告版本
    Then 旧版本仍可查且显示更正提示

  @T11
  Scenario: 来源失败不是零结果
    Given PubMed返回429且重试耗尽
    When 结束本轮研究
    Then coverage为failed或partial而非完整no_change

  @T12
  Scenario: 分页截断要披露
    Given 来源候选数超过项目record_limit
    When 同步达到上限
    Then 标truncated且不推进完整覆盖水位

  @T13
  Scenario: 引用篡改阻止送审
    Given evidence的quote与snapshot locator不匹配
    When 校验报告草稿
    Then 返回EVIDENCE_INVALID并阻止发布

  @T14
  Scenario: 跨工作区证据不可读
    Given 用户只属于workspace-A
    When 请求workspace-B的evidence或SSE
    Then 返回404且不泄漏正文/任务信息

  @T15
  Scenario: 外部文本不能获得执行权限
    Given 来源正文要求读取环境变量或发信
    When 模型尝试调用未授权能力
    Then 执行层拒绝且审计不包含秘密

  @T16
  Scenario: 禁止自审
    Given 分析员或reviewer是报告任务发起人
    When 批准自己报告
    Then 返回SELF_REVIEW_FORBIDDEN

  @T17
  Scenario: 批准绑定具体版本
    Given reviewer已批准version1
    When 编辑生成version2后使用旧批准发布
    Then 返回STALE_VERSION或REPORT_NOT_APPROVED

  @T18
  Scenario: SMTP结果未知不盲发
    Given SMTP可能已接受但本地未存回执
    When 恢复投递任务
    Then 进入unknown且不自动重复外发

  @T19
  Scenario: 重复排程只建一个发生记录
    Given 同订阅同scheduled_at被两个scheduler扫描
    When 并发触发
    Then 只有一个逻辑occurrence和对应run

  @T20
  Scenario: 断线恢复不重新执行
    Given 浏览器收到run seq5后断线
    When 以Last-Event-ID=5重连
    Then 按序补后续事件且run标识不变

  @T21
  Scenario: 旧worker不能覆盖新租约
    Given 旧owner租约已过期新owner已领取
    When 旧owner尝试写回成功
    Then 写入被拒且保留新owner状态

  @T22
  Scenario: 预算耗尽保存部分结果
    Given run已达共享工具或模型预算
    When 再次尝试调用
    Then 停止新调用并交partial附未完成问题

  @T23
  Scenario: 历史评测不能看未来资料
    Given 评测截止D3
    When 执行D3研究
    Then 不可读取D4或D5证据，即使它们存在fixture目录

  @T24
  Scenario: 虚构标识不得联网
    Given APP_DATA_MODE=demo且ID以DEMO开头
    When 请求真实来源适配器
    Then 拒绝实际HTTP调用并保持显著DEMO标识

  @T25
  Scenario: reader不能查看他人草稿
    Given reader可见该workspace已发布报告
    When 请求未发布version的直接ID
    Then 返回404或明确授权失败

  @T26
  Scenario: 完整旅程可复演
    Given demo分析员和独立reviewer以及开发SMTP可用
    When 按demo-guide完成建档研究审核发布投递
    Then 所有引用可定位且邮箱面板不被称为真实医疗使用
