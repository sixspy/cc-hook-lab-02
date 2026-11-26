"""争用失败测（hook-02-并发投递互斥）。

事故：双会话同事件并发双成。互斥坑必须是独立队列服务（app/modules/并发投递锁），
按事件号占坑、拒绝重复回刷，并在事件队列读模型上暴露占坑态与中文命运。
禁止单点改一处救齐三红：本测由并发投递锁模块救绿。
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


def test_并发投递锁按事件号占坑并暴露占坑态():
    # 模块级互斥坑必须真实存在，而不是投递函数里的内联判断
    from app.modules import 并发投递锁

    assert hasattr(并发投递锁, "占坑"), "并发投递锁未挂占坑能力，空桩尚未实现"
    assert hasattr(并发投递锁, "占坑态"), "并发投递锁未提供占坑态读口"

    app = create_app()
    事件号 = 备事故事件()
    收口 = 双会话同点(app, 事件号)

    状态码 = sorted(码 for _, 码, _ in 收口)
    assert 状态码 == [200, 409], f"双会话争用应一成一拒，实际：{状态码}"

    conn = 连接()
    try:
        坑 = conn.execute("SELECT * FROM 投递锁 WHERE 事件号=?", (事件号,)).fetchone()
        成功行 = conn.execute(
            "SELECT COUNT(*) AS c FROM 投递尝试 WHERE 事件号=? AND 状态='成功'",
            (事件号,),
        ).fetchone()["c"]
    finally:
        conn.close()

    assert 坑 is not None, "投递锁队列中找不到该事件的占坑记录"
    assert 成功行 == 1, "争用双成事故未被互斥坑拦住"

    # 读口要给得出占坑态与中文命运，页面据此直读
    态 = 并发投递锁.占坑态(事件号)
    assert 态["事件号"] == 事件号
    assert 态["占坑态"] in ("占用中", "已释放", "终票占坑")
    assert 态["中文命运"]

    # 拒重复回刷：占坑完成后再来一路，必须被坑拒绝且不新增尝试行
    再 = 双会话同点(app, 事件号)
    assert all(码 == 409 for _, 码, _ in 再), "终票事件的回刷必须被投递坑拒绝"
    conn = 连接()
    try:
        再数 = conn.execute(
            "SELECT COUNT(*) AS c FROM 投递尝试 WHERE 事件号=? AND 状态='成功'",
            (事件号,),
        ).fetchone()["c"]
    finally:
        conn.close()
    assert 再数 == 1
