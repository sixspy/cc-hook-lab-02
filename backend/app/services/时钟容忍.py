"""兼容入口：时钟容忍上限/快照读集合，实现见 app.services.验签。"""
from app.services.验签 import *  # noqa: F401,F403
from app.services import 验签 as _核心

取容忍上限 = _核心.取容忍上限
读集合 = _核心.读集合
上限档位 = _核心.上限档位
验签 = _核心.验签
