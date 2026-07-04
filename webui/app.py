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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session

from tw50_rebalance_arb.schedule import quarterly_dates, next_effective_date, is_effective_today
from tw50_rebalance_arb.signal import evaluate
from tw50_rebalance_arb.journal import TradeJournal
from tw50_rebalance_arb.config import STRATEGY, COST
from tw50_rebalance_arb.stocks import lookup_name, get_all_stocks, refresh_stocks
from tw50_rebalance_arb.adjustment import AdjustmentList
from tw50_rebalance_arb.market import current_price, recent_daily_volatility, is_market_open_today

app = Flask(__name__)
app.secret_key = os.urandom(24).hex()


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
}


def _log(msg):
    monitor_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


@app.route("/")
def index():
    today = date.today()
    nxt = next_effective_date(today)
    journal = TradeJournal()
    open_trades = [t for t in journal.trades if t["status"] == "open"]
    return render_template("index.html", today=today, nxt=nxt, open_count=len(open_trades), COST=COST, STRATEGY=STRATEGY,
                           market_open=is_market_open_today())


@app.route("/schedule")
def schedule():
    today = date.today()
    nxt = next_effective_date(today)
    quarters = []
    for y in range(today.year, today.year + 2):
        quarters.extend(quarterly_dates(y))
    return render_template("schedule.html", today=today, quarters=quarters, nxt=nxt)


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
    return render_template("adjust.html", adj=adj, stocks=sorted(get_all_stocks().items()))


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
    _log(f"開始監控 {len(targets)} 檔標的: {', '.join(targets)}")

    def _run():
        try:
            start_dt = datetime.strptime(f"{date.today()} 13:25", "%Y-%m-%d %H:%M")
            end_dt = datetime.strptime(f"{date.today()} 13:30", "%Y-%m-%d %H:%M")
            now = datetime.now()

            if now < start_dt:
                wait_sec = (start_dt - now).total_seconds()
                _log(f"等待 13:25 (約 {int(wait_sec)} 秒)...")
                monitor_state["phase"] = "waiting"
                while datetime.now() < start_dt:
                    if monitor_state["cancel"]:
                        _log("已取消")
                        return
                    time.sleep(1)

            if monitor_state["cancel"]:
                _log("已取消")
                return

            monitor_state["phase"] = "capturing_ref"
            _log("捕捉 13:25 基準價...")
            for sid in monitor_state["targets"]:
                q = current_price(sid)
                z = q.get("z") if q else None
                p = float(z) if z and z != "-" else None
                if p is not None:
                    monitor_state["refs"][sid] = {
                        "price": p,
                        "name": q.get("n") or lookup_name(sid),
                        "prev_close": float(q["y"]) if q.get("y") and q["y"] != "-" else None,
                    }
                    _log(f"  {sid} ({monitor_state['refs'][sid]['name']}): 基準價 {p}")
                time.sleep(0.5)

            missing = [s for s in monitor_state["targets"] if s not in monitor_state["refs"]]
            if missing:
                _log(f"⚠️ 以下股票未取得基準價: {', '.join(missing)}")

            now = datetime.now()
            if now < end_dt:
                wait_sec = (end_dt - now).total_seconds()
                _log(f"等待 13:30 收盤價 (約 {int(wait_sec)} 秒)...")
                monitor_state["phase"] = "waiting_final"
                while datetime.now() < end_dt:
                    if monitor_state["cancel"]:
                        _log("已取消")
                        return
                    time.sleep(1)

            monitor_state["phase"] = "capturing_final"
            _log("捕捉 13:30 收盤價...")
            for sid in monitor_state["targets"]:
                if sid not in monitor_state["refs"]:
                    continue
                q = current_price(sid)
                z_raw = q.get("z") if q else "-"
                final_z = float(z_raw) if z_raw and z_raw != "-" else None
                if final_z is not None:
                    monitor_state["finals"][sid] = final_z
                else:
                    a_val = q.get("a", "") if q else ""
                    b_val = q.get("b", "") if q else ""
                    try:
                        ask = float(a_val.split("_")[0]) if a_val and a_val != "-" else None
                        bid = float(b_val.split("_")[0]) if b_val and b_val != "-" else None
                        if ask and bid:
                            monitor_state["finals"][sid] = round((ask + bid) / 2, 2)
                    except (ValueError, IndexError, TypeError):
                        pass
                _log(f"  {sid}: 收盤價 {monitor_state['finals'].get(sid, '−')}")
                time.sleep(0.5)

            for sid in monitor_state["targets"]:
                if sid not in monitor_state["refs"] or sid not in monitor_state["finals"]:
                    continue
                ref = monitor_state["refs"][sid]
                final_p = monitor_state["finals"][sid]
                deviation = round((final_p - ref["price"]) / ref["price"] * 100, 2)
                hist_vol = recent_daily_volatility(sid, 5) or 0
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


@app.route("/api/monitor/stop", methods=["POST"])
def api_monitor_stop():
    if not monitor_state["running"]:
        return jsonify({"error": "not running"}), 400
    monitor_state["cancel"] = True
    _log("正在停止...")
    return jsonify({"status": "stopped"})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
