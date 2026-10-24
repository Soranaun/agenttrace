"""Run with: python -m streamlit run app.py"""
import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st

from agenttrace.demo import run_local_demo
from agenttrace.diagnostics import compare_runs
from agenttrace.models import Run, TraceValidationError
from agenttrace.storage import MAX_TRACE_BYTES, load_directory

ROOT = Path(__file__).resolve().parent
MAX_SESSION_RUNS = 20
MAX_SESSION_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_STEPS = 200


def retain_run(key, run):
    records = st.session_state.imported
    if key in records:
        return
    if len(records) >= MAX_SESSION_RUNS:
        raise TraceValidationError("当前会话最多保留 20 条记录，请先下载并清空会话。")
    size = sum(len(r.to_json().encode("utf-8")) for r in records.values())
    if size + len(run.to_json().encode("utf-8")) > MAX_SESSION_BYTES:
        raise TraceValidationError("当前会话记录总量超过 10 MB，请先下载并清空会话。")
    records[key] = run


def clear_session():
    epoch = st.session_state.get("upload_epoch", 0) + 1
    for key in list(st.session_state):
        del st.session_state[key]
    st.session_state.upload_epoch = epoch


st.set_page_config(page_title="AgentTrace · 执行追踪工作台", page_icon="🔎", layout="wide")
st.markdown("""<style>
.block-container {padding: 2rem 2rem 3rem; max-width: 1440px;}
[data-testid="stMetric"] {background: #f0f4fa; padding: 14px; border-radius: 12px; color: #172238;}
.stApp h1 {letter-spacing: -1px;}
@media (max-width: 1100px) {
    .block-container {padding-left: 1rem; padding-right: 1rem;}
}
</style>""", unsafe_allow_html=True)
st.title("🔎 AgentTrace")
st.caption("轻量级 Agent 执行追踪 · 离线故障回放 · 差异诊断 | 本地运行，无需 API Key")

if "imported" not in st.session_state:
    st.session_state.imported = {}

with st.sidebar:
    st.header("工作台")
    st.info("内置数据均为模拟数据。现场演示仅执行本地字典查询，不调用模型或外部服务。")
    st.caption("上传内容会发送到应用服务器，仅供当前会话查看；请勿上传密钥、个人信息或保密记录。")
    st.button("清空当前会话记录", on_click=clear_session)
    uploads = st.file_uploader("导入本地历史 JSON（单文件 ≤ 5 MB）", type=["json"], accept_multiple_files=True, key=f"uploads:{st.session_state.get('upload_epoch', 0)}")
    for upload in uploads or []:
        try:
            if upload.size > MAX_TRACE_BYTES:
                raise TraceValidationError("记录超过 5 MB 限制")
            raw = upload.getvalue()
            run = Run.from_json(raw)
            if len(run.steps) > MAX_UPLOAD_STEPS:
                raise TraceValidationError("公开工作台每条导入记录最多 200 个步骤")
            key = "import:" + hashlib.sha256(raw).hexdigest()
            retain_run(key, run)
            st.success(f"已加载：{upload.name}")
        except TraceValidationError as exc:
            st.error(f"{upload.name}：{exc}")
    st.divider()
    fixed = st.toggle("启用编码规范化修复", value=True)
    if st.button("▶ 执行本地模拟 Agent", width="stretch"):
        live = run_local_demo(fixed)
        try:
            retain_run("live:" + live.id, live)
            st.success("模拟运行已记录，可在列表与对比中查看。")
        except TraceValidationError as exc:
            st.error(str(exc))
    st.caption("导入记录仅在当前会话保存；需要留存时请下载 JSON。内置记录位于 data/runs。")

builtin, errors = load_directory(ROOT / "data" / "runs")
for error in errors:
    st.warning(f"跳过无效记录：{error}")
records = {f"builtin:{r.id}": r for r in builtin}
records.update(st.session_state.imported)
if not records:
    st.info("暂无记录。请导入 JSON，或在侧栏执行本地模拟 Agent。")
    st.stop()

keys = list(records)
status_label = {"success": "成功", "failed": "失败", "skipped": "跳过"}


def label(key):
    r = records[key]
    source = "导入" if key.startswith("import:") else "现场" if key.startswith("live:") else "内置"
    return f"[{source}] {r.name} · {r.id} · {status_label[r.status]}"


