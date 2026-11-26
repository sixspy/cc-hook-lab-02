"""失败测甲（hook-02-并发投递互斥）。

事故：同事件第二路仍写出成功尝试 → 正式尝试集合出现双成功行。
修复分工：投递服务（app/services/投递.py）接入互斥坑，同事件只允许一路成功。
本测在修复前必须红，禁止跳过。
"""
import os
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ["数据目录"] = _tmp
os.environ["夹具目录"] = str(Path(__file__).resolve().parents[2] / "fixtures")

from app import seed
from app.db import 连接
from app.factory import create_app
from tests.并发夹具 import 备事故事件, 双会话同点


def setup_module():
    seed.初始化库()


def test_同事件双会话投递只允许一路成功():
    app = create_app()
    事件号 = 备事故事件()

    收口 = 双会话同点(app, 事件号)
    assert len(收口) == 2

    conn = 连接()
    try:
        成功行 = conn.execute(
            "SELECT * FROM 投递尝试 WHERE 事件号=? AND 状态='成功'", (事件号,)
        ).fetchall()
        总行 = conn.execute(
            "SELECT COUNT(*) AS c FROM 投递尝试 WHERE 事件号=?", (事件号,)
        ).fetchone()["c"]
        事件 = conn.execute("SELECT * FROM 事件 WHERE 事件号=?", (事件号,)).fetchone()
    finally:
        conn.close()

    # 同事件投递必须先占互斥坑；尝试集合与事件命运同票，正式尝试最多一行成功
    assert len(成功行) == 1, f"同事件出现{len(成功行)}行成功尝试，互斥坑缺失"
    assert 总行 == 1, "第二路回刷不得在正式尝试集合落任何行"
    assert dict(事件)["状态"] == "已投递"

    # 被坑拒绝的一路必须拿到明确的冲突反馈，而不是第二张成功票
    码组 = sorted(码 for _, 码, _ in 收口)
    assert 码组[0] in (200, 409) and 码组[1] == 409, f"争用响应不符合预期：{码组}"
