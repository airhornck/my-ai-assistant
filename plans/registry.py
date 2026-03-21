"""
Plan 模板注册中心：所有 Plan（固定 / 动态）均通过模板 ID 引用，实现插件化解耦与模板化。

- 固定 Plan：注册时提供 template_id、name（展示名）、steps 等，通过 get_plan(template_id) 获取步骤列表。
- 动态 Plan：模板 ID 为 PLAN_TEMPLATE_DYNAMIC，由调用方根据 context 用 LLM 生成步骤，仍写入 plan_template_id="dynamic" 保持统一引用。
- 选择逻辑：resolve_template_id(intent, ip_context) 返回匹配的 template_id，无匹配时返回 PLAN_TEMPLATE_DYNAMIC。
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# 动态 Plan 的模板 ID（LLM 按意图生成步骤时使用）
PLAN_TEMPLATE_DYNAMIC = "dynamic"

# 模板类型
PLAN_TYPE_FIXED = "fixed"
PLAN_TYPE_DYNAMIC = "dynamic"


def _default_intent_selector(_intent: str, _ip_context: dict) -> bool:
    """默认选择器：不匹配任何固定模板。"""
    return False


# 模板元数据：template_id, name, type, steps(可选), description(可选), intent_selector(可选)
# intent_selector(intent, ip_context) -> bool，返回 True 表示当前意图/上下文应使用该模板
_PlanTemplate = dict[str, Any]
_REGISTRY: dict[str, _PlanTemplate] = {}
# 用于 resolve 的 (priority, selector, template_id)，priority 越小越先匹配
_SELECTORS: list[tuple[int, Callable[[str, dict], bool], str]] = []


def register(
    template_id: str,
    *,
    name: str = "",
    plan_type: str = PLAN_TYPE_FIXED,
    steps: list[dict] | None = None,
    description: str = "",
    intent_selector: Callable[[str, dict], bool] | None = None,
    selector_priority: int = 100,
) -> None:
    """
    注册一个 Plan 模板。

    Args:
        template_id: 唯一标识，如 ip_diagnosis、capability_content_direction_ranking、dynamic。
        name: 固定模板对外展示名（短标题，如「账号打造」）。固定 Plan 建议必填；缺省时回退为 template_id 并打 debug 日志。
        plan_type: PLAN_TYPE_FIXED 或 PLAN_TYPE_DYNAMIC。
        steps: 固定模板的步骤列表，每步含 step、plugins、params、reason；dynamic 可省略。
        description: 人类可读补充说明（流程概要、文档与调试）；可与 name 区分长短。
        intent_selector: 可选；(intent, ip_context) -> bool，在 resolve_template_id 时用于匹配。
        selector_priority: 选择器优先级，数值越小越先匹配，默认 100。
    """
    if not template_id or not template_id.strip():
        logger.warning("plan_registry: 忽略空 template_id")
        return
    tid = template_id.strip()
    resolved_type = plan_type if plan_type in (PLAN_TYPE_FIXED, PLAN_TYPE_DYNAMIC) else PLAN_TYPE_FIXED
    display_name = (name or "").strip()
    if resolved_type == PLAN_TYPE_FIXED and not display_name:
        display_name = tid
        logger.debug("plan_registry: 固定模板 %s 未提供 name，已回退为 template_id", tid)
    elif not display_name:
        display_name = tid
    spec: _PlanTemplate = {
        "template_id": tid,
        "name": display_name,
        "type": resolved_type,
        "description": description or "",
    }
    if steps is not None:
        spec["steps"] = list(steps)
    _REGISTRY[tid] = spec
    if intent_selector is not None and callable(intent_selector):
        _SELECTORS.append((selector_priority, intent_selector, tid))
        _SELECTORS.sort(key=lambda x: x[0])
    logger.debug("plan_registry: 已注册模板 %s (type=%s)", tid, spec["type"])


def get_plan(template_id: str, context: dict[str, Any] | None = None) -> list[dict] | None:
    """
    按模板 ID 获取 Plan 步骤列表。固定模板返回深拷贝步骤；动态模板返回 None（由调用方用 LLM 生成）。

    Args:
        template_id: 模板 ID。
        context: 可选上下文，当前仅固定模板未使用；预留供后续扩展（如按 context 过滤步骤）。

    Returns:
        步骤列表的深拷贝，或 None（表示需动态生成或模板不存在）。
    """
    if not template_id or template_id.strip() == "":
        return None
    tid = template_id.strip()
    spec = _REGISTRY.get(tid)
    if spec is None:
        logger.debug("plan_registry: 未找到模板 %s", tid)
        return None
    if spec.get("type") == PLAN_TYPE_DYNAMIC:
        return None
    steps = spec.get("steps")
    if not steps:
        return None
    return copy.deepcopy(steps)


def resolve_template_id(intent: str, ip_context: dict) -> str:
    """
    根据意图与 ip_context 解析应使用的模板 ID。按已注册的 intent_selector 优先级匹配，无匹配时返回 PLAN_TEMPLATE_DYNAMIC。

    Args:
        intent: 当前意图，如 account_diagnosis、generate_content。
        ip_context: IP 流程上下文，如 topic、brand_name。

    Returns:
        模板 ID，固定模板或 PLAN_TEMPLATE_DYNAMIC。
    """
    intent_str = (intent or "").strip().lower()
    ctx = ip_context or {}
    for _prio, selector, tid in _SELECTORS:
        try:
            if selector(intent_str, ctx):
                return tid
        except Exception as e:
            logger.debug("plan_registry: selector %s 执行异常: %s", tid, e)
    return PLAN_TEMPLATE_DYNAMIC


def list_template_ids(*, plan_type: str | None = None) -> list[str]:
    """返回已注册的模板 ID 列表；可选按 plan_type 过滤。"""
    if plan_type is None:
        return list(_REGISTRY.keys())
    return [tid for tid, spec in _REGISTRY.items() if spec.get("type") == plan_type]


def get_template_meta(template_id: str) -> dict[str, Any] | None:
    """返回模板元数据（不含 steps 深拷贝），不存在则返回 None。"""
    tid = (template_id or "").strip()
    spec = _REGISTRY.get(tid)
    if spec is None:
        return None
    return {
        "template_id": spec.get("template_id"),
        "name": (spec.get("name") or spec.get("template_id") or "").strip(),
        "type": spec.get("type"),
        "description": spec.get("description", ""),
        "has_steps": bool(spec.get("steps")),
    }
