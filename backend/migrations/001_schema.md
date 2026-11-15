# 初始数据结构
SQLAlchemy metadata创建schema；后续版本应新增真实迁移。唯一约束为sample_batches.code、sample_units(batch_id,code)、margin_targets(batch_id,dimension,category)、weight_reviews.run_id、users.email、register_versions(batch_id,version)、correction_packages(batch_id,code)。不可用create_all做列变更。

# 更正包与底册版本(002)
- sample_units.trip_minutes/base_weight 使用DOUBLE(MySQL)，保证CSV→库→快照→CSV往返一致。
- register_versions：底册每次变更(CSV导入/更正包合并)后的完整JSON快照，(batch_id,version)唯一。
- correction_packages：更正包，状态机 pending→applied/conflict/failed；(batch_id,code)唯一保证重复投递幂等。
- correction_conflicts：字段级冲突，open/resolved；解决值随包合并强制写入。
