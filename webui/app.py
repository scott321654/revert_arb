#!/usr/bin/env python3
import sys
import os

os.environ["TZ"] = "Asia/Taipei"
try:
    import time as _time_mod
    _time_mod.tzset()
except AttributeError:
    pass

import json
import time
import threading
from datetime import date, datetime, timedelta
from tw50_rebalance.tzutil import now, today, strptime as tz_strptime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session

from tw50_rebalance.schedule import quarterly_dates, next_effective_date, is_effective_today
from tw50_rebalance.signal import evaluate
from tw50_rebalance.journal import TradeJournal
from tw50_rebalance.config import STRATEGY, COST
from tw50_rebalance.stocks import lookup_name, get_all_stocks, refresh_stocks, auto_compare_tw50, fetch_tw50_holdings
from tw50_rebalance.adjustment import AdjustmentList
from tw50_rebalance.market import current_price, recent_daily_volatility, is_market_open_today, fetch_all_prices, _fetch_realtime_batch, yahoo_5m_price, yahoo_close_price

app = Flask(__name__)
app.secret_key = os.urandom(24).hex()


@app.after_request
def _no_cache(resp):
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


def fmt_pct(value, digits=2):
    if value is None:
        return ""
    return f"{value:+.{digits}f}%"


def fmt(value, digits=2):
    if value is None:
        return ""
    return f"{value:.{digits}f}"


app.jinja_env.filters["pct"] = fmt_pct
app.jinja_env.filters["fmt"] = fmt

monitor_state = {
    "running": False,
    "targets": [],
    "refs": {},
    "finals": {},
    "results": [],
    "phase": "",  # waiting / capturing_ref / waiting_final / capturing_final / done / cancelled
    "log": [],
    "cancel": False,
    "wait_total": 0,
    "wait_remaining": 0,
}


def _log(msg):
    monitor_state["log"].append(f"[{now().strftime('%H:%M:%S')}] {msg}")


@app.route("/")
def index():
    _today = today()
    nxt = next_effective_date(_today)
    journal = TradeJournal()
    open_trades = [t for t in journal.trades if t["status"] == "open"]
    return render_template("index.html", today=_today, nxt=nxt, open_count=len(open_trades), COST=COST, STRATEGY=STRATEGY,
                           market_open=is_market_open_today())


@app.route("/schedule")
def schedule():
    _today = today()
    nxt = next_effective_date(_today)
    quarters = []
    for y in range(_today.year, _today.year + 2):
        quarters.extend(quarterly_dates(y))
    return render_template("schedule.html", today=_today, quarters=quarters, nxt=nxt)


@app.route("/adjust", methods=["GET", "POST"])
def adjust():
    adj = AdjustmentList()
    if request.method == "POST":
        quarter = request.form.get("quarter", "").strip()
        removed = [x.strip() for x in request.form.get("removed", "").split(",") if x.strip()]
        added = [x.strip() for x in request.form.get("added", "").split(",") if x.strip()]
        reweight = [x.strip() for x in request.form.get("reweight", "").split(",") if x.strip()]
        adj.set(quarter=quarter, removed=removed, added=added, reweight=reweight)
        flash("已儲存調整名單", "success")
        return redirect(url_for("adjust"))
    tw50, _ = fetch_tw50_holdings()
    if tw50:
        extra = set(adj.data.get("removed", []) + adj.data.get("added", []) + adj.data.get("reweight", [])) - set(tw50.keys())
        all_stocks = get_all_stocks()
        for code in extra:
            tw50[code] = all_stocks.get(code, code)
        stock_items = sorted(tw50.items())
    else:
        stock_items = sorted(get_all_stocks().items())
    priority = adj.data.get("removed", []) + adj.data.get("added", []) + adj.data.get("reweight", [])
    prices = fetch_all_prices(priority_codes=priority or None)
    return render_template("adjust.html", adj=adj, stocks=stock_items, stock_dict=get_all_stocks(), prices=prices)


