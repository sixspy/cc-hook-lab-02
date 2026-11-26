import os
import sqlite3
from pathlib import Path

数据目录 = Path(os.environ.get("数据目录", Path(__file__).resolve().parent.parent / "data"))
夹具目录 = Path(os.environ.get("夹具目录", Path(__file__).resolve().parent.parent.parent / "fixtures"))
库路径 = 数据目录 / "投递台.db"


def 连接() -> sqlite3.Connection:
    数据目录.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(库路径, timeout=5.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    # 并发占坑争写时给写锁留出排队窗口，而不是立刻抛 SQLITE_BUSY
    c.execute("PRAGMA busy_timeout = 5000")
    return c
