# -*- coding: utf-8 -*-
"""失败测甲 · 对端时钟快五十秒仍被放行（hook-02 · 验签时钟容忍）。

骨签：对端时钟比本仓快 40 秒（含）以内必须容忍，快过 40 秒必须拒绝。
容忍上限 40 写在签名规上供人核对；投递验签按同一上限比较，裁决文案必须是
“容忍内通过”或“超出容忍已拒”，不得出现“成功但验签超限”的假绿。

未接线主干上没有 app.services.验签，签名规没有时钟容忍秒键，投递一次也不接收
对端时钟 —— 本文件在修复前必须红，禁止跳过。救绿责任：时间/验签服务 + 投递服务。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="test_skew_tol_b_")
os.environ["数据目录"] = _TMP
os.environ["夹具目录"] = str(Path(__file__).resolve().parents[2] / "fixtures")

import pytest  # noqa: E402

import app.db as db  # noqa: E402
from app import seed  # noqa: E402
from app.services import 签名目录, 投递, 验签  # noqa: E402

try:  # noqa: E402
    from tests.时钟夹具 import 备时钟事件, 键快签
except ImportError:  # pragma: no cover
    from 时钟夹具 import 备时钟事件, 键快签  # type: ignore  # noqa: E402


@pytest.fixture()
def 库(tmp_path):
    old_dir, old_path = db.数据目录, db.库路径
    db.数据目录 = tmp_path
    db.库路径 = tmp_path / "skew_b.db"
    seed.初始化库()
    try:
        yield db.库路径
    finally:
        db.数据目录, db.库路径 = old_dir, old_path


def test_签名规上留着四十秒上限供人核对(库):
    规 = 签名目录.签名规()
    # 至少有一个“时钟/容忍/秒/上限”键，其值读得出 40。
    候选 = [
        (k, v) for k, v in 规.items()
        if any(w in str(k) for w in ("时钟", "容忍", "偏差", "skew", "Skew"))
    ]
    assert 候选, f"签名规上找不到时钟容忍上限键：{规}"
    assert any(str(v).strip().startswith("40") for _, v in 候选), 候选
    assert int(验签.取容忍上限()) == 40
    # 数字 40 必须原样留在签名规字典里供页面/人核对。
    assert any("40" in str(v) for v in 规.values())


def test_甲_快四十秒边界容忍内通过_再快一秒即拒(库):
    eid = 备时钟事件()

    刚好 = 验签.验签(事件号=eid, 对端快秒=40)
    assert 刚好["秒差"] == 40
    assert 刚好["容忍上限秒"] == 40
    assert 刚好["判定"] == "容忍内通过", 刚好
    assert 刚好["验签状态"] == "通过"
    assert 刚好["受理"] is True or 刚好["受理"] == 1

    多一秒 = 验签.验签(事件号=eid, 对端快秒=41)
    assert 多一秒["判定"] == "超出容忍已拒", 多一秒
    assert 多一秒["受理"] is False or 多一秒["受理"] == 0


def test_甲_夹具键快五十秒的签必须拒_不得放行(库):
    签 = 键快签(快秒=50)
    eid = 备时钟事件(摘要=签["载荷摘要"])
    签["事件号"] = eid

    rep = 验签.验签(**{k: v for k, v in 签.items() if k in (
        "事件号", "密钥版本", "载荷摘要", "签名时刻", "对端时刻", "时间戳",
        "快秒", "对端快秒", "签名摘要", "签名",
    )})
    assert int(rep["秒差"]) >= 50 or int(rep.get("对端快秒") or 50) >= 50
    assert rep["容忍上限秒"] == 40
    assert rep["判定"] == "超出容忍已拒", f"快五十秒竟被放行：{rep}"
    assert rep.get("验签状态") in ("拒绝", "拒签", "不通过")
    assert rep.get("受理") in (False, 0)
    assert "40" in str(rep.get("上限档") or ""), "裁决必须写明用的是哪一档上限"
    assert rep.get("快照号"), "验签瞬间的上限必须收进快照表并回指快照号"

    # 同一事件的通过/放行集合里，绝不允许出现秒差跑出 40 上限的票。
    for row in 验签.裁决列表(事件号=eid):
        if row["判定"] == "容忍内通过":
            assert int(row["秒差"]) <= int(row["容忍上限秒"]) == 40


def test_甲_投递口收到快五十秒时钟必须记失败_事件不得已投递(库):
    eid = 备时钟事件()
    rep = 投递.投递一次(eid, 对端快秒=50)
    assert rep["状态"] == "失败", f"快五十秒的投递竟成功：{rep}"
    assert rep.get("事件状态") != "已投递"
    assert str(rep.get("判定") or rep.get("验签判定") or "") == "超出容忍已拒" or \
        "超出容忍" in str(rep.get("拒因") or "") or "容忍" in str(rep.get("拒因") or "")

    detail = 签名目录.事件一条(eid)
    assert detail["状态"] != "已投递"
    row = detail["尝试"][0]
    assert row["状态"] == "失败"
    assert int(row["秒差"]) == 50
    assert int(row["容忍上限秒"]) == 40
    assert row["判定"] == "超出容忍已拒"
    assert "40" in str(row["上限档"])


def test_甲_正常时钟投递仍是成功主链不被误伤(库):
    eid = 备时钟事件(端点键="ep-partner")
    rep = 投递.投递一次(eid)
    assert rep["状态"] == "成功"
    assert rep["事件状态"] == "已投递"
    assert rep.get("判定") == "容忍内通过"