@app.route("/check", methods=["GET", "POST"])
def check():
    result = None
    if request.method == "POST":
        stock_id = request.form.get("stock_id", "").strip()
        deviation = request.form.get("deviation", "").strip()
        volatility = request.form.get("volatility", "").strip()
        short_interest = request.form.get("short_interest", "").strip()
        regulated = request.form.get("regulated") == "on"

        if not stock_id or not deviation or not volatility:
            flash("請填入股票代號、尾盤跌幅與波動率", "danger")
            return render_template("check.html", result=None, stocks=sorted(get_all_stocks().items()), STRATEGY=STRATEGY)

        try:
            dev = float(deviation)
            vol = float(volatility)
        except ValueError:
            flash("跌幅與波動率請輸入數字", "danger")
            return render_template("check.html", result=None, stocks=sorted(get_all_stocks().items()), STRATEGY=STRATEGY)

        stock_name = lookup_name(stock_id) or stock_id
        adj_obj = AdjustmentList()
        event = adj_obj.get_event(stock_id) or "被剔除"

        si = float(short_interest) / 100 if short_interest else None

        sig = evaluate(
            stock_id=stock_id,
            stock_name=stock_name,
            event=event,
            price_deviation_pct=dev,
            historical_volatility=vol,
            short_interest_ratio=si,
            regulated=regulated,
            zscore_threshold=STRATEGY["zscore_threshold"],
        )
        result = sig
        return render_template("check.html", result=result, form=request.form, stocks=sorted(get_all_stocks().items()), STRATEGY=STRATEGY)

    return render_template("check.html", result=None, stocks=sorted(get_all_stocks().items()), STRATEGY=STRATEGY)


@app.route("/record_entry", methods=["POST"])
def record_entry():
    stock_id = request.form.get("stock_id")
    stock_name = request.form.get("stock_name")
    event = request.form.get("event")
    deviation = float(request.form.get("deviation"))
    zscore = float(request.form.get("zscore"))
    entry_price = float(request.form.get("entry_price"))
    shares = int(float(request.form.get("shares")) * 1000)

    sig = evaluate(
        stock_id=stock_id,
        stock_name=stock_name,
        event=event,
        price_deviation_pct=deviation,
        historical_volatility=1.0,
        zscore_threshold=0,
    )
    sig.zscore = zscore
    sig.threshold_met = True

    journal = TradeJournal()
    rec = journal.record_entry(sig, entry_price, shares)
    flash(f"已記錄: {stock_id} {shares//1000}張 @ {entry_price}", "success")
    return redirect(url_for("positions"))


@app.route("/positions")
def positions():
    journal = TradeJournal()
    open_trades = [t for t in journal.trades if t["status"] == "open"]
    return render_template("positions.html", trades=open_trades)


@app.route("/exit", methods=["GET", "POST"])
def exit_view():
    journal = TradeJournal()
    open_trades = [t for t in journal.trades if t["status"] == "open"]

    if request.method == "POST":
        stock_id = request.form.get("stock_id")
        exit_price = request.form.get("exit_price")
        note = request.form.get("note", "").strip()
        try:
            ep = float(exit_price)
        except (ValueError, TypeError):
            flash("請輸入有效價格", "danger")
            return redirect(url_for("exit_view"))
        result = journal.record_exit(stock_id, ep, note)
        if result:
            flash(f"已平倉 {stock_id} | 淨報酬: {result['net_return_pct']:+.3f}%", "success")
        else:
            flash("找不到對應持倉", "danger")
        return redirect(url_for("exit_view"))

    return render_template("exit.html", trades=open_trades)


@app.route("/summary")
def summary_view():
    journal = TradeJournal()
    closed = [t for t in journal.trades if t["status"] == "closed"]
    wins = [t for t in closed if t["net_return_pct"] > 0]
    stats = {
        "total": len(journal.trades),
        "closed": len(closed),
        "wins": len(wins),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
        "avg_return": round(sum(t["net_return_pct"] for t in closed) / len(closed), 3) if closed else 0,
        "total_return": round(sum(t["net_return_pct"] for t in closed), 3) if closed else 0,
    }
    return render_template("summary.html", stats=stats, trades=closed)


@app.route("/summary/clear", methods=["POST"])
def summary_clear():
    journal = TradeJournal()
    journal.trades = []
    journal._save()
    flash("已清除所有交易紀錄", "success")
    return redirect(url_for("summary_view"))


