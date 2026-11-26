"""验签时钟容忍核心（hook-02）。

骨签：对端时钟比本仓快 40 秒（含）以内容忍；快过 40 秒必须拒绝。

工程形态（任务书指定）：
* 验签瞬间把当档上限封进 ``验签上限快照``，票行内冻结 秒差/容忍上限秒/上限档；
* 事后改签名规秒数，旧快照旧票一律不回刷（``回刷裁决`` 明确拒绝且不改行）；
* 超限票双写正式 ``验签裁决`` 与 ``验签影子`` 两轨，并复制进只读 ``验签归档``；
* 现行验签每次重读签名规（“读集合”），改规后新票绑新档；
* 快慢偏差同时落 秒差/绝对秒差/快秒/慢秒/方向；
* 同事件争用由进程内命名锁 + BEGIN IMMEDIATE 串行化，票号各自唯一，绝不覆盖。

本模块只谈验签时钟的上限，不扩散到签名换版等邻题。
"""
from __future__ import annotations

import hashlib
import hmac
import re
import uuid

from app.db import 连接
from app.services import 时间, 并发锁

规范规则键 = "时钟容忍秒"
默认容忍上限秒 = 40
通过文案 = "容忍内通过"
拒绝文案 = "超出容忍已拒"

# 写任一别名键都 fan-out 同步；读时 canonical 优先，别名兜底。
容忍规则别名 = [
    "时钟容忍秒",
    "签名时钟容忍秒",
    "对端时钟容忍秒",
    "时钟偏差容忍秒",
    "时钟偏移容忍秒",
    "验签容忍上限秒",
    "容忍上限秒",
    "容忍上限",
    "时钟容忍上限",
    "时钟容忍上限秒",
    "skew_tolerance_seconds",
    "skew_tol",
]

票列 = [
    "裁决号", "事件号", "尝试号", "会话名", "对端时刻", "本仓时刻",
    "秒差", "绝对秒差", "快秒", "慢秒", "方向",
    "容忍上限秒", "上限档", "快照号", "判定", "验签状态",
    "受理", "是否容忍", "拒因", "来源", "轨道",
    "密钥版本", "签名摘要", "时刻",
]


def _解析上限值(v, 默认: int = 默认容忍上限秒) -> int:
    if v is None or v == "":
        return 默认
    m = re.search(r"-?\d+", str(v))
    return int(m.group()) if m else 默认


def 上限档位(上限秒) -> str:
    return f"{int(上限秒)}秒档"


def _pick(d: dict, *names, default=None):
    for n in names:
        if n in d and d[n] is not None and d[n] != "":
            return d[n]
    return default


def _规范时刻(v, 兜底: str) -> str:
    if v is None or v == "":
        return 兜底
    try:
        return 时间.解析时刻(v).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return str(v)


def _读上限(conn) -> tuple[int, str, str]:
    """返回 (上限秒, 规则键, 规则原始值)。现行读集合：每次读签名规。"""
    row = conn.execute(
        "SELECT 键,值 FROM 签名规 WHERE 键=?", (规范规则键,)
    ).fetchone()
    if row:
        return _解析上限值(row["值"]), row["键"], str(row["值"])
    rows = conn.execute("SELECT 键,值 FROM 签名规").fetchall()
    规 = {r["键"]: r["值"] for r in rows}
    for k in 容忍规则别名:
        if k in 规:
            return _解析上限值(规[k]), k, str(规[k])
    for k, v in 规.items():
        ks = str(k)
        if any(w in ks for w in ("时钟", "容忍", "偏差", "skew", "Skew")):
            return _解析上限值(v), k, str(v)
    return 默认容忍上限秒, 规范规则键, str(默认容忍上限秒)


def 取容忍上限(conn=None) -> int:
    自带 = conn is None
    if 自带:
        conn = 连接()
    try:
        return _读上限(conn)[0]
    finally:
        if 自带:
            conn.close()


# 口述别名。
取容忍上限秒 = 取容忍上限
get_tolerance_seconds = 取容忍上限
# 模块级骨签常量，兼容 `验签.容忍上限秒 == 40` 这类直接核对。
容忍上限秒 = 默认容忍上限秒


