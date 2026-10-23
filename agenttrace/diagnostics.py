"""Deterministic comparisons by stable step ID (names may change)."""
from dataclasses import asdict
from .models import Run


def compare_runs(before: Run, after: Run):
    left = {s.id: s for s in before.steps}
    right = {s.id: s for s in after.steps}
    rows = []
    for sid in list(left) + [sid for sid in right if sid not in left]:
        a, b = left.get(sid), right.get(sid)
        changed = []
        if a and b:
            changed = [key for key in asdict(a) if key not in {"started_at", "duration_ms"} and getattr(a, key) != getattr(b, key)]
            if before.steps.index(a) != after.steps.index(b):
                changed.append("order")
        change = "新增" if a is None else "缺失" if b is None else "变化" if changed else "相同"
        rows.append({"步骤 ID": sid, "步骤": (b or a).name, "差异": change, "变化字段": ", ".join(changed) or "—", "之前状态": a.status if a else "—", "之后状态": b.status if b else "—", "之前耗时(ms)": a.duration_ms if a else None, "之后耗时(ms)": b.duration_ms if b else None, "之前错误": a.error if a and a.error else "—", "之后错误": b.error if b and b.error else "—"})
    failed_before = [s.id for s in before.steps if s.status == "failed"]
    failed_after = [s.id for s in after.steps if s.status == "failed"]
    recovered = [sid for sid in failed_before if sid in right and right[sid].status == "success"]
    missing_failures = [sid for sid in failed_before if sid not in right]
    delta = after.duration_ms - before.duration_ms
    summary = [f"运行结果：{before.status} → {after.status}；步骤成功率：{before.success_rate:.0%} → {after.success_rate:.0%}（不含跳过步骤）。", f"累计步骤耗时：{before.duration_ms:.3f} → {after.duration_ms:.3f} ms，变化 {delta:+.3f} ms。"]
    if recovered:
        summary.append(f"已恢复成功的步骤：{'、'.join(recovered)}。")
    if missing_failures:
        summary.append(f"原失败步骤已缺失，不能视为修复：{'、'.join(missing_failures)}。")
    if failed_after:
        summary.append(f"当前仍有失败步骤：{'、'.join(failed_after)}；请检查对应工具输入与异常。")
    summary.append("差异依据稳定步骤 ID 匹配；耗时单独展示，不作为内容变化。诊断来自记录对比，不推断未经记录的根因。")
    return {"rows": rows, "summary": summary}
