"""失败测乙（hook-02-并发投递互斥）。

事故：事件队列对账把双成功标成单票已齐——同事件两张成功票必须被对账判异常，
且对账为只读，跨表联查痕迹不得混进正式集合。
修复分工：互证服务（app/services/互证.py）增加双票异常对账。
本测在修复前必须红，禁止跳过。
"""
import os
import tempfile
import uuid
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ["数据目录"] = _tmp
os.environ["夹具目录"] = str(Path(__file__).resolve().parents[2] / "fixtures")

from app import seed
from app.db import 连接
from app.services import 互证, 入队, 签名目录, 时间
from tests.并发夹具 import 备事故事件, 双会话同点
from app.factory import create_app


def setup_module():
    seed.初始化库()


def test_对账识别同事件双成功票且只读不污染正式集合():
    app = create_app()
    事件号 = 备事故事件()

    # 先打一次真并发，前置实现下这里就会产生双成功事故
    双会话同点(app, 事件号)

    # 再显式造一张“历史双票”：模拟曾经无互斥坑时留下的脏账
    脏事件号 = f"EVT-DUP-{uuid.uuid4().hex[:10]}"
    入队.建事件({"事件类型": "invoice.paid", "端点键": "ep-billing",
                "载荷摘要": "dup", "事件号": 脏事件号})
    t = 时间.此刻()
    conn = 连接()
    try:
        conn.execute("UPDATE 事件 SET 状态='已投递', 更新时=? WHERE 事件号=?", (t, 脏事件号))
        for i in range(2):
            conn.execute(
                "INSERT INTO 投递尝试(尝试号,事件号,端点键,签名摘要,状态,响应码,说明,投递时)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (f"TRY-DUP-{uuid.uuid4().hex[:8]}", 脏事件号, "ep-billing",
                 f"sig{i}", "成功", 200, "投递成功", t),
            )
        conn.commit()
        尝试前 = conn.execute(
            "SELECT COUNT(*) AS c FROM 投递尝试"
        ).fetchone()["c"]
    finally:
        conn.close()

    报 = 互证.跑一次()

    conn = 连接()
    try:
        尝试后 = conn.execute("SELECT COUNT(*) AS c FROM 投递尝试").fetchone()["c"]
        影子表 = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            if "影子" in r[0] or "对账" in r[0]
        ]
        双票数 = conn.execute(
            "SELECT COUNT(*) AS c FROM ("
            "SELECT 事件号 FROM 投递尝试 WHERE 状态='成功' GROUP BY 事件号 HAVING COUNT(*)>1)"
        ).fetchone()["c"]
    finally:
        conn.close()

    # 双成功不得被标成单票已齐：对账必须把双票事件列为异常并判不对齐
    assert "双票异常" in 报, "对账缺少双票异常口径，会把双成功误判单票已齐"
    assert 脏事件号 in 报["双票异常"]
    assert 报["是否对齐"] is False, "存在双成功票时互证不得判对齐"

    # 对账是跨表联查的只读影子，不得写正式集合、不得落影子表
    assert 尝试后 == 尝试前, "对账写入了正式投递尝试集合"
    # 修复后真并发不再产生新双票；显式注入的历史脏账（1 个）必须被抓到
    assert 双票数 >= 1
    assert 影子表 == [], f"对账影子不得落成混库表：{影子表}"

    # 事件队列详情读模型仍能读到事件号与中文命运
    详情 = 签名目录.事件一条(脏事件号)
    assert 详情["事件号"] == 脏事件号
    assert 详情["状态"] == "已投递"
