#!/usr/bin/env python3
"""
台灣50指數成分股調整 — 尾盤均值回歸套利策略

使用方法:
  python3 run.py schedule                          查看近期調整時程
  python3 run.py adjust                            輸入本次調整刪/納入名單
  python3 run.py monitor <stock_id>                從證交所自動拉報價，產生訊號
  python3 run.py check <stock_id> <跌幅%> <波動率%>  手動輸入數據
  python3 run.py exit                              隔日開盤平倉
  python3 run.py summary                           查看績效統計
  python3 run.py positions                         查看目前持倉
"""
import sys
import time
from typing import Optional
from datetime import date, datetime, timedelta

from .schedule import quarterly_dates, next_effective_date, is_effective_today
from .signal import evaluate
from .journal import TradeJournal
from .config import STRATEGY, COST
from .stocks import lookup_name
from .adjustment import AdjustmentList
from .market import current_price, recent_daily_volatility


def cmd_schedule():
    today = date.today()
    print(f"今日日期: {today}")
    print(f"交易成本: {COST}% (雙邊)")
    print(f"策略方向: 只做多超跌股")
    print(f"進場門檻: {STRATEGY['zscore_threshold']}σ")
    print()

    for y in range(today.year, today.year + 2):
        for q in quarterly_dates(y):
            label = "🟢 下次" if q["effective_date"] >= today else "  "
            status = ""
            if q["effective_date"] == today:
                status = " ← 今天!"
            elif q["effective_date"] < today:
                status = " (已過期)"
            elif q == next_effective_date(today):
                status = " ← 下一次"

            print(f"{label} {q['quarter']:>8}  "
                  f"審核日: {q['review_date']}  "
                  f"生效日: {q['effective_date']}{status}")


def cmd_adjust():
    print("=== 輸入本次調整名單 ===")
    quarter = input("季度 (如 2026Q3): ").strip()

    removed = input("被剔除的股票代號 (逗號分隔): ").strip()
    added = input("新納入的股票代號 (逗號分隔): ").strip()
    reweight = input("權重調降的代號 (選填): ").strip()

    def parse(s):
        return [x.strip() for x in s.split(",") if x.strip()]

    adj = AdjustmentList()
    adj.set(
        quarter=quarter,
        removed=parse(removed),
        added=parse(added),
        reweight=parse(reweight),
    )

    print()
    print("✅ 已儲存:")
    print(adj.summary())


def cmd_check():
    today = date.today()

    if len(sys.argv) < 4:
        print("用法: python3 run.py check <股票代號> <尾盤跌幅%> <日內波動率%>")
        print("範例: python3 run.py check 5871 -3.9 1.2")
        return

    stock_id = sys.argv[2].strip()
    try:
        deviation = float(sys.argv[3])
    except ValueError:
        print("跌幅請輸入數字")
        return
    try:
        hist_vol = float(sys.argv[4])
    except ValueError:
        print("波動率請輸入數字")
        return

    stock_name = lookup_name(stock_id)
    if not stock_name:
        stock_name = input(f"未知代號 {stock_id}，請輸入名稱: ").strip()

    adj = AdjustmentList()
    event = adj.get_event(stock_id)

    if not event:
        print()
        print("事件類型:")
        print("  1) 被剔除")
        print("  2) 權重調降")
        print("  3) 被納入 → 忽略 (不做空)")
        choice = input("選擇 (1/2/3): ").strip()
        event = {"1": "被剔除", "2": "權重調降", "3": "被納入"}.get(choice, "")
        if choice == "3":
            print("⛔ 策略不做空，跳過")
            return
        if not event:
            print("無效選擇")
            return
    elif event == "被納入":
        print(f"⛔ {stock_id} 是被納入股，策略不做空，跳過")
        return

    if deviation >= 0:
        print("⛔ 未下跌，不進場")
        return

    short_interest = None
    si = input("融券比率 (選填, Enter跳過): ").strip()
    if si:
        try:
            short_interest = float(si) / 100
        except ValueError:
            pass

    regulated = input("處置股/注意股？(y/n, 預設n): ").strip().lower() == "y"

    sig = evaluate(
        stock_id=stock_id,
        stock_name=stock_name,
        event=event,
        price_deviation_pct=deviation,
        historical_volatility=hist_vol,
        short_interest_ratio=short_interest,
        regulated=regulated,
        zscore_threshold=STRATEGY["zscore_threshold"],
    )

    print()
    print("=" * 50)
    print("📊 訊號評估結果")
    print("=" * 50)
    print(f"股票:    {sig.stock_id} {sig.stock_name}")
    print(f"事件:    {sig.event}")
    print(f"尾盤偏差: {sig.price_deviation_pct:+.2f}%")
    print(f"Z-score: {sig.zscore:.1f}σ (門檻: {STRATEGY['zscore_threshold']}σ)")
    print(f"方向:    {sig.expected_direction}")
    if sig.short_interest_ratio:
        print(f"融券比:  {sig.short_interest_ratio:.1%}")
    print(f"門檻達標: {'✅' if sig.threshold_met else '❌'}")
    print(f"處置股:   {'⚠️ 是' if sig.regulated else '否'}")
    print(f"空單擁擠: {'⚠️ 是' if sig.crowded_warning else '否'}")
    if sig.notes:
        print(f"備註:    {sig.notes}")
    print()

    if sig.actionable:
        print("✅ 建議進場!")
        try:
            entry_price = float(input("你的成交均價: "))
            shares = int(float(input("買進張數: ")) * 1000)
            journal = TradeJournal()
            rec = journal.record_entry(sig, entry_price, shares)
            print(f"✅ 已記錄: {rec['stock_id']} {shares//1000}張 @ {entry_price}")
        except (ValueError, KeyboardInterrupt):
            print("❌ 取消記錄")
    else:
        print("❌ 不符合進場條件，不交易")