def step_detail(step):
    if step.status == "failed":
        st.error(step.error)
    elif step.status == "skipped":
        st.warning("此步骤已跳过")
    else:
        st.success("步骤执行成功")
    st.caption(f"ID：{step.id} | 类型：{step.kind} | 工具：{step.tool or '—'} | 耗时：{step.duration_ms:.3f} ms | 时间：{step.started_at}")
    left, right = st.columns(2)
    with left:
        st.markdown("**输入**")
        if isinstance(step.input, (dict, list)):
            st.json(step.input, expanded=True)
        else:
            st.code(str(step.input), language=None)
    with right:
        st.markdown("**输出**")
        if isinstance(step.output, (dict, list)):
            st.json(step.output, expanded=True)
        else:
            st.code(str(step.output), language=None)


def move_replay(position_key, delta):
    st.session_state[position_key] += delta


overview, replay, comparison = st.tabs(["📊 运行总览", "⏮ 离线回放", "🔬 差异诊断"])
with overview:
    cols = st.columns(3)
    cols[0].metric("运行记录", len(records))
    cols[1].metric("运行成功率", f"{sum(r.status == 'success' for r in records.values()) / len(records):.0%}")
    cols[2].metric("失败运行", sum(r.status == "failed" for r in records.values()))
    st.caption("运行成功率按运行统计；步骤成功率不含跳过步骤。耗时为累计步骤耗时。")
    frame = pd.DataFrame([{"运行": r.name, "状态": status_label[r.status], "数据": "模拟" if r.simulated else "用户记录", "步骤": len(r.steps), "成功率": r.success_rate * 100, "耗时(ms)": r.duration_ms} for r in records.values()])
    st.dataframe(frame.style.map(lambda v: "background-color: #fee2e2; color: #991b1b" if v == "失败" else "", subset=["状态"]), width="stretch", hide_index=True, column_config={
        "运行": st.column_config.TextColumn(width="medium"),
        "状态": st.column_config.TextColumn(width="small"),
        "数据": st.column_config.TextColumn(width="small"),
        "步骤": st.column_config.NumberColumn(width="small", format="%d"),
        "成功率": st.column_config.NumberColumn(width="small", format="%.0f%%"),
        "耗时(ms)": st.column_config.NumberColumn(width="small", format="%.3f"),
    })
    selected = st.selectbox("查看运行", keys, format_func=label)
    run = records[selected]
    st.markdown(f"### {run.name}")
    st.caption("模拟数据" if run.simulated else "用户导入记录（来源标记由文件提供）")
    st.caption(f"运行 ID：{run.id} · 开始时间：{run.started_at} · 累计耗时：{run.duration_ms:.3f} ms · 步骤成功率：{run.success_rate:.0%}")
    st.download_button("下载此运行 JSON", run.to_json(), file_name="agenttrace-run.json", mime="application/json")
    if run.steps:
        timeline = []
        start = 0
        for i, step in enumerate(run.steps):
            timeline.append({"步骤": f"{i + 1:02d} {step.name}", "开始": start, "结束": start + step.duration_ms, "耗时": step.duration_ms, "状态": status_label[step.status]})
            start += step.duration_ms
        st.markdown("**执行时间线**")
        st.vega_lite_chart(pd.DataFrame(timeline), {
            "autosize": {"type": "fit", "contains": "padding", "resize": True},
            "padding": {"left": 5, "right": 16, "top": 5, "bottom": 5},
            "mark": {"type": "bar", "cornerRadius": 4},
            "encoding": {
                "y": {"field": "步骤", "type": "ordinal", "sort": None, "axis": {"title": None, "labelLimit": 160, "labelOverlap": False, "labelPadding": 8}},
                "x": {"field": "开始", "type": "quantitative", "title": "累计步骤耗时 (ms)", "axis": {"tickCount": 8}},
                "x2": {"field": "结束"},
                "color": {"field": "状态", "scale": {"domain": ["成功", "失败", "跳过"], "range": ["#16a085", "#e74c3c", "#94a3b8"]}, "legend": {"orient": "bottom", "direction": "horizontal", "columns": 3, "title": None, "offset": 12}},
                "tooltip": [{"field": "步骤"}, {"field": "状态"}, {"field": "开始", "format": ".3f"}, {"field": "结束", "format": ".3f"}, {"field": "耗时", "format": ".3f"}],
            },
            "height": max(240, len(timeline) * 42 + 125),
        }, width="stretch")
        st.caption("按 steps 数组顺序展示；横轴为步骤耗时累加，不包含步骤间等待，不代表并行执行的墙钟耗时。")
        for i, step in enumerate(run.steps):
            with st.expander(f"{'🔴' if step.status == 'failed' else '🟢' if step.status == 'success' else '⚪'} {i + 1}. {step.name} · {status_label[step.status]} · {step.duration_ms:g} ms", expanded=step.status == "failed"):
                step_detail(step)
    else:
        st.info("此运行没有步骤。")

