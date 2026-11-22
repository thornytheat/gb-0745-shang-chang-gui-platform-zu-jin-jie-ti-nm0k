from app.modules.m2_contracts.coverage import FORMAL, HOLD, PROVISIONAL, resolve_day
from app.reasons import issue


def bind_sales(contracts, events):
    """把销售绑定到计费版本。

    正式日按当日合同；空档日按上一版条款暂估并标记 ``暂估``；无可依依据的
    日子按原因码隔离，不进入计费。暂估销售与正式销售共享同一份净额和保底，
    不会在每个柜台上形成第二份对外金额。
    """
    sales, isolated = {}, []
    for event in events:
        if event["kind"] != "sale":
            continue
        resolved = resolve_day(contracts, event["shop"], event["day"])
        if resolved["status"] == FORMAL:
            sales[event["id"]] = {**event, "version": resolved["basis"], "basis": FORMAL}
            continue
        if resolved["status"] == PROVISIONAL:
            sales[event["id"]] = {**event, "version": resolved["basis"], "basis": PROVISIONAL}
            continue
        code = "OVERLAP" if resolved["status"] != HOLD else resolved["reason"]
        isolated.append(issue(event["line"], _reason_code(code), event["id"]))
    return sales, isolated


_HOLD_REASON = {
    "NO_PREDECESSOR": "NO_CONTRACT",
    "AMBIGUOUS_PREDECESSOR": "PROVISIONAL_AMBIGUOUS",
    "PROVISIONAL_EXPIRED": "PROVISIONAL_EXPIRED",
}


def _reason_code(code):
    # 隔离原因码沿用既有词汇；暂估失败的两类另给明确码，便于结算页复看。
    return _HOLD_REASON.get(code, code)


def version_conflicts(contracts):
    conflicts = []
    for index, left in enumerate(contracts):
        for right in contracts[index + 1 :]:
            if left["shop"] != right["shop"] or right["start"] >= left["end"]:
                break
            conflicts.append(
                {
                    "柜台": left["shop"],
                    "版本甲": left["version"],
                    "版本乙": right["version"],
                    "起始": right["start"].isoformat(),
                    "截止": min(left["end"], right["end"]).isoformat(),
                }
            )
    return conflicts
