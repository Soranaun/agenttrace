import json
import pytest

from agenttrace import Run, TraceRecorder, TraceValidationError
from agenttrace.demo import run_local_demo, sample_runs, write_samples
from agenttrace.diagnostics import compare_runs
from agenttrace.storage import load_directory, load_trace


def test_three_scenarios_roundtrip(tmp_path):
    write_samples(tmp_path)
    runs, errors = load_directory(tmp_path)
    assert not errors
    assert [r.status for r in runs] == ["success", "failed", "success"]
    assert all(r.simulated for r in runs)
    assert all(Run.from_json(r.to_json()) == r for r in runs)
    assert runs[1].steps[-1].tool == "inventory_lookup"
    assert "KeyError" in runs[1].steps[-1].error
    assert runs[1].success_rate == 0.5


def test_live_local_tool_and_fix():
    failed, fixed = run_local_demo(False), run_local_demo(True)
    assert failed.status == "failed"
    assert fixed.status == "success"
    assert fixed.steps[-1].output.startswith("校园纪念笔记本")
    assert all(s.duration_ms >= 0 for s in fixed.steps)
    assert failed.steps[-1].input == {"sku": "a-101"}
    assert fixed.steps[2].input == {"sku": "A-101"}


def test_recorder_records_then_reraises(tmp_path):
    recorder = TraceRecorder("test")
    with pytest.raises(RuntimeError):
        with recorder.step("fetch", "工具", kind="tool", tool="fetch", input={"x": 1}):
            raise RuntimeError("offline")
    path = tmp_path / "trace.json"
    recorder.save(path)
    run = load_trace(path)
    assert run.status == "failed"
    assert run.steps[0].error == "RuntimeError: offline"
    assert not run.simulated
    with pytest.raises(ValueError, match="重复"):
        with recorder.step("fetch", "工具"):
            pass


def test_comparison_recovery_and_added():
    _, failed, repaired = sample_runs()
    result = compare_runs(failed, repaired)
    rows = {row["步骤 ID"]: row for row in result["rows"]}
    assert rows["lookup"]["差异"] == "变化"
    assert rows["lookup"]["之后错误"] == "—"
    assert rows["normalize"]["差异"] == "新增"
    assert rows["answer"]["差异"] == "新增"
    assert any("已恢复成功的步骤：lookup" in line for line in result["summary"])
    reverse = compare_runs(repaired, failed)
    assert any(row["差异"] == "缺失" for row in reverse["rows"])


def test_missing_failure_is_not_repair():
    normal, failed, _ = sample_runs()
    normal.steps = [s for s in normal.steps if s.id != "lookup"]
    report = compare_runs(failed, normal)
    assert any("不能视为修复" in line for line in report["summary"])


@pytest.mark.parametrize("payload", ["{", "[]", '{"steps":{}}', '{"steps":[null]}', b"\xff"])
def test_invalid_json_has_friendly_error(payload):
    with pytest.raises(TraceValidationError):
        Run.from_json(payload)


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(schema_version=2),
    lambda d: d.update(simulated="yes"),
    lambda d: d.update(started_at="yesterday"),
    lambda d: d["steps"][0].update(duration_ms=-1),
    lambda d: d["steps"][0].update(duration_ms=float("nan")),
    lambda d: d["steps"].append(d["steps"][0]),
    lambda d: d["steps"][0].update(status="unknown"),
    lambda d: d.update(status="failed"),
])
def test_validation(mutate):
    data = json.loads(sample_runs()[0].to_json())
    mutate(data)
    with pytest.raises(TraceValidationError):
        Run.from_json(json.dumps(data))


def test_skip_rate_and_empty_run():
    run = sample_runs()[0]
    run.steps[-1].status = "skipped"
    assert run.success_rate == 1
    run.steps.clear()
    assert run.success_rate == 0
    assert compare_runs(run, run)["rows"] == []


def test_bad_file_does_not_hide_valid_files(tmp_path):
    write_samples(tmp_path)
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    runs, errors = load_directory(tmp_path)
    assert len(runs) == 3
    assert len(errors) == 1


def test_oversized_file(tmp_path):
    path = tmp_path / "large.json"
    path.write_bytes(b" " * (5 * 1024 * 1024 + 1))
    with pytest.raises(TraceValidationError, match="5 MB"):
        load_trace(path)


def test_time_only_changes_do_not_mark_content_changed():
    before = sample_runs()[0]
    after = Run.from_json(before.to_json())
    after.steps[0].duration_ms += 15
    after.steps[0].started_at = "2026-10-24T10:00:00+00:00"
    report = compare_runs(before, after)
    assert all(row["差异"] == "相同" for row in report["rows"])
    assert report["rows"][0]["之后耗时(ms)"] - report["rows"][0]["之前耗时(ms)"] == 15


def test_utf8_bom_and_missing_failure_error():
    run = sample_runs()[1]
    assert Run.from_json(b"\xef\xbb\xbf" + run.to_json().encode("utf-8")) == run
    data = json.loads(run.to_json())
    data["steps"][-1]["error"] = None
    with pytest.raises(TraceValidationError, match="error"):
        Run.from_json(json.dumps(data))


def test_fixture_statistics_match_diagnosis():
    runs, errors = load_directory("data/runs")
    assert not errors
    assert [r.duration_ms for r in runs] == [620, 630, 612]
    assert [r.success_rate for r in runs] == [1, 0.5, 1]
    assert sum(r.status == "success" for r in runs) == 2
    report = compare_runs(runs[1], runs[2])
    rows = {r["步骤 ID"]: r for r in report["rows"]}
    assert rows["lookup"]["之前耗时(ms)"] == 450
    assert rows["lookup"]["之后耗时(ms)"] == 300
    net_change = sum((r["之后耗时(ms)"] or 0) - (r["之前耗时(ms)"] or 0) for r in report["rows"])
    assert net_change == runs[2].duration_ms - runs[1].duration_ms == -18
    assert "630.000 → 612.000 ms，变化 -18.000 ms" in report["summary"][1]


def test_json_rejects_overflow_in_payload_and_total():
    data = json.loads(sample_runs()[0].to_json())
    raw = json.dumps(data).replace('"metadata": {', '"metadata": {"overflow": 1e999,')
    with pytest.raises(TraceValidationError, match="浮点数"):
        Run.from_json(raw)
    for step in data["steps"]:
        step["duration_ms"] = 1e308
    with pytest.raises(TraceValidationError, match="累计"):
        Run.from_json(json.dumps(data))
