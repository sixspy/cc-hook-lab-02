# -*- coding: utf-8 -*-
"""时钟偏移 / 双会话争用夹具（hook-02 · 验签时钟容忍）。

纯函数造“快 N 秒的签”，以及两个独立 Flask 会话在屏障处同时放行的争用器。
三卷红测 test_skew_tol_a/b/c 共用；不依赖外网与真实时钟睡眠。
"""
from __future__ import annotations

import hashlib
import hmac
import threading
import uuid
from datetime import datetime, timedelta, timezone

账号 = "admin"
密码 = "123456"


def iso偏移秒(秒: int = 0, 基准: datetime | None = None) -> str:
    """返回相对 UTC 此刻偏移 指定秒 的 ISO-Z 时刻；正秒=对端时钟快。"""
    base = 基准 or datetime.now(timezone.utc)
    return (base + timedelta(seconds=int(秒))).strftime("%Y-%m-%dT%H:%M:%SZ")


def 快五十秒时刻() -> str:
    return iso偏移秒(50)


def 快四十秒时刻() -> str:
    return iso偏移秒(40)


def 键快签(
    快秒: int = 50,
    *,
    密钥版本: str = "v1",
    事件号: str = "EVT-SKEW-FIX",
    摘要: str = "skew-fixture",
) -> dict:
    """用夹具键封一张把签名时间戳拨快 快秒 秒的签（含两种常见待签串形态）。"""
    ts = iso偏移秒(快秒)
    材料 = f"hook-secret-{密钥版本}".encode("utf-8")
    新版待签 = f"{密钥版本}|{ts}|{事件号}|{摘要}".encode("utf-8")
    新版签名 = hmac.new(材料, 新版待签, hashlib.sha256).hexdigest()[:24]
    旧版待签 = f"{密钥版本}|{事件号}|{摘要}".encode("utf-8")
    旧版签名 = hmac.new(材料, 旧版待签, hashlib.sha256).hexdigest()[:24]
    return {
        "事件号": 事件号,
        "密钥版本": 密钥版本,
        "载荷摘要": 摘要,
        "签名时刻": ts,
        "对端时刻": ts,
        "时间戳": ts,
        "快秒": 快秒,
        "对端快秒": 快秒,
        "签名摘要": 新版签名,
        "签名": 新版签名,
        "旧版签名摘要": 旧版签名,
    }


# 兼容不同评测/口述对“造签函数”的命名习惯。
def 造快签(*a, **k):
    return 键快签(*a, **k)


def 快五十秒的签(**k):
    k.setdefault("快秒", 50)
    return 键快签(**k)


def 备时钟事件(端点键: str = "ep-billing", 摘要: str | None = None) -> str:
    from app.services import 入队

    eid = f"EVT-SKEW-{uuid.uuid4().hex[:10]}"
    入队.建事件(
        {
            "事件号": eid,
            "事件类型": "invoice.paid",
            "端点键": 端点键,
            "载荷摘要": 摘要 or f"skew-{eid}",
            "优先级": "紧急",
        }
    )
    return eid


# 口述/评测可能使用的别名。
备事故事件 = 备时钟事件


def 双会话同点验签(app, 载荷们: list[dict], 路径: str = "/api/验签") -> list[tuple]:
    """两路独立浏览器会话（各自登录与 Cookie 罐）屏障对齐后同时打验签口。

    载荷们长度必须为 2；返回 [(会话名, HTTP码, JSON), ...]。
    """
    assert len(载荷们) == 2
    屏障 = threading.Barrier(2)
    锁 = threading.Lock()
    收口: list[tuple] = []

    def 一路(名: str, 载荷: dict) -> None:
        c = app.test_client()
        r = c.post("/api/登录", json={"账号": 账号, "密码": 密码})
        assert r.status_code == 200, f"{名} 登录失败 {r.status_code}"
        屏障.wait()
        resp = c.post(路径, json=载荷)
        body = resp.get_json(silent=True)
        with 锁:
            收口.append((名, resp.status_code, body))

    ts = [
        threading.Thread(target=一路, args=(str(载荷.get("会话名") or f"会话{i+1}"), 载荷))
        for i, 载荷 in enumerate(载荷们)
    ]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return 收口


# 与并发投递卷同名的通用别名。
双会话同点 = 双会话同点验签


def 双会话争用投递(app, 体甲: dict, 体乙: dict) -> list[tuple]:
    return 双会话同点验签(app, [体甲, 体乙], 路径="/api/投递")
