"""补签后的版本失效判断。

同一账期同一规则下，一个后写的批次只有在“没有让挂起/冲突变多、暂估日没有变多、
覆盖的柜台不缩水”时，才取代当前生效的批次。这样：

- 补签合同后重跑，新批次把暂估日转成正式日，旧暂估批次标记「已失效」；
- 暂估失败（新批次挂起或冲突变多）时，旧版继续「有效」，失败批次标「未采用」，
  不会用坏批次覆盖掉还能收款的暂估版；
- 同一份资料重跑命中同一批次号，不会多算第二份金额。

失效只是标记，被替代批次的原始载荷完整保留，随时可以追回原合同依据。
"""

OPERATIVE = "有效"
SUPERSEDED = "已失效"
REJECTED = "未采用"


def _key(run):
    """同一账期、同一规则、同一批柜台才算同一份账的先后版本。

    把柜台集合纳入标识，避免把两份互不相干的账簿（例如不同馆的月结）当成
    彼此的替代版本。
    """
    meta = run.get("运行清单", {})
    return meta.get("账期"), meta.get("规则"), frozenset(_shops(run))


def _status(run):
    return run.get(
        "覆盖状态",
        {"暂估日合计": 0, "挂起日合计": 0, "冲突日合计": 0},
    )


def _blocked(run):
    status = _status(run)
    return status.get("挂起日合计", 0) + status.get("冲突日合计", 0)


def _provisional(run):
    return _status(run).get("暂估日合计", 0)


def _shops(run):
    return {row["柜台"] for row in run.get("覆盖汇总", [])}


def supersedes(newer, older):
    """后写的批次是否取代当前生效批次。

    要求覆盖不劣化：暂估日、挂起日都不增加，柜台不缩水；并且确实让暂估或
    挂起减少。``_key`` 已保证两批柜台集合一致，这里再做一次防御。
    """
    if not _shops(newer) or _shops(newer) != _shops(older):
        return False
    if _provisional(newer) > _provisional(older):
        return False
    if _blocked(newer) > _blocked(older):
        return False
    return (
        _provisional(newer) < _provisional(older) or _blocked(newer) < _blocked(older)
    )


def supersession(entries):
    """按写入顺序计算每批次的版本状态。

    ``entries`` 为 ``[(rowid, run), ...]``，按写入先后排列。返回
    ``{批次号: {"状态": ..., "替代批次": ...}}``。同一账期只有一个「有效」批次。
    """
    operative = {}
    result = {}
    for _, run in entries:
        key = _key(run)
        run_id = run.get("运行清单", {}).get("批次")
        current = operative.get(key)
        if current is not None and supersedes(run, current):
            result[current["运行清单"]["批次"]] = {"状态": SUPERSEDED, "替代批次": run_id}
            operative[key] = run
            result[run_id] = {"状态": OPERATIVE, "替代批次": None}
        elif current is None:
            operative[key] = run
            result[run_id] = {"状态": OPERATIVE, "替代批次": None}
        else:
            # 不劣化也不改善、或明显变差的批次：保留但不作为对外版本。
            result[run_id] = {"状态": REJECTED, "替代批次": current["运行清单"]["批次"]}
    return result


def apply_status(run, status):
    run = dict(run)
    run["版本状态"] = status
    return run
