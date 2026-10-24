"""End-to-end browser test: real Streamlit app + real browser audio pipeline +
mock OpenAI server, driven by a synthetic microphone WAV.

  python tools/e2e_test.py scenario.wav [seconds]
Requires the mock (tools/mock_openai.py) and the app to be running with the mock env vars.
"""
import asyncio
import json
import sys

from playwright.async_api import async_playwright

WAV = sys.argv[1]
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 75
SETUP_JS = sys.argv[3] if len(sys.argv) > 3 else ""
URL = "http://localhost:8599"

STUB_TTS = """
(() => {
  const synth = window.speechSynthesis; if (!synth) return;
  window.__said = [];
  synth.speak = (u) => { window.__said.push(u.text); setTimeout(() => u.onend && u.onend(), 600); };
  synth.cancel = () => {};
})();
"""


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=[
            "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
            f"--use-file-for-fake-audio-capture={WAV}%noloop", "--autoplay-policy=no-user-gesture-required"])
        ctx = await b.new_context(permissions=["microphone"])
        await ctx.add_init_script(STUB_TTS)
        page = await ctx.new_page()
        logs = []
        page.on("console", lambda m: logs.append(f"[{m.type}] {m.text}"))
        await page.goto(URL)
        frame = None
        for _ in range(120):
            for f in page.frames:
                if "native_voice" in f.url or "component" in f.url:
                    frame = f
            if frame:
                try:
                    if await frame.evaluate("!!window.__native && !!window.ort"):
                        break
                except Exception:
                    pass
            await asyncio.sleep(0.5)
        assert frame, "component iframe not found"
        await frame.evaluate("window.__native.preload()")
        print("pair before:", await frame.inner_text("#pair"))
        if SETUP_JS:
            await frame.evaluate(SETUP_JS)
        await frame.click("#toggle")
        t0 = None
        for i in range(int(SECONDS * 2)):
            await asyncio.sleep(0.5)
            st = await frame.inner_text("#status")
            if i % 4 == 0:
                print(f"{i/2:5.1f}s  {st}  | {await frame.inner_text('#cloudText')}")
        hist = await frame.evaluate("window.__native.history")
        said = await frame.evaluate("window.__said || []")
        err = await frame.inner_text("#err")
        pair = await frame.inner_text("#pair")
        cache = await frame.evaluate("window.__native.lastTranslation ? window.__native.lastTranslation.length : 0")
        await frame.click("#toggle")  # deactivate
        await asyncio.sleep(0.5)
        after = await frame.evaluate("({state: window.__native.state, stream: !!window.__native.stream, rt: !!window.__native.rt})")
        await page.screenshot(path="e2e_screenshot.png", full_page=True)
        print(json.dumps({"history": hist, "said": said, "error": err, "pair": pair, "cache": cache, "after_deactivate": after}, indent=1))
        print("\n".join(l for l in logs if "error" in l.lower() or "warn" in l.lower())[:3000])
        await b.close()


asyncio.run(main())
