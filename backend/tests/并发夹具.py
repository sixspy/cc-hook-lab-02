"""并发事故夹具：同事件号双会话同时点投递（hook-02-并发投递互斥）。

两个线程各持一个独立 Flask 测试客户端（各自登录、各自 Cookie 罐，
模拟两个浏览器会话），在屏障处同时放行，对同一事件号并发 POST /api/投递。
事故事件体取自 fixtures/并发投递样例.json，事件号每次调用覆写为唯一名，
避免同一测试库内多模块复用冲突。
"""
from __future__ import annotations

import threading
import uuid

from app.services import 入队, 夹具

_账号 = "admin"
_密码 = "123456"


def 备事故事件() -> str:
    """按并发投递样例入队一条待投事件，返回唯一事件号。"""
    样例 = 夹具.读取("并发投递样例")
    体 = dict(样例["事件"][0])
    体["事件号"] = f"EVT-RACE-{uuid.uuid4().hex[:10]}"
    return 入队.建事件(体)["事件号"]


def 双会话同点(app, 事件号: str, 投递体: dict | None = None) -> list:
    """两路浏览器会话同时对同一事件号点投递，返回 [(会话名, 状态码, 响应体), ...]。"""
    屏障 = threading.Barrier(2)
    收口: list = []
    锁 = threading.Lock()
    体 = {"事件号": 事件号}
    if 投递体:
        体.update(投递体)

    def 一路(会话名: str) -> None:
        客户端 = app.test_client()
        登录 = 客户端.post("/api/登录", json={"账号": _账号, "密码": _密码})
        assert 登录.status_code == 200
        屏障.wait()  # 两路在此对齐后同时放行，制造真争用
        响应 = 客户端.post("/api/投递", json=体)
        with 锁:
            收口.append((会话名, 响应.status_code, 响应.get_json()))

    线程 = [threading.Thread(target=一路, args=(f"会话{i + 1}",)) for i in range(2)]
    for t in 线程:
        t.start()
    for t in 线程:
        t.join()
    return 收口