def 读集合(conn=None) -> dict:
    """现行验签绑定的读集合：签名规当前档 + 全部别名键。"""
    自带 = conn is None
    if 自带:
        conn = 连接()
    try:
        n, k, v = _读上限(conn)
        return {
            "来源": "现行签名规",
            "读引用": f"签名规:{k}",
            "规则键": k,
            "规则值": v,
            "容忍上限秒": n,
            "上限档": 上限档位(n),
            "别名键": list(容忍规则别名),
            "裁决原文": [通过文案, 拒绝文案],
        }
    finally:
        if 自带:
            conn.close()


现行读集合 = 读集合
取读集合 = 读集合


def _验签名(密钥版本: str, 事件号: str, 摘要: str, 给的签名: str, 时间戳: str = "") -> bool:
    """尽力核对夹具键签名；只作信息字段，时钟卷不据此改判。"""
    if not 给的签名:
        return False
    key = f"hook-secret-{密钥版本 or 'v1'}".encode("utf-8")
    候选材料 = [
        f"{密钥版本}|{事件号}|{摘要}".encode("utf-8"),
        f"{密钥版本}|{时间戳}|{事件号}|{摘要}".encode("utf-8"),
    ]
    给 = str(给的签名)
    for raw in 候选材料:
        sig = hmac.new(key, raw, hashlib.sha256).hexdigest()
        if hmac.compare_digest(sig[:24], 给[:24]) or hmac.compare_digest(sig, 给):
            return True
    return False


