"""
Capture README demo assets with Playwright (video + screenshots).

Requires: API :8000, Celery worker, Vite :5173, Chromium via Playwright.

Usage:
  uv run python scripts/capture_demo.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "docs" / "images"
RAW = ROOT / "docs" / "media" / "raw"
MEDIA = ROOT / "docs" / "media"
APP_URL = "http://localhost:5173/"
VIEWPORT = {"width": 1440, "height": 900}
SLOW_MO_MS = 120
TYPE_DELAY_MS = 80
ANALYSIS_TIMEOUT_MS = 600_000  # reasoning models can be slow


def _ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def _ensure_dirs() -> None:
    IMAGES.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    MEDIA.mkdir(parents=True, exist_ok=True)


def _log(events: dict, name: str, t0: float) -> None:
    events[name] = round(time.perf_counter() - t0, 3)
    print(f"[ts] {name}={events[name]}s", flush=True)


def _shot(page, name: str, full_page: bool = True) -> Path:
    path = IMAGES / f"{name}.png"
    page.screenshot(path=str(path), full_page=full_page)
    print(f"[shot] {path.relative_to(ROOT)}", flush=True)
    return path


def _shot_locator(locator, name: str) -> Path:
    path = IMAGES / f"{name}.png"
    locator.screenshot(path=str(path))
    print(f"[shot] {path.relative_to(ROOT)} (element)", flush=True)
    return path


def _hide_noise(page) -> None:
    page.add_style_tag(
        content="""
        #vite-error-overlay, vite-error-overlay, [data-vite-dev-id] { display: none !important; }
        """
    )


def _wait_report(page) -> None:
    page.get_by_text("Bull case", exact=False).first.wait_for(
        state="visible", timeout=ANALYSIS_TIMEOUT_MS
    )
    page.get_by_text("Bear case", exact=False).first.wait_for(
        state="visible", timeout=30_000
    )


def _add_watchlist(page, tickers: list[str]) -> None:
    for t in tickers:
        inp = page.get_by_placeholder("Add ticker")
        inp.fill("")
        inp.type(t, delay=TYPE_DELAY_MS)
        page.get_by_role("button", name="Add", exact=True).click()
        page.wait_for_timeout(600)


def _run_backtest(page) -> None:
    page.get_by_role("button", name="Backtests").click()
    page.wait_for_timeout(1000)
    page.get_by_placeholder("Backtest name").fill("Demo backtest")
    page.get_by_role("button", name="Run Backtest").click()
    # Wait for summary cards or an error
    try:
        page.get_by_text("Total reports", exact=False).first.wait_for(
            state="visible", timeout=300_000
        )
    except PlaywrightTimeout:
        err = page.locator("text=/failed|error|Failed/i").first
        if err.count():
            print(f"[warn] backtest may have failed: {err.inner_text()[:200]}", flush=True)
        else:
            raise


def capture() -> dict:
    _ensure_dirs()
    events: dict = {}
    video_path: Path | None = None
    # Best-data ticker from diagnose: full ML suite + rich earnings/news.
    demo_ticker = "ACN"
    demo_question = (
        "What is the earnings outlook and key accounting risk for Accenture?"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, slow_mo=SLOW_MO_MS)
        context = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(RAW),
            record_video_size=VIEWPORT,
            device_scale_factor=1,
        )
        page = context.new_page()
        t0 = time.perf_counter()

        page.goto(APP_URL, wait_until="networkidle")
        _hide_noise(page)
        page.wait_for_timeout(1000)
        _log(events, "landing", t0)

        # Seed watchlist before analysis so the sidebar looks populated
        _add_watchlist(page, ["AAPL", "MSFT", demo_ticker, "JPM"])
        page.wait_for_timeout(800)
        _log(events, "watchlist_seeded", t0)
        _shot(page, "watchlist", full_page=False)

        ticker = page.get_by_placeholder("Enter ticker — AAPL, MSFT, NVDA...")
        ticker.click()
        ticker.fill("")
        ticker.type(demo_ticker, delay=TYPE_DELAY_MS)
        question = page.get_by_placeholder(
            "Optional question — defaults to a comprehensive analysis"
        )
        question.fill(demo_question)
        page.wait_for_timeout(400)

        analyze_btn = page.get_by_role("main").get_by_role("button", name="Analyze →")
        analyze_btn.click()
        _log(events, "submit_click", t0)

        try:
            page.get_by_role("button", name="Analyzing...").wait_for(
                state="visible", timeout=15_000
            )
            page.wait_for_timeout(1500)
            _shot(page, "agent_progress", full_page=False)
            _log(events, "progress_visible", t0)
        except PlaywrightTimeout:
            print("[warn] progress UI not seen", flush=True)

        _wait_report(page)
        _log(events, "report_rendered", t0)
        page.wait_for_timeout(1500)

        # Crop just the report card (glass section with Bull case).
        report_card = page.locator("section").filter(has_text="Bull case").first
        report_card.scroll_into_view_if_needed()
        page.wait_for_timeout(400)
        _shot_locator(report_card, "report")

        # Top of dashboard: header, watchlist, stats, sentiment bars.
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(800)
        # Wait for sentiment bars if the chart has rendered
        try:
            page.locator(".recharts-bar-rectangle, .recharts-rectangle").first.wait_for(
                state="visible", timeout=10_000
            )
            page.wait_for_timeout(500)
        except PlaywrightTimeout:
            print("[warn] sentiment bars not seen", flush=True)
        _shot(page, "dashboard", full_page=False)

        # Slow scroll through report (for video)
        report_card.scroll_into_view_if_needed()
        for _ in range(6):
            page.mouse.wheel(0, 350)
            page.wait_for_timeout(450)
        _log(events, "report_scrolled", t0)
        page.mouse.wheel(0, -2000)
        page.wait_for_timeout(500)

        page.wait_for_timeout(1500)
        _log(events, "end", t0)

        video_path = Path(page.video.path()) if page.video else None
        context.close()
        browser.close()

    # Drop redundant / weak README assets from prior captures.
    for stale in ("landing.png", "watchlist_filled.png", "backtest.png"):
        path = IMAGES / stale
        if path.exists():
            path.unlink()
            print(f"[rm] {path.relative_to(ROOT)}", flush=True)

    if video_path and video_path.exists():
        dest = RAW / "capture.webm"
        if dest.exists():
            dest.unlink()
        video_path.replace(dest)
        events["raw_video"] = str(dest.relative_to(ROOT)).replace("\\", "/")
        print(f"[video] {dest}", flush=True)
    else:
        print("[error] no video recorded", flush=True)
        sys.exit(1)

    events_path = RAW / "timestamps.json"
    events_path.write_text(json.dumps(events, indent=2), encoding="utf-8")
    print(f"[ts] wrote {events_path}", flush=True)
    return events


def _run(cmd: list[str]) -> None:
    print("[ffmpeg]", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def postprocess(events: dict) -> None:
    ff = _ffmpeg()
    raw = ROOT / events["raw_video"]
    submit = float(events["submit_click"])
    report = float(events["report_rendered"])
    end = float(events["end"])

    parts = RAW / "parts"
    parts.mkdir(exist_ok=True)

    # Full demo: keep interactions 1x, speed LLM wait ~8x (single filter graph).
    demo_mp4 = MEDIA / "demo.mp4"
    fc_demo = (
        f"[0:v]trim=0:{submit:.3f},setpts=PTS-STARTPTS,scale=1920:-2[pre];"
        f"[0:v]trim={submit:.3f}:{report:.3f},setpts=(PTS-STARTPTS)/8,scale=1920:-2[wait];"
        f"[0:v]trim={report:.3f}:{end:.3f},setpts=PTS-STARTPTS,scale=1920:-2[post];"
        f"[pre][wait][post]concat=n=3:v=1:a=0[out]"
    )
    _run([
        ff, "-y", "-i", str(raw),
        "-filter_complex", fc_demo,
        "-map", "[out]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(demo_mp4),
    ])

    # GIF: NVDA flow from typing/submit through report scroll (~15–25s).
    # Speed the wait less aggressively (4x) so the clip isn't too short.
    gif_start = max(0.0, submit - 2.5)  # include last of typing
    gif_end = min(end, report + 12.0)
    gif_mp4 = parts / "gif_src.mp4"
    fc_gif = (
        f"[0:v]trim={gif_start:.3f}:{submit:.3f},setpts=PTS-STARTPTS,scale=1000:-2[pre];"
        f"[0:v]trim={submit:.3f}:{report:.3f},setpts=(PTS-STARTPTS)/4,scale=1000:-2[wait];"
        f"[0:v]trim={report:.3f}:{gif_end:.3f},setpts=PTS-STARTPTS,scale=1000:-2[post];"
        f"[pre][wait][post]concat=n=3:v=1:a=0[out]"
    )
    _run([
        ff, "-y", "-i", str(raw),
        "-filter_complex", fc_gif,
        "-map", "[out]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(gif_mp4),
    ])

    demo_gif = MEDIA / "demo.gif"
    fps, width = 14, 1000
    for attempt in range(3):
        palette = parts / f"palette_{attempt}.png"
        _run([
            ff, "-y", "-i", str(gif_mp4),
            "-vf", f"fps={fps},scale={width}:-1:flags=lanczos,palettegen=stats_mode=diff",
            str(palette),
        ])
        _run([
            ff, "-y", "-i", str(gif_mp4), "-i", str(palette),
            "-lavfi",
            f"fps={fps},scale={width}:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5",
            "-loop", "0",
            str(demo_gif),
        ])
        size_mb = demo_gif.stat().st_size / (1024 * 1024)
        print(f"[gif] attempt {attempt+1}: {size_mb:.2f} MB @ {fps}fps {width}px", flush=True)
        if size_mb <= 10:
            break
        fps = max(10, fps - 2)
        width = max(720, width - 100)

    probe = subprocess.run(
        [ff, "-i", str(demo_gif)],
        capture_output=True,
        text=True,
    )
    print(probe.stderr[-500:] if probe.stderr else "", flush=True)


def main() -> None:
    events = capture()
    postprocess(events)
    print("\n=== outputs ===", flush=True)
    for folder in (IMAGES, MEDIA):
        for p in sorted(folder.rglob("*")):
            if p.is_file() and "raw" not in p.parts and "parts" not in p.parts:
                mb = p.stat().st_size / (1024 * 1024)
                print(f"  {p.relative_to(ROOT)}  {mb:.2f} MB", flush=True)


if __name__ == "__main__":
    main()
