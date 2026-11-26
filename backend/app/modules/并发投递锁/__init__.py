"""并发投递锁（hook-02-并发投递互斥）。

工程形态（择定，禁止与双写两轨并存）：独立队列按事件号占投递坑并拒绝重复回刷。
- 投递锁是独立于「投递尝试」正式集合的占坑队列，同事件号全库只有一个坑位；
- 占坑写入与尝试写入由调用方放进同一个事务，同成同败；
- 本模块只管坑（占坑/释放/终票/读口），不写投递尝试、不做对账影子；
- 双写归档轨维持空桩，冲突尝试不进只读归档轨。
"""
from __future__ import annotations

import sqlite3

from app.db import 连接
from app.services.时间 import 此刻

NAME = "并发投递锁"

# 占坑态词表（中文命运同源）
占用中 = "占用中"
已释放 = "已释放"
终票占坑 = "终票占坑"


class 占坑冲突(Exception):
    """同事件号的投递坑已被另一路会话占用或已终票，拒绝重复回刷。"""


建表 = """
CREATE TABLE IF NOT EXISTS 投递锁 (
  事件号 TEXT PRIMARY KEY,
  占坑态 TEXT NOT NULL DEFAULT '占用中',
  轮次 INTEGER NOT NULL DEFAULT 1,
  尝试号 TEXT NOT NULL DEFAULT '',
  占坑时 TEXT NOT NULL,
  释放时 TEXT NOT NULL DEFAULT '',
  中文命运 TEXT NOT NULL DEFAULT '',
  FOREIGN KEY (事件号) REFERENCES 事件(事件号)
);
"""


def 确保表() -> None:
    conn = 连接()
    try:
        conn.execute(建表)
        conn.commit()
    finally:
        conn.close()


def 占坑(conn: sqlite3.Connection, 事件号: str, 轮次: int = 1) -> None:
    """在调用方事务内按事件号占坑。坑位被占用/终票时抛 占坑冲突（HTTP 409）。

    仅当旧坑处于「已释放」（上一轮投递失败让出坑位）时才允许同事件重新占坑，
    且同事务内完成 UPSERT，与调用方后续的尝试写入同成同败。
    """
    t = 此刻()
    try:
        conn.execute(
            "INSERT INTO 投递锁(事件号,占坑态,轮次,占坑时,中文命运) VALUES (?,?,?,?,?)",
            (事件号, 占用中, 轮次, t, "投递中"),
        )
        return
    except sqlite3.IntegrityError:
        pass
    row = conn.execute("SELECT 占坑态, 轮次 FROM 投递锁 WHERE 事件号=?", (事件号,)).fetchone()
    if row is None:  # 极端并发下理论不可达，保底按冲突处理
        raise 占坑冲突(f"事件{事件号}投递坑争用失败")
    if row["占坑态"] != 已释放:
        raise 占坑冲突(f"事件{事件号}投递坑{row['占坑态']}，拒绝重复回刷")
    conn.execute(
        "UPDATE 投递锁 SET 占坑态=?, 轮次=?, 尝试号='', 占坑时=?, 释放时='', 中文命运=? "
        "WHERE 事件号=?",
        (占用中, 轮次, t, "投递中", 事件号),
    )


def 释放(conn: sqlite3.Connection, 事件号: str, 尝试号: str, 命运: str = "待投") -> None:
    """本轮投递失败，让出坑位给后续重试；与尝试写入同事务。"""
    conn.execute(
        "UPDATE 投递锁 SET 占坑态=?, 尝试号=?, 释放时=?, 中文命运=? WHERE 事件号=?",
        (已释放, 尝试号, 此刻(), 命运, 事件号),
    )


def 终票(conn: sqlite3.Connection, 事件号: str, 尝试号: str, 命运: str) -> None:
    """事件命运落定（已投递/死信）后终票占坑，永久拒绝回刷。"""
    conn.execute(
        "UPDATE 投递锁 SET 占坑态=?, 尝试号=?, 释放时=?, 中文命运=? WHERE 事件号=?",
        (终票占坑, 尝试号, 此刻(), 命运, 事件号),
    )


def 占坑态(事件号: str) -> dict | None:
    """占坑态读口：给页面直读事件号、占坑态、轮次与中文命运。"""
    conn = 连接()
    try:
        row = conn.execute("SELECT * FROM 投递锁 WHERE 事件号=?", (事件号,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def 锁列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM 投递锁 ORDER BY 占坑时 DESC LIMIT 200"
        ).fetchall()]
    finally:
        conn.close()
