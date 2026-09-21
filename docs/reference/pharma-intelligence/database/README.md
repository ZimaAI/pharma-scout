# 数据库合同说明

`schema.sql` 为 PostgreSQL 初始DDL参考，**没有在本次文档生成中执行数据库迁移**。实施时转换为Alembic，测试创建/回滚策略与复合外键，再据实记录结果。

表内JSON结构由OpenAPI/JSON Schema/业务服务共同校验；数据库不能仅靠JSONB保证语义。before/after属于同一逻辑记录、approval绑定当前version、JSON内evidence_id均同workspace等业务规则需服务层事务校验。

源原始内容、规范化版本、evidence与report_version不可更新。claim保存最终一次自动核验结果，若需重验或人工改写生成新report_version；不要直接更新immutable claim。

注意循环引用：source_record.current_*、report.current_version_id等先允许空以完成同事务插入，最后设置并提交；对外GET必须保证已初始化完成，不返回悬空对象。seed先插记录再插快照/观察；始终按场景日推进，不预加载未来证据。

观察记录物理保留与日志保留区别：SSE旧事件清理如触及immutable触发器，需要专门的受审计维护迁移/角色，不能给普通worker绕过权限。清理过程不得删除仍被报告引用的证据链。
