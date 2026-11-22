from collections import Counter
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.errors import InputError
from app.modules.m1_intake.service import transaction_key
from app.modules.m2_contracts.coverage import FORMAL, HOLD, PROVISIONAL, resolve_day
from app.modules.m3_calendar.month import days_between, month_window


def exempt_days(rows):
    try:
        return {(transaction_key(row, "shop"), date.fromisoformat(row["day"])) for row in rows}
    except (ValueError, KeyError, TypeError) as exc:
        raise InputError("BAD_HOLIDAY", "免租日期或柜台无效") from exc


def billable_days(contracts, exempt, period, active_shops=()):
    """按合同覆盖把当月每一天归到“正式”或“暂估”的受理版本。

    暂估日沿用上一版条款计入同一版本，因此每个柜台对外仍只有一个应缴数；
    没有可依依据的日子（无上一版、上一版不唯一、空档超窗、合同重叠）不计租，
    单列在日历例外里，原合同依据随行保留以便追回。

    ``active_shops`` 是本月确有销售、但合同在本月前已到期的柜台，用于给跨月
    空档寻找上一版条款；没有销售又无合同覆盖的柜台不参与计租。
    """
    days = Counter()
    day_status = Counter()
    exceptions = []
    start, end = month_window(period)
    shops = {c["shop"] for c in contracts if c["start"] < end} | set(active_shops)
    for shop in sorted(shops):
        for day in days_between(start, end):
            resolved = resolve_day(contracts, shop, day)
            if (shop, day) in exempt:
                exceptions.append(
                    {
                        "柜台": shop,
                        "日期": day.isoformat(),
                        "状态": "免保底",
                        "依据版本": resolved["basis"],
                    }
                )
                continue
            if resolved["status"] in (FORMAL, PROVISIONAL):
                days[(shop, resolved["basis"])] += 1
                day_status[(shop, resolved["basis"], resolved["status"])] += 1
                continue
            exceptions.append(
                {
                    "柜台": shop,
                    "日期": day.isoformat(),
                    "状态": _exception_label(resolved),
                    "依据版本": resolved["basis"],
                    "候选版本": resolved["candidates"],
                }
            )
    return days, exceptions, (end - start).days, day_status


def _exception_label(resolved):
    if resolved["status"] == HOLD:
        return {
            "NO_PREDECESSOR": "合同空档",
            "AMBIGUOUS_PREDECESSOR": "上一版不唯一",
            "PROVISIONAL_EXPIRED": "空档超暂估期",
        }.get(resolved["reason"], "合同空档")
    return "版本冲突"


def prorated_floor(monthly_floor, billable, month_days):
    return int(
        (Decimal(monthly_floor) * billable / month_days).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    )
