import urllib.request
import json
from datetime import date, timedelta
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


def recent_daily_volatility(stock_id: str, days: int = 5) -> Optional[float]:
    today = date.today()
    ranges = []

    for i in range(30):
        d = today - timedelta(days=i)
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
