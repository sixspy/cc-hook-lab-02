"""兼容入口：签名验签能力别名，实现见 app.services.验签。"""
from app.services.验签 import *  # noqa: F401,F403
from app.services import 验签 as _核心

验签 = _核心.验签
验签一次 = _核心.验签
取容忍上限 = _核心.取容忍上限
裁决列表 = _核心.裁决列表
