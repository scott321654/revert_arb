import json
import math
import os
import re
import urllib.request
from datetime import date
from .tzutil import today
from typing import Optional

TWSE_ALL_STOCKS = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
STOCK_CACHE = "stock_names.json"

TW50_SOURCES = [
    "https://cdn.jsdelivr.net/gh/tbdavid2019/stock-index-api@main/data/fund_0050.json",
    "https://raw.githubusercontent.com/tbdavid2019/stock-index-api/main/data/fund_0050.json",
]
TW50_ETFINFO = "https://www.etfinfo.tw/etf/0050/holdings"
TW50_SNAPSHOT_FILE = os.path.join(os.path.dirname(__file__), "tw50_snapshots.json")

FALLBACK_STOCKS = {
    "2330": "台積電", "2317": "鴻海", "2454": "聯發科", "2303": "聯電",
    "2382": "廣達", "2357": "華碩", "2308": "台達電", "2881": "富邦金",
    "2882": "國泰金", "2891": "中信金", "2886": "兆豐金", "2885": "元大金",
    "2884": "玉山金", "5880": "合庫金", "2892": "第一金", "1301": "台塑",
    "1303": "南亞", "1326": "台化", "2002": "中鋼", "2412": "中華電",
    "3008": "大立光", "3711": "日月光投控", "8046": "南電", "3037": "欣興",
    "3665": "貿聯-KY", "5871": "中租-KY", "5876": "上海商銀", "2408": "南亞科",
    "2603": "長榮", "2609": "陽明", "2618": "長榮航", "2610": "華航",
    "2207": "和泰車", "3231": "緯創", "2356": "英業達", "2376": "技嘉",
    "2377": "微星", "4938": "和碩", "2383": "台光電", "2368": "金像電",
    "3034": "聯詠", "2458": "義隆", "3443": "創意", "3532": "台勝科",
    "6415": "矽力*-KY", "6669": "緯穎", "2301": "光寶科", "2327": "國巨",
    "2347": "聯強", "2395": "研華", "2409": "友達", "3481": "群創",
    "4904": "遠傳", "3045": "台灣大", "8454": "富邦媒",
}


def _fetch_json(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=5)
        return json.loads(resp.read())
    except Exception:
        return None


def get_all_stocks():
    cache_path = os.path.join(os.path.dirname(__file__), STOCK_CACHE)
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)

    data = _fetch_json(TWSE_ALL_STOCKS)
    if data and isinstance(data, list):
        result = {s["Code"]: s["Name"] for s in data if s.get("Code") and s.get("Name")}
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result

    return dict(FALLBACK_STOCKS)


def refresh_stocks():
    cache_path = os.path.join(os.path.dirname(__file__), STOCK_CACHE)
    data = _fetch_json(TWSE_ALL_STOCKS)
    if data and isinstance(data, list):
        result = {s["Code"]: s["Name"] for s in data if s.get("Code") and s.get("Name")}
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result
    return None


def lookup_name(stock_id):
    all_stocks = get_all_stocks()
    return all_stocks.get(stock_id, "")


def _quarter_label(d: date = None) -> str:
    if d is None:
        d = today()
    return f"{d.year}Q{math.ceil(d.month / 3)}"


def _prev_quarter_label(d: date = None, from_label: str = None) -> str:
    if from_label:
        parts = from_label.split("Q")
        if len(parts) == 2:
            y, qn = int(parts[0]), int(parts[1])
            if qn == 1:
                return f"{y - 1}Q4"
            return f"{y}Q{qn - 1}"
    if d is None:
        d = today()
    q = math.ceil(d.month / 3)
    if q == 1:
        return f"{d.year - 1}Q4"
    return f"{d.year}Q{q - 1}"


