"""兼容入口：上限快照/只读归档查询，实现见 app.services.验签。"""
from app.services.验签 import *  # noqa: F401,F403
from app.services import 验签 as _核心

快照列表 = _核心.快照列表
归档列表 = _核心.归档列表
影子列表 = _核心.影子列表
回刷裁决 = _核心.回刷裁决
影子回写现行 = _核心.影子回写现行
验签 = _核心.验签