def _monitor_single(stock_id: str, has_ref: bool, ref_price=None, ref_name="", prev_close=None, ref_props=None, final_price=None) -> Optional[dict]:
    if ref_props:
        stock_name = ref_props["name"]
        prev_close = ref_props["prev_close"]
    else:
        stock_name = ref_name

    if ref_price is not None and final_price is not None:
        deviation = round((final_price - ref_price) / ref_price * 100, 2)
        day_change = round((final_price - prev_close) / prev_close * 100, 2)
    else:
        deviation = None

    if deviation is None:
        q = current_price(stock_id)
        if not q or q["price"] is None:
            return None
        stock_name = stock_name or q["name"] or lookup_name(stock_id)
        prev_close = prev_close or q["prev_close"]
        deviation = round((q["price"] - prev_close) / prev_close * 100, 2)
        final_price = q["price"]

    adj = AdjustmentList()
    event = adj.get_event(stock_id)
    if not event:
        return None
    if event == "被納入":
        return None

    hist_vol = recent_daily_volatility(stock_id, 5) or 0
    sig = evaluate(
        stock_id=stock_id,
        stock_name=stock_name,
        event=event,
        price_deviation_pct=deviation,
        historical_volatility=hist_vol,
        zscore_threshold=STRATEGY["zscore_threshold"],
    )
    return {
        "stock_id": stock_id,
        "stock_name": stock_name,
        "event": event,
        "ref_price": ref_price,
        "final_price": final_price,
        "deviation": deviation,
        "volatility": hist_vol,
        "zscore": sig.zscore,
        "threshold_met": sig.threshold_met,
        "actionable": sig.actionable,
        "notes": sig.notes,
    }


