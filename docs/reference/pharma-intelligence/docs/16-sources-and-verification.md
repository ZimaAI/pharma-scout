# 16｜外部依据、来源与验证范围

核对日期：2026-09-21。下列是外部能力/风险说明的主要依据；本包大部分业务流程、数据结构和验收门槛是针对本项目的原创设计，不能理解为上游已经提供。

| 编号 | 一手来源 | 本包使用范围 | 核验状态 |
|---|---|---|---|
| S01 | https://github.com/bytedance/deer-flow | DeerFlow 2.x定位、嵌入式/工具能力 | 已读取官方README，未部署 |
| S02 | https://raw.githubusercontent.com/bytedance/deer-flow/main/backend/AGENTS.md | harness/app分层与扩展方向 | 已读取；不是固定SHA快照 |
| S03 | https://github.com/bytedance/deer-flow#embedded-python-client | 嵌入式客户端入口存在 | 已读取示例；本项目adapter方法需实测 |
| S04 | https://raw.githubusercontent.com/bytedance/deer-flow/main/backend/docs/GUARDRAILS.md | 工具执行安全扩展参考 | 已读取说明；策略需要自己实现 |
| S05 | https://github.com/mims-harvard/ToolUniverse | 可选科学工具生态 | 已读取仓库说明；不作为V1必需 |
| S06 | https://clinicaltrials.gov/data-api/api | ClinicalTrials.gov API入口 | 官网页面可达；JS文档正文/实时schema未在本次成功读取 |
| S06a | https://clinicaltrials.gov/data-api/about-api | API说明 | 同上；字段映射需开发时验证 |
| S07 | https://www.ncbi.nlm.nih.gov/home/develop/api/ | E-utilities、PubMed访问范围 | 已读取官方介绍 |
| S08 | https://eutilities.github.io/site/API_Key/usageandkey/ | NCBI速率/批量访问策略 | 已读取；部署前再核对 |
| S09 | https://open.fda.gov/apis/drug/label/ | 标签的范围、非批准等价、非医疗决策 | 已读取 |
| S10 | https://open.fda.gov/apis/authentication/ | key配置与用量约束 | 已读取；有key要求与无key额度并列，项目保守要求key |
| S11 | https://open.fda.gov/apis/drug/event/ | 不良事件数据限制（后续范围） | 已读取；V1不提供该分析 |
| S12 | https://www.ncbi.nlm.nih.gov/home/about/policies/ | 数据使用政策上线核查入口 | 已读取政策页面；不声称完成具体授权/法务审查 |
| S13 | https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html | SSRF分层防护参考 | 官方安全参考；本包不是安全认证 |
| S14 | https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html | 外部文本提示注入/最小权限 | 官方安全参考 |

## 重要限制
1. 未成功取得可核验的最新commit SHA，因此upstream.lock保持null；M0必须填真实SHA，不把main当永久版本。
2. 本次未部署DeerFlow、未对真实CT.gov/PubMed记录或SMTP执行端到端集成；所有live测试初始NOT_RUN。
3. 早前原型图中真实药物名称和数据只是生成图像的演示文字，存在事实风险，不用于种子/标准答案/接口样例。
4. 外部API与软件版本可能变化，项目记录source schema version、normalizer version和锁文件；不能仅依赖本文永久运行。
5. 本包不包含受版权限制的论文全文，也不包含患者资料。fixtures是原创虚构数据。
