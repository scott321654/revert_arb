import urllib.request
import json
from datetime import date, datetime, timedelta
from .tzutil import now, today
from typing import Optional


TWSE_REALTIME = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={}_{}.tw&json=1"
TWSE_DAILY = "https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={}&stockNo={}"


def _fetch_json(url: str) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=5)
        return json.loads(resp.read())
    except Exception:
        return None


def _mid_price(m: dict) -> Optional[float]:
    ask = m.get("a", "")
    bid = m.get("b", "")
    try:
        a = float(ask.split("_")[0]) if ask and ask != "-" else None
        b = float(bid.split("_")[0]) if bid and bid != "-" else None
        if a and b:
            return round((a + b) / 2, 2)
        return a or b
    except (ValueError, IndexError):
        return None


def is_market_open_today() -> bool:
    q = current_price("2330")
    if not q:
        return False
    now_hour = now().hour
    if q.get("volume", 0) > 0 and q.get("price"):
        return True
    if 9 <= now_hour <= 13 or (now_hour == 13 and now().minute <= 35):
        return True
    return False


def current_price(stock_id: str, exchange: str = "tse") -> Optional[dict]:
    url = TWSE_REALTIME.format(exchange, stock_id)
    data = _fetch_json(url)
    if not data or "msgArray" not in data or not data["msgArray"]:
        return None
    m = data["msgArray"][0]

    z = m.get("z")
    price = (
        float(z) if z and z != "-"
        else _mid_price(m)
        or (float(m["o"]) if m.get("o") and m["o"] != "-" else None)
    )
    return {
        "price": price,
        "open": float(m.get("o", 0)) if m.get("o") and m["o"] != "-" else None,
        "high": float(m.get("h", 0)) if m.get("h") and m["h"] != "-" else None,
        "low": float(m.get("l", 0)) if m.get("l") and m["l"] != "-" else None,
        "prev_close": float(m.get("y", 0)) if m.get("y") and m["y"] != "-" else None,
        "name": m.get("n", ""),
        "time": m.get("t", ""),
        "volume": int(m.get("v", 0)) if m.get("v") and m["v"] != "-" else 0,
    }


TWSE_DAY_ALL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"


def _parse_day_all(data: list) -> dict:
    result = {}
    for item in data:
        code = item.get("Code", "")
        close = item.get("ClosingPrice", "")
        change = item.get("Change", "0")
        try:
            p = float(close)
            ch = float(change)
            prev = p - ch
            chg_pct = (ch / prev * 100) if prev else 0
            result[code] = {"price": p, "change": ch, "change_pct": round(chg_pct, 2)}
        except (ValueError, ZeroDivisionError):
            pass
    return result


def _fetch_realtime_batch(codes: list) -> dict:
    if not codes:
        return {}
    batch = "|".join(f"tse_{c}.tw" for c in codes)
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={batch}&json=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
    except Exception:
        return {}

    result = {}
    for m in data.get("msgArray", []):
        code = m.get("c", "")
        z = m.get("z", "-")
        y = m.get("y", "-")
        try:
            price = float(z) if z != "-" else _mid_price(m) or (float(m["o"]) if m.get("o") and m["o"] != "-" else None)
            prev = float(y) if y != "-" else None
            if price and prev:
                chg = price - prev
                chg_pct = chg / prev * 100
                result[code] = {"price": price, "change": round(chg, 2), "change_pct": round(chg_pct, 2)}
        except (ValueError, TypeError):
            pass
    return result


def fetch_all_prices(priority_codes: list = None) -> dict:
    try:
        req = urllib.request.Request(TWSE_DAY_ALL, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
    except Exception:
        return {}

    result = _parse_day_all(data)

    if priority_codes and is_market_open_today():
        realtime = _fetch_realtime_batch(priority_codes)
        result.update(realtime)

    return result


def recent_daily_volatility(stock_id: str, days: int = 5) -> Optional[float]:
    _today = today()
    ranges = []

    for i in range(30):
        d = _today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        url = TWSE_DAILY.format(d.strftime("%Y%m%d"), stock_id)
        data = _fetch_json(url)
        if not data or "data" not in data:
            continue
        for row in data["data"]:
            try:
                high = float(row[4].replace(",", ""))
                low = float(row[5].replace(",", ""))
                close = float(row[6].replace(",", ""))
                pct = (high - low) / close * 100
                ranges.append(pct)
            except (ValueError, IndexError):
                continue
        if len(ranges) >= days:
            break

    if len(ranges) < 2:
        return None
    mean = sum(ranges) / len(ranges)
    var = sum((x - mean) ** 2 for x in ranges) / len(ranges)
    return round(var ** 0.5, 2)
