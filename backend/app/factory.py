from __future__ import annotations
import os
from pathlib import Path
from flask import Flask, jsonify, redirect, request, send_from_directory

from app import seed
from app.services import 会话, 入队, 投递, 死信, 重试, 互证, 端点, 夹具, 说明, 签名目录, 验签

_STATIC = Path(__file__).resolve().parent / "static"


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(_STATIC), static_url_path="")
    app.secret_key = os.environ.get("密钥", "hook-lab-dev")

    @app.before_request
    def _gate():
        if request.path.startswith("/api/") and request.path not in ("/api/登录",):
            if not 会话.已登录():
                return jsonify({"错误": "未登录"}), 401
        return None

    @app.route("/login")
    def 登录页():
        return send_from_directory(_STATIC, "login.html")

    @app.route("/")
    def 首页():
        return send_from_directory(_STATIC, "index.html")

    @app.route("/<path:name>")
    def 静态页(name):
        p = _STATIC / name
        if p.is_file():
            return send_from_directory(_STATIC, name)
        return redirect("/")

    @app.post("/api/登录")
    def api_登录():
        body = request.get_json(force=True, silent=True) or {}
        账号 = str(body.get("账号") or body.get("user") or "")
        密码 = str(body.get("密码") or body.get("password") or "")
        if 会话.校验登录(账号, 密码):
            会话.写入会话(账号)
            return jsonify({"ok": True, "用户": 账号})
        return jsonify({"ok": False, "错误": "账号或密码不对"}), 401

    @app.post("/api/登出")
    def api_登出():
        会话.登出()
        return jsonify({"ok": True})

    @app.get("/api/概览")
    def api_概览():
        return jsonify(签名目录.概览())

    @app.get("/api/仓情")
    def api_仓情():
        return jsonify(说明.仓情())

    @app.get("/api/签名规")
    def api_签名规_get():
        return jsonify(签名目录.签名规())

    @app.post("/api/签名规")
    def api_签名规_post():
        body = request.get_json(force=True, silent=True) or {}
        try:
            return jsonify(签名目录.改签名规(body))
        except ValueError as e:
            return jsonify({"错误": str(e)}), 400

    @app.get("/api/事件")
    def api_事件():
        return jsonify(签名目录.事件列表())

    @app.get("/api/事件/<eid>")
    def api_事件一条(eid):
        row = 签名目录.事件一条(eid)
        if not row:
            return jsonify({"错误": "无此事件"}), 404
        return jsonify(row)

    @app.post("/api/事件/入队")
    def api_入队():
        body = request.get_json(force=True, silent=True) or {}
        try:
            return jsonify(入队.建事件(body))
        except ValueError as e:
            return jsonify({"错误": str(e)}), 400

    @app.get("/api/投递")
    def api_投递列表():
        return jsonify(签名目录.投递列表())

    @app.post("/api/投递")
    def api_投递():
        body = request.get_json(force=True, silent=True) or {}
        try:
            b = dict(body)
            eid = b.pop("事件号")
            强制 = b.pop("强制失败", False)
            # 其余键（对端快秒/对端时刻/秒差/会话名 …）整体透传给时钟验签。
            return jsonify(投递.投递一次(eid, 强制, **b))
        except (KeyError, ValueError) as e:
            return jsonify({"错误": str(e)}), 400

    @app.post("/api/验签")
    @app.post("/api/签名/验签")
    @app.post("/api/投递验签")
    @app.post("/api/skew/verify")
    def api_验签_post():
        body = request.get_json(force=True, silent=True) or {}
        try:
            # 时钟超限是“验签动作完成但裁决拒绝”，HTTP 仍 200，由 body.受理/判定表达。
            return jsonify(验签.验签(body))
        except ValueError as e:
            return jsonify({"错误": str(e)}), 400

    @app.get("/api/验签")
    def api_验签_get():
        eid = request.args.get("事件号") or request.args.get("event_id") or ""
        return jsonify(验签.裁决列表(eid or None))

    @app.get("/api/验签/列表")
    def api_验签列表包():
        eid = request.args.get("事件号") or request.args.get("event_id") or ""
        rows = 验签.裁决列表(eid or None)
        return jsonify({"rows": rows, "裁决": rows, "总数": len(rows)})

    @app.get("/api/验签/影子")
    def api_验签影子():
        eid = request.args.get("事件号") or ""
        return jsonify(验签.影子列表(eid or None))

    @app.get("/api/验签/归档")
    def api_验签归档():
        eid = request.args.get("事件号") or ""
        return jsonify(验签.归档列表(eid or None))

    @app.get("/api/验签/快照")
    def api_验签快照():
        return jsonify(验签.快照列表())

    @app.get("/api/验签/读集合")
    @app.get("/api/时钟容忍")
    @app.get("/api/skew-tolerance")
    def api_验签读集合():
        return jsonify(验签.读集合())

    @app.post("/api/时钟验签")
    @app.post("/api/clock/verify")
    def api_时钟验签别名():
        body = request.get_json(force=True, silent=True) or {}
        try:
            return jsonify(验签.验签(body))
        except ValueError as e:
            return jsonify({"错误": str(e)}), 400

    @app.post("/api/验签/回刷")
    def api_验签回刷():
        body = request.get_json(force=True, silent=True) or {}
        return jsonify(验签.回刷裁决(body.get("裁决号") or body.get("id") or ""))

    @app.post("/api/验签/影子回写")
    def api_影子回写():
        body = request.get_json(force=True, silent=True) or {}
        return jsonify(验签.影子回写现行(body.get("裁决号") or body.get("id") or ""))

    @app.get("/api/互证/对账时钟")
    @app.post("/api/互证/对账时钟")
    @app.get("/api/对账时钟")
    def api_对账时钟():
        eid = request.args.get("事件号") or (
            (request.get_json(silent=True) or {}).get("事件号") if request.method == "POST" else None
        )
        return jsonify(互证.对账时钟(eid or None))

    @app.post("/api/投递/批量重试")
    def api_批量重试():
        return jsonify(重试.批量重试待投())

    @app.get("/api/死信")
    def api_死信():
        return jsonify(签名目录.死信列表())

    @app.post("/api/死信/重投")
    def api_死信重投():
        body = request.get_json(force=True, silent=True) or {}
        try:
            return jsonify(死信.重投(body["事件号"]))
        except (KeyError, ValueError) as e:
            return jsonify({"错误": str(e)}), 400

    @app.post("/api/死信/作废")
    def api_死信作废():
        body = request.get_json(force=True, silent=True) or {}
        try:
            return jsonify(死信.作废(body["事件号"], body.get("原因", "人工作废")))
        except (KeyError, ValueError) as e:
            return jsonify({"错误": str(e)}), 400

    @app.get("/api/端点")
    def api_端点():
        return jsonify(签名目录.端点列表())

    @app.post("/api/端点")
    def api_端点登记():
        body = request.get_json(force=True, silent=True) or {}
        try:
            return jsonify(端点.登记(body))
        except ValueError as e:
            return jsonify({"错误": str(e)}), 400

    @app.post("/api/端点/启用")
    def api_端点启用():
        body = request.get_json(force=True, silent=True) or {}
        try:
            return jsonify(端点.改启用(body["端点键"], bool(body.get("启用"))))
        except (KeyError, ValueError) as e:
            return jsonify({"错误": str(e)}), 400

    @app.get("/api/互证")
    def api_互证列表():
        return jsonify(签名目录.互证列表())

    @app.post("/api/互证/跑")
    def api_互证跑():
        return jsonify(互证.跑一次())

    @app.get("/api/夹具")
    def api_夹具():
        return jsonify(夹具.列表())

    @app.post("/api/夹具入队/<name>")
    def api_夹具入队(name):
        try:
            体 = 夹具.读取(name)
            out = [入队.建事件(item) for item in 体.get("事件", [])]
            return jsonify({"入队": out})
        except FileNotFoundError:
            return jsonify({"错误": name}), 404
        except ValueError as e:
            return jsonify({"错误": str(e)}), 400

    @app.get("/api/空桩")
    def api_空桩():
        root = Path(__file__).resolve().parent / "modules"
        out = []
        if root.is_dir():
            for p in sorted(root.iterdir()):
                if p.is_dir() and (p / "__init__.py").is_file():
                    out.append(p.name)
        return jsonify({"空桩": out, "条数": len(out)})

    with app.app_context():
        seed.初始化库()
    return app
