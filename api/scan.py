import os
import json
import time
import math
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler

PAIRS = [
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "AUD/USD",
    "USD/CHF",
    "EUR/JPY",
    "EUR/GBP",
    "NZD/USD",
]

# Cache ใน warm serverless instance
CACHE = {
    "time": 0,
    "data": None
}

CACHE_SECONDS = 55


def get_json(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "IQOrange/6.3"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def batch_5m(key, n=300):
    """
    ดึง 8 คู่ใน HTTP request เดียว
    Twelve Data ยังคิด credits ตามจำนวน symbol
    แต่ลดจำนวน network requests จาก 8 -> 1
    """
    query = urllib.parse.urlencode({
        "symbol": ",".join(PAIRS),
        "interval": "5min",
        "outputsize": n,
        "apikey": key,
        "format": "JSON",
    })

    data = get_json(
        "https://api.twelvedata.com/time_series?" + query
    )

    if isinstance(data, dict) and data.get("status") == "error":
        raise RuntimeError(
            data.get("message", "Twelve Data error")
        )

    result = {}
    errors = []

    for pair in PAIRS:
        item = None

        # Batch response ปกติ
        if isinstance(data, dict):
            item = data.get(pair)

        # fallback เผื่อ key ถูก normalize
        if item is None and isinstance(data, dict):
            for k, v in data.items():
                if str(k).upper().replace(" ", "") == pair.upper():
                    item = v
                    break

        if not isinstance(item, dict):
            errors.append(f"{pair}: no data")
            continue

        if item.get("status") == "error":
            errors.append(
                f"{pair}: {item.get('message', 'error')}"
            )
            continue

        values = item.get("values", [])

        candles = []

        for v in reversed(values):
            try:
                candles.append({
                    "o": float(v["open"]),
                    "h": float(v["high"]),
                    "l": float(v["low"]),
                    "c": float(v["close"]),
                })
            except Exception:
                pass

        if candles:
            result[pair] = candles
        else:
            errors.append(f"{pair}: empty")

    return result, errors


def aggregate(candles, group):
    out = []

    for i in range(0, len(candles), group):
        chunk = candles[i:i + group]

        if len(chunk) < group:
            continue

        out.append({
            "o": chunk[0]["o"],
            "h": max(x["h"] for x in chunk),
            "l": min(x["l"] for x in chunk),
            "c": chunk[-1]["c"],
        })

    return out


def ema(v, n):
    if not v:
        return 0

    k = 2 / (n + 1)
    e = v[0]

    for x in v[1:]:
        e = x * k + e * (1 - k)

    return e


def rsi(v, n=14):
    if len(v) < n + 1:
        return 50

    g = 0
    l = 0

    for a, b in zip(v[-n - 1:-1], v[-n:]):
        d = b - a
        g += max(d, 0)
        l += max(-d, 0)

    if l == 0:
        return 100

    rs = (g / n) / (l / n)
    return 100 - 100 / (1 + rs)


def trend(c):
    cl = [x["c"] for x in c]

    if len(cl) < 22:
        return 0

    e8 = ema(cl[-30:], 8)
    e21 = ema(cl[-40:], 21)
    slope = cl[-1] - cl[-4]

    if e8 > e21 and slope > 0:
        return 1

    if e8 < e21 and slope < 0:
        return -1

    return 0


def analyze(pair, c5):

    # NEW v6.3
    # 5m source
    # 10m = MAIN SETUP
    # 15m = trend confirm
    # 1H = big trend
    c10 = aggregate(c5, 2)
    c15 = aggregate(c5, 3)
    c60 = aggregate(c5, 12)

    if len(c10) < 30 or len(c15) < 22 or len(c60) < 22:
        return None

    t10 = trend(c10)
    t15 = trend(c15)
    t60 = trend(c60)

    # ใช้ 10m เป็นแกนหลัก
    sign = t10 if t10 else (t15 if t15 else t60)

    if sign == 0:
        direction = "WAIT"
    else:
        direction = "CALL" if sign == 1 else "PUT"

    score = 0

    # 10m main trend สำคัญสุด
    if t10 == sign and sign != 0:
        score += 30

    # 15m confirm
    if t15 == sign and sign != 0:
        score += 20

    # 1H confirm
    if t60 == sign and sign != 0:
        score += 20

    recent = c10[-8:]
    x = c10[-1]

    rng = max(
        x["h"] - x["l"],
        1e-12
    )

    body = abs(
        x["c"] - x["o"]
    )

    # breakout / reclaim
    if sign == 1:
        resistance = max(
            a["h"] for a in recent[:-1]
        )

        reclaim = (
            x["c"] > x["o"]
            and x["l"] <= resistance * 1.0015
            and x["c"] >= resistance
        )

    elif sign == -1:
        support = min(
            a["l"] for a in recent[:-1]
        )

        reclaim = (
            x["c"] < x["o"]
            and x["h"] >= support * 0.9985
            and x["c"] <= support
        )

    else:
        reclaim = False

    if reclaim:
        score += 15
    elif body / rng > 0.45:
        score += 8

    rr = rsi(
        [a["c"] for a in c10]
    )

    momentum_ok = (
        sign == 1 and 48 <= rr <= 72
    ) or (
        sign == -1 and 28 <= rr <= 52
    )

    if momentum_ok:
        score += 10

    # แท่ง 10m ล่าสุดยืนยัน direction
    confirm = (
        sign == 1 and x["c"] > x["o"]
    ) or (
        sign == -1 and x["c"] < x["o"]
    )

    if confirm:
        score += 10

    hi = max(
        a["h"] for a in c10[-12:]
    )

    lo = min(
        a["l"] for a in c10[-12:]
    )

    span = max(
        hi - lo,
        1e-12
    )

    room = (
        (hi - x["c"]) / span
        if sign == 1
        else (x["c"] - lo) / span
    )

    if room > 0.28:
        score += 5

    # quality / candle activity
    q = (
        sum(
            abs(a["c"] - a["o"])
            for a in c10[-6:]
        )
        /
        max(
            a["h"] - a["l"]
            for a in c10[-6:]
        )
        /
        6
    )

    if q > 0.45:
        score += 5
    elif q > 0.30:
        score += 2

    score = min(
        100,
        round(score)
    )

    if direction == "WAIT":
        status = "NO TRADE"
    elif score >= 90:
        status = "READY"
    elif score >= 75:
        status = "WATCH"
    else:
        status = "NO TRADE"

    if score >= 90:
        risk = "LOWER"
    elif score >= 75:
        risk = "MEDIUM"
    else:
        risk = "HIGH"

    # entry เวลาแท่ง 10 นาทีถัดไป +5 วินาที
    now = time.time()
    ten_min = 600

    entry_epoch = (
        math.floor(now / ten_min) + 1
    ) * ten_min + 5

    entry_time = datetime.fromtimestamp(
        entry_epoch,
        timezone(timedelta(hours=7))
    ).strftime("%H:%M:%S")

    reason = (
        f"10m/{t10:+d} · "
        f"15m/{t15:+d} · "
        f"1H/{t60:+d} · "
        f"RSI {rr:.1f} · "
        f"10m confirm {'ผ่าน' if confirm else 'ยัง'}"
    )

    return {
        "pair": pair,
        "direction": direction,
        "score": score,
        "status": status,
        "risk": risk,
        "entry_time": entry_time,
        "reason": reason,

        # ให้ frontend รู้ว่า v6.3 ใช้ 10m
        "setup_tf": "10m",
        "trend_tf": "15m/1H",
    }


def run():

    key = os.environ.get(
        "TWELVE_DATA_API_KEY"
    )

    if not key:
        raise RuntimeError(
            "ยังไม่ได้ตั้ง TWELVE_DATA_API_KEY"
        )

    now = time.time()

    # ใช้ cache ถ้ายังไม่เกิน 55 วินาที
    if (
        CACHE["data"] is not None
        and now - CACHE["time"] < CACHE_SECONDS
    ):
        cached = dict(CACHE["data"])
        cached["cached"] = True
        return cached

    candles_by_pair, errors = batch_5m(
        key,
        300
    )

    out = []

    for pair in PAIRS:
        try:
            c5 = candles_by_pair.get(pair)

            if not c5:
                continue

            a = analyze(
                pair,
                c5
            )

            if a:
                out.append(a)

        except Exception as e:
            errors.append(
                f"{pair}: {e}"
            )

    out.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    if not out:
        raise RuntimeError(
            "Twelve Data ไม่มีข้อมูลที่ใช้ได้: "
            + " | ".join(errors[:3])
        )

    result = {
        "top": out,

        # 8 credits แต่ HTTP network request เหลือ 1
        "api_calls": len(candles_by_pair),
        "http_requests": 1,

        "cached": False,
        "setup_tf": "10m",
        "version": "6.3",

        "errors": errors[:3],
    }

    CACHE["time"] = now
    CACHE["data"] = result

    return result


class handler(BaseHTTPRequestHandler):

    def do_GET(self):

        try:
            d = run()
            code = 200

        except Exception as e:
            d = {
                "error": str(e)
            }
            code = 500

        b = json.dumps(
            d,
            ensure_ascii=False
        ).encode()

        self.send_response(code)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "Cache-Control",
            "public, s-maxage=50, stale-while-revalidate=120"
        )

        self.end_headers()

        self.wfile.write(b)
