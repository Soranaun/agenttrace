"""All examples are explicitly simulated. Tools only read in-memory fixtures."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .models import Run, Step
from .recorder import TraceRecorder

CATALOG = {"A-101": {"name": "校园纪念笔记本", "stock": 24, "price": 12.5}}


def inventory_lookup(sku):
    if sku not in CATALOG:
        raise KeyError(f"商品编码 {sku!r} 不存在；请使用大写标准编码 A-101")
    return dict(CATALOG[sku])


def run_local_demo(fixed=True):
    recorder = TraceRecorder("现场模拟 · 修复后成功" if fixed else "现场模拟 · 工具调用失败", simulated=True, metadata={"scenario": "校园商品库存查询", "source": "本地模拟工具，无模型调用"})
    try:
        with recorder.step("plan", "理解查询任务", input={"query": "查询 a-101 是否有货"}) as step:
            step.output = {"sku": "a-101", "action": "inventory_lookup"}
        sku = "a-101"
        if fixed:
            with recorder.step("normalize", "规范化商品编码", kind="transform", input={"sku": sku}) as step:
                sku = sku.strip().upper()
                step.output = {"sku": sku}
        with recorder.step("lookup", "查询库存", kind="tool", tool="inventory_lookup", input={"sku": sku}) as step:
            product = inventory_lookup(sku)
            step.output = product
        with recorder.step("answer", "生成查询结果", input=product) as step:
            step.output = f"{product['name']}：库存 {product['stock']} 件，单价 {product['price']} 元。"
    except KeyError:
        pass  # The failed call remains recorded; this is the intended demo case.
    return recorder.finish()


def sample_runs():
    """Stable fixture timings are illustrative, never claimed as benchmarks."""
    base = datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)
    normal = run_local_demo(True)
    normal.steps = [s for s in normal.steps if s.id != "normalize"]
    normal.steps[0].input = {"query": "查询 A-101 是否有货"}
    normal.steps[0].output = {"sku": "A-101", "action": "inventory_lookup"}
    failed = run_local_demo(False)
    repaired = run_local_demo(True)
    result = []
    for i, (run, label, times) in enumerate([(normal, "正常运行", [180, 320, 120]), (failed, "工具调用失败", [180, 450]), (repaired, "修复后成功", [180, 12, 300, 120])]):
        run.id = f"demo-{i + 1:03d}"
        run.name = f"模拟 · {label}"
        run.started_at = (base + timedelta(minutes=i * 5)).isoformat()
        offset = 0
        for step, duration in zip(run.steps, times):
            step.started_at = (base + timedelta(minutes=i * 5, milliseconds=offset)).isoformat()
            step.duration_ms = duration
            offset += duration
        run.metadata["timing_note"] = "模拟耗时，仅用于演示，非性能基准"
        result.append(run)
    return result


def write_samples(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for run in sample_runs():
        (directory / f"{run.id}.json").write_text(run.to_json(), encoding="utf-8")


if __name__ == "__main__":
    write_samples(Path(__file__).resolve().parents[1] / "data" / "runs")
    print("已生成三组模拟运行记录。")
