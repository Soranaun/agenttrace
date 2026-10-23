from pathlib import Path
from streamlit.testing.v1 import AppTest
from agenttrace.demo import sample_runs

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_workbench_and_replay():
    at = AppTest.from_file(str(APP)).run(timeout=30)
    assert not at.exception
    assert len(at.tabs) == 3
    assert at.metric[0].value == "3"
    at.selectbox[0].select("builtin:demo-002").run()
    assert not at.exception
    assert any("KeyError" in error.value for error in at.error)
    at.selectbox(key="replay_run").select("builtin:demo-002").run()
    next(b for b in at.button if b.label == "下一步 →").click().run()
    assert at.selectbox(key="position:builtin:demo-002").value == 1
    assert not at.exception
    next(b for b in at.button if b.label == "← 上一步").click().run()
    assert at.selectbox(key="position:builtin:demo-002").value == 0


def test_live_demo_recording():
    at = AppTest.from_file(str(APP)).run(timeout=30)
    next(b for b in at.button if "执行本地模拟" in b.label).click().run()
    assert not at.exception
    assert at.metric[0].value == "4"
    at.toggle[0].set_value(False).run()
    next(b for b in at.button if "执行本地模拟" in b.label).click().run()
    assert not at.exception
    assert at.metric[0].value == "5"


def test_imported_history_and_single_step_replay():
    at = AppTest.from_file(str(APP))
    run = sample_runs()[0]
    run.id = "external-001"
    run.simulated = False
    run.steps = run.steps[:1]
    at.session_state["imported"] = {"import:test": run}
    at.run(timeout=30)
    at.selectbox(key="replay_run").select("import:test").run()
    assert not at.exception
    assert next(b for b in at.button if b.label == "下一步 →").disabled
    assert next(b for b in at.button if b.label == "← 上一步").disabled


def test_overview_and_diagnosis_statistics():
    at = AppTest.from_file(str(APP)).run(timeout=30)
    assert not at.exception
    assert at.metric[1].value == "67%"
    table = at.dataframe[0].value
    assert list(table["耗时(ms)"]) == [620, 630, 612]
    assert list(table["成功率"]) == [100, 50, 100]
    assert at.metric[3].value == "100%"
    assert at.metric[3].delta == "+50.0 个百分点"
    assert at.metric[4].value == "612.000 ms"
    assert at.metric[4].delta == "-18.000 ms"
    assert len(at.dataframe[1].value.columns) == 5
    assert "KeyError" in " ".join(e.value for e in at.error)


def test_replay_does_not_execute_tools(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline replay must not execute tools")
    monkeypatch.setattr("agenttrace.demo.inventory_lookup", forbidden)
    at = AppTest.from_file(str(APP)).run(timeout=30)
    at.selectbox(key="replay_run").select("builtin:demo-003").run()
    for _ in range(3):
        next(b for b in at.button if b.label == "下一步 →").click().run()
    assert not at.exception
    assert at.selectbox(key="position:builtin:demo-003").value == 3
    assert next(b for b in at.button if b.label == "下一步 →").disabled
