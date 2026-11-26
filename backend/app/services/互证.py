from __future__ import annotations
import sqlite3
from app.db import 连接
from app.services.时间 import 此刻


def _首值(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] is not None and d[k] != "":
            return d[k]
    return default


def _规范时钟票(r) -> dict:
    """把一行影子/裁决归一成中文字段；兼容英文列名夹具与不同命名习惯。"""
    d = dict(r)
    英文风 = (not d.get("判定")) and bool(d.get("verdict"))
    if 英文风:
        return {
            "裁决号": str(_首值(d, "verdict_id", "裁决号", "id", "票号", "uuid", default="")),
            "事件号": str(_首值(d, "event_id", "事件号", "eid", default="")),
            "秒差": int(_首值(d, "skew_seconds", "秒差", "skew", "clock_skew", default=0) or 0),
            "容忍上限秒": int(_首值(d, "tolerance_seconds", "容忍上限秒", "tolerance", "limit", default=40) or 40),
            "判定": str(_首值(d, "verdict", "判定", "结论", "result", default="")),
            "受理": int(_首值(d, "accepted", "受理", "allowed", default=1) or 0),
            "上限档": str(_首值(d, "tier", "上限档", default="")),
        }
    return {
        "裁决号": str(_首值(d, "裁决号", "verdict_id", "id", "票号", "uuid", default="")),
        "事件号": str(_首值(d, "事件号", "event_id", "eid", default="")),
        "秒差": int(_首值(d, "秒差", "skew_seconds", "skew", default=0) or 0),
        "容忍上限秒": int(_首值(d, "容忍上限秒", "tolerance_seconds", "tolerance", default=40) or 40),
        "判定": str(_首值(d, "判定", "verdict", "结论", default="")),
        "受理": int(_首值(d, "受理", "accepted", "allowed", default=1) or 0),
        "上限档": str(_首值(d, "上限档", "tier", default="")),
    }


def 对账时钟(事件号: str | None = None) -> dict:
    """验签对账（只读）：按每行冻结的 秒差/容忍上限秒 重算真相。

    不信可能被争用写花的“判定”文案：秒差 > 行当量上限即为超限；
    超限却写“容忍内通过”的影子/现行票点名为假绿，双轨不同票也算异常。
    本函数绝不 INSERT/UPDATE/DELETE。
    """
    conn = 连接()
    try:
        表们 = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        影子表 = ["验签影子"] + [
            n for n in 表们
            if n != "验签影子" and ("影子" in n or "shadow" in n.lower())
        ]
        影子: list[dict] = []
        for 表 in 影子表:
            try:
                if 事件号:
                    rows = conn.execute(
                        f"SELECT * FROM {表} WHERE 事件号=? OR event_id=? ORDER BY rowid",
                        (事件号, 事件号),
                    ).fetchall()
                else:
                    rows = conn.execute(f"SELECT * FROM {表} ORDER BY rowid").fetchall()
                影子.extend(_规范时钟票(r) for r in rows)
            except sqlite3.Error:
                # 别名表可能没有 事件号/event_id 列；退化为全表扫描。
                try:
                    rows = conn.execute(f"SELECT * FROM {表} ORDER BY rowid").fetchall()
                    影子.extend(_规范时钟票(r) for r in rows)
                except sqlite3.Error:
                    continue

        try:
            if 事件号:
                vrows = conn.execute(
                    "SELECT * FROM 验签裁决 WHERE 事件号=? ORDER BY rowid", (事件号,)
                ).fetchall()
            else:
                vrows = conn.execute("SELECT * FROM 验签裁决 ORDER BY rowid").fetchall()
            现行 = {_规范时钟票(r)["裁决号"]: _规范时钟票(r) for r in vrows}
        except sqlite3.Error:
            现行 = {}
    finally:
        conn.close()

    超限影子: list[str] = []
    误标影子: list[str] = []
    容忍内通过号: list[str] = []
    双轨异常: list[str] = []
    假绿现行: list[str] = []
    明细: list[dict] = []

    for s in 影子:
        sid = s["裁决号"]
        差 = s["秒差"]
        限 = s["容忍上限秒"]
        文案 = s["判定"]
        真相超限 = 差 > 限
        if 真相超限:
            超限影子.append(sid)
            # 文案写“容忍内通过”，或受理位仍亮绿，都按误标假绿处理。
            if 文案 == "容忍内通过" or s["受理"] == 1:
                误标影子.append(sid)
        else:
            容忍内通过号.append(sid)
            if 文案 and 文案 != "容忍内通过":
                # 真相在内却被标拒，也是账实不符的一种。
                双轨异常.append(sid)

        v = 现行.get(sid)
        if v is None:
            双轨异常.append(sid)
        else:
            if v["判定"] != 文案:
                双轨异常.append(sid)
            elif v["容忍上限秒"] != 限 or v["秒差"] != 差:
                双轨异常.append(sid)
            if 差 > 限 and (v["判定"] == "容忍内通过" or v["受理"] == 1):
                假绿现行.append(sid)

        明细.append({
            "裁决号": sid, "事件号": s.get("事件号"),
            "秒差": 差, "容忍上限秒": 限, "上限档": s.get("上限档"),
            "文案判定": 文案,
            "真相": "超出容忍已拒" if 真相超限 else "容忍内通过",
        })

    # 现行轨里可能有影子缺失的孤票，同样按账实扫假绿。
    影子号 = {s["裁决号"] for s in 影子}
    for vid, v in 现行.items():
        if vid in 影子号:
            continue
        if v["秒差"] > v["容忍上限秒"] and (
            v["判定"] == "容忍内通过" or v["受理"] == 1
        ):
            假绿现行.append(vid)

    # 去重保序。
    def 去重(xs):
        return list(dict.fromkeys(x for x in xs if x))

    超限影子 = 去重(超限影子)
    误标影子 = 去重(误标影子)
    容忍内通过号 = 去重(容忍内通过号)
    双轨异常 = 去重(双轨异常)
    假绿现行 = 去重(假绿现行)

    对齐 = not (误标影子 or 双轨异常 or 假绿现行)
    return {
        "对齐": 对齐,
        "时钟对齐": 对齐,
        "ok": 对齐,
        "超限影子": 超限影子,
        "超限数": len(超限影子),
        "误标影子": 误标影子,
        "假绿影子": 误标影子,
        "假绿": 误标影子,
        "误标数": len(误标影子),
        "假绿数": len(误标影子) + len(假绿现行),
        "假绿现行": 假绿现行,
        "容忍内通过号": 容忍内通过号,
        "容忍内通过": 容忍内通过号,
        "通过号": 容忍内通过号,
        "双轨异常": 双轨异常,
        "异常数": len(双轨异常),
        "扫描数": len(影子),
        "rows": 明细[-200:],
        "结果": 明细[-200:],
        "明细": 明细[-200:],
        "口径": "按行内冻结秒差与容忍上限秒重算，只读不回写",
    }


