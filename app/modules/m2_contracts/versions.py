from datetime import date

from app.errors import InputError
from app.modules.m1_intake.amounts import cents
from app.modules.m1_intake.service import transaction_key


def normalize_contracts(records):
    versions = []
    keys = set()
    for item in records:
        try:
            shop = transaction_key(item, "shop")
            version = transaction_key(item, "version")
            start, end = date.fromisoformat(item["start"]), date.fromisoformat(item["end"])
            if start >= end or (shop, version) in keys:
                raise ValueError("合同版本重复或日期无效")
            rates = item["tiers"]
            if not isinstance(rates, list) or not rates or len(rates) > 12 or rates[-1][0] is not None:
                raise ValueError("阶梯须以无上限档结束")
            tiers = []
            previous = 0
            for index, (ceiling, points) in enumerate(rates):
                limit = cents(ceiling) if ceiling is not None else None
                if (limit is None and index != len(rates) - 1) or (limit is not None and limit <= previous):
                    raise ValueError("档位边界须严格递增")
                if type(points) is not int or not 0 <= points <= 10000:
                    raise ValueError("费率须为万分比整数")
                tiers.append((limit, points))
                previous = limit
            guarantee = cents(item["minimum"])
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            raise InputError("BAD_CONTRACT", "合同、日期或阶梯费率无效") from exc
        keys.add((shop, version))
        versions.append(
            dict(shop=shop, version=version, start=start, end=end, floor=guarantee, tiers=tiers)
        )
    return sorted(versions, key=lambda row: (row["shop"], row["start"], row["version"]))


def version_on(contracts, shop, day):
    matched = [c for c in contracts if c["shop"] == shop and c["start"] <= day < c["end"]]
    if len(matched) != 1:
        return None, "OVERLAP" if matched else "NO_CONTRACT"
    return matched[0], None


def predecessor_candidates(contracts, shop, day):
    """空档期顺延暂估的候选：已经结束且结束日不晚于当日、结束日最晚的合同。

    正常情况下只有一版；若历史合同交叠导致多版同日结束，则候选不唯一，
    调用方不得擅自选一版，应把该日判为暂估失败。
    """
    ended = [c for c in contracts if c["shop"] == shop and c["end"] <= day]
    if not ended:
        return []
    latest_end = max(c["end"] for c in ended)
    return [c for c in ended if c["end"] == latest_end]
