# -*- coding: utf-8 -*-
"""争用失败测 · 双会话异钟同时验签互相覆盖（hook-02 · 头红）。

事故命题：左右两名同时提交相差五十秒的签，各拿不同对端时钟比较；朴素实现把
“本次对端时钟/判定”放在共享行或模块变量里，后写覆盖先写，结果两份判定都写成
通过，静默把快五十秒的超限签放进去，与签名规 40 秒上限不符。

正确形态：验签瞬间封上限快照，裁决/影子分轨只增不改，临界区串行读规+写票，
两份判定各自忠于自己的秒差 —— 一档容忍内通过、一档超出容忍已拒，谁也不覆盖谁。

本文件在修复前必须红，禁止跳过。
"""
from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="test_skew_tol_a_")
os.environ["数据目录"] = _TMP
os.environ["夹具目录"] = str(Path(__file__).resolve().parents[2] / "fixtures")

import pytest  # noqa: E402

import app.db as db  # noqa: E402
from app import seed  # noqa: E402
from app.db import 连接  # noqa: E402
from app.factory import create_app  # noqa: E402
from app.services import 验签  # noqa: E402

try:  # noqa: E402
    from tests.时钟夹具 import 备时钟事件, 双会话同点验签
except ImportError:  # pragma: no cover
    from 时钟夹具 import 备时钟事件, 双会话同点验签  # type: ignore  # noqa: E402


@pytest.fixture()
def 库(tmp_path):
    old_dir, old_path = db.数据目录, db.库路径
    db.数据目录 = tmp_path
    db.库路径 = tmp_path / "skew_a.db"
    seed.初始化库()
    try:
        yield db.库路径
    finally:
        db.数据目录, db.库路径 = old_dir, old_path


def test_头_服务层双线程异钟争用_两份判定不得互相覆盖(库):
    eid = 备时钟事件()
    栅 = threading.Barrier(2)
    收口: dict[str, dict] = {}
    错: list[BaseException] = []

    def 一路(名: str, 快秒: int) -> None:
        try:
            栅.wait()
            收口[名] = 验签.验签(事件号=eid, 会话名=名, 对端快秒=快秒)
        except BaseException as exc:  # noqa: BLE001
            错.append(exc)

    ta = threading.Thread(target=一路, args=("左", 0))
    tb = threading.Thread(target=一路, args=("右", 50))
    ta.start(); tb.start(); ta.join(); tb.join()

    assert not 错, f"争用验签报错：{错!r}"
    assert 收口["左"]["判定"] == "容忍内通过", 收口["左"]
    assert 收口["右"]["判定"] == "超出容忍已拒", (
        f"快五十秒的一路被覆盖成通过：{收口['右']}"
    )

    rows = 验签.裁决列表(事件号=eid)
    assert len(rows) >= 2, "两路验签必须各留各的裁决，不得共享一行互相覆盖"
    # 账实：所有写成容忍内通过的票，秒差都不得跑出 40 上限。
    for r in rows:
        if r["判定"] == "容忍内通过":
            assert int(r["秒差"]) <= 40
    右行 = [r for r in rows if int(r["秒差"]) == 50]
    assert 右行 and all(r["判定"] == "超出容忍已拒" for r in 右行)

    # 双写两轨：正式裁决与影子按裁决号同票。
    conn = 连接()
    try:
        正式 = {r["裁决号"]: dict(r) for r in conn.execute(
            "SELECT * FROM 验签裁决 WHERE 事件号=?", (eid,)).fetchall()}
        影子 = {r["裁决号"]: dict(r) for r in conn.execute(
            "SELECT * FROM 验签影子 WHERE 事件号=?", (eid,)).fetchall()}
    finally:
        conn.close()
    assert set(正式) == set(影子), "正式轨与影子轨必须双写同票"
    for k, row in 正式.items():
        assert 影子[k]["判定"] == row["判定"]
        assert int(影子[k]["容忍上限秒"]) == int(row["容忍上限秒"]) == 40


def test_头_双会话HTTP同点打验签口_一成一拒且持久化不被覆盖(库):
    app = create_app()
    eid = 备时钟事件()

    收口 = 双会话同点验签(app, [
        {"事件号": eid, "会话名": "左会话", "对端快秒": 30},
        {"事件号": eid, "会话名": "右会话", "对端快秒": 50},
    ])
    assert len(收口) == 2
    for 名, 码, body in 收口:
        assert 码 == 200, f"{名} /api/验签 应返回裁决包：{码} {body}"
        assert body and body.get("判定") in ("容忍内通过", "超出容忍已拒"), body

    判定集 = sorted(str(b["判定"]) for _, _, b in 收口)
    assert 判定集 == ["容忍内通过", "超出容忍已拒"], f"两份判定被覆盖：{收口}"

    # 再从读口核对一次：HTTP 响应不是孤证，库里的判定也必须一成一拒。
    c = app.test_client()
    c.post("/api/登录", json={"账号": "admin", "密码": "123456"})
    got = c.get(f"/api/验签?事件号={eid}").get_json()
    rows = got["rows"] if isinstance(got, dict) and "rows" in got else got
    判 = [r["判定"] for r in rows if r["事件号"] == eid]
    assert "容忍内通过" in 判 and "超出容忍已拒" in 判, 判
    assert not any(int(r["秒差"]) > 40 and r["判定"] == "容忍内通过" for r in rows)


def test_头_双会话抢同一次验签不产生静默假绿(库):
    """同目标并发再打一轮 40/50，连续两轮都不得出现超限通过票。"""
    app = create_app()
    eid = 备时钟事件()
    for _ in range(2):
        收口 = 双会话同点验签(app, [
            {"事件号": eid, "会话名": "甲", "对端快秒": 40},
            {"事件号": eid, "会话名": "乙", "对端快秒": 50},
        ])
        for _, _, body in 收口:
            if int(body.get("秒差") or 0) > 40:
                assert body["判定"] == "超出容忍已拒", body

    conn = 连接()
    try:
        假绿 = conn.execute(
            "SELECT COUNT(*) c FROM 验签裁决 WHERE 事件号=? AND 判定='容忍内通过' AND 秒差>容忍上限秒",
            (eid,),
        ).fetchone()["c"]
    finally:
        conn.close()
    assert 假绿 == 0, "争用后存在秒差跑出上限却写成容忍内通过的假绿票"
