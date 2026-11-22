"""合同覆盖：逐柜台逐营业日判定该日按正式合同、上一版条款暂估，还是挂起。

暂估只在“合同已到期、新合同尚未签”的空档期使用，且必须满足：
- 能找到唯一一版已经结束、结束日不晚于当日的合同作为依据；
- 空档没有超过 ``PROVISIONAL_MAX_DAYS``，避免柜台已停业却继续凭空计租。

暂估不是第二份对外金额：它和正式日共用同一套计费口径，按受理版本合并计算，
每个柜台最终只产生一个应缴数。
"""
from app.config import PROVISIONAL_MAX_DAYS
from app.modules.m2_contracts.versions import predecessor_candidates, version_on
from app.modules.m3_calendar.month import days_between, month_window

FORMAL = "正式"
PROVISIONAL = "暂估"
HOLD = "挂起"
CONFLICT = "冲突"

HOLD_LABELS = {
    "NO_PREDECESSOR": "无上一版合同可依",
    "AMBIGUOUS_PREDECESSOR": "上一版合同不唯一",
    "PROVISIONAL_EXPIRED": "空档超过暂估期限",
}


def resolve_day(contracts, shop, day):
    """返回某柜台某日的合同依据。

    ``status`` 为 ``正式``/``暂估``/``挂起``/``冲突``。挂起时 ``basis`` 仍可能
    保留候选版本，便于追回原合同依据；``candidates`` 列出所有候选版本。
    """
    contract, error = version_on(contracts, shop, day)
    if contract is not None:
        return {
            "status": FORMAL,
            "contract": contract,
            "basis": contract["version"],
            "reason": None,
            "gap_days": 0,
            "candidates": [contract["version"]],
        }
    if error == "OVERLAP":
        return {
            "status": CONFLICT,
            "contract": None,
            "basis": None,
            "reason": "OVERLAP",
            "gap_days": 0,
            "candidates": [],
        }
    candidates = predecessor_candidates(contracts, shop, day)
    versions = sorted({c["version"] for c in candidates})
    if not versions:
        return {
            "status": HOLD,
            "contract": None,
            "basis": None,
            "reason": "NO_PREDECESSOR",
            "gap_days": None,
            "candidates": [],
        }
    if len(versions) != 1:
        # 历史合同交叠，无法判断哪一版是“上一版”，宁可挂起也不猜。
        return {
            "status": HOLD,
            "contract": None,
            "basis": None,
            "reason": "AMBIGUOUS_PREDECESSOR",
            "gap_days": None,
            "candidates": versions,
        }
    previous = candidates[0]
    gap_days = (day - previous["end"]).days + 1
    if gap_days > PROVISIONAL_MAX_DAYS:
        return {
            "status": HOLD,
            "contract": previous,
            "basis": previous["version"],
            "reason": "PROVISIONAL_EXPIRED",
            "gap_days": gap_days,
            "candidates": versions,
        }
    return {
        "status": PROVISIONAL,
        "contract": previous,
        "basis": previous["version"],
        "reason": None,
        "gap_days": gap_days,
        "candidates": versions,
    }


def coverage_segments(contracts, period, active_shops=()):
    """压缩成连续区间，供结算页面逐柜台展示暂估日与正式日。"""
    start, end = month_window(period)
    shops = {c["shop"] for c in contracts if c["start"] < end} | set(active_shops)
    segments = []
    for shop in sorted(shops):
        run = None
        for day in days_between(start, end):
            resolved = resolve_day(contracts, shop, day)
            signature = (resolved["status"], resolved["basis"], resolved["reason"])
            if run is not None and run["signature"] == signature:
                run["end"] = day
                run["days"] += 1
                continue
            if run is not None:
                segments.append(_segment(shop, run))
            run = {
                "signature": signature,
                "start": day,
                "end": day,
                "days": 1,
                "status": resolved["status"],
                "basis": resolved["basis"],
                "reason": resolved["reason"],
                "candidates": resolved["candidates"],
            }
        if run is not None:
            segments.append(_segment(shop, run))
    return segments


def _segment(shop, run):
    reason = run["reason"]
    note = HOLD_LABELS.get(reason, "") if run["status"] == HOLD else ""
    return {
        "柜台": shop,
        "状态": run["status"],
        "起始": run["start"].isoformat(),
        "截止": run["end"].isoformat(),
        "天数": run["days"],
        "依据版本": run["basis"],
        "候选版本": list(run["candidates"]),
        "说明": "合同重叠" if run["status"] == CONFLICT else note,
    }


def shop_coverage(segments):
    """按柜台汇总状态天数，供对账页显示，不引入第二个对外金额。"""
    summary = {}
    for segment in segments:
        row = summary.setdefault(
            segment["柜台"],
            {"柜台": segment["柜台"], "正式日": 0, "暂估日": 0, "挂起日": 0, "冲突日": 0, "暂估依据": []},
        )
        key = {
            FORMAL: "正式日",
            PROVISIONAL: "暂估日",
            HOLD: "挂起日",
            CONFLICT: "冲突日",
        }[segment["状态"]]
        row[key] += segment["天数"]
        if segment["状态"] == PROVISIONAL and segment["依据版本"] not in row["暂估依据"]:
            row["暂估依据"].append(segment["依据版本"])
    return [summary[shop] for shop in sorted(summary)]


def coverage_state(segments):
    """整批的暂估/挂起概览，用于批次状态与补签后的替代判断。"""
    provisional = sum(s["天数"] for s in segments if s["状态"] == PROVISIONAL)
    held = sum(s["天数"] for s in segments if s["状态"] == HOLD)
    conflict = sum(s["天数"] for s in segments if s["状态"] == CONFLICT)
    if held or conflict:
        status = "含挂起"
    elif provisional:
        status = "暂估中"
    else:
        status = "无暂估"
    return {
        "状态": status,
        "暂估日合计": provisional,
        "挂起日合计": held,
        "冲突日合计": conflict,
    }
