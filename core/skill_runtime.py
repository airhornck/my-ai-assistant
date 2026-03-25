"""
Skill runtime：覆盖所有「固定 Plan」steps 中出现的分析/生成插件。
- 提供 A/B 分桶、插件候选链（主名 + 与注册中心一致的 *_plugin 别名）
- 新增固定 Plan 时应在 MANAGED_SKILLS 中补全对应主名与别名，或通过 collect_fixed_plan_plugin_ids 在测试中校验
"""
from __future__ import annotations

from typing import Any


MANAGED_SKILLS: dict[str, list[str]] = {
    "account_diagnosis": ["account_diagnosis", "account_diagnosis_plugin"],
    "business_positioning": ["business_positioning", "business_positioning_plugin"],
    "content_positioning": ["content_positioning", "content_positioning_plugin"],
    "topic_selection": ["topic_selection", "topic_selection_plugin"],
    "content_direction_ranking": ["content_direction_ranking"],
    "industry_news_bilibili_rankings": ["industry_news_bilibili_rankings"],
    "weekly_decision_snapshot": ["weekly_decision_snapshot"],
    "text_generator": ["text_generator"],
}


def collect_fixed_plan_plugin_ids() -> set[str]:
    """扫描已注册固定 Plan 的 steps，汇总所有非空 plugins 名称（需先加载 plans.templates）。"""
    import plans.templates  # noqa: F401  # 触发 register_plan
    from plans.registry import PLAN_TYPE_FIXED, get_plan, list_template_ids

    ids: set[str] = set()
    for tid in list_template_ids(plan_type=PLAN_TYPE_FIXED):
        steps = get_plan(tid) or []
        for st in steps:
            pls = st.get("plugins") or []
            if not isinstance(pls, list):
                continue
            for p in pls:
                s = str(p).strip()
                if s:
                    ids.add(s)
    return ids


def _stable_bucket(seed: str) -> str:
    if not seed:
        return "A"
    # 轻量稳定分桶：字符码求和
    s = sum(ord(c) for c in seed)
    return "A" if (s % 2 == 0) else "B"


def build_skill_execution_plan(
    plugins: list[str],
    *,
    user_id: str = "",
) -> dict[str, Any]:
    """
    输入步骤插件列表，输出 skill runtime 解析后的执行计划：
    - resolved_plugins: 最终候选链（顺序执行，遇到成功即停）
    - skill_ids: 命中的 skill
    - ab_bucket: A/B 桶
    """
    normalized = [str(p).strip() for p in (plugins or []) if str(p).strip()]
    skill_ids: list[str] = []
    resolved: list[str] = []

    for p in normalized:
        if p in MANAGED_SKILLS:
            skill_ids.append(p)
            for candidate in MANAGED_SKILLS[p]:
                if candidate not in resolved:
                    resolved.append(candidate)
        else:
            if p not in resolved:
                resolved.append(p)

    # B 组保守增强：优先把托管 skill 候选放前面，提升别名兼容命中率
    bucket = _stable_bucket(user_id or "")
    if bucket == "B" and skill_ids:
        managed_front = [p for p in resolved if any(p in MANAGED_SKILLS[s] for s in skill_ids)]
        others = [p for p in resolved if p not in managed_front]
        resolved = managed_front + others

    return {
        "resolved_plugins": resolved,
        "skill_ids": skill_ids,
        "ab_bucket": bucket,
    }


def fallback_plugins_for_step(step_name: str, plugins: list[str]) -> list[str]:
    """
    同类 skill 回退链（MVP）：
    - analyze：对托管 skill 使用别名回退
    - generate：先 text_generator，再保留原列表
    """
    step = (step_name or "").lower()
    base = [str(p).strip() for p in (plugins or []) if str(p).strip()]
    out: list[str] = []

    if step == "analyze":
        for p in base:
            if p in MANAGED_SKILLS:
                for c in MANAGED_SKILLS[p]:
                    if c not in out:
                        out.append(c)
            elif p.endswith("_plugin"):
                if p not in out:
                    out.append(p)
                raw = p[:-7]
                if raw and raw not in out:
                    out.append(raw)
            else:
                if p not in out:
                    out.append(p)
                alias = f"{p}_plugin"
                if alias not in out:
                    out.append(alias)
        return out or base

    if step == "generate":
        if "text_generator" not in base:
            out.append("text_generator")
        out.extend(base)
        dedup: list[str] = []
        for p in out:
            if p not in dedup:
                dedup.append(p)
        return dedup

    return base
