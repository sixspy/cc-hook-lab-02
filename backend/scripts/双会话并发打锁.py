#!/usr/bin/env python3
"""双会话并发打同锁脚本（hook-02-并发投递互斥）。

对运行中的投递台起两个独立浏览器会话（各自登录、各自 Cookie 罐），
用屏障对齐后同时 POST 同一事件号，验证只有一路成功、另一路 409 拒绝回刷。
纯标准库，建议用 `python3 -I 双会话并发打锁.py` 运行。
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid

_BASE = "http://127.0.0.1:8500"
_账号 = "admin"
_密码 = "123456"


class 会话:
    def __init__(self, 名: str):
        self.名 = 名
        self.cookie: str | None = None

    def _请求(self, 路径: str, 体: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(体 or {}).encode("utf-8")
        安全路径 = urllib.parse.quote(路径, safe="/")
        req = urllib.request.Request(
            _BASE + 安全路径, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        if self.cookie:
            req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                self._存cookie(resp)
                return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            self._存cookie(e)
            return e.code, json.loads(e.read().decode("utf-8") or "{}")

    def _存cookie(self, resp) -> None:
        头 = resp.headers.get("Set-Cookie")
        if 头:
            self.cookie = 头.split(";", 1)[0]

    def 登录(self) -> None:
        码, _ = self._请求("/api/登录", {"账号": _账号, "密码": _密码})
        if 码 != 200:
            raise RuntimeError(f"{self.名} 登录失败：{码}")

    def 入队(self, 事件号: str) -> None:
        码, rep = self._请求("/api/事件/入队", {
            "事件号": 事件号, "事件类型": "invoice.paid",
            "端点键": "ep-billing", "载荷摘要": f"race={事件号}", "优先级": "紧急",
        })
        if 码 != 200:
            raise RuntimeError(f"入队失败：{码} {rep}")

    def 投递(self, 事件号: str, 屏障: threading.Barrier) -> tuple[int, dict]:
        屏障.wait()
        return self._请求("/api/投递", {"事件号": 事件号})


def main() -> int:
    parser = argparse.ArgumentParser(description="双会话并发打同锁")
    parser.add_argument("--事件号", default=f"EVT-LOCK-{uuid.uuid4().hex[:10]}")
    args = parser.parse_args()
    事件号 = args.事件号

    a, b = 会话("会话甲"), 会话("会话乙")
    a.登录()
    b.登录()
    a.入队(事件号)

    收口: list[tuple[str, int, dict]] = []
    锁 = threading.Lock()
    屏障 = threading.Barrier(2)

    def 打(s: 会话) -> None:
        码, rep = s.投递(事件号, 屏障)
        with 锁:
            收口.append((s.名, 码, rep))

    ts = [threading.Thread(target=打, args=(x,)) for x in (a, b)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    print(f"事件号：{事件号}")
    for 名, 码, rep in 收口:
        print(f"{名} -> HTTP {码} {json.dumps(rep, ensure_ascii=False)}")
    码组 = sorted(码 for _, 码, _ in 收口)
    if 码组 == [200, 409]:
        print("结论：互斥坑生效，一成一拒，无双成功票")
        return 0
    print(f"结论：异常，状态码组合 {码组}，互斥坑未生效")
    return 1


if __name__ == "__main__":
    sys.exit(main())
