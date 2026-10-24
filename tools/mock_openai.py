"""Offline stand-in for the OpenAI Realtime API, for end-to-end testing of the
controller without spending tokens. NOT used by the app in normal operation.

  python tools/mock_openai.py  → HTTP :8701 (client_secrets), WS :8702 (realtime)
Then run the app with:
  NATIVE_OPENAI_API_BASE=http://127.0.0.1:8701/v1 NATIVE_REALTIME_WS_URL=ws://127.0.0.1:8702/v1/realtime \
  OPENAI_API_KEY=sk-mock streamlit run app.py

Behavior: interpretation → 0.8 s tone; COMMAND → intents from MOCK_COMMANDS in
order (default choose_languages, repeat_last_translation); LANGUAGE_SELECTION →
set_languages(MOCK_LANG_1, MOCK_LANG_2). Every client event is logged as JSON lines.
"""
import asyncio
import base64
import json
import math
import os
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import websockets

LOG = open(os.getenv("MOCK_LOG", "mock_openai.log"), "a", buffering=1)
COMMANDS = os.getenv("MOCK_COMMANDS", "choose_languages,repeat_last_translation").split(",")
LANGS = (os.getenv("MOCK_LANG_1", "Spanish"), os.getenv("MOCK_LANG_2", "French"))


def log(kind, **kw):
    LOG.write(json.dumps({"t": round(time.time(), 3), "kind": kind, **kw}) + "\n")


WS_REJECT = [m for m in os.getenv("MOCK_WS_REJECT", "").split(",") if m]
MODELS_404 = [m for m in os.getenv("MOCK_MODELS_404", "").split(",") if m]


class H(BaseHTTPRequestHandler):
    def do_GET(self):  # GET /v1/models/<id>
        m = self.path.rstrip("/").split("/")[-1]
        code = 404 if m in MODELS_404 else 200
        log("models_get", model=m, code=code)
        out = json.dumps({"id": m} if code == 200 else {"error": {"message": "not found"}}).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        log("client_secret", model=body.get("session", {}).get("model"),
            auth=self.headers.get("Authorization", "")[:12])
        out = json.dumps({"value": "ek_mock_" + str(int(time.time())), "expires_at": int(time.time()) + 600}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

    def log_message(self, *a):
        pass


def tone(sec=0.8, hz=440, rate=24000):
    return struct.pack("<%dh" % int(sec * rate),
                       *[int(8000 * math.sin(2 * math.pi * hz * i / rate)) for i in range(int(sec * rate))])


async def handler(ws):
    n = 0
    cmd_i = 0
    audio_bytes = 0
    model = ws.request.path.split("model=")[-1] if "model=" in ws.request.path else ""
    log("ws_open", model=model, protocols=ws.request.headers.get("Sec-WebSocket-Protocol", "")[:60])
    if model in WS_REJECT:
        await ws.send(json.dumps({"type": "error", "error": {"type": "invalid_request_error", "code": "model_not_found",
                                                            "message": f"The model {model} does not exist."}}))
        await ws.close(1008, "invalid_request_error.model_not_found")
        return
    await ws.send(json.dumps({"type": "session.created", "session": {}}))
    async for raw in ws:
        ev = json.loads(raw)
        t = ev.get("type")
        if t == "input_audio_buffer.append":
            audio_bytes += len(base64.b64decode(ev["audio"]))
            continue
        if t == "input_audio_buffer.commit":
            n += 1
            item = f"item_u{n}"
            log("commit", seconds=round(audio_bytes / 2 / 24000, 2))
            audio_bytes = 0
            await ws.send(json.dumps({"type": "input_audio_buffer.committed", "item_id": item}))
            await ws.send(json.dumps({"type": "conversation.item.added", "item": {"id": item}}))
            continue
        if t == "response.create":
            r = ev.get("response", {})
            instr = r.get("instructions", "")
            mode = "INTERPRETATION"
            for m in ("LANGUAGE_SELECTION", "COMMAND"):
                if f"CURRENT APPLICATION MODE: {m}." in instr:
                    mode = m
            langs = instr.split("CURRENT INTERPRETATION LANGUAGES: ")[1].split(".")[0] if instr else ""
            log("response.create", mode=mode, modalities=r.get("output_modalities"), langs=langs,
                tools=[x["name"] for x in r.get("tools", [])], tool_choice=r.get("tool_choice"))
            await asyncio.sleep(0.3)
            if mode == "INTERPRETATION":
                pcm = tone()
                for i in range(0, len(pcm), 9600):
                    await ws.send(json.dumps({"type": "response.output_audio.delta",
                                              "delta": base64.b64encode(pcm[i:i + 9600]).decode()}))
                    await asyncio.sleep(0.05)
                out = [{"id": f"item_a{n}", "type": "message"}]
            else:
                if mode == "COMMAND":
                    name, args = COMMANDS[cmd_i % len(COMMANDS)], {}
                    cmd_i += 1
                else:
                    name, args = "set_languages", {"language_1": LANGS[0], "language_2": LANGS[1]}
                out = [{"id": f"item_f{n}", "type": "function_call", "name": name, "call_id": "c1",
                        "arguments": json.dumps(args)}]
            await ws.send(json.dumps({"type": "response.done", "response": {"status": "completed", "output": out}}))
            continue
        log(t, **{k: v for k, v in ev.items() if k in ("item_id",)})
    log("ws_close")


async def main():
    threading.Thread(target=HTTPServer(("127.0.0.1", 8701), H).serve_forever, daemon=True).start()
    async with websockets.serve(handler, "127.0.0.1", 8702, subprotocols=["realtime"]):
        print("mock ready", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
