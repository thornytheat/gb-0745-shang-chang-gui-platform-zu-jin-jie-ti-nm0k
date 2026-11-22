from collections import Counter

from app.modules.m2_contracts.coverage import FORMAL, PROVISIONAL
from app.modules.m3_calendar.service import billable_days, prorated_floor
from app.modules.m4_tiers.progressive import charge


def calculate_period(sales, deductions, contracts, exempt, period):
    period_sales = {
        key: item for key, item in sales.items() if item["day"].isoformat()[:7] == period
    }
    active_shops = {item["shop"] for item in period_sales.values()}
    days, restrictions, month_days, day_status = billable_days(contracts, exempt, period, active_shops)
    net = Counter()
    for key, item in period_sales.items():
        net[item["shop"], item["version"]] += item["cents"] - deductions.get(key, 0)
    rows = []
    for c in contracts:
        key = (c["shop"], c["version"])
        if key not in days and key not in net:
            continue
        floor = prorated_floor(c["floor"], days[key], month_days)
        commission, bands = charge(net[key], c["tiers"])
        rows.append(
            {
                "柜台": key[0],
                "版本": key[1],
                "净销售分": net[key],
                "计租日": days[key],
                "正式日": day_status[(key[0], key[1], FORMAL)],
                "暂估日": day_status[(key[0], key[1], PROVISIONAL)],
                "保底分": floor,
                "抽成分": commission,
                "应计分": max(floor, commission),
                "选择": "保底" if floor >= commission else "抽成",
                "档段": bands,
            }
        )
    return rows, restrictions