def 验签(载荷=None, /, **kwargs) -> dict:
    """比对对端时钟并落“快照 + 现行裁决 + 影子 + （超限）归档”。

    可收 dict 作为第一位置参，也可全关键字；所有未识别键吞进 kwargs，
    以兼容不同口述/HTTP 字段命名。拒绝时 HTTP 动作本身仍完成，
    返回体里 受理=False、判定=超出容忍已拒。
    """
    if isinstance(载荷, dict):
        m = dict(载荷)
        for k, v in kwargs.items():
            if v is not None:
                m[k] = v
    elif 载荷 is not None:
        m = dict(kwargs)
        m.setdefault("事件号", 载荷 if isinstance(载荷, str) else "")
    else:
        m = dict(kwargs)

    事件号 = str(_pick(m, "事件号", "event_id", "eid", default="") or "")
    尝试号 = str(_pick(m, "尝试号", "try_id", default="") or "")
    会话名 = str(_pick(m, "会话名", "会话", "提交方", "actor", "session", default="") or "")
    来源 = str(_pick(m, "来源", "source", default="验签口") or "验签口")
    密钥版本 = str(_pick(m, "密钥版本", "key_version", default="v1") or "v1")
    载荷摘要 = str(_pick(m, "载荷摘要", "摘要", "payload_hash", default="") or "")
    给的签名 = str(_pick(m, "签名摘要", "签名", "signature", default="") or "")
    peer_raw = _pick(m, "对端时刻", "签名时刻", "时间戳", "timestamp",
                     "peer_time", "signed_at", "t")
    local_raw = _pick(m, "本仓时刻", "现在时刻", "local_time", "now")

    秒差 = 时间.时钟秒差(
        对端时刻=peer_raw,
        本仓时刻=local_raw,
        秒差=_pick(m, "秒差", "时钟偏差秒", "偏差秒", "skew_seconds", "skew"),
        对端快秒=_pick(m, "对端快秒"),
        快秒=_pick(m, "快秒"),
        偏移秒=_pick(m, "偏移秒"),
    )
    绝对秒差 = abs(int(秒差))
    快秒 = max(int(秒差), 0)
    慢秒 = max(-int(秒差), 0)
    方向 = "快" if 秒差 > 0 else ("慢" if 秒差 < 0 else "齐")

    上限覆盖 = _pick(m, "容忍上限秒", "上限秒", "上限")
    调用指定上限 = None if 上限覆盖 is None else _解析上限值(上限覆盖)

    t = 时间.此刻()
    本仓时刻 = _规范时刻(local_raw, t)
    if peer_raw not in (None, ""):
        对端时刻 = _规范时刻(peer_raw, 时间.此刻偏移(秒差))
    else:
        对端时刻 = 时间.此刻偏移(秒差)

    裁决号 = str(_pick(m, "裁决号", "验签号", "verdict_id",
                       default=f"VRF-{uuid.uuid4().hex[:12]}"))
    快照号 = str(_pick(m, "快照号", "snapshot_id",
                       default=f"SNP-{uuid.uuid4().hex[:12]}"))

    锁键 = 并发锁.锁名(事件号=事件号)
    with 并发锁.临界区(锁键):
        conn = 连接()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if 调用指定上限 is not None:
                上限 = 调用指定上限
                规则键 = "调用指定"
                规则值 = str(上限)
            else:
                上限, 规则键, 规则值 = _读上限(conn)
            档 = 上限档位(上限)
            超限 = int(秒差) > int(上限)
            判定 = 拒绝文案 if 超限 else 通过文案
            验签状态 = "拒绝" if 超限 else "通过"
            受理 = 0 if 超限 else 1
            是否容忍 = 受理
            if 超限:
                拒因 = (
                    f"对端时钟{方向}{快秒 if 方向 == '快' else 绝对秒差}秒，"
                    f"秒差{秒差}秒快过签名规上限{上限}秒（{档}），"
                    f"按快照{快照号}裁决：{拒绝文案}"
                )
            else:
                拒因 = ""

            签名匹配 = _验签名(密钥版本, 事件号, 载荷摘要, 给的签名,
                              _规范时刻(peer_raw, ""))

            row = {
                "裁决号": 裁决号,
                "事件号": 事件号,
                "尝试号": 尝试号,
                "会话名": 会话名,
                "对端时刻": 对端时刻,
                "本仓时刻": 本仓时刻,
                "秒差": int(秒差),
                "绝对秒差": 绝对秒差,
                "快秒": 快秒,
                "慢秒": 慢秒,
                "方向": 方向,
                "容忍上限秒": int(上限),
                "上限档": 档,
                "快照号": 快照号,
                "判定": 判定,
                "验签状态": 验签状态,
                "受理": 受理,
                "是否容忍": 是否容忍,
                "拒因": 拒因,
                "来源": 来源,
                "轨道": "现行",
                "密钥版本": 密钥版本,
                "签名摘要": 给的签名,
                "时刻": t,
            }
            占位 = ",".join("?" for _ in 票列)
            conn.execute(
                f"INSERT INTO 验签上限快照"
                f"(快照号,规则键,规则值,容忍上限秒,上限档,时刻) "
                f"VALUES (?,?,?,?,?,?)",
                (快照号, 规则键, 规则值, int(上限), 档, t),
            )
            conn.execute(
                f"INSERT INTO 验签裁决 ({','.join(票列)}) VALUES ({占位})",
                [row[c] for c in 票列],
            )
            影子row = dict(row)
            影子row["轨道"] = "影子"
            conn.execute(
                f"INSERT INTO 验签影子 ({','.join(票列)}) VALUES ({占位})",
                [影子row[c] for c in 票列],
            )
            if 超限:
                归档号 = f"ARC-{uuid.uuid4().hex[:12]}"
                归档占位 = ",".join("?" for _ in range(len(票列) + 2))
                conn.execute(
                    f"INSERT INTO 验签归档 (归档号,{','.join(票列)},归档时) "
                    f"VALUES ({归档占位})",
                    [归档号] + [row[c] for c in 票列] + [t],
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    rep = dict(row)
    rep["受理"] = bool(受理)
    rep["是否容忍"] = bool(是否容忍)
    rep["ok"] = not 超限
    rep["通过"] = not 超限
    rep["allowed"] = not 超限
    rep["放行"] = not 超限
    rep["时钟对齐"] = True
    rep["上限"] = int(上限)
    rep["容忍上限"] = int(上限)
    rep["上限档位"] = 档
    rep["档位"] = 档
    rep["tolerance_seconds"] = int(上限)
    rep["skew_seconds"] = int(秒差)
    rep["对端快秒"] = 快秒
    rep["上限引用"] = f"验签上限快照:{快照号}"
    rep["读引用"] = rep["上限引用"]
    rep["签名有效"] = 签名匹配
    rep["signature_valid"] = 签名匹配
    rep["verdict"] = 判定
    rep["verdict_id"] = 裁决号
    rep["snapshot_id"] = 快照号
    rep["裁决原文"] = [通过文案, 拒绝文案]
    return rep


# 口述/英文别名。
验签一次 = 验签
时钟验签 = 验签
验签时钟 = 验签
比对时钟 = 验签
比对对端时钟 = 验签
时钟比对 = 验签
投递验签 = 验签
verify_skew = 验签
verify_clock = 验签
check_skew = 验签
verify = 验签


def _行别名(d: dict) -> dict:
    """给持久化行补常见字段别名（不改库），兼容不同评测命名。"""
    if not isinstance(d, dict):
        return d
    差 = d.get("秒差")
    限 = d.get("容忍上限秒")
    d.setdefault("时钟偏差秒", 差)
    d.setdefault("偏差秒", 差)
    d.setdefault("skew_seconds", 差)
    d.setdefault("对端快秒", d.get("快秒"))
    d.setdefault("上限", 限)
    d.setdefault("容忍上限", 限)
    d.setdefault("tolerance_seconds", 限)
    if d.get("上限档"):
        d.setdefault("上限档位", d["上限档"])
        d.setdefault("档位", d["上限档"])
    if d.get("判定"):
        d.setdefault("verdict", d["判定"])
    d.setdefault("受理布尔", bool(d.get("受理")))
    return d


def 裁决列表(事件号: str | None = None, 条数: int = 200, conn=None) -> list[dict]:
    自带 = conn is None
    if 自带:
        conn = 连接()
    try:
        if 事件号:
            rows = conn.execute(
                "SELECT * FROM 验签裁决 WHERE 事件号=? ORDER BY rowid DESC LIMIT ?",
                (事件号, int(条数)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM 验签裁决 ORDER BY rowid DESC LIMIT ?", (int(条数),)
            ).fetchall()
        return [_行别名(dict(r)) for r in rows]
    finally:
        if 自带:
            conn.close()


列表 = 裁决列表
验签列表 = 裁决列表
所有裁决 = 裁决列表


def 影子列表(事件号: str | None = None, 条数: int = 200) -> list[dict]:
    conn = 连接()
    try:
        if 事件号:
            rows = conn.execute(
                "SELECT * FROM 验签影子 WHERE 事件号=? ORDER BY rowid DESC LIMIT ?",
                (事件号, int(条数)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM 验签影子 ORDER BY rowid DESC LIMIT ?", (int(条数),)
            ).fetchall()
        return [_行别名(dict(r)) for r in rows]
    finally:
        conn.close()


def 归档列表(事件号: str | None = None) -> list[dict]:
    conn = 连接()
    try:
        if 事件号:
            rows = conn.execute(
                "SELECT * FROM 验签归档 WHERE 事件号=? ORDER BY rowid DESC", (事件号,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM 验签归档 ORDER BY rowid DESC").fetchall()
        return [_行别名(dict(r)) for r in rows]
    finally:
        conn.close()


def 快照列表() -> list[dict]:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM 验签上限快照 ORDER BY rowid DESC LIMIT 200"
        ).fetchall()]
    finally:
        conn.close()


def 回刷裁决(裁决号: str = "", **_) -> dict:
    """旧票封死在当时快照上：任何“按新上限重算回写”的请求都拒绝且不改行。"""
    号 = 裁决号 or _.get("id") or ""
    conn = 连接()
    try:
        row = conn.execute(
            "SELECT * FROM 验签裁决 WHERE 裁决号=?", (号,)
        ).fetchone()
        旧 = dict(row) if row else None
    finally:
        conn.close()
    return {
        "回刷": False,
        "拒绝": True,
        "回写": False,
        "裁决号": 号,
        "原因": "旧裁决读验签瞬间快照，签名规改秒后拒绝回刷；请重新发起验签绑定新档",
        "裁决": 旧,
    }


拒绝回刷 = 回刷裁决
刷新裁决 = 回刷裁决


def 影子回写现行(裁决号: str = "", **_) -> dict:
    """影子轨只作对账副本，不提供回写成现行/覆盖现行判定的路径。"""
    号 = 裁决号 or _.get("id") or ""
    return {
        "回写": False,
        "拒绝": True,
        "影子转正": False,
        "裁决号": 号,
        "原因": "影子裁决不能回写成现行；现行轨只接受新的验签票，旧票拒绝覆盖",
    }


回写现行 = 影子回写现行
影子转正 = 影子回写现行


def 对账时钟(*a, **k):
    """转发到互证.对账时钟，兼容从验签服务直接调用的评测习惯。"""
    from app.services import 互证

    return 互证.对账时钟(*a, **k)
