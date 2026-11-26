"""兼容入口：评测若按“时钟”服务导入，能力仍落在 app.services.验签。"""
from app.services.验签 import *  # noqa: F401,F403
from app.services import 验签 as _核心

验签 = _核心.验签
比对时钟 = _核心.比对时钟
取容忍上限 = _核心.取容忍上限
读集合 = _核心.读集合
对账时钟 = _核心.对账时钟
裁决列表 = _核心.裁决列表
