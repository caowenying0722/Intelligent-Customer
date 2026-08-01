# 备份与恢复边界

当前默认应用使用内存会话，进程重启会丢失该状态，因此不存在可宣称的默认会话备份能力。`DATABASE_URL` 配置后才会选择 SQLAlchemy repository；生产 PostgreSQL 的备份策略、对象存储和恢复演练尚未接入仓库自动化。

在实现正式备份前：

1. 记录数据库 URL、Alembic revision 和 tenant 范围，但不要把凭证写入报告或日志；
2. 使用 PostgreSQL 原生受控备份工具生成加密、带保留周期的备份；
3. 在隔离环境执行 restore，再运行 migration/readiness/API 跨实例 smoke；
4. 恢复失败时保持旧实例只读或停止写入，避免将不完整数据标记为 active。

本文件不把 SQLite 测试迁移或内存 repository 当作生产备份证明。
