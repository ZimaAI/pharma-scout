# 文档包静态校验结果

生成日期：2026-09-21。以下仅验证文档与样例，不代表平台软件已实现。

- PASS：All JSON files parse
- PASS：68 OpenAPI operations: refs, unique IDs, path parameters and response presence checked
- PASS：Standalone JSON Schemas pass Draft202012 meta-schema and local reference checks
- PASS：All typed fixtures validate against the API schemas
- PASS：Fixture snapshot hashes, evidence locators, quote hashes and workspace refs are consistent
- PASS：Repeated observation and content-reversion fixtures preserve the expected history
- PASS：Sample report has known evidence/claim/event refs and does not use future evidence
- PASS：All explicit local Markdown links resolve
- PASS：32 SQL table declarations and textual FK target names are consistent (SQL NOT executed)
- PASS：26 Gherkin scenarios present (step definitions NOT implemented)

未执行：PostgreSQL建表/迁移、完整OpenAPI规范验证器、DeerFlow运行、真实来源/模型、浏览器E2E、SMTP投递。