def cmd_monitor_all():
    adj = AdjustmentList()
    targets = adj.data.get("removed", []) + adj.data.get("reweight", [])
    if not targets:
        print("❌ adjustment.json 中沒有被剔除或權重調降的股票")
        print("   請先執行: python3 run.py adjust")
        return

    print(f"📋 將監控 {len(targets)} 檔標的: {', '.join(targets)}")
    print()

    entry_start, entry_end = STRATEGY["entry_window"]
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    start_dt = datetime.strptime(f"{today_str} {entry_start}", "%Y-%m-%d %H:%M")
    end_dt = datetime.strptime(f"{today_str} {entry_end}", "%Y-%m-%d %H:%M")
    poll_start = start_dt.replace(second=0) - timedelta(seconds=5)

    if now < poll_start:
        last_bar = ""
        while datetime.now() < poll_start:
            remaining = int((poll_start - datetime.now()).total_seconds())
            h, r = divmod(remaining, 3600)
            m, s = divmod(r, 60)
            bar = f"\r⏳ 等待尾盤窗口  {h:02d}:{m:02d}:{s:02d}"
            if bar != last_bar:
                print(bar, end="", flush=True)
                last_bar = bar
            time.sleep(1)
        print()

    has_ref = datetime.now() < start_dt.replace(second=0)
    if has_ref:
        print(f"📡 批次捕捉 {len(targets)} 檔 13:25 前最後成交價...")
        deadline_13_25 = start_dt.replace(second=0)
        while datetime.now() < deadline_13_25:
            for sid in targets:
                if sid not in refs:
                    q = current_price(sid)
                    z = q.get("z") if q else None
                    p = float(z) if z and z != "-" else None
                    if p is not None:
                        refs[sid] = {
                            "price": p,
                            "name": q.get("n") or lookup_name(sid),
                            "prev_close": float(q["y"]) if q.get("y") and q["y"] != "-" else None,
                        }
                        done = len(refs)
                        print(f"\r   {sid}: {p}  ({done}/{len(targets)})", end="", flush=True)
            time.sleep(1)
        print()

        missing = [s for s in targets if s not in refs]
        if missing:
            print(f"⚠️  以下股票未取得基準價: {', '.join(missing)}")
            targets = [s for s in targets if s in refs]

        remaining = (end_dt - datetime.now()).total_seconds()
        if remaining > 0:
            print(f"⏳ 等待 13:30 收盤價，約再等 {remaining:.0f} 秒...")
            time.sleep(remaining)

        print(f"📡 批次查詢 {len(targets)} 檔 13:30 收盤價...")
        finals = {}
        for sid in targets:
            q = current_price(sid)
            z_raw = q.get("z") if q else "-"
            final_z = float(z_raw) if z_raw and z_raw != "-" else None
            if final_z is not None:
                finals[sid] = final_z
            else:
                a = q.get("a", "") if q else ""
                b = q.get("b", "") if q else ""
                try:
                    ask = float(a.split("_")[0]) if a and a != "-" else None
                    bid = float(b.split("_")[0]) if b and b != "-" else None
                    if ask and bid:
                        finals[sid] = round((ask + bid) / 2, 2)
                except (ValueError, IndexError, TypeError):
                    pass
            print(f"\r   {sid}: {finals.get(sid, '−')}  ({list(finals.keys()).index(sid)+1}/{len(targets)})", end="", flush=True)
        print()
    else:
        finals = {}
        for sid in targets:
            q = current_price(sid)
            if q and q["price"]:
                finals[sid] = q["price"]
                print(f"\r   {sid}: {q['price']}", end="", flush=True)
        print()

    results = []
    for sid in targets:
        r = _monitor_single(
            sid,
            has_ref,
            ref_price=refs.get(sid, {}).get("price") if has_ref else None,
            ref_props=refs.get(sid) if has_ref else None,
            final_price=finals.get(sid),
        )
        if r:
            results.append(r)

    if not results:
        print("\n❌ 沒有符合條件的標的")
        return

    print()
    print("=" * 70)
    label = "尾盤5分鐘偏離度" if has_ref else "今日漲跌"
    print(f"{'股票':<10} {'事件':<8} {'基準':>8} {'收盤':>8} {label:<12} {'波動率':>6} {'Z-score':>8}  結果")
    print("=" * 70)
    for r in results:
        ref_str = f"{r['ref_price']:.2f}" if r["ref_price"] else "−"
        ok = "✅" if r["actionable"] else "❌"
        print(f"{r['stock_id']:<6} {r['stock_name']:<4} {r['event']:<8} {ref_str:>8} {r['final_price']:>8.2f} {r['deviation']:>+7.2f}%  {r['volatility']:>5.2f}%  {r['zscore']:>5.1f}σ  {ok} {r['notes']}")
    print("=" * 70)
    actionable = [r for r in results if r["actionable"]]
    if actionable:
        print(f"\n✅ 建議進場: {' '.join(r['stock_id'] for r in actionable)}")
        print("   請個別執行 python3 run.py monitor <代號> 來記錄交易")


