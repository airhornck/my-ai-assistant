"""
生成脑模块：文本、图片、视频等，分别配置不同模型接口。
"""
from domain.content.generators.text_generator import TextGenerator
from domain.content.generators.image_generator import ImageGenerator
from domain.content.generators.video_generator import VideoGenerator

__all__ = ["TextGenerator", "ImageGenerator", "VideoGenerator"]
