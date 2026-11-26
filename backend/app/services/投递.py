from __future__ import annotations
import hashlib
import hmac
import uuid
from app.db import 连接
from app.services.时间 import 此刻
from app.services import 签名目录, 验签


def _签名(密钥版本: str, 事件号: str, 摘要: str) -> str:
    raw = f"{密钥版本}|{事件号}|{摘要}".encode("utf-8")
    key = f"hook-secret-{密钥版本}".encode("utf-8")
    return hmac.new(key, raw, hashlib.sha256).hexdigest()[:24]


def 投递一次(事件号=None, 强制失败=False, 时钟包: dict | None = None, **额外) -> dict:
    """对事件执行一次签名投递。本地模拟：默认成功；强制失败/端点停用/时钟超限则失败。

    时钟入参可通过关键字（对端快秒=/对端时刻=/秒差= ...）或第二个 dict 位置参传入。
    无任何时钟参数时秒差为 0，正常时钟主链不被误伤。
    """
    # 兼容 投递一次({...整包...}) 的 dict 第一参形态。
    if isinstance(事件号, dict):
        包 = dict(事件号)
        事件号 = 包.pop("事件号", None) or 包.pop("event_id", None)
        if "强制失败" in 包:
            强制失败 = 包.pop("强制失败")
        额外.update(包)
    # 兼容 投递一次(eid, {"对端快秒": 50}) 的 dict 第二参形态。
    if isinstance(强制失败, dict):
        时钟包 = 强制失败
        强制失败 = bool(时钟包.get("强制失败", False))
    强制失败 = bool(强制失败)

    时钟入参: dict = {}
    if isinstance(时钟包, dict):
        时钟入参.update(时钟包)
    时钟入参.update({k: v for k, v in 额外.items() if v is not None})

    t = 此刻()
    尝试号 = f"TRY-{uuid.uuid4().hex[:10]}"
    conn = 连接()
    try:
        ev = conn.execute("SELECT * FROM 事件 WHERE 事件号=?", (事件号,)).fetchone()
        if not ev:
            raise ValueError("无此事件")
        if ev["状态"] in ("已投递", "死信"):
            raise ValueError(f"事件状态为{ev['状态']}，不可再投")
        ep = conn.execute("SELECT * FROM 投递端点 WHERE 端点键=?", (ev["端点键"],)).fetchone()
        if not ep:
            raise ValueError("端点缺失")
        if int(ep["启用"]) != 1:
            raise ValueError("端点停用")
        规 = 签名目录.签名规()
        最大 = int(规.get("最大重试") or 3)
        sig = _签名(ep["密钥版本"], 事件号, ev["载荷摘要"])
        失败次数 = conn.execute(
            "SELECT COUNT(*) AS c FROM 投递尝试 WHERE 事件号=? AND 状态='失败'", (事件号,)
        ).fetchone()["c"]

        # 投递验签按签名规当前时钟容忍上限比较；裁决服务自管快照/双写/归档事务。
        裁决 = 验签.验签(
            事件号=事件号,
            尝试号=尝试号,
            来源="投递",
            密钥版本=ep["密钥版本"],
            载荷摘要=ev["载荷摘要"],
            签名摘要=sig,
            **时钟入参,
        )
        时钟拒 = not bool(裁决.get("受理", True))

        成功 = (not 强制失败) and (失败次数 < 1000) and (not 时钟拒)
        # 模拟：事件类型含 .fail 或 body 强制 → 失败
        if 强制失败 or str(ev["事件类型"]).endswith(".fail"):
            成功 = False

        时钟列 = (
            裁决.get("对端时刻", ""), 裁决.get("本仓时刻", ""),
            int(裁决.get("秒差") or 0), int(裁决.get("绝对秒差") or 0),
            int(裁决.get("快秒") or 0), 裁决.get("方向", "齐"),
            int(裁决.get("容忍上限秒") or 40), 裁决.get("上限档", "40秒档"),
            裁决.get("快照号", ""), 裁决.get("裁决号", ""),
            裁决.get("判定", ""), 裁决.get("验签状态", ""),
            裁决.get("拒因", ""), 裁决.get("会话名", ""), "投递",
        )

        if 成功:
            conn.execute(
                "INSERT INTO 投递尝试(尝试号,事件号,端点键,签名摘要,状态,响应码,说明,投递时,"
                "对端时刻,本仓时刻,秒差,绝对秒差,快秒,方向,容忍上限秒,上限档,快照号,裁决号,"
                "判定,验签状态,拒因,会话名,来源) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (尝试号, 事件号, ev["端点键"], sig, "成功", 200, "投递成功", t, *时钟列),
            )
            conn.execute("UPDATE 事件 SET 状态=?, 更新时=? WHERE 事件号=?", ("已投递", t, 事件号))
            conn.execute("INSERT INTO 操作留痕(时刻,操作,事件号,详情) VALUES (?,?,?,?)",
                         (t, "投递成功", 事件号, 尝试号))
            conn.commit()
            return {
                "尝试号": 尝试号, "状态": "成功", "事件状态": "已投递", "签名摘要": sig,
                "判定": 裁决["判定"], "验签判定": 裁决["判定"],
                "验签状态": 裁决["验签状态"], "受理": True,
                "秒差": 裁决["秒差"], "容忍上限秒": 裁决["容忍上限秒"],
                "上限档": 裁决["上限档"], "快照号": 裁决["快照号"],
                "裁决号": 裁决["裁决号"],
            }

        # 失败：时钟超限优先把拒因写成规定裁决原文。
        if 时钟拒:
            说明 = 裁决["拒因"] or "超出容忍已拒"
            响应码 = 401
        else:
            说明 = "投递失败"
            响应码 = 500
        conn.execute(
            "INSERT INTO 投递尝试(尝试号,事件号,端点键,签名摘要,状态,响应码,说明,投递时,"
            "对端时刻,本仓时刻,秒差,绝对秒差,快秒,方向,容忍上限秒,上限档,快照号,裁决号,"
            "判定,验签状态,拒因,会话名,来源) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (尝试号, 事件号, ev["端点键"], sig, "失败", 响应码, 说明, t, *时钟列),
        )
        新失败 = 失败次数 + 1
        if 新失败 >= 最大:
            dl = f"DL-{uuid.uuid4().hex[:10]}"
            if not conn.execute("SELECT 1 FROM 死信 WHERE 事件号=?", (事件号,)).fetchone():
                conn.execute(
                    "INSERT INTO 死信(死信号,事件号,端点键,失败次数,末次原因,状态,入匣时,"
                    "容忍上限秒,上限档,裁决号,快照号,判定,秒差) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (dl, 事件号, ev["端点键"], 新失败,
                     说明 if 时钟拒 else "重试耗尽", "待处置", t,
                     int(裁决.get("容忍上限秒") or 40), 裁决.get("上限档", "40秒档"),
                     裁决.get("裁决号", ""), 裁决.get("快照号", ""),
                     裁决.get("判定", ""), int(裁决.get("秒差") or 0)),
                )
            conn.execute("UPDATE 事件 SET 状态=?, 更新时=? WHERE 事件号=?", ("死信", t, 事件号))
            事件状态 = "死信"
        else:
            conn.execute("UPDATE 事件 SET 状态=?, 更新时=? WHERE 事件号=?", ("投递中", t, 事件号))
            事件状态 = "投递中"
        conn.execute("INSERT INTO 操作留痕(时刻,操作,事件号,详情) VALUES (?,?,?,?)",
                     (t, "投递失败", 事件号, f"失败{新失败}/{最大}"))
        conn.commit()
        return {
            "尝试号": 尝试号, "状态": "失败", "事件状态": 事件状态,
            "失败次数": 新失败, "签名摘要": sig,
            "判定": 裁决["判定"], "验签判定": 裁决["判定"],
            "验签状态": 裁决["验签状态"], "受理": False,
            "拒因": 说明,
            "秒差": 裁决["秒差"], "容忍上限秒": 裁决["容忍上限秒"],
            "上限档": 裁决["上限档"], "快照号": 裁决["快照号"],
            "裁决号": 裁决["裁决号"],
        }
    finally:
        conn.close()
