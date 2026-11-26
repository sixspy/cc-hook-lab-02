"""进程内命名锁：把“读上限 → 封快照 → 双写裁决”临界区串行化。

双会话/双线程争用同一事件的验签时，保证两份不同时钟的裁决各自完整落票，
不会因共享模块变量或后写覆盖先写而静默假绿。多进程部署再由
BEGIN IMMEDIATE 的 SQLite 写事务兜底。
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

_锁表: dict[str, threading.RLock] = {}
_名册锁 = threading.Lock()
_统计: dict[str, dict] = {}


def 同锁(名: str) -> threading.RLock:
    with _名册锁:
        lk = _锁表.get(名)
        if lk is None:
            lk = threading.RLock()
            _锁表[名] = lk
            _统计[名] = {"累计进入": 0, "当前": 0, "最大并发": 0}
        return lk


@contextmanager
def 临界区(名: str):
    lk = 同锁(名)
    st = _统计.setdefault(名, {"累计进入": 0, "当前": 0, "最大并发": 0})
    with lk:
        st["累计进入"] += 1
        st["当前"] += 1
        st["最大并发"] = max(st["最大并发"], st["当前"])
        try:
            yield lk
        finally:
            st["当前"] -= 1


def 锁名(事件号: str = "", 端点键: str = "") -> str:
    if 事件号:
        return f"验签:{事件号}"
    if 端点键:
        return f"endpoint:{端点键}"
    return "验签:全局"


def 名册() -> dict:
    with _名册锁:
        return {k: dict(v) for k, v in _统计.items()}
