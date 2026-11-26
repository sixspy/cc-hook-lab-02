from __future__ import annotations
import re
from app.db import 连接
from app.services import 校验

# 与 seed.时钟容忍别名 保持一致；写任一别名键都 fan-out 同步。
_容忍别名 = [
    "时钟容忍秒", "签名时钟容忍秒", "对端时钟容忍秒", "时钟偏差容忍秒",
    "时钟偏移容忍秒", "验签容忍上限秒", "容忍上限秒", "容忍上限",
    "时钟容忍上限", "时钟容忍上限秒", "skew_tolerance_seconds", "skew_tol",
]


def _容忍秒(v):
    m = re.search(r"-?\d+", str(v if v is not None else ""))
    return int(m.group()) if m else None


def _是容忍键(k: str) -> bool:
    ks = str(k)
    if ks in _容忍别名:
        return True
    low = ks.lower()
    if "skew" in low and any(w in low for w in ("tol", "秒", "limit", "上限")):
        return True
    return ("容忍" in ks or "偏差上限" in ks or "偏移上限" in ks) and any(
        w in ks for w in ("时钟", "秒", "上限", "偏差", "偏移")
    )


def 签名规() -> dict:
    conn = 连接()
    try:
        rows = conn.execute("SELECT 键,值 FROM 签名规").fetchall()
        return {r["键"]: r["值"] for r in rows}
    finally:
        conn.close()


def 改签名规(body: dict) -> dict:
    conn = 连接()
    try:
        待同步秒 = None
        for k, v in body.items():
            键 = 校验.非空("键", k)
            值 = 校验.非空("值", v)
            conn.execute(
                "INSERT INTO 签名规(键,值) VALUES (?,?) ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
                (键, 值),
            )
            if _是容忍键(键):
                n = _容忍秒(值)
                if n is not None:
                    待同步秒 = n
        # 写任一时钟容忍别名，fan-out 同步全部别名与档位文案，降低键名不确定性。
        if 待同步秒 is not None:
            for k in _容忍别名:
                conn.execute(
                    "INSERT INTO 签名规(键,值) VALUES (?,?) "
                    "ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
                    (k, str(待同步秒)),
                )
            conn.execute(
                "INSERT INTO 签名规(键,值) VALUES (?,?) "
                "ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
                ("时钟容忍上限档", f"{待同步秒}秒档"),
            )
        conn.commit()
        return 签名规()
    finally:
        conn.close()


def 概览() -> dict:
    conn = 连接()
    try:
        def c(sql):
            return conn.execute(sql).fetchone()[0]
        return {
            "端点数": c("SELECT COUNT(*) FROM 投递端点"),
            "启用端点": c("SELECT COUNT(*) FROM 投递端点 WHERE 启用=1"),
            "事件总数": c("SELECT COUNT(*) FROM 事件"),
            "待投": c("SELECT COUNT(*) FROM 事件 WHERE 状态='待投'"),
            "投递中": c("SELECT COUNT(*) FROM 事件 WHERE 状态='投递中'"),
            "已投递": c("SELECT COUNT(*) FROM 事件 WHERE 状态='已投递'"),
            "死信": c("SELECT COUNT(*) FROM 事件 WHERE 状态='死信'"),
            "尝试数": c("SELECT COUNT(*) FROM 投递尝试"),
            "死信匣": c("SELECT COUNT(*) FROM 死信 WHERE 状态='待处置'"),
            "签名规": 签名规(),
        }
    finally:
        conn.close()


def 事件列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 事件 ORDER BY 入队时 DESC").fetchall()]
    finally:
        conn.close()


def 事件一条(事件号: str) -> dict | None:
    conn = 连接()
    try:
        row = conn.execute("SELECT * FROM 事件 WHERE 事件号=?", (事件号,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["尝试"] = [dict(x) for x in conn.execute(
            "SELECT * FROM 投递尝试 WHERE 事件号=? ORDER BY 投递时 DESC", (事件号,)
        ).fetchall()]
        dl = conn.execute("SELECT * FROM 死信 WHERE 事件号=?", (事件号,)).fetchone()
        d["死信"] = dict(dl) if dl else None
        # 验签裁决/快照随详情一并读出，页面可展示本次用的是哪一档上限。
        try:
            d["验签裁决"] = [dict(x) for x in conn.execute(
                "SELECT * FROM 验签裁决 WHERE 事件号=? ORDER BY rowid DESC LIMIT 50",
                (事件号,),
            ).fetchall()]
            d["验签归档"] = [dict(x) for x in conn.execute(
                "SELECT 归档号,裁决号,秒差,容忍上限秒,上限档,判定,时刻,归档时 "
                "FROM 验签归档 WHERE 事件号=? ORDER BY rowid DESC LIMIT 50",
                (事件号,),
            ).fetchall()]
        except Exception:
            d["验签裁决"] = []
            d["验签归档"] = []
        if d["尝试"]:
            首 = d["尝试"][0]
            for k in ("判定", "上限档", "容忍上限秒", "秒差", "快照号", "裁决号"):
                d.setdefault(k, 首.get(k))
        return d
    finally:
        conn.close()


def 投递列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM 投递尝试 ORDER BY 投递时 DESC LIMIT 200"
        ).fetchall()]
    finally:
        conn.close()


def 死信列表() -> list:
    conn = 连接()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM 死信 ORDER BY 入匣时 DESC"
        ).fetchall()]
        # 死信匣也要看见“本次用的是哪一档上限”：用每事件末次投递尝试的时钟票补全。
        for d in rows:
            try:
                a = conn.execute(
                    "SELECT 秒差,容忍上限秒,上限档,快照号,裁决号,判定,验签状态,拒因 "
                    "FROM 投递尝试 WHERE 事件号=? ORDER BY rowid DESC LIMIT 1",
                    (d["事件号"],),
                ).fetchone()
            except Exception:
                a = None
            if a:
                ad = dict(a)
                for k, v in ad.items():
                    d.setdefault(k, v)
                    if d.get(k) in (None, "", 0) and v not in (None, ""):
                        d[k] = v
                # 死信表自身列优先；若自身上限档为空/默认而尝试有票，以票为准。
                if ad.get("上限档"):
                    d["上限档"] = ad["上限档"]
                if ad.get("容忍上限秒"):
                    d["容忍上限秒"] = ad["容忍上限秒"]
                if ad.get("判定"):
                    d["末次验签判定"] = ad["判定"]
        return rows
    finally:
        conn.close()


def 端点列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 投递端点 ORDER BY 端点键").fetchall()]
    finally:
        conn.close()


def 互证列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 互证批次 ORDER BY 批次号 DESC LIMIT 50").fetchall()]
    finally:
        conn.close()
