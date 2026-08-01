# 本地向量入库状态边界

`VectorStoreService.load_document()` 现在返回有界的 `DocumentLoadSummary`，区分 loaded/skipped/failed，并对摘要缺失和异常记录固定类型；调用方不再只能依赖日志判断本轮是否部分失败。

向量写入成功后，MD5 marker 通过 flush + `os.fsync()` 追加，降低进程崩溃导致 marker 丢失的概率。向量库和 marker 仍是两个存储，不能宣称原子提交或 exactly-once：向量已写入但 marker 未写入时，下一轮可能重复处理，必须由后续批次幂等/唯一约束/任务状态解决。
