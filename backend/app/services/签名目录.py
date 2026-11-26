from __future__ import annotations
from app.db import 连接
from app.services import 校验


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
        for k, v in body.items():
            键 = 校验.非空("键", k)
            值 = 校验.非空("值", v)
            conn.execute(
                "INSERT INTO 签名规(键,值) VALUES (?,?) ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
                (键, 值),
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
            "占用坑位": c("SELECT COUNT(*) FROM 投递锁 WHERE 占坑态='占用中'"),
            "终票坑位": c("SELECT COUNT(*) FROM 投递锁 WHERE 占坑态='终票占坑'"),
            "双票事件": c(
                "SELECT COUNT(*) FROM (SELECT 事件号 FROM 投递尝试 WHERE 状态='成功' "
                "GROUP BY 事件号 HAVING COUNT(*)>1)"
            ),
            "签名规": 签名规(),
        }
    finally:
        conn.close()


def 事件列表() -> list:
    conn = 连接()
    try:
        rows = conn.execute(
            "SELECT E.*, L.占坑态, L.中文命运 AS 坑命运, "
            "(SELECT COUNT(*) FROM 投递尝试 T WHERE T.事件号=E.事件号) AS 尝试行数 "
            "FROM 事件 E LEFT JOIN 投递锁 L ON L.事件号=E.事件号 "
            "ORDER BY E.入队时 DESC"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["中文命运"] = d["状态"]
            d["占坑态"] = d["占坑态"] or "未占坑"
            out.append(d)
        return out
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
        锁 = conn.execute("SELECT * FROM 投递锁 WHERE 事件号=?", (事件号,)).fetchone()
        d["占坑"] = dict(锁) if 锁 else None
        d["中文命运"] = d["状态"]
        d["尝试行数"] = conn.execute(
            "SELECT COUNT(*) AS c FROM 投递尝试 WHERE 事件号=?", (事件号,)
        ).fetchone()["c"]
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
        return [dict(r) for r in conn.execute("SELECT * FROM 死信 ORDER BY 入匣时 DESC").fetchall()]
    finally:
        conn.close()


def 锁列表() -> list:
    """投递坑队列读模型：事件号、占坑态、轮次、尝试号、尝试行数、中文命运，库页同源。"""
    conn = 连接()
    try:
        rows = conn.execute(
            "SELECT L.*, (SELECT COUNT(*) FROM 投递尝试 T WHERE T.事件号=L.事件号) AS 尝试行数 "
            "FROM 投递锁 L ORDER BY L.占坑时 DESC LIMIT 200"
        ).fetchall()
        return [dict(r) for r in rows]
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
