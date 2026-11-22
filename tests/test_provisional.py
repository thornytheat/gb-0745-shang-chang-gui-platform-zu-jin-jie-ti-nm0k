from pathlib import Path

import pytest
from app.modules.m2_contracts.coverage import (
    HOLD,
    PROVISIONAL,
    coverage_segments,
    coverage_state,
    resolve_day,
    shop_coverage,
)
from app.modules.m7_publish.service import calculate, run_once
from app.modules.m7_publish.supersede import REJECTED, SUPERSEDED, supersession
from app.store import RunStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def gap():
    return (ROOT / "sample_data" / "gap.json").read_bytes()


@pytest.fixture(scope="module")
def gap_run(gap):
    return calculate(gap, "2026-11")


def _segment(segments, shop):
    return [row for row in segments if row["柜台"] == shop]


def test_mid_month_signing_splits_provisional_and_formal(gap_run):
    segments = _segment(gap_run["合同覆盖"], "001")
    assert [(row["状态"], row["起始"], row["截止"], row["依据版本"]) for row in segments] == [
        ("暂估", "2026-11-01", "2026-11-05", "N-A"),
        ("正式", "2026-11-06", "2026-11-30", "N-B"),
    ]


def test_each_shop_has_single_outward_amount(gap_run):
    rows = [row for row in gap_run["柜台对账"] if row["柜台"] == "001"]
    assert len(rows) == 1
    # 暂估日 5 天 + 正式日 25 天合并在同一柜台的一个应缴数里。
    assert rows[0]["应缴分"] == 28000
    # 合同月清单按版本分行，但柜台对账只有一行。
    versions = {row["版本"] for row in gap_run["分段核算"] if row["柜台"] == "001"}
    assert versions == {"N-A", "N-B"}


def test_provisional_days_counted_in_billing(gap_run):
    summary = next(row for row in gap_run["覆盖汇总"] if row["柜台"] == "001")
    assert (summary["正式日"], summary["暂估日"]) == (25, 5)
    assert summary["暂估依据"] == ["N-A"]


def test_full_month_gap_remains_provisional(gap_run):
    summary = next(row for row in gap_run["覆盖汇总"] if row["柜台"] == "002")
    assert (summary["正式日"], summary["暂估日"]) == (0, 30)


def test_prior_version_used_when_gap_crosses_month():
    from app.modules.m2_contracts.versions import normalize_contracts

    contracts = normalize_contracts(
        [
            {
                "shop": "001",
                "version": "N-OLD",
                "start": "2026-09-01",
                "end": "2026-11-01",
                "minimum": "0",
                "tiers": [[None, 1000]],
            }
        ]
    )
    resolved = resolve_day(contracts, "001", __import__("datetime").date(2026, 11, 20))
    assert resolved["status"] == PROVISIONAL
    assert resolved["basis"] == "N-OLD"


def test_no_predecessor_holds_without_guessing():
    from app.modules.m2_contracts.versions import normalize_contracts

    contracts = normalize_contracts(
        [
            {
                "shop": "009",
                "version": "N-1",
                "start": "2026-12-01",
                "end": "2027-01-01",
                "minimum": "0",
                "tiers": [[None, 1000]],
            }
        ]
    )
    resolved = resolve_day(contracts, "009", __import__("datetime").date(2026, 11, 10))
    assert (resolved["status"], resolved["reason"]) == (HOLD, "NO_PREDECESSOR")


def test_expired_gap_holds_and_keeps_basis(gap_run):
    summary = next(row for row in gap_run["覆盖汇总"] if row["柜台"] == "004")
    assert summary["挂起日"] == 30
    segments = _segment(gap_run["合同覆盖"], "004")
    assert segments[0]["状态"] == "挂起"
    # 原合同依据仍可追回。
    assert segments[0]["依据版本"] == "N-A"


def test_ambiguous_predecessor_holds(gap_run):
    summary = next(row for row in gap_run["覆盖汇总"] if row["柜台"] == "005")
    assert summary["挂起日"] == 30
    segments = _segment(gap_run["合同覆盖"], "005")
    assert segments[0]["候选版本"] == ["N-P", "N-Q"]
    assert segments[0]["说明"] == "上一版合同不唯一"


def test_held_sales_are_isolated_with_reason(gap_run):
    codes = {(row["流水号"], row["原因码"]) for row in gap_run["隔离"]}
    assert ("G005", "PROVISIONAL_EXPIRED") in codes
    assert ("G006", "PROVISIONAL_AMBIGUOUS") in codes
    assert ("G004", "NO_CONTRACT") in codes


