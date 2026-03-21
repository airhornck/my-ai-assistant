"""
用户友好引导：将本轮抽取字段合并进 ip_context，不覆盖已有非空值，支持多轮累积。
"""
from __future__ import annotations

from typing import Any, Iterable


def merge_context(
    existing: dict | None,
    extracted: dict | None,
    *,
    overwrite_keys: Iterable[str] = (),
) -> dict:
    """
    合并抽取字段到 ip_context，不覆盖已有非空值。
    用于：用户输入 → 字段抽取 → ip_context 更新 → 下一轮可继续累积。
    """
    out = dict(existing or {})
    overwrite = set(overwrite_keys or ())
    for k, v in (extracted or {}).items():
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        if k in overwrite:
            out[k] = v.strip() if isinstance(v, str) else v
            continue
        if k not in out or not (out.get(k) or "").strip():
            out[k] = v.strip() if isinstance(v, str) else v
    return out
