from __future__ import annotations

import math
from datetime import datetime, timezone


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def 此刻datetime() -> datetime:
    return datetime.now(timezone.utc)


def 此刻偏移(秒: int = 0) -> str:
    from datetime import timedelta

    return (此刻datetime() + timedelta(seconds=int(秒))).strftime("%Y-%m-%dT%H:%M:%SZ")


def 解析时刻(v) -> datetime:
    """把 epoch 秒/毫秒、数值串、ISO-Z 文本统一解析成 aware UTC datetime。"""
    if isinstance(v, datetime):
        d = v
    elif isinstance(v, (int, float)) and not isinstance(v, bool):
        x = float(v)
        if abs(x) > 1e12:  # 毫秒时间戳
            x /= 1000.0
        d = datetime.fromtimestamp(x, tz=timezone.utc)
    else:
        s = str(v if v is not None else "").strip()
        if not s:
            raise ValueError("空时刻")
        # 纯数字（可带小数）按时间戳处理
        try:
            x = float(s)
            if abs(x) > 1e12:
                x /= 1000.0
            d = datetime.fromtimestamp(x, tz=timezone.utc)
        except ValueError:
            txt = s[:-1] + "+00:00" if s.endswith("Z") else s
            d = datetime.fromisoformat(txt)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def _首个(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def 时钟秒差(
    对端时刻=None,
    本仓时刻=None,
    *,
    秒差=None,
    对端快秒=None,
    快秒=None,
    偏移秒=None,
    **_,
) -> int:
    """返回带符号秒差 = 对端时钟 - 本仓时钟；正数表示对端更快（在未来）。

    显式整数偏移（秒差/对端快秒/快秒/偏移秒）优先，便于夹具确定性复现；
    否则解析两个时刻做差。本仓时刻缺省取当前 UTC。
    """
    显式 = 秒差 if 秒差 is not None else 对端快秒
    if 显式 is None:
        显式 = 快秒 if 快秒 is not None else 偏移秒
    if 显式 is not None and str(显式) != "":
        return int(float(显式))
    if 对端时刻 is None:
        return 0
    peer = 解析时刻(对端时刻)
    local = 解析时刻(本仓时刻) if 本仓时刻 not in (None, "") else 此刻datetime()
    return int(math.floor((peer - local).total_seconds() + 0.5))


def 取体时钟秒差(body: dict) -> int:
    """从 HTTP/服务入参字典的常见别名字段里求秒差。"""
    if not isinstance(body, dict):
        return 0
    显式 = _首个(
        body, "秒差", "时钟偏差秒", "偏差秒", "对端快秒", "快秒", "偏移秒",
        "skew_seconds", "skew", default=None,
    )
    if 显式 is not None:
        return 时钟秒差(秒差=显式)
    peer = _首个(
        body, "对端时刻", "签名时刻", "时间戳", "timestamp", "peer_time", "t",
        "signed_at", "date",
    )
    local = _首个(body, "本仓时刻", "现在时刻", "local_time", "now")
    return 时钟秒差(peer, local)
