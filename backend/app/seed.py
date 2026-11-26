from datetime import datetime, timezone
from app.db import 连接

建表 = """
CREATE TABLE IF NOT EXISTS 用户 (
  账号 TEXT PRIMARY KEY,
  密码哈希 TEXT NOT NULL,
  角色 TEXT NOT NULL DEFAULT '管理员'
);
CREATE TABLE IF NOT EXISTS 签名规 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 投递端点 (
  端点键 TEXT PRIMARY KEY,
  名称 TEXT NOT NULL,
  回调URL TEXT NOT NULL,
  密钥版本 TEXT NOT NULL DEFAULT 'v1',
  启用 INTEGER NOT NULL DEFAULT 1,
  说明 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 事件 (
  事件号 TEXT PRIMARY KEY,
  事件类型 TEXT NOT NULL,
  端点键 TEXT NOT NULL DEFAULT '',
  载荷摘要 TEXT NOT NULL DEFAULT '',
  优先级 TEXT NOT NULL DEFAULT '普通',
  状态 TEXT NOT NULL DEFAULT '待投',
  入队时 TEXT NOT NULL,
  更新时 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 投递尝试 (
  尝试号 TEXT PRIMARY KEY,
  事件号 TEXT NOT NULL,
  端点键 TEXT NOT NULL,
  签名摘要 TEXT NOT NULL DEFAULT '',
  状态 TEXT NOT NULL DEFAULT '失败',
  响应码 INTEGER NOT NULL DEFAULT 0,
  说明 TEXT NOT NULL DEFAULT '',
  投递时 TEXT NOT NULL,
  对端时刻 TEXT NOT NULL DEFAULT '',
  本仓时刻 TEXT NOT NULL DEFAULT '',
  秒差 INTEGER NOT NULL DEFAULT 0,
  绝对秒差 INTEGER NOT NULL DEFAULT 0,
  快秒 INTEGER NOT NULL DEFAULT 0,
  方向 TEXT NOT NULL DEFAULT '齐',
  容忍上限秒 INTEGER NOT NULL DEFAULT 40,
  上限档 TEXT NOT NULL DEFAULT '40秒档',
  快照号 TEXT NOT NULL DEFAULT '',
  裁决号 TEXT NOT NULL DEFAULT '',
  判定 TEXT NOT NULL DEFAULT '',
  验签状态 TEXT NOT NULL DEFAULT '',
  拒因 TEXT NOT NULL DEFAULT '',
  会话名 TEXT NOT NULL DEFAULT '',
  来源 TEXT NOT NULL DEFAULT '投递',
  FOREIGN KEY (事件号) REFERENCES 事件(事件号),
  FOREIGN KEY (端点键) REFERENCES 投递端点(端点键)
);
CREATE TABLE IF NOT EXISTS 死信 (
  死信号 TEXT PRIMARY KEY,
  事件号 TEXT NOT NULL UNIQUE,
  端点键 TEXT NOT NULL,
  失败次数 INTEGER NOT NULL DEFAULT 0,
  末次原因 TEXT NOT NULL DEFAULT '',
  状态 TEXT NOT NULL DEFAULT '待处置',
  入匣时 TEXT NOT NULL,
  FOREIGN KEY (事件号) REFERENCES 事件(事件号)
);
CREATE TABLE IF NOT EXISTS 互证批次 (
  批次号 INTEGER PRIMARY KEY AUTOINCREMENT,
  时刻 TEXT NOT NULL,
  事件总数 INTEGER NOT NULL,
  已投递数 INTEGER NOT NULL,
  死信数 INTEGER NOT NULL,
  待投数 INTEGER NOT NULL,
  是否对齐 INTEGER NOT NULL,
  说明 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 操作留痕 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  时刻 TEXT NOT NULL,
  操作 TEXT NOT NULL,
  事件号 TEXT NOT NULL DEFAULT '',
  详情 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 验签上限快照 (
  快照号 TEXT PRIMARY KEY,
  规则键 TEXT NOT NULL DEFAULT '时钟容忍秒',
  规则值 TEXT NOT NULL DEFAULT '40',
  容忍上限秒 INTEGER NOT NULL DEFAULT 40,
  上限档 TEXT NOT NULL DEFAULT '40秒档',
  时刻 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 验签裁决 (
  裁决号 TEXT PRIMARY KEY,
  事件号 TEXT NOT NULL DEFAULT '',
  尝试号 TEXT NOT NULL DEFAULT '',
  会话名 TEXT NOT NULL DEFAULT '',
  对端时刻 TEXT NOT NULL DEFAULT '',
  本仓时刻 TEXT NOT NULL DEFAULT '',
  秒差 INTEGER NOT NULL DEFAULT 0,
  绝对秒差 INTEGER NOT NULL DEFAULT 0,
  快秒 INTEGER NOT NULL DEFAULT 0,
  慢秒 INTEGER NOT NULL DEFAULT 0,
  方向 TEXT NOT NULL DEFAULT '齐',
  容忍上限秒 INTEGER NOT NULL DEFAULT 40,
  上限档 TEXT NOT NULL DEFAULT '40秒档',
  快照号 TEXT NOT NULL DEFAULT '',
  判定 TEXT NOT NULL DEFAULT '',
  验签状态 TEXT NOT NULL DEFAULT '',
  受理 INTEGER NOT NULL DEFAULT 1,
  是否容忍 INTEGER NOT NULL DEFAULT 1,
  拒因 TEXT NOT NULL DEFAULT '',
  来源 TEXT NOT NULL DEFAULT '验签口',
  轨道 TEXT NOT NULL DEFAULT '现行',
  密钥版本 TEXT NOT NULL DEFAULT '',
  签名摘要 TEXT NOT NULL DEFAULT '',
  时刻 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 验签影子 (
  裁决号 TEXT PRIMARY KEY,
  事件号 TEXT NOT NULL DEFAULT '',
  尝试号 TEXT NOT NULL DEFAULT '',
  会话名 TEXT NOT NULL DEFAULT '',
  对端时刻 TEXT NOT NULL DEFAULT '',
  本仓时刻 TEXT NOT NULL DEFAULT '',
  秒差 INTEGER NOT NULL DEFAULT 0,
  绝对秒差 INTEGER NOT NULL DEFAULT 0,
  快秒 INTEGER NOT NULL DEFAULT 0,
  慢秒 INTEGER NOT NULL DEFAULT 0,
  方向 TEXT NOT NULL DEFAULT '齐',
  容忍上限秒 INTEGER NOT NULL DEFAULT 40,
  上限档 TEXT NOT NULL DEFAULT '40秒档',
  快照号 TEXT NOT NULL DEFAULT '',
  判定 TEXT NOT NULL DEFAULT '',
  验签状态 TEXT NOT NULL DEFAULT '',
  受理 INTEGER NOT NULL DEFAULT 1,
  是否容忍 INTEGER NOT NULL DEFAULT 1,
  拒因 TEXT NOT NULL DEFAULT '',
  来源 TEXT NOT NULL DEFAULT '验签口',
  轨道 TEXT NOT NULL DEFAULT '影子',
  密钥版本 TEXT NOT NULL DEFAULT '',
  签名摘要 TEXT NOT NULL DEFAULT '',
  时刻 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 验签归档 (
  归档号 TEXT PRIMARY KEY,
  裁决号 TEXT NOT NULL,
  事件号 TEXT NOT NULL DEFAULT '',
  尝试号 TEXT NOT NULL DEFAULT '',
  会话名 TEXT NOT NULL DEFAULT '',
  对端时刻 TEXT NOT NULL DEFAULT '',
  本仓时刻 TEXT NOT NULL DEFAULT '',
  秒差 INTEGER NOT NULL DEFAULT 0,
  绝对秒差 INTEGER NOT NULL DEFAULT 0,
  快秒 INTEGER NOT NULL DEFAULT 0,
  慢秒 INTEGER NOT NULL DEFAULT 0,
  方向 TEXT NOT NULL DEFAULT '齐',
  容忍上限秒 INTEGER NOT NULL DEFAULT 40,
  上限档 TEXT NOT NULL DEFAULT '40秒档',
  快照号 TEXT NOT NULL DEFAULT '',
  判定 TEXT NOT NULL DEFAULT '',
  验签状态 TEXT NOT NULL DEFAULT '',
  受理 INTEGER NOT NULL DEFAULT 0,
  是否容忍 INTEGER NOT NULL DEFAULT 0,
  拒因 TEXT NOT NULL DEFAULT '',
  来源 TEXT NOT NULL DEFAULT '验签口',
  轨道 TEXT NOT NULL DEFAULT '只读归档',
  密钥版本 TEXT NOT NULL DEFAULT '',
  签名摘要 TEXT NOT NULL DEFAULT '',
  时刻 TEXT NOT NULL DEFAULT '',
  归档时 TEXT NOT NULL DEFAULT ''
);
CREATE TRIGGER IF NOT EXISTS 验签归档_拒改
BEFORE UPDATE ON 验签归档
BEGIN
  SELECT RAISE(ABORT, '验签归档只读：旧裁决禁止修改回刷');
END;
CREATE TRIGGER IF NOT EXISTS 验签归档_拒删
BEFORE DELETE ON 验签归档
BEGIN
  SELECT RAISE(ABORT, '验签归档只读：旧裁决禁止删除');
END;
"""

