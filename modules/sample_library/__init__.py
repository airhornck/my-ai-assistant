"""
样本库模块：爆款特征存储与检索。
按需调用，不进入主流程。供预测模型训练、样本检索插件使用。
"""
from modules.sample_library.port import SampleLibraryPort, SampleRecord
from modules.sample_library.factory import get_sample_library

__all__ = [
    "SampleLibraryPort",
    "SampleRecord",
    "get_sample_library",
]
