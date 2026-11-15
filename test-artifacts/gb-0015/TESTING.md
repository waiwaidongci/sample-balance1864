# TESTING · 样本更正包合并(gb-0015)

## 范围

机构离线更正样本的更正包合并：字段级三向合并、冲突裁决、前序依赖乱序级联、
并发/中断/重投幂等、底册版本快照下载、历史校准运行按原样本交付。

## 测试位置与运行

```sh
cd test-artifacts/gb-0015 && python3 -m pytest . -q
```

- `test_merge_engine.py`：纯函数三向合并引擎，不依赖数据库与Web框架(6用例)。
- `test_correction_api.py`：FastAPI TestClient + SQLite 文件库 + 内存队列桩，
  覆盖 HTTP 层全链路(19用例)。SQLite 无行锁语义，生产 MySQL 的
  `SELECT ... FOR UPDATE` 串行化由 `lock_batch` 按方言启用。

## 覆盖与结论(25 passed)

| 需求 | 用例 | 结果 |
|---|---|---|
| 不同字段独立改动合并保留 | test_independent_field_changes_merge、引擎 test_independent_fields_merge | 通过 |
| 同字段不同新值列出冲突 | test_same_field_different_values_conflict_and_resolve、引擎 test_divergent_same_field_is_conflict | 通过 |
| 同字段相同新值幂等收敛 | test_same_new_value_converges_without_conflict、引擎 test_convergent_same_new_value_is_not_conflict | 通过 |
| 包内全部成功才更新底册 | test_package_atomicity_unknown_code(一行未知编号→整包failed，底册与版本零变化) | 通过 |
| 依赖未到达→乱序级联 | test_out_of_order_dependency_cascade(先到后继pending并给出原因，前序到达后自动级联) | 通过 |
| 冲突阻塞后继不挡独立包 | test_conflict_blocks_dependents_but_not_independent | 通过 |
| 中断恢复结果相同 | test_recovery_matches_normal_processing(直接落库pending包，recover_corrections后与应用路径结果一致，重复恢复无副作用) | 通过 |
| 重复投递不重复写入 | test_duplicate_delivery_idempotent(同内容返回原包不增版本；同代码异内容409) | 通过 |
| 失败包同代码修正重投 | test_failed_package_redelivery_with_same_code | 通过 |
| 底册版本下载 | test_import_applies_and_versions_downloadable(v1/v2快照CSV内容正确) | 通过 |
| 冲突裁决(传入/当前/自定义) | test_same_field_different_values_conflict_and_resolve、test_resolve_keep_current_and_custom_value、test_partial_resolution_rejected(必须一次性裁决全部开放冲突) | 通过 |
| 待处理原因可查 | 依赖缺失/前序冲突/冲突数/校验失败均经 reason 字段断言 | 通过 |
| 旧校准结果按原样本交付 | test_historical_run_delivers_original_samples(合并后底册已变，运行快照与导出CSV仍为原值) | 通过 |
| 权限与输入校验 | test_permissions_and_validation(viewer只读、自依赖/未知基线/坏CSV 422、CSV导入重复编号409并提示更正包) | 通过 |

另验证：种子脚本连跑两次幂等(版本4、包2、冲突0不变)；MySQL方言下
建表(DOUBLE/JSON/唯一约束)与 `FOR UPDATE` 语句经 SQLAlchemy 编译检查；
uvicorn 真实进程冒烟(健康检查、登录、级联、冲突、裁决、幂等重投、审计)通过。

## 并发口径说明

并发合并等价于串行：每个批次的导入/合并/裁决/恢复都先取批次行锁
(MySQL InnoDB `SELECT ... FOR UPDATE`)，每个包的应用是独立事务，
状态机 pending→applied/conflict/failed 单调前进。SQLite 测试环境无法复现
行锁竞争，该路径以确定性重放(恢复扫描==正常处理)间接验证。