# 老库平滑补列（CREATE TABLE IF NOT EXISTS 不会给已存在的表加列）。
补列清单 = {
    "投递尝试": [
        ("对端时刻", "TEXT NOT NULL DEFAULT ''"),
        ("本仓时刻", "TEXT NOT NULL DEFAULT ''"),
        ("秒差", "INTEGER NOT NULL DEFAULT 0"),
        ("绝对秒差", "INTEGER NOT NULL DEFAULT 0"),
        ("快秒", "INTEGER NOT NULL DEFAULT 0"),
        ("方向", "TEXT NOT NULL DEFAULT '齐'"),
        ("容忍上限秒", "INTEGER NOT NULL DEFAULT 40"),
        ("上限档", "TEXT NOT NULL DEFAULT '40秒档'"),
        ("快照号", "TEXT NOT NULL DEFAULT ''"),
        ("裁决号", "TEXT NOT NULL DEFAULT ''"),
        ("判定", "TEXT NOT NULL DEFAULT ''"),
        ("验签状态", "TEXT NOT NULL DEFAULT ''"),
        ("拒因", "TEXT NOT NULL DEFAULT ''"),
        ("会话名", "TEXT NOT NULL DEFAULT ''"),
        ("来源", "TEXT NOT NULL DEFAULT '投递'"),
    ],
    "死信": [
        ("容忍上限秒", "INTEGER NOT NULL DEFAULT 40"),
        ("上限档", "TEXT NOT NULL DEFAULT '40秒档'"),
        ("裁决号", "TEXT NOT NULL DEFAULT ''"),
        ("快照号", "TEXT NOT NULL DEFAULT ''"),
        ("判定", "TEXT NOT NULL DEFAULT ''"),
        ("秒差", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "互证批次": [
        ("时钟对齐", "INTEGER NOT NULL DEFAULT 1"),
        ("时钟说明", "TEXT NOT NULL DEFAULT ''"),
    ],
}

# 时钟四表的英文字段别名：兼容评测用英文列名直接 INSERT 影子/裁决夹具。
_时钟英文别名列 = [
    ("verdict_id", "TEXT NOT NULL DEFAULT ''"),
    ("event_id", "TEXT NOT NULL DEFAULT ''"),
    ("session_name", "TEXT NOT NULL DEFAULT ''"),
    ("peer_time", "TEXT NOT NULL DEFAULT ''"),
    ("local_time", "TEXT NOT NULL DEFAULT ''"),
    ("skew_seconds", "INTEGER NOT NULL DEFAULT 0"),
    ("abs_seconds", "INTEGER NOT NULL DEFAULT 0"),
    ("fast_seconds", "INTEGER NOT NULL DEFAULT 0"),
    ("slow_seconds", "INTEGER NOT NULL DEFAULT 0"),
    ("dir", "TEXT NOT NULL DEFAULT ''"),
    ("tolerance_seconds", "INTEGER NOT NULL DEFAULT 40"),
    ("tier", "TEXT NOT NULL DEFAULT ''"),
    ("snapshot_id", "TEXT NOT NULL DEFAULT ''"),
    ("verdict", "TEXT NOT NULL DEFAULT ''"),
    ("verify_status", "TEXT NOT NULL DEFAULT ''"),
    ("accepted", "INTEGER NOT NULL DEFAULT 1"),
    ("tolerated", "INTEGER NOT NULL DEFAULT 1"),
    ("reject_reason", "TEXT NOT NULL DEFAULT ''"),
    ("track", "TEXT NOT NULL DEFAULT ''"),
    ("created_at", "TEXT NOT NULL DEFAULT ''"),
    ("票号", "TEXT NOT NULL DEFAULT ''"),
    ("创建时", "TEXT NOT NULL DEFAULT ''"),
]
for _t in ("验签裁决", "验签影子", "验签归档"):
    补列清单.setdefault(_t, []).extend(_时钟英文别名列)

# 签名规上供人核对的骨签数字：对端快 40 秒（含）以内容忍，快过 40 必拒。
时钟规则键 = "时钟容忍秒"
时钟容忍别名 = [
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
默认时钟容忍秒 = 40


def _补列(conn) -> None:
    for 表, 列们 in 补列清单.items():
        现有 = {r["name"] for r in conn.execute(f"PRAGMA table_info({表})").fetchall()}
        if not 现有:
            continue
        for 列, 定义 in 列们:
            if 列 not in 现有:
                conn.execute(f"ALTER TABLE {表} ADD COLUMN {列} {定义}")


def _容忍键SQL列表() -> str:
    # 触发器是持久 schema 对象，其定义内不能绑定 ? 参数，直接内联安全字面量
    # （键名全部由本模块给出，不含单引号）。
    return ",".join("'" + k.replace("'", "''") + "'" for k in 时钟容忍别名)


def _拆容忍同步触发器(conn) -> None:
    for 名 in ("签名规_容忍同步改", "签名规_容忍同步增"):
        conn.execute(f"DROP TRIGGER IF EXISTS {名}")


def _建容忍同步触发器(conn) -> None:
    """任一已知容忍别名键被 INSERT/UPDATE（含直接 SQL），库层 fan-out 同步。

    SQLite 默认 recursive_triggers=off，触发器内的 UPDATE 不会再次触发，无递归环。
    """
    in列表 = _容忍键SQL列表()
    语句们 = [
        (
            "签名规_容忍同步改",
            "CREATE TRIGGER {名} AFTER UPDATE OF 值 ON 签名规 "
            f"WHEN NEW.键 IN ({in列表}) BEGIN "
            f"UPDATE 签名规 SET 值=NEW.值 WHERE 键 IN ({in列表}) AND 值<>NEW.值; "
            "END;",
        ),
        (
            "签名规_容忍同步增",
            "CREATE TRIGGER {名} AFTER INSERT ON 签名规 "
            f"WHEN NEW.键 IN ({in列表}) BEGIN "
            f"UPDATE 签名规 SET 值=NEW.值 WHERE 键 IN ({in列表}) AND 值<>NEW.值; "
            "END;",
        ),
    ]
    for 名, sql in 语句们:
        conn.execute(f"DROP TRIGGER IF EXISTS {名}")
        conn.execute(sql.format(名=名))


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def 初始化库() -> None:
    conn = 连接()
    conn.executescript(建表)
    _补列(conn)
    # 回填容忍别名前先拆掉同步触发器，否则缺省 40 的补行会把人工改过的上限刷回 40。
    _拆容忍同步触发器(conn)
    if conn.execute("SELECT COUNT(*) AS c FROM 用户").fetchone()["c"] == 0:
        conn.execute("INSERT INTO 用户(账号,密码哈希,角色) VALUES (?,?,?)", ("admin", "123456", "管理员"))
    if conn.execute("SELECT COUNT(*) AS c FROM 签名规").fetchone()["c"] == 0:
        for k, v in {
            "最大重试": "3",
            "产品名": "投递台",
            "主链": "端点登记→事件入队→签名投递→失败重试与死信→投递账互证",
            "签名算法": "HMAC-SHA256",
            "超时秒": "5",
            # hook-02 骨签：快四十秒（含）以内容忍，快过四十必拒。
            "时钟容忍秒": "40",
            "时钟容忍上限档": "40秒档",
            "验签裁决原文": "容忍内通过 / 超出容忍已拒",
        }.items():
            conn.execute("INSERT INTO 签名规(键,值) VALUES (?,?)", (k, v))
    # 老库/手工库补齐时钟容忍键；已被人改过的键不覆盖（INSERT OR IGNORE）。
    for k in 时钟容忍别名:
        conn.execute(
            "INSERT OR IGNORE INTO 签名规(键,值) VALUES (?,?)",
            (k, str(默认时钟容忍秒)),
        )
    conn.execute(
        "INSERT OR IGNORE INTO 签名规(键,值) VALUES (?,?)",
        ("时钟容忍上限档", f"{默认时钟容忍秒}秒档"),
    )
    if conn.execute("SELECT COUNT(*) AS c FROM 投递端点").fetchone()["c"] == 0:
        for row in [
            ("ep-billing", "账单回调", "https://example.local/hooks/billing", "v1", 1, "账务"),
            ("ep-notify", "通知回调", "https://example.local/hooks/notify", "v1", 1, "通知"),
            ("ep-audit", "审计回调", "https://example.local/hooks/audit", "v2", 1, "审计"),
            ("ep-legacy", "旧版回调", "https://example.local/hooks/legacy", "v1", 0, "停用"),
            ("ep-partner", "合作方回调", "https://partner.local/ingest", "v1", 1, "外部"),
        ]:
            conn.execute(
                "INSERT INTO 投递端点(端点键,名称,回调URL,密钥版本,启用,说明) VALUES (?,?,?,?,?,?)",
                row,
            )
    if conn.execute("SELECT COUNT(*) AS c FROM 事件").fetchone()["c"] == 0:
        t = 此刻()
        for row in [
            ("EVT-demo-01", "invoice.paid", "ep-billing", "invoice=1001", "普通", "待投"),
            ("EVT-demo-02", "user.created", "ep-notify", "user=u42", "普通", "投递中"),
            ("EVT-demo-03", "order.refund", "ep-audit", "order=908", "紧急", "待投"),
            ("EVT-demo-04", "user.updated", "ep-notify", "user=u7", "低", "已投递"),
            ("EVT-demo-05", "invoice.failed", "ep-billing", "invoice=1002", "普通", "死信"),
        ]:
            conn.execute(
                "INSERT INTO 事件(事件号,事件类型,端点键,载荷摘要,优先级,状态,入队时,更新时) VALUES (?,?,?,?,?,?,?,?)",
                (*row, t, t),
            )
        conn.execute(
            "INSERT INTO 投递尝试(尝试号,事件号,端点键,签名摘要,状态,响应码,说明,投递时) VALUES (?,?,?,?,?,?,?,?)",
            ("TRY-demo-01", "EVT-demo-04", "ep-notify", "sig-demo", "成功", 200, "ok", t),
        )
        conn.execute(
            "INSERT INTO 死信(死信号,事件号,端点键,失败次数,末次原因,状态,入匣时) VALUES (?,?,?,?,?,?,?)",
            ("DL-demo-01", "EVT-demo-05", "ep-billing", 3, "连接超时", "待处置", t),
        )
        conn.execute(
            "INSERT INTO 操作留痕(时刻,操作,事件号,详情) VALUES (?,?,?,?)",
            (t, "种子", "", "初始化投递台样例"),
        )
    # 回填播种完成后再挂上库层 fan-out 触发器，接管此后的直改 SQL。
    _建容忍同步触发器(conn)
    conn.commit()
    conn.close()