with replay:
    st.info("历史记录回放：只读取已保存的输入、输出与异常，不会重新调用模型或工具。")
    replay_key = st.selectbox("选择回放记录", keys, format_func=label, key="replay_run")
    historical = records[replay_key]
    if historical.steps:
        position_key = "position:" + replay_key
        if position_key not in st.session_state:
            st.session_state[position_key] = 0
        prev, nxt, progress = st.columns([1, 1, 4])
        prev.button("← 上一步", disabled=st.session_state[position_key] == 0, on_click=move_replay, args=(position_key, -1))
        nxt.button("下一步 →", disabled=st.session_state[position_key] >= len(historical.steps) - 1, on_click=move_replay, args=(position_key, 1))
        index = st.selectbox("执行顺序", list(range(len(historical.steps))), format_func=lambda i: f"{i + 1}. {historical.steps[i].name}", key=position_key)
        progress.progress((index + 1) / len(historical.steps), text=f"步骤 {index + 1} / {len(historical.steps)}")
        step_detail(historical.steps[index])
    else:
        st.info("此记录没有可回放步骤。")

with comparison:
    st.caption("默认展示工具调用失败 → 修复后成功；可选择任意两次运行。")
    left, right = st.columns(2)
    before_key = left.selectbox("基准运行（之前）", keys, index=min(1, len(keys) - 1), format_func=label)
    after_key = right.selectbox("目标运行（之后）", keys, index=min(2, len(keys) - 1), format_func=label)
    a, b = records[before_key], records[after_key]
    if before_key == after_key:
        st.warning("当前选择相同记录，可切换目标运行查看差异。")
    m1, m2, m3 = st.columns(3)
    m1.metric("目标步骤成功率", f"{b.success_rate:.0%}", f"{(b.success_rate - a.success_rate) * 100:+.1f} 个百分点")
    m2.metric("目标累计耗时", f"{b.duration_ms:.3f} ms", f"{b.duration_ms - a.duration_ms:+.3f} ms", delta_color="inverse")
    m3.metric("目标失败步骤", sum(s.status == "failed" for s in b.steps), sum(s.status == "failed" for s in b.steps) - sum(s.status == "failed" for s in a.steps), delta_color="inverse")
    result = compare_runs(a, b)
    st.markdown("### 诊断总结")
    for line in result["summary"]:
        st.write("• " + line)
    if result["rows"]:
        compact_rows = [{"步骤": row["步骤"], "差异": row["差异"], "之前": status_label.get(row["之前状态"], "—"), "之后": status_label.get(row["之后状态"], "—"), "耗时变化(ms)": (row["之后耗时(ms)"] - row["之前耗时(ms)"]) if row["之前耗时(ms)"] is not None and row["之后耗时(ms)"] is not None else None} for row in result["rows"]]
        diff_frame = pd.DataFrame(compact_rows)
        colors = {"新增": "#dcfce7", "缺失": "#fee2e2", "变化": "#fef3c7"}
        st.dataframe(diff_frame.style.map(lambda v: f"background-color: {colors[v]}; color: #172238" if v in colors else "", subset=["差异"]), width="stretch", hide_index=True, column_config={
            "步骤": st.column_config.TextColumn(width="medium"),
            "差异": st.column_config.TextColumn(width="small"),
            "之前": st.column_config.TextColumn(width="small"),
            "之后": st.column_config.TextColumn(width="small"),
            "耗时变化(ms)": st.column_config.NumberColumn(width=130, format="%+.3f"),
        })
        st.caption("耗时变化 = 之后 − 之前；新增或缺失步骤没有可比耗时，以空值显示。完整输入输出、错误及变化字段见下方详情，下载报告保留全部列。")
        before_steps = {s.id: s for s in a.steps}
        after_steps = {s.id: s for s in b.steps}
        for row in result["rows"]:
            with st.expander(f"{row['差异']} · {row['步骤']}（{row['步骤 ID']}）"):
                st.write(f"变化字段：{row['变化字段']}")
                old, new = st.columns(2)
                for column, title, steps in ((old, "之前", before_steps), (new, "之后", after_steps)):
                    with column:
                        st.markdown(f"**{title}**")
                        step = steps.get(row["步骤 ID"])
                        if step is None:
                            st.info("本次运行没有此步骤")
                        else:
                            st.caption(f"{status_label[step.status]} · {step.duration_ms:.3f} ms")
                            if step.error:
                                st.error(step.error)
                            st.json({"input": step.input, "output": step.output}, expanded=True)
    st.download_button("下载诊断报告", "\n".join(result["summary"]) + "\n\n" + pd.DataFrame(result["rows"]).to_csv(index=False), file_name="agenttrace-diagnosis.txt", mime="text/plain")
