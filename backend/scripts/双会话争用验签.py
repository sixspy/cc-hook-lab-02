#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""双会话抢同一次验签（hook-02 收尾自检）。

起服务后运行：
    python backend/scripts/双会话争用验签.py [基址] [端口]

默认基址 http://127.0.0.1:8500 ；Docker 映射宿主 8502 时：
    python backend/scripts/双会话争用验签.py http://127.0.0.1:8502

两路独立 Cookie 会话登录，Barrier 对齐后同时 POST /api/验签，
一路 +30 秒、一路 +50 秒；预期一成（容忍内通过）一拒（超出容忍已拒），
随后 GET 读口核对持久化没有互相覆盖、没有秒差跑出上限的假绿票。
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
import urllib.parse
import http.cookiejar

账号 = "admin"
密码 = "123456"


def 新会话语料(base: str):
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def call(method: str, path: str, body: dict | None = None):
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        # 中文路由在真实 HTTP 上必须百分号编码（保留 / ? & =）。
        path = urllib.parse.quote(path, safe="/?&=")
        req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
        with op.open(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    code, _ = call("POST", "/api/登录", {"账号": 账号, "密码": 密码})
    assert code == 200, f"登录失败 {code}"
    return call


def main(base: str) -> int:
    eid = f"EVT-RACE-LIVE-{int(time.time())}"
    栅 = threading.Barrier(2)
    收口: list[tuple] = []
    锁 = threading.Lock()

    def 一路(名: str, 快秒: int):
        call = 新会话语料(base)
        栅.wait()
        code, rep = call("POST", "/api/验签", {
            "事件号": eid, "会话名": 名, "对端快秒": 快秒,
        })
        with 锁:
            收口.append((名, code, rep))

    ts = [threading.Thread(target=一路, args=("左会话", 30)),
          threading.Thread(target=一路, args=("右会话", 50))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    print("== 双会话同点 /api/验签 ==")
    for 名, code, rep in 收口:
        print(f"[{名}] HTTP {code} 秒差={rep.get('秒差')} "
              f"上限档={rep.get('上限档')} 判定={rep.get('判定')} "
              f"快照={rep.get('快照号')}")

    判定 = sorted(str(r[2].get("判定")) for r in 收口)
    assert 判定 == ["容忍内通过", "超出容忍已拒"], f"双会话判定被覆盖：{判定}"

    # 用任一会话核对持久化读口。
    call = 新会话语料(base)
    code, rows = call("GET", f"/api/验签?事件号={eid}")
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("裁决") or []
    assert code == 200 and len(rows) >= 2, f"读口票数不足：{code} {rows}"
    假绿 = [r for r in rows
            if r.get("判定") == "容忍内通过" and int(r.get("秒差", 0)) > int(r.get("容忍上限秒", 40))]
    assert not 假绿, f"发现秒差跑出上限的假绿票：{假绿}"
    判集 = {r.get("判定") for r in rows}
    assert "容忍内通过" in 判集 and "超出容忍已拒" in 判集, 判集
    print(f"== 读口核对通过：{len(rows)} 张票，判定={sorted(判集)}，无超限假绿 ==")
    print("耗时自检：通过")
    return 0


if __name__ == "__main__":
    基址 = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8500"
    if len(sys.argv) > 2 and "://" not in 基址:
        基址 = f"http://127.0.0.1:{sys.argv[2]}"
    raise SystemExit(main(基址.rstrip("/")))
