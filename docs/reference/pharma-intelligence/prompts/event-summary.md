# 事件差异说明提示模板 v1.0

输入是服务端确定性生成的changes及对应前后观察。只把字段变化解释为易读研究记录，不扩写临床结果。
必须区分注册记录source_updated、系统observed和真正有来源的事件日期。初次记录只能说建立基线；同内容重抓不生成新进展。
若estimated人数从120到160，表述为“目标入组数量调整”，不是“新增40名已入组受试者”。如果来源更正或回退，说明相对前次观察的变化，保留历史。
输出title、summary、change_category、evidence_ids、limitations。无证据医学解释不允许出现。
