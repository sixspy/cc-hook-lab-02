from __future__ import annotations
from app.db import 连接
from app.services.时间 import 此刻


def 跑一次() -> dict:
    t = 此刻()
    conn = 连接()
    try:
        总 = conn.execute("SELECT COUNT(*) AS c FROM 事件").fetchone()["c"]
        已 = conn.execute("SELECT COUNT(*) AS c FROM 事件 WHERE 状态='已投递'").fetchone()["c"]
        死 = conn.execute("SELECT COUNT(*) AS c FROM 事件 WHERE 状态='死信'").fetchone()["c"]
        待 = conn.execute("SELECT COUNT(*) AS c FROM 事件 WHERE 状态 IN ('待投','投递中')").fetchone()["c"]
        匣 = conn.execute("SELECT COUNT(*) AS c FROM 死信 WHERE 状态='待处置'").fetchone()["c"]

        # 双票对账（只读跨表联查）：同事件在正式尝试集合出现多于一张成功票，
        # 即无互斥坑时代留下的双成功事故，绝不能标成单票已齐。
        双票行 = conn.execute(
            "SELECT 事件号, COUNT(*) AS 票数 FROM 投递尝试 "
            "WHERE 状态='成功' GROUP BY 事件号 HAVING COUNT(*) > 1"
        ).fetchall()
        双票异常 = [r["事件号"] for r in 双票行]
        双票数 = len(双票异常)

        # 坑账联查：锁队列判终票的事件，命运必须与事件表一致；占用中/已释放属在途，不判异常
        坑账不符 = [
            r["事件号"] for r in conn.execute(
                "SELECT L.事件号 FROM 投递锁 L JOIN 事件 E ON E.事件号 = L.事件号 "
                "WHERE L.占坑态='终票占坑' AND L.中文命运 <> E.状态"
            ).fetchall()
        ]

        基础对齐 = (死 == 匣 and 已 + 死 + 待 <= 总)
        对齐 = 1 if (基础对齐 and 双票数 == 0 and not 坑账不符) else 0
        if not 基础对齐:
            说明 = "死信匣与事件死信数不一致或水位异常"
        elif 双票数:
            说明 = f"发现{双票数}个事件双成功票，单票口径不齐"
        elif 坑账不符:
            说明 = "投递锁终票命运与事件表不符"
        else:
            说明 = "事件/投递/死信/投递锁口径对齐"
        conn.execute(
            "INSERT INTO 互证批次(时刻,事件总数,已投递数,死信数,待投数,是否对齐,说明) VALUES (?,?,?,?,?,?,?)",
            (t, 总, 已, 死, 待, 对齐, 说明),
        )
        conn.commit()
        return {
            "时刻": t,
            "事件总数": 总,
            "已投递数": 已,
            "死信数": 死,
            "待投数": 待,
            "死信匣待处置": 匣,
            "双票异常": 双票异常,
            "双票数": 双票数,
            "坑账不符": 坑账不符,
            "是否对齐": bool(对齐),
            "是否全部对齐": bool(对齐),
            "说明": 说明,
            "明细": {"总": 总, "已": 已, "死": 死, "待": 待, "匣": 匣, "双票": 双票数},
        }
    finally:
        conn.close()