def cmd_monitor():
    if len(sys.argv) < 3:
        print("用法: python3 run.py monitor <股票代號>")
        print("  或: python3 run.py monitor all    # 批次掃描所有剔除/調降股")
        return

    stock_id = sys.argv[2].strip()
    if stock_id == "all":
        cmd_monitor_all()
        return

    entry_start, entry_end = STRATEGY["entry_window"]
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    start_dt = datetime.strptime(f"{today_str} {entry_start}", "%Y-%m-%d %H:%M")
    end_dt = datetime.strptime(f"{today_str} {entry_end}", "%Y-%m-%d %H:%M")

    poll_start = start_dt.replace(second=0) - timedelta(seconds=10)
    if now < poll_start:
        last_bar = ""
        while datetime.now() < poll_start:
            remaining = int((poll_start - datetime.now()).total_seconds())
            h, r = divmod(remaining, 3600)
            m, s = divmod(r, 60)
            bar = f"\r⏳ 等待尾盤窗口  {h:02d}:{m:02d}:{s:02d}"
            if bar != last_bar:
                print(bar, end="", flush=True)
                last_bar = bar
            time.sleep(1)
        print()

    has_ref = datetime.now() < start_dt.replace(second=0)
    if has_ref:
        print(f"📡 持續捕捉 {stock_id} 13:25 前最後一筆成交價...")
        ref_price = None
        last_print = ""
        deadline_13_25 = start_dt.replace(second=0)
        while datetime.now() < deadline_13_25:
            q = current_price(stock_id)
            z = q.get("z") if q else None
            p = float(z) if z and z != "-" else None
            if p is not None:
                ref_price = p
                stock_name = q["name"] or lookup_name(stock_id)
                prev_close = q["prev_close"]
            now_str = datetime.now().strftime("%H:%M:%S")
            msg = f"\r   {now_str}  最新價: {p or '−':>8}   基準價: {ref_price or '−'}"
            if msg != last_print:
                print(msg, end="", flush=True)
                last_print = msg
            time.sleep(1)

        if ref_price is None:
            print("\n❌ 無法在13:25前取得成交價")
            return
        print(f"\n✅ 13:25 基準價: {ref_price}")

        remaining = (end_dt - datetime.now()).total_seconds()
        if remaining > 0:
            print(f"⏳ 等待 13:30 收盤價，約再等 {remaining:.0f} 秒...")
            time.sleep(remaining)

        print(f"📡 查詢 {stock_id} 13:30 收盤價...")
        final_quote = current_price(stock_id)
        z_raw = final_quote.get("z") if final_quote else "-"
        final_z = float(z_raw) if z_raw and z_raw != "-" else None
        if final_z is not None:
            final_price = final_z
        else:
            a = final_quote.get("a", "") if final_quote else ""
            b = final_quote.get("b", "") if final_quote else ""
            try:
                ask = float(a.split("_")[0]) if a and a != "-" else None
                bid = float(b.split("_")[0]) if b and b != "-" else None
                if ask and bid:
                    final_price = round((ask + bid) / 2, 2)
                else:
                    print("❌ 無法取得13:30收盤價")
                    return
            except (ValueError, IndexError, TypeError):
                print("❌ 無法取得13:30收盤價")
                return

        day_change = round((final_price - prev_close) / prev_close * 100, 2)
        deviation = round((final_price - ref_price) / ref_price * 100, 2)

        print(f"   昨收: {prev_close}")
        print(f"   今開: {final_quote.get('o', '')}")
        print(f"   13:25 基準: {ref_price}")
        print(f"   13:30 收盤: {final_price}")
        print(f"   尾盤5分鐘偏離度: {deviation:+.2f}%")
        print(f"   今日漲跌(對昨收): {day_change:+.2f}%")
        print()
    else:
        print(f"⚠️  已過 13:25，無法計算尾盤5分鐘偏離度")
        quote = current_price(stock_id)
        if not quote or quote["price"] is None:
            print("❌ 無法取得報價")
            return
        final_price = quote["price"]
        stock_name = quote["name"] or lookup_name(stock_id)
        prev_close = quote["prev_close"]
        deviation = round((final_price - prev_close) / prev_close * 100, 2)
        print(f"✅ {stock_id} {stock_name}")
        print(f"   現價: {final_price}  昨收: {prev_close}")
        print(f"   今日漲跌: {deviation:+.2f}% (非尾盤5分鐘)")
        print()

    label = "尾盤" if has_ref else "今日"
    if deviation >= 0:
        print(f"⚠️  {label}未下跌 (偏離度 {deviation:+.2f}%)，不符合超跌條件")
        override = input(f"   仍想手動輸入{label}跌幅？(輸入負值, Enter跳過): ").strip()
        if override:
            try:
                deviation = float(override)
            except ValueError:
                print("⛔ 跳過")
                return
        else:
            print("⛔ 跳過")
            return
    else:
        print(f"   {label}下跌 {deviation:.2f}%，符合超跌方向")
        override = input(f"   可手動修正偏離度 (Enter = 沿用 {deviation}%): ").strip()
        if override:
            try:
                deviation = float(override)
            except ValueError:
                pass
        print(f"   採用偏離度: {deviation:+.2f}%")

    adj = AdjustmentList()
    event = adj.get_event(stock_id)
    if not event:
        print()
        print("事件類型:")
        print("  1) 被剔除")
        print("  2) 權重調降")
        choice = input("選擇 (1/2): ").strip()
        event = {"1": "被剔除", "2": "權重調降"}.get(choice, "")
        if not event:
            print("無效選擇")
            return
    elif event == "被納入":
        print(f"⛔ {stock_id} 是被納入股，不做空")
        return

    print()
    print("📡 正在計算近5日日內波動率...")
    hist_vol = recent_daily_volatility(stock_id, 5)
    if hist_vol:
        print(f"   波動率: {hist_vol}%")
    else:
        hist_vol_str = input("   無法自動計算，請手動輸入波動率(%): ").strip()
        try:
            hist_vol = float(hist_vol_str)
        except ValueError:
            print("❌ 無效")
            return

    short_interest = None
    si = input("融券比率 (選填, Enter跳過): ").strip()
    if si:
        try:
            short_interest = float(si) / 100
        except ValueError:
            pass

    regulated = input("處置股/注意股？(y/n, 預設n): ").strip().lower() == "y"

    sig = evaluate(
        stock_id=stock_id,
        stock_name=stock_name,
        event=event,
        price_deviation_pct=deviation,
        historical_volatility=hist_vol,
        short_interest_ratio=short_interest,
        regulated=regulated,
        zscore_threshold=STRATEGY["zscore_threshold"],
    )

    print()
    print("=" * 50)
    print("📊 訊號評估結果")
    print("=" * 50)
    print(f"股票:    {sig.stock_id} {sig.stock_name}")
    print(f"事件:    {sig.event}")
    print(f"尾盤偏差: {sig.price_deviation_pct:+.2f}%")
    print(f"波動率:   {hist_vol}%")
    print(f"Z-score: {sig.zscore:.1f}σ (門檻: {STRATEGY['zscore_threshold']}σ)")
    print(f"方向:    {sig.expected_direction}")
    if sig.short_interest_ratio:
        print(f"融券比:  {sig.short_interest_ratio:.1%}")
    print(f"門檻達標: {'✅' if sig.threshold_met else '❌'}")
    print(f"處置股:   {'⚠️ 是' if sig.regulated else '否'}")
    print(f"空單擁擠: {'⚠️ 是' if sig.crowded_warning else '否'}")
    if sig.notes:
        print(f"備註:    {sig.notes}")
    print()

    if sig.actionable:
        print("✅ 建議進場!")
        try:
            entry_price = float(input("你的成交均價: "))
            shares = int(float(input("買進張數: ")) * 1000)
            journal = TradeJournal()
            rec = journal.record_entry(sig, entry_price, shares)
            print(f"✅ 已記錄: {rec['stock_id']} {shares//1000}張 @ {entry_price}")
        except (ValueError, KeyboardInterrupt):
            print("❌ 取消記錄")
    else:
        print("❌ 不符合進場條件，不交易")


def cmd_exit():
    journal = TradeJournal()
    journal.print_open()
    stock_id = input("平倉股票代號: ").strip()
    try:
        exit_price = float(input("出場均價: "))
    except ValueError:
        print("請輸入數字")
        return
    note = input("備註(選填): ").strip()
    result = journal.record_exit(stock_id, exit_price, note)
    if result:
        print(f"✅ 已平倉 {result['stock_id']} | "
              f"毛報酬: {result['gross_return_pct']:+.3f}% | "
              f"淨報酬: {result['net_return_pct']:+.3f}%")
    else:
        print("❌ 找不到對應的持倉")


def cmd_summary():
    journal = TradeJournal()
    print(journal.summary())


def cmd_positions():
    journal = TradeJournal()
    journal.print_open()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    handlers = {
        "schedule": cmd_schedule,
        "adjust": cmd_adjust,
        "monitor": cmd_monitor,
        "check": cmd_check,
        "exit": cmd_exit,
        "summary": cmd_summary,
        "positions": cmd_positions,
    }
    fn = handlers.get(cmd)
    if fn is None:
        print(f"未知指令: {cmd}")
        print(__doc__)
        sys.exit(1)
    fn()


if __name__ == "__main__":
    main()
