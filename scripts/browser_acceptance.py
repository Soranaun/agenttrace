"""Optional real-browser acceptance test; uses installed Chrome, no browser download.

Run: .venv/Scripts/python.exe scripts/browser_acceptance.py
Requires a running app on 127.0.0.1:8501 and the optional playwright package.
"""
import json
import os
from pathlib import Path
import re
import sys

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agenttrace.models import Run

OUTPUT = ROOT / "artifacts" / "acceptance"
CHROME = os.environ.get("AGENTTRACE_CHROME", str(Path(os.environ.get("PROGRAMFILES", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"))


def choose(page, run_id, index=0, source="内置"):
    page.get_by_role("combobox").nth(index).click()
    page.get_by_role("option", name=re.compile(rf"\[{source}\].*{run_id}")).click()


def check_table(page, rows=3):
    table = page.locator('[data-testid="stDataFrame"]:visible')
    table.wait_for()
    # Streamlit's canvas grid resizes asynchronously after the viewport changes.
    # Checking only inner scrollbars misses a grid that still has its old width.
    page.wait_for_function("""rows => {
        const root = Array.from(document.querySelectorAll('[data-testid="stDataFrame"]')).find(e => e.clientWidth > 0);
        if (!root) return false;
        const r = root.getBoundingClientRect();
        return r.right <= innerWidth + 1 && r.width <= root.parentElement.clientWidth + 1
            && r.height >= 35 * rows + 35;
    }""", arg=rows)
    overflow = table.evaluate("""root => Array.from(root.querySelectorAll('div')).filter(e =>
        e.clientWidth > 0 && ['auto', 'scroll'].includes(getComputedStyle(e).overflowX)
        && e.scrollWidth > e.clientWidth + 2
    ).map(e => ({className: e.className, width: e.clientWidth, content: e.scrollWidth}))""")
    assert not overflow, f"Table requires horizontal scrolling: {overflow}"
    return table


def check_chart(page, expected_steps=4):
    chart = page.locator('[data-testid="stVegaLiteChart"]:visible')
    chart.locator("svg").wait_for()
    page.wait_for_function("""() => {
        const root = document.querySelector('[data-testid="stVegaLiteChart"]');
        const svg = root?.querySelector('svg');
        return svg && Array.from(svg.querySelectorAll('.role-legend text')).filter(e => e.textContent).length === 3
            && svg.getBoundingClientRect().width <= root.getBoundingClientRect().width + 2;
    }""")
    bounds = chart.evaluate("""root => {
        const svg = root.querySelector('svg').getBoundingClientRect();
        return Array.from(root.querySelectorAll('.role-legend text')).filter(e => e.textContent).map(e => {
            const r = e.getBoundingClientRect();
            return {text: e.textContent, inside: r.left >= svg.left - 2 && r.right <= svg.right + 2
                && r.top >= svg.top - 2 && r.bottom <= svg.bottom + 2};
        });
    }""")
    assert {b["text"] for b in bounds} == {"成功", "失败", "跳过"}
    assert all(b["inside"] for b in bounds), f"Clipped legend: {bounds}"
    labels = chart.locator(".role-axis-label text").all_text_contents()
    assert len([text for text in labels if re.match(r"^\d{2} ", text)]) == expected_steps, "Timeline hid step labels"
    return chart


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=CHROME, headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 768}, device_scale_factor=1)
        page.goto("http://127.0.0.1:8501", wait_until="networkidle")
        page.get_by_role("heading", name="AgentTrace", exact=False).wait_for()
        for run_id, duration in (("demo-001", 620), ("demo-002", 630), ("demo-003", 612)):
            choose(page, run_id)
            page.get_by_text(re.compile(rf"运行 ID：{run_id}.*累计耗时：{duration}.000 ms")).wait_for()
            check_chart(page, expected_steps={"demo-001": 3, "demo-002": 2, "demo-003": 4}[run_id])
            with page.expect_download() as download:
                page.get_by_role("button", name="下载此运行 JSON", exact=True).click()
            path = OUTPUT / f"{run_id}-export.json"
            download.value.save_as(str(path))
            assert Run.from_json(path.read_bytes()) == Run.from_json((ROOT / "data" / "runs" / f"{run_id}.json").read_bytes())
        for width in (1366, 1280, 1024):
            page.set_viewport_size({"width": width, "height": 768})
            check_chart(page).screenshot(path=str(OUTPUT / f"timeline-{width}.png"))
            page.locator('[data-testid="stMain"]').evaluate("el => el.scrollTo(0, 0)")
            check_table(page).screenshot(path=str(OUTPUT / f"overview-table-{width}.png"))

        # Real upload of a downloaded record; repeated imports must not inflate counts.
        upload = page.locator('input[type="file"]')
        upload.set_input_files(str(OUTPUT / "demo-002-export.json"))
        page.get_by_text("已加载：demo-002-export.json", exact=True).wait_for()
        assert page.locator('[data-testid="stMetricValue"]:visible').first.inner_text() == "4"
        upload.set_input_files({"name": "broken.json", "mimeType": "application/json", "buffer": b"{"})
        page.get_by_text(re.compile("broken.json：无法解析")).wait_for()
        upload.set_input_files(str(OUTPUT / "demo-002-export.json"))
        page.get_by_text("已加载：demo-002-export.json", exact=True).wait_for()
        assert page.locator('[data-testid="stMetricValue"]:visible').first.inner_text() == "4"

        page.get_by_role("tab", name="⏮ 离线回放").click()
        choose(page, "demo-002", source="导入")
        page.get_by_role("button", name="下一步 →", exact=True).click()
        page.locator('[role="tabpanel"]:visible').get_by_text(re.compile("KeyError:.*商品编码")).wait_for()
        expect(page.get_by_role("button", name="下一步 →", exact=True)).to_be_disabled()
        page.screenshot(path=str(OUTPUT / "replay-1024.png"))
        page.get_by_role("button", name="← 上一步", exact=True).click()
        expect(page.get_by_role("button", name="← 上一步", exact=True)).to_be_disabled()

        page.get_by_role("tab", name="🔬 差异诊断").click()
        page.get_by_text(re.compile("累计步骤耗时：630.000 → 612.000 ms，变化 -18.000 ms")).wait_for()
        for width in (1366, 1280, 1024):
            page.set_viewport_size({"width": width, "height": 768})
            page.locator('[data-testid="stMain"]').evaluate("el => el.scrollTo(0, 0)")
            check_table(page, rows=4).screenshot(path=str(OUTPUT / f"diagnosis-table-{width}.png"))
        page.get_by_text("变化 · 查询库存（lookup）", exact=True).click()
        page.locator('[role="tabpanel"]:visible').get_by_text(re.compile("KeyError:.*商品编码")).wait_for()
        with page.expect_download() as download:
            page.get_by_role("button", name="下载诊断报告", exact=True).click()
        download.value.save_as(str(OUTPUT / "diagnosis.txt"))
        assert "变化 -18.000 ms" in (OUTPUT / "diagnosis.txt").read_text(encoding="utf-8")
        assert page.locator('[data-testid="stException"]').count() == 0
        (OUTPUT / "result.json").write_text(json.dumps({"result": "passed", "viewport_widths": [1366, 1280, 1024], "checks": ["all scenarios and JSON downloads", "legend bounds", "table horizontal overflow", "download-upload round trip", "invalid JSON", "import deduplication", "offline replay", "diagnosis and report download"]}, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Browser acceptance passed at widths 1366, 1280, 1024; JSON import/export and replay passed.")
        browser.close()


if __name__ == "__main__":
    main()
