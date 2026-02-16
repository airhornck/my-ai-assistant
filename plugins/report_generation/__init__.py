"""
Word 报告生成插件注册
通用报告生成插件，支持生成各类 Word 文档报告（账号诊断、推广策略、爆款预测等）
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_REALTIME

logger = logging.getLogger(__name__)

PLUGIN_NAME = "word_report"

# 报告输出目录
REPORT_OUTPUT_DIR = "data/reports"


def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """
    注册 Word 报告生成插件

    支持的报告类型：
    - account_diagnosis: 账号诊断报告
    - marketing_strategy: 推广策略报告
    - viral_prediction: 爆款预测报告
    - custom: 自定义报告
    """

    # 延迟导入，避免循环依赖
    from plugins.report_generation.word_generator import (
        ReportContentBuilder,
        WordReportGenerator,
    )

    # 初始化生成器
    output_dir = config.get("report_output_dir", REPORT_OUTPUT_DIR)
    report_generator = WordReportGenerator(output_dir=output_dir)

    async def generate_word_report(state: dict) -> dict:
        """
        生成 Word 报告的处理函数

        根据 state 中的内容类型自动判断生成哪种报告：
        - account_diagnosis: 账号诊断报告
        - marketing_strategy: 推广策略报告
        - viral_prediction: 爆款预测报告
        - custom: 自定义报告
        """
        try:
            # 1. 提取必要信息
            analysis = state.get("analysis", {})
            content = state.get("content", "")
            user_id = state.get("user_id", "unknown")
            session_id = state.get("session_id", "")

            # 2. 判断报告类型
            report_type = _detect_report_type(analysis, content)

            logger.info(
                f"[{PLUGIN_NAME}] 开始生成报告, type={report_type}, user_id={user_id}"
            )

            # 3. 构建报告内容
            report_data = _build_report_content(
                report_type, analysis, content, user_id
            )

            # 4. 生成 Word 文档
            file_path = report_generator.generate_report(
                report_type=report_data["report_type"],
                title=report_data["title"],
                summary=report_data["summary"],
                sections=report_data["sections"],
                metadata=report_data.get("metadata"),
            )

            # 5. 生成下载链接
            download_url = report_generator.get_download_url(file_path)

            # 6. 构建返回内容
            report_type_display = report_data.get("metadata", {}).get(
                "report_type_display", "报告"
            )

            result_content = f"""📄 {report_type_display}已生成！

【摘要】
{report_data['summary']}

📥 下载链接: {download_url}

点击上方链接即可下载 Word 版报告，报告中包含详细的分析和建议，供您留存参考。

如需修改或有其他需求，请随时告诉我！"""

            logger.info(
                f"[{PLUGIN_NAME}] 报告生成完成, file={file_path}, url={download_url}"
            )

            return {
                **state,
                "content": result_content,
                "report_file_path": file_path,
                "report_download_url": download_url,
                "report_type": report_type,
            }

        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 报告生成失败: {e}", exc_info=True)
            return {
                **state,
                "content": "抱歉，报告生成过程中遇到问题，请稍后重试或联系客服。",
                "report_error": str(e),
            }

    # 注册插件
    plugin_center.register_plugin(
        name=PLUGIN_NAME,
        plugin_type=PLUGIN_TYPE_REALTIME,
        handler=generate_word_report,
    )

    logger.info(f"[{PLUGIN_NAME}] 插件已注册")


def _detect_report_type(analysis: Dict[str, Any], content: str) -> str:
    """检测应该生成哪种类型的报告"""

    # 1. 账号诊断报告
    if analysis.get("account_diagnosis"):
        return "account_diagnosis"

    # 2. 爆款预测报告
    if analysis.get("viral_prediction"):
        return "viral_prediction"

    # 3. 推广策略报告 (有 angle 和 reason)
    if analysis.get("angle") and analysis.get("reason"):
        return "marketing_strategy"

    # 4. 默认自定义报告
    return "custom"


def _build_report_content(
    report_type: str, analysis: Dict[str, Any], content: str, user_id: str
) -> Dict[str, Any]:
    """构建报告内容"""

    from plugins.report_generation.word_generator import ReportContentBuilder

    if report_type == "account_diagnosis":
        return ReportContentBuilder.build_account_diagnosis_report(analysis, user_id)

    elif report_type == "viral_prediction":
        return ReportContentBuilder.build_viral_prediction_report(
            analysis, content, user_id
        )

    elif report_type == "marketing_strategy":
        return ReportContentBuilder.build_marketing_strategy_report(
            analysis, content, user_id
        )

    else:
        # custom
        return ReportContentBuilder.build_custom_report(
            title="内容分析报告",
            content=content,
            analysis=analysis,
            user_id=user_id,
        )