def _fetch_from_etfinfo() -> Optional[dict]:
    try:
        req = urllib.request.Request(TW50_ETFINFO, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
        resp = urllib.request.urlopen(req, timeout=15)
        html = resp.read().decode("utf-8")
        m = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if not m:
            return None
        nuxt = json.loads(m.group(1))
        for item in nuxt:
            if isinstance(item, dict) and "stocks" in item:
                stocks = nuxt[item["stocks"]]
                result = {}
                for ref in stocks:
                    s = nuxt[ref]
                    code = nuxt[s["code"]]
                    name = nuxt[s["name"]]
                    result[code] = name
                return result
    except Exception:
        return None


def fetch_tw50_holdings() -> tuple:
    result = _fetch_from_etfinfo()
    if result:
        return result, None

    errors = []
    for url in TW50_SOURCES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            if isinstance(data, dict) and data:
                return {k: (v if isinstance(v, str) else v.get("name", k)) for k, v in data.items()}, None
            if isinstance(data, list) and data:
                first = data[0]
                if isinstance(first, dict) and "code" in first:
                    return {s["code"]: s.get("name", "") for s in data}, None
            errors.append(f"{url}: 格式不符")
        except Exception as e:
            reason = str(e) or type(e).__name__
            errors.append(f"{url}: {reason}")
    return None, "；".join(errors)


def _load_all_snapshots() -> dict:
    if os.path.exists(TW50_SNAPSHOT_FILE):
        try:
            with open(TW50_SNAPSHOT_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_all_snapshots(snapshots: dict):
    with open(TW50_SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshots, f, ensure_ascii=False, indent=2)


def save_tw50_snapshot(holdings: dict, label: str = None):
    if label is None:
        label = _quarter_label()
    snapshots = _load_all_snapshots()
    snapshots[label] = holdings
    _save_all_snapshots(snapshots)


def load_tw50_snapshot(label: str) -> Optional[dict]:
    snapshots = _load_all_snapshots()
    return snapshots.get(label)


def get_latest_tw50_snapshot_label() -> Optional[str]:
    snapshots = _load_all_snapshots()
    labels = sorted(snapshots.keys(), reverse=True)
    return labels[0] if labels else None


GIT_COMMITS_API = "https://api.github.com/repos/tbdavid2019/stock-index-api/commits?path=data/fund_0050.json&per_page=2"


def _fetch_prev_from_git() -> Optional[dict]:
    try:
        req = urllib.request.Request(GIT_COMMITS_API, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        commits = json.loads(resp.read())
        if isinstance(commits, list) and len(commits) >= 2:
            sha = commits[1]["sha"]
            url = f"https://raw.githubusercontent.com/tbdavid2019/stock-index-api/{sha}/data/fund_0050.json"
            req2 = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp2 = urllib.request.urlopen(req2, timeout=10)
            raw = json.loads(resp2.read())
            return {k: (v if isinstance(v, str) else v.get("name", k)) for k, v in raw.items()}
    except Exception:
        return None


def auto_compare_tw50(quarter_label: str = None) -> dict:
    if quarter_label is None:
        quarter_label = _quarter_label()

    current, err = fetch_tw50_holdings()
    if not current:
        return {"error": f"無法取得 0050 持股資料：{err}"}

    data_quarter = _prev_quarter_label()
    compare_quarter = _prev_quarter_label(from_label=data_quarter)

    previous = load_tw50_snapshot(compare_quarter) or _fetch_prev_from_git()

    save_tw50_snapshot(current, data_quarter)

    if not previous:
        return {
            "data_quarter": data_quarter,
            "compare_quarter": compare_quarter,
            "current_count": len(current),
            "removed": [],
            "added": [],
            "note": f"已儲存 {data_quarter} 快照，但無法取得上一版歷史資料比對。",
        }

    current_set = set(current.keys())
    previous_set = set(previous.keys())

    removed = sorted(previous_set - current_set)
    added = sorted(current_set - previous_set)

    result = {
        "data_quarter": data_quarter,
        "compare_quarter": compare_quarter,
        "current_count": len(current),
        "prev_count": len(previous),
        "removed": removed,
        "added": added,
    }
    if not removed and not added:
        result["note"] = "本次成分股無變動"
    return result
