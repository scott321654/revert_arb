import json
import os
import urllib.request
from typing import Optional

TWSE_ALL_STOCKS = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
STOCK_CACHE = "stock_names.json"

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
