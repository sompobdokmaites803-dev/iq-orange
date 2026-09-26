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
        raise RuntimeError(
            f"OpenAI HTTP {e.code}: {body}"
        )


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

            if (
                content.get("type") == "output_text"
                and isinstance(content.get("text"), str)
            ):
                texts.append(content["text"])

            if content.get("type") == "refusal":
                raise RuntimeError(
                    "AI refused: "
                    + str(content.get("refusal", ""))
                )

    return "\n".join(texts)


class handler(BaseHTTPRequestHandler):

    def do_POST(self):

        try:
            n = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )

            body = json.loads(
                self.rfile.read(n).decode()
            )

            key = os.environ.get(
                "OPENAI_API_KEY"
            )

            if not key:
                raise RuntimeError(
                    "ยังไม่ได้ตั้ง OPENAI_API_KEY"
                )

            image = body.get("image")

            if not image:
                raise RuntimeError(
                    "ไม่มี screenshot สำหรับ STEP 2"
                )

            pair = body.get("pair", "")
            stage1_direction = body.get(
                "stage1_direction",
                "WAIT"
            )
            stage1_score = body.get(
                "stage1_score",
                0
            )

            prompt = f"""
คุณคือ STEP 2 FINAL SNAP CONFIRM ของระบบ IQ ORANGE 10M v6.3

ระบบ STEP 1 วิเคราะห์:
- 10 นาที = MAIN SETUP
- 15 นาที = Trend confirm
- 1 ชั่วโมง = Big trend

คู่เงิน: {pair}
STEP 1 direction: {stage1_direction}
STEP 1 score: {stage1_score}

หน้าที่ของคุณคือดู Screenshot ล่าสุดจาก IQ Option
เพื่อ CONFIRM ก่อนเข้าเท่านั้น
ห้ามฝืน STEP 1 ถ้าภาพยังไม่ชัดเจน

ให้พิจารณาจากสิ่งที่มองเห็นจริง เช่น:
- trend
- candle structure
- support / resistance
- breakout / rejection
- momentum
- stochastic
- RSI / indicator
- การชนแนวต้านหรือแนวรับ
- แท่งล่าสุดยืนยันหรือขัดแย้งกับ STEP 1

กฎสำคัญ:

1. ถ้าหลักฐานชัดและสอดคล้องกับ STEP 1
   ให้ READY

2. ถ้ายังต้องรอ confirmation
   ให้ WATCH หรือ WAIT

3. ถ้าภาพไม่ชัด / คู่เงินไม่ตรง /
   popup บัง / สัญญาณขัดกันมาก
   ให้ WAIT และ NO TRADE

4. อย่าให้ READY ง่ายเกินไป

5. ACTION NOW ต้องเลือกเพียงหนึ่งข้อ:
- พร้อมเข้า CALL
- พร้อมเข้า PUT
- รอแท่งถัดไป
- รอ Stochastic cross
- รอ Breakout confirm
- รอ Momentum ยืนยัน
- NO TRADE

6. reason ให้เป็นภาษาไทยสั้น กระชับ
   ประมาณ 1-2 ประโยค
   บอกว่าทำไม และต้องรออะไร

7. ถ้า direction = WAIT
   ห้าม status = READY
"""

            schema = {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": [
                            "UP",
                            "DOWN",
                            "WAIT"
                        ]
                    },
                    "score": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 100
                    },
                    "risk": {
                        "type": "string",
                        "enum": [
                            "LOW",
                            "MEDIUM",
                            "HIGH"
                        ]
                    },
                    "status": {
                        "type": "string",
                        "enum": [
                            "READY",
                            "WATCH",
                            "NO TRADE"
                        ]
                    },
                    "action": {
                        "type": "string",
                        "enum": [
                            "พร้อมเข้า CALL",
                            "พร้อมเข้า PUT",
                            "รอแท่งถัดไป",
                            "รอ Stochastic cross",
                            "รอ Breakout confirm",
                            "รอ Momentum ยืนยัน",
                            "NO TRADE"
                        ]
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
                    "action",
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
                        "name": "iq_orange_step2_v63",
                        "strict": True,
                        "schema": schema
                    }
                },

                "max_output_tokens": 450
            }

            resp = call_openai(
                payload,
                key
            )

            text = extract_output_text(
                resp
            )

            if not text:
                raise RuntimeError(
                    "AI returned no output_text: "
                    + json.dumps(
                        resp,
                        ensure_ascii=False
                    )[:1200]
                )

            try:
                d = json.loads(text)

            except Exception:
                raise RuntimeError(
                    "AI JSON parse failed: "
                    + text[:1000]
                )

            direction = d.get(
                "direction",
                "WAIT"
            )

            status = d.get(
                "status",
                "WATCH"
            )

            action = d.get(
                "action",
                "รอแท่งถัดไป"
            )

            # Safety logic
            if direction == "WAIT":
                if status == "READY":
                    status = "WATCH"

                if action in [
                    "พร้อมเข้า CALL",
                    "พร้อมเข้า PUT"
                ]:
                    action = "รอแท่งถัดไป"

            entry = None

            # v6.3 = รอบ 10 นาที + 5 วินาที
            if (
                direction != "WAIT"
                and status == "READY"
            ):
                ten_min = 600

                ep = (
                    math.floor(
                        time.time() / ten_min
                    ) + 1
                ) * ten_min + 5

                entry = datetime.fromtimestamp(
                    ep,
                    timezone(
                        timedelta(hours=7)
                    )
                ).strftime(
                    "%H:%M:%S"
                )

            out = {
                "direction": direction,
                "score": int(
                    d.get("score", 0)
                ),
                "risk": d.get(
                    "risk",
                    "HIGH"
                ),
                "status": status,
                "action": action,
                "reason": d.get(
                    "reason",
                    ""
                ),
                "entry_time": entry,
                "setup_tf": "10m",
                "version": "6.3"
            }

            code = 200

        except Exception as e:

            out = {
                "error": str(e)
            }

            code = 500

        b = json.dumps(
            out,
            ensure_ascii=False
        ).encode()

        self.send_response(code)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "Cache-Control",
            "no-store"
        )

        self.end_headers()

        self.wfile.write(b)