@app.route("/monitor")
def monitor():
    adj = AdjustmentList()
    targets = adj.data.get("removed", []) + adj.data.get("reweight", [])
    return render_template("monitor.html", targets=targets, stocks=sorted(get_all_stocks().items()),
                           monitor_state=monitor_state, is_effective=is_effective_today(),
                           market_open=is_market_open_today())


@app.route("/api/fetch_price", methods=["POST"])
def api_fetch_price():
    stock_id = request.json.get("stock_id")
    q = current_price(stock_id)
    if q and q.get("price"):
        return jsonify({"price": q["price"], "name": q.get("name", "")})
    return jsonify({"price": None, "name": ""}), 400


@app.route("/api/monitor/start", methods=["POST"])
def api_monitor_start():
    if monitor_state["running"]:
        return jsonify({"error": "already running"}), 400

    adj = AdjustmentList()
    targets = adj.data.get("removed", []) + adj.data.get("reweight", [])
    if not targets:
        return jsonify({"error": "請先在「調整名單」頁面設定標的"}), 400

    monitor_state["running"] = True
    monitor_state["targets"] = targets
    monitor_state["refs"] = {}
    monitor_state["finals"] = {}
    monitor_state["results"] = []
    monitor_state["phase"] = "capturing_ref"
    monitor_state["log"] = []
    monitor_state["cancel"] = False
    monitor_state["wait_total"] = 0
    monitor_state["wait_remaining"] = 0
    _log(f"開始監控 {len(targets)} 檔標的: {', '.join(targets)}")

    def _run():
        try:
            _now = now()
            if _now.hour < 8:
                ref_date = today() - timedelta(days=1)
                _log(f"凌晨時段，以 {ref_date} 為交易日進行盤後監控...")
            else:
                ref_date = today()
            start_dt = tz_strptime(f"{ref_date} 13:25", "%Y-%m-%d %H:%M")
            end_dt = tz_strptime(f"{ref_date} 13:30", "%Y-%m-%d %H:%M")

            if _now < start_dt:
                wait_sec = int((start_dt - _now).total_seconds())
                _log("等待 13:25 基準價...")
                monitor_state["phase"] = "waiting"
                monitor_state["wait_total"] = wait_sec
                while now() < start_dt:
                    if monitor_state["cancel"]:
                        _log("已取消")
                        return
                    monitor_state["wait_remaining"] = int((start_dt - now()).total_seconds())
                    if monitor_state["wait_remaining"] <= 0:
                        break
                    time.sleep(1)
                monitor_state["wait_total"] = 0
                monitor_state["wait_remaining"] = 0

            if monitor_state["cancel"]:
                _log("已取消")
                return

            monitor_state["phase"] = "capturing_ref"
            past_1325 = now() >= start_dt
            if past_1325:
                _log("已過 13:25，改用 Yahoo 5 分線回溯基準價...")
            else:
                _log("捕捉 13:25 基準價...")
            for sid in monitor_state["targets"]:
                if past_1325:
                    p = yahoo_5m_price(sid, target_date=ref_date.strftime("%Y-%m-%d"))
                    name = lookup_name(sid) or sid
                    prev = None
                    q = current_price(sid)
                    if q:
                        prev = q.get("prev_close")
                        name = q.get("name") or name
                else:
                    q = current_price(sid)
                    p = q.get("price") if q else None
                    name = q.get("name") or lookup_name(sid) if q else lookup_name(sid)
                    prev = q.get("prev_close") if q else None
                if p is not None:
                    monitor_state["refs"][sid] = {
                        "price": p,
                        "name": name,
                        "prev_close": prev,
                    }
                    _log(f"  {sid} ({name}): 基準價 {p}")
                time.sleep(0.5)

            missing = [s for s in monitor_state["targets"] if s not in monitor_state["refs"]]
            if missing:
                _log(f"⚠️ 以下股票未取得基準價: {', '.join(missing)}")

            _now = now()
            if _now < end_dt:
                wait_sec = int((end_dt - _now).total_seconds())
                _log("等待 13:30 收盤價...")
                monitor_state["phase"] = "waiting_final"
                monitor_state["wait_total"] = wait_sec
                while now() < end_dt:
                    if monitor_state["cancel"]:
                        _log("已取消")
                        return
                    monitor_state["wait_remaining"] = int((end_dt - now()).total_seconds())
                    if monitor_state["wait_remaining"] <= 0:
                        break
                    time.sleep(1)
                monitor_state["wait_total"] = 0
                monitor_state["wait_remaining"] = 0

            monitor_state["phase"] = "capturing_final"
            past_1330 = now() >= end_dt
            if past_1330:
                _log("已過 13:30，改用 Yahoo 5 分線回溯收盤價...")
            elif now() < end_dt + timedelta(seconds=30):
                _log("等待收盤搓合結果 (30秒)...")
                time.sleep(30)
                _log("捕捉 13:30 收盤價...")
            else:
                _log("捕捉 13:30 收盤價...")
            for sid in monitor_state["targets"]:
                if sid not in monitor_state["refs"]:
                    continue
                if past_1330:
                    final_p = yahoo_close_price(sid, target_date=ref_date.strftime("%Y-%m-%d"))
                    if final_p is None:
                        q = current_price(sid)
                        final_p = q.get("price") if q else None
                else:
                    q = current_price(sid)
                    final_p = q.get("price") if q else None
                if final_p is not None:
                    monitor_state["finals"][sid] = final_p
                _log(f"  {sid}: 收盤價 {monitor_state['finals'].get(sid, '−')}")
                time.sleep(0.5)

            for sid in monitor_state["targets"]:
                if sid not in monitor_state["refs"] or sid not in monitor_state["finals"]:
                    continue
                ref = monitor_state["refs"][sid]
                final_p = monitor_state["finals"][sid]
                deviation = round((final_p - ref["price"]) / ref["price"] * 100, 2)
                hist_vol = recent_daily_volatility(sid) or 0
                adj_obj = AdjustmentList()
                event = adj_obj.get_event(sid) or "被剔除"
                sig = evaluate(
                    stock_id=sid,
                    stock_name=ref["name"],
                    event=event,
                    price_deviation_pct=deviation,
                    historical_volatility=hist_vol,
                    zscore_threshold=STRATEGY["zscore_threshold"],
                )
                monitor_state["results"].append({
                    "stock_id": sid,
                    "stock_name": ref["name"],
                    "event": event,
                    "ref_price": ref["price"],
                    "final_price": final_p,
                    "deviation": deviation,
                    "volatility": hist_vol,
                    "zscore": sig.zscore,
                    "threshold_met": sig.threshold_met,
                    "actionable": sig.actionable,
                    "notes": sig.notes,
                })
                _log(f"  {sid} {ref['name']}: 偏差 {deviation:+.2f}% Z={sig.zscore:.1f}σ {'✅' if sig.actionable else '❌'}")

            if not monitor_state["cancel"]:
                monitor_state["phase"] = "done"
                _log("監控完成")
        except Exception as e:
            _log(f"錯誤: {e}")
        finally:
            monitor_state["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "started", "targets": targets})


@app.route("/api/monitor/status")
def api_monitor_status():
    return jsonify(monitor_state)


@app.route("/api/refresh_stocks", methods=["POST"])
def api_refresh_stocks():
    result = refresh_stocks()
    if result:
        return jsonify({"status": "ok", "count": len(result)})
    return jsonify({"error": "無法從證交所取得資料"}), 400


@app.route("/api/tw50/compare", methods=["POST"])
def api_tw50_compare():
    try:
        body = request.get_json(silent=True) or {}
        quarter = body.get("quarter", "").strip()
        result = auto_compare_tw50(quarter or None)
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"伺服器錯誤: {e}"}), 500


@app.route("/api/prices", methods=["POST"])
def api_prices():
    codes = (request.json or {}).get("codes", [])
    if not codes or not isinstance(codes, list):
        return jsonify({})
    return jsonify(_fetch_realtime_batch(codes))


@app.route("/api/monitor/stop", methods=["POST"])
def api_monitor_stop():
    if not monitor_state["running"]:
        return jsonify({"error": "not running"}), 400
    monitor_state["cancel"] = True
    _log("正在停止...")
    return jsonify({"status": "stopped"})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