def test_resigning_turns_provisional_into_formal(gap):
    import json

    data = json.loads(gap)
    data["contracts"].append(
        {
            "shop": "002",
            "version": "N-B",
            "start": "2026-11-01",
            "end": "2027-01-01",
            "minimum": "300",
            "tiers": [["1000", 1000], [None, 2000]],
        }
    )
    # 新合同从月初生效后，002 不再需要暂估。
    rerun = calculate(json.dumps(data, ensure_ascii=False).encode(), "2026-11")
    summary = next(row for row in rerun["覆盖汇总"] if row["柜台"] == "002")
    assert (summary["正式日"], summary["暂估日"]) == (30, 0)
    assert rerun["覆盖状态"]["暂估日合计"] < calculate(gap, "2026-11")["覆盖状态"]["暂估日合计"]


def test_supersession_marks_old_provisional_invalid(gap_run, gap):
    import json

    data = json.loads(gap)
    # 补签合同把 N-B 的生效日提前到月初，空档消失。
    for contract in data["contracts"]:
        if contract["shop"] == "001" and contract["version"] == "N-B":
            contract["start"] = "2026-11-01"
    signed = calculate(json.dumps(data, ensure_ascii=False).encode(), "2026-11")
    entries = [(1, gap_run), (2, signed)]
    status = supersession(entries)
    assert status[gap_run["运行清单"]["批次"]]["状态"] == SUPERSEDED
    assert status[gap_run["运行清单"]["批次"]]["替代批次"] == signed["运行清单"]["批次"]
    assert status[signed["运行清单"]["批次"]]["状态"] == "有效"


def test_failed_rerun_keeps_old_provisional(gap_run, gap):
    import json

    # 删掉合同：暂估依据丢失，新批次只能挂起，属暂估失败。
    data = json.loads(gap)
    data["contracts"] = [c for c in data["contracts"] if c["shop"] != "002"]
    failed = calculate(json.dumps(data, ensure_ascii=False).encode(), "2026-11")
    status = supersession([(1, gap_run), (2, failed)])
    assert status[gap_run["运行清单"]["批次"]]["状态"] == "有效"
    assert status[failed["运行清单"]["批次"]]["状态"] == REJECTED


def test_rerunning_same_input_does_not_double_count(tmp_path, gap):
    store = RunStore(tmp_path / "gap.sqlite")
    first, reused_first = run_once(store, gap, "2026-11")
    second, reused_second = run_once(store, gap, "2026-11")
    assert (reused_first, reused_second) == (False, True)
    assert first["运行清单"]["批次"] == second["运行清单"]["批次"]
    assert second["金额勾稽"] == first["金额勾稽"]
    assert len(store.entries()) == 1


def test_superseded_batch_still_traceable(tmp_path, gap):
    import json

    store = RunStore(tmp_path / "trace.sqlite")
    original, _ = run_once(store, gap, "2026-11")
    data = json.loads(gap)
    # 补签合同把 N-B 的生效日提前到月初，空档消失。
    for contract in data["contracts"]:
        if contract["shop"] == "001" and contract["version"] == "N-B":
            contract["start"] = "2026-11-01"
    signed, _ = run_once(store, json.dumps(data, ensure_ascii=False).encode(), "2026-11")
    reloaded = store.get(original["运行清单"]["批次"])
    assert reloaded["版本状态"]["状态"] == SUPERSEDED
    # 失效批次仍保留完整载荷，原合同依据可追回。
    assert reloaded["合同覆盖"]
    assert any(row["依据版本"] == "N-A" for row in reloaded["合同覆盖"])
    assert store.get(signed["运行清单"]["批次"])["版本状态"]["状态"] == "有效"


def test_api_reports_coverage_and_status(client, gap):
    import io

    first = client.post("/api/runs", data={"sample": "gap", "file": (io.BytesIO(gap), "gap.json")})
    assert first.status_code == 201
    assert first.json["coverage"]["暂估日合计"] == 35
    assert first.json["status"] == "有效"
    contracts = client.get(f"/api/contracts/{first.json['id']}").json
    assert contracts["覆盖汇总"][0]["柜台"] == "001"
    assert contracts["覆盖状态"]["状态"] == "含挂起"


def test_unrelated_ledgers_do_not_supersede_each_other(clean_run, gap_run):
    # 同为 2026-11、同规则，但柜台集合不同，属不同账簿，不能互相判失效。
    status = supersession([(1, clean_run), (2, gap_run)])
    assert status[clean_run["运行清单"]["批次"]]["状态"] == "有效"
    assert status[gap_run["运行清单"]["批次"]]["状态"] == "有效"
