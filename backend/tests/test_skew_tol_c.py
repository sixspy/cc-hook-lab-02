# -*- coding: utf-8 -*-
"""失败测乙 · 验签对账把超限影子误标成容忍内通过（hook-02）。

事故命题：双写影子轨里躺着“秒差 50 / 上限 40”的超限裁决，对账若只读被争用
写花的判定文案，就会把它误标成“容忍内通过”，形成第二处假绿。对账必须按
影子行自封的快照上限与账实秒差重新归类，点出超限影子并判不对齐。

另钉死工程形态：
* 验签瞬间上限进 验签上限快照，事后改签名规秒数，旧快照/旧裁决拒绝回刷；
* 超限旧裁决进 验签归档（只读）；
* 影子裁决不得回写成现行；对账本身只读，不得改写裁决/影子。

未接线主干没有 互证.对账时钟 —— 本文件先红，禁止跳过。
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="test_skew_tol_c_")
os.environ["数据目录"] = _TMP
os.environ["夹具目录"] = str(Path(__file__).resolve().parents[2] / "fixtures")

import pytest  # noqa: E402
import sqlite3  # noqa: E402

import app.db as db  # noqa: E402
from app import seed  # noqa: E402
from app.db import 连接  # noqa: E402
from app.services import 互证, 签名目录, 验签  # noqa: E402

try:  # noqa: E402
    from tests.时钟夹具 import 备时钟事件
except ImportError:  # pragma: no cover
    from 时钟夹具 import 备时钟事件  # type: ignore  # noqa: E402


@pytest.fixture()
def 库(tmp_path):
    old_dir, old_path = db.数据目录, db.库路径
    db.数据目录 = tmp_path
    db.库路径 = tmp_path / "skew_c.db"
    seed.初始化库()
    try:
        yield db.库路径
    finally:
        db.数据目录, db.库路径 = old_dir, old_path


def _植一条误标影子(*, 秒差: int = 50, 上限: int = 40, 误标文案: str = "容忍内通过") -> str:
    号 = f"VRF-SHADOW-{uuid.uuid4().hex[:10]}"
    t = "2026-01-01T00:00:00Z"
    conn = 连接()
    try:
        conn.execute(
            "INSERT INTO 验签影子(裁决号,事件号,会话名,对端时刻,本仓时刻,秒差,绝对秒差,快秒,"
            "方向,容忍上限秒,上限档,快照号,判定,验签状态,受理,是否容忍,拒因,来源,轨道,时刻) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (号, f"EVT-{号}", "影子", t, t, 秒差, abs(秒差), max(秒差, 0), "快",
             上限, f"{上限}秒档", f"SNP-{号}", 误标文案, "通过", 1, 1, "", "对账夹具", "影子", t),
        )
        conn.commit()
    finally:
        conn.close()
    return 号


def test_乙_对账按账实秒差识破超限影子_不冒认容忍内通过(库):
    sid = _植一条误标影子()

    audit = 互证.对账时钟()
    assert "超限影子" in audit, f"对账缺少超限影子口径：{audit.keys()}"
    assert sid in audit["超限影子"], "秒差50/上限40 的影子必须被点名为超限影子"
    assert int(audit.get("超限数") or len(audit["超限影子"])) >= 1
    # 真相口径下它绝不能被算进容忍内通过。
    assert all(x != sid for x in audit.get("容忍内通过号", [])), audit
    assert audit["对齐"] is False, "存在超限误标影子时时钟对账不得判对齐"

    rep = 互证.跑一次()
    assert rep.get("时钟对齐") is False
    assert rep.get("是否全部对齐") is False, "超限影子假绿时总对账不得判全部对齐"


def test_乙_对账只读_不回写影子与现行(库):
    sid = _植一条误标影子()
    conn = 连接()
    try:
        前影子 = conn.execute("SELECT COUNT(*) c FROM 验签影子").fetchone()["c"]
        前现行 = conn.execute("SELECT COUNT(*) c FROM 验签裁决").fetchone()["c"]
    finally:
        conn.close()

    互证.对账时钟()
    互证.跑一次()

    conn = 连接()
    try:
        后影子 = conn.execute("SELECT COUNT(*) c FROM 验签影子").fetchone()["c"]
        后现行 = conn.execute("SELECT COUNT(*) c FROM 验签裁决").fetchone()["c"]
        文案 = conn.execute("SELECT 判定 FROM 验签影子 WHERE 裁决号=?", (sid,)).fetchone()["判定"]
    finally:
        conn.close()
    assert (前影子, 前现行) == (后影子, 后现行), "对账不得新增/回写裁决集合"
    assert 文案 == "容忍内通过", "对账必须只读，不得顺手改写影子原文案"


def test_快照封死四十秒_改规后旧裁决拒绝回刷_新验签改绑新上限(库):
    eid = 备时钟事件()
    old = 验签.验签(事件号=eid, 对端快秒=50)
    assert old["判定"] == "超出容忍已拒"
    snp = old["快照号"]

    # 有人事后把秒数改大。
    签名目录.改签名规({"时钟容忍秒": "99"})

    conn = 连接()
    try:
        snap = conn.execute("SELECT * FROM 验签上限快照 WHERE 快照号=?", (snp,)).fetchone()
        verdict = conn.execute("SELECT * FROM 验签裁决 WHERE 裁决号=?", (old["裁决号"],)).fetchone()
    finally:
        conn.close()
    assert int(snap["容忍上限秒"]) == 40, "验签瞬间快照不得被改规回刷"
    assert int(verdict["容忍上限秒"]) == 40
    assert verdict["判定"] == "超出容忍已拒", "旧裁决不得按新上限重算回刷"

    # 显式回刷口必须拒绝且不改行。
    刷 = 验签.回刷裁决(old["裁决号"])
    assert 刷.get("回刷") is False or 刷.get("拒绝") is True
    conn = 连接()
    try:
        still = conn.execute("SELECT 判定,容忍上限秒 FROM 验签裁决 WHERE 裁决号=?",
                            (old["裁决号"],)).fetchone()
    finally:
        conn.close()
    assert still["判定"] == "超出容忍已拒" and int(still["容忍上限秒"]) == 40

    # 现行验签改绑新上限所在读集合：同样快 50 秒，现在落在 99 档内。
    new = 验签.验签(事件号=eid, 对端快秒=50)
    assert int(new["容忍上限秒"]) == 99
    assert new["判定"] == "容忍内通过"


def test_超限旧裁决进只读归档_影子不能回写成现行(库):
    eid = 备时钟事件()
    r = 验签.验签(事件号=eid, 对端快秒=50)
    assert r["判定"] == "超出容忍已拒"

    conn = 连接()
    try:
        arc = conn.execute("SELECT * FROM 验签归档 WHERE 裁决号=?", (r["裁决号"],)).fetchone()
        assert arc is not None, "超限裁决必须放进只读归档"
        assert int(arc["容忍上限秒"]) == 40
        # 归档库层只读：任何 UPDATE/DELETE 都要被拒。
        with pytest.raises(sqlite3.Error):
            conn.execute("UPDATE 验签归档 SET 判定='容忍内通过' WHERE 裁决号=?", (r["裁决号"],))
            conn.commit()
        conn.rollback()
        with pytest.raises(sqlite3.Error):
            conn.execute("DELETE FROM 验签归档 WHERE 裁决号=?", (r["裁决号"],))
            conn.commit()
        conn.rollback()
    finally:
        conn.close()

    # 影子不得提供“回写成现行”的成功路径。
    assert 验签.影子回写现行(r["裁决号"]).get("回写") is False
    conn = 连接()
    try:
        n = conn.execute(
            "SELECT COUNT(*) c FROM 验签裁决 WHERE 裁决号=? AND 判定='容忍内通过'",
            (r["裁决号"],),
        ).fetchone()["c"]
    finally:
        conn.close()
    assert n == 0, "超限影子/归档不得回写成容忍内通过的现行裁决"
