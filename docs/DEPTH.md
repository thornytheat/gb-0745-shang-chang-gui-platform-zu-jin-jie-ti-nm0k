# 深度登记 商场柜台租金阶梯

- 规模：中型
- 核心规则：版本保底与累进抽成后，将旧期退单定位到原版本、重新计算应计租金并入本期差额。
- 使用者与流程：商场运营结算员导入收银、合同、免租和缴款四本账，逐柜台核账并留档。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 收银采信 | 上传账簿，隔离坏金额和同号矛盾 | `GET /api/intake/{id}` | `app/modules/m1_intake/service.py` `app/modules/m1_intake/amounts.py` | `tests/test_intake.py` |
| M2 合同版本 | 查销售日的合同、重叠区间与暂估/正式覆盖 | `GET /api/contracts/{id}` | `app/modules/m2_contracts/versions.py` `app/modules/m2_contracts/coverage.py` `app/modules/m2_contracts/service.py` | `tests/test_contracts.py` `tests/test_provisional.py` |
| M3 免租日历 | 查看合同日历、免租日期和保底折算 | `GET /api/calendar/{id}` | `app/modules/m3_calendar/month.py` `app/modules/m3_calendar/service.py` | `tests/test_calendar.py` |
| M4 累进抽成 | 对照档位费用与版本保底 | `GET /api/tiers/{id}` | `app/modules/m4_tiers/progressive.py` `app/modules/m4_tiers/service.py` | `tests/test_tiers.py` |
| M5 退单回冲 | 追原流水，重算旧月应计差 | `GET /api/refunds/{id}` | `app/modules/m5_refunds/credits.py` `app/modules/m5_refunds/service.py` | `tests/test_refunds.py` |
| M6 租金勾稽 | 核对实缴、欠缴与账簿行数 | `GET /api/reconcile/{id}` | `app/modules/m6_reconcile/service.py` `app/modules/m6_reconcile/totals.py` | `tests/test_reconcile.py` |
| M7 结算复核 | 从批次凭证复算、下载证据 | `GET /api/publish/{id}` `POST /api/runs` | `app/modules/m7_publish/service.py` `app/modules/m7_publish/export.py` `app/store.py` | `tests/test_publish.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现会怎样 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-06 | `mall.json` 含全角千分位 | 金额解析失败 | 归一后严格解析 | `app/modules/m1_intake/amounts.py` | `tests/test_intake.py::test_normalized_thousands` |
| TRAP-07 | `mall.json` 收银金额为 N/A | 当零元销售 | 隔离带原因码 | `app/modules/m1_intake/service.py` | `tests/test_intake.py::test_missing_amount_isolated` |
| TRAP-08 | `mall.json` 柜台号有前导零 | 归并时丢失 | 按字符串处理 | `app/modules/m1_intake/service.py` | `tests/test_intake.py::test_leading_zero_and_long_id` |
| TRAP-10 | 费率产生半分 | 浮点或分档舍入偏差 | 按费率整数分子汇总后统一舍入 | `app/modules/m4_tiers/progressive.py` | `tests/test_tiers.py::test_half_up_precise` |
| TRAP-13 | `mall.json` 退单在原销售前读到 | 当成缺原单 | 按业务日归档后匹配 | `app/modules/m5_refunds/credits.py` | `tests/test_refunds.py::test_out_of_order_matched` |
| TRAP-14 | `mall.json` 重复流水金额有差 | 后写覆盖 | 两条都隔离并保留行号 | `app/modules/m1_intake/service.py` | `tests/test_intake.py::test_conflicts_quarantine_both` |
| TRAP-15 | `mall.json` 金额单位混合 | 误把分计为元 | 归一为整数分 | `app/modules/m1_intake/amounts.py` | `tests/test_intake.py::test_unit_is_applied` |
| TRAP-16 | `clean.json` 剪去尾部 | 误入部分交易 | 拒绝结构断裂 | `app/modules/m1_intake/reader.py` | `tests/test_intake.py::test_truncated_source` |
| TRAP-17 | `mall.json` 旧金额字段 gross | 旧账对应列丢失 | 显式兼容别名 | `app/modules/m1_intake/service.py` | `tests/test_intake.py::test_legacy_alias` |
| TRAP-23 | `mall.json` 合同于当日切换 | 同时计入两个版本 | 合同 `[start,end)` | `app/modules/m2_contracts/versions.py` | `tests/test_contracts.py::test_adjacent_boundaries` |
| TRAP-25 | `mall.json` 存在合同重叠 | 随机采信一版 | 暂停区间内归属并提供冲突区间 | `app/modules/m2_contracts/service.py` | `tests/test_contracts.py::test_overlap_not_guessed` |
| TRAP-31 | `gap.json` 合同到期后仍营业 | 空档期销售当缺合同丢弃、本期收款断档 | 顺延上一版条款暂估，正式/暂估合并到同一柜台金额 | `app/modules/m2_contracts/coverage.py` | `tests/test_provisional.py::test_mid_month_signing_splits_provisional_and_formal` |
| TRAP-32 | `gap.json` 补签只从中段生效 | 前段凭空空转或重复计一份暂估 | 逐日拆分正式/暂估区间，同一柜台只出一个应缴数 | `app/modules/m2_contracts/coverage.py` `app/modules/m4_tiers/service.py` | `tests/test_provisional.py::test_each_shop_has_single_outward_amount` |
| TRAP-33 | `gap.json` 空档超期或上一版不唯一 | 无限顺延或随机挑一版 | 判为暂估失败并挂起，保留候选依据 | `app/modules/m2_contracts/coverage.py` | `tests/test_provisional.py::test_expired_gap_holds_and_keeps_basis` `tests/test_provisional.py::test_ambiguous_predecessor_holds` |
| TRAP-34 | 补签后重跑旧暂估 | 旧版仍对外、两版金额并存 | 新批次减少暂估后旧批标 `已失效`，载荷与依据保留 | `app/modules/m7_publish/supersede.py` | `tests/test_provisional.py::test_supersession_marks_old_provisional_invalid` |
| TRAP-35 | 补签重跑同一份资料 | 重复计同一笔销售 | 摘要/账期/规则决定同一批次，不再新增 | `app/store.py` `app/manifest.py` | `tests/test_provisional.py::test_rerunning_same_input_does_not_double_count` |
| TRAP-36 | 暂估失败的新批次 | 坏批次覆盖还能收款的暂估版 | 旧版保持 `有效`，失败批次标 `未采用` | `app/modules/m7_publish/supersede.py` | `tests/test_provisional.py::test_failed_rerun_keeps_old_provisional` |

## 验算

`clean.json` 中 001 柜台的本月净销售 1400 元。前 1000 元按 10%，后 400 元按 20%，抽成为 180 元。旧期退单使原月应计由 130 调整为 110 元。本期应缴 160 元，与实缴平账。

## 已知不覆盖

单场结算以自然月为周期，适用内置样本所示合同规则。跨币种租金、税额和历史更正审批由外围系统处理。