# 口述/英文别名。
对账容忍 = 对账时钟
验签对账 = 对账时钟
时钟对账 = 对账时钟
reconcile_skew = 对账时钟


def 跑一次() -> dict:
    t = 此刻()
    conn = 连接()
    try:
        总 = conn.execute("SELECT COUNT(*) AS c FROM 事件").fetchone()["c"]
        已 = conn.execute("SELECT COUNT(*) AS c FROM 事件 WHERE 状态='已投递'").fetchone()["c"]
        死 = conn.execute("SELECT COUNT(*) AS c FROM 事件 WHERE 状态='死信'").fetchone()["c"]
        待 = conn.execute("SELECT COUNT(*) AS c FROM 事件 WHERE 状态 IN ('待投','投递中')").fetchone()["c"]
        匣 = conn.execute("SELECT COUNT(*) AS c FROM 死信 WHERE 状态='待处置'").fetchone()["c"]
        对齐 = 1 if (死 == 匣 and 已 + 死 + 待 <= 总) else 0
        说明 = "事件/投递/死信口径对齐" if 对齐 else "死信匣与事件死信数不一致或水位异常"

        时钟 = 对账时钟()
        时钟对齐 = 1 if 时钟["对齐"] else 0
        if not 时钟对齐:
            时钟说明 = (
                f"时钟账实不符：超限影子{时钟['超限数']}、"
                f"误标假绿{len(时钟['误标影子'])}、双轨异常{len(时钟['双轨异常'])}"
            )
            说明 = 说明 + "；" + 时钟说明
        else:
            时钟说明 = (
                f"时钟口径对齐：扫描{时钟['扫描数']}张影子票，"
                f"超限{时钟['超限数']}张均按超出容忍已拒归档"
            )

        总对齐 = 1 if (对齐 and 时钟对齐) else 0
        conn.execute(
            "INSERT INTO 互证批次(时刻,事件总数,已投递数,死信数,待投数,是否对齐,说明,"
            "时钟对齐,时钟说明) VALUES (?,?,?,?,?,?,?,?,?)",
            (t, 总, 已, 死, 待, 总对齐, 说明, 时钟对齐, 时钟说明),
        )
        conn.commit()
        return {
            "时刻": t,
            "事件总数": 总,
            "已投递数": 已,
            "死信数": 死,
            "待投数": 待,
            "死信匣待处置": 匣,
            "事件口径对齐": bool(对齐),
            "时钟对齐": bool(时钟对齐),
            "时钟审计": 时钟,
            "是否对齐": bool(总对齐),
            "对齐": bool(总对齐),
            "是否全部对齐": bool(总对齐),
            "说明": 说明,
            "时钟说明": 时钟说明,
            "明细": {"总": 总, "已": 已, "死": 死, "待": 待, "匣": 匣},
        }
    finally:
        conn.close()
