import os
import json
import urllib.request
import urllib.error
import time
import math
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler


def call_openai(payload, key):
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")
        raise RuntimeError(f"OpenAI HTTP {e.code}: {body}")


def extract_output_text(resp):
    if isinstance(resp.get("output_text"), str):
        return resp["output_text"]

    texts = []

    for item in resp.get("output", []):
        if not isinstance(item, dict):
            continue

        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue

            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                texts.append(content["text"])

            if content.get("type") == "refusal":
                raise RuntimeError("AI refused: " + str(content.get("refusal", "")))

    return "\n".join(texts)


class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n).decode())

            key = os.environ.get("OPENAI_API_KEY")
            if not key:
                raise RuntimeError("ยังไม่ได้ตั้ง OPENAI_API_KEY")

            image = body.get("image")
            if not image:
                raise RuntimeError("ไม่มี screenshot สำหรับ STEP 2")

            prompt = f"""
วิเคราะห์ screenshot กราฟ IQ Option เพื่อยืนยันแผน 5 นาที

คู่เงิน: {body.get('pair')}
STEP 1 direction: {body.get('stage1_direction')}
STEP 1 score: {body.get('stage1_score')}

พิจารณาเฉพาะสิ่งที่มองเห็นจากภาพ เช่น
trend, support/resistance, momentum, stochastic/indicator,
แท่งเทียนล่าสุด และความขัดแย้งของสัญญาณ

ถ้าภาพไม่ชัด, คู่เงินไม่ตรง, มี popup บัง,
หรือหลักฐานยังไม่พอ ให้ direction = WAIT

ให้ reason เป็นภาษาไทยสั้น กระชับ
"""

            schema = {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["UP", "DOWN", "WAIT"]
                    },
                    "score": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 100
                    },
                    "risk": {
                        "type": "string",
                        "enum": ["LOW", "MEDIUM", "HIGH"]
                    },
                    "status": {
                        "type": "string",
                        "enum": ["READY", "WATCH", "NO TRADE"]
                    },
                    "reason": {
                        "type": "string"
                    }
                },
                "required": [
                    "direction",
                    "score",
                    "risk",
                    "status",
                    "reason"
                ],
                "additionalProperties": False
            }

            payload = {
                "model": "gpt-5.6-luna",
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": prompt
                            },
                            {
                                "type": "input_image",
                                "image_url": image
                            }
                        ]
                    }
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "iq_orange_step2",
                        "strict": True,
                        "schema": schema
                    }
                },
                "max_output_tokens": 400
            }

            resp = call_openai(payload, key)

            text = extract_output_text(resp)
            if not text:
                raise RuntimeError(
                    "AI returned no output_text: " +
                    json.dumps(resp, ensure_ascii=False)[:1200]
                )

            try:
                d = json.loads(text)
            except Exception:
                raise RuntimeError("AI JSON parse failed: " + text[:1000])

            direction = d.get("direction", "WAIT")
            status = d.get("status", "WATCH")

            entry = None
            if direction != "WAIT" and status == "READY":
                ep = (math.floor(time.time() / 300) + 1) * 300 + 5
                entry = datetime.fromtimestamp(
                    ep,
                    timezone(timedelta(hours=7))
                ).strftime("%H:%M:%S")

            out = {
                "direction": direction,
                "score": int(d.get("score", 0)),
                "risk": d.get("risk", "HIGH"),
                "status": status,
                "reason": d.get("reason", ""),
                "entry_time": entry
            }

            code = 200

        except Exception as e:
            out = {
                "error": str(e)
            }
            code = 500

        b = json.dumps(out, ensure_ascii=False).encode()

        self.send_response(code)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)
