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
from datetime import date, datetime

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


def cmd_monitor():
    if len(sys.argv) < 3:
        print("用法: python3 run.py monitor <股票代號>")
        print("範例: python3 run.py monitor 5871")
        return

    stock_id = sys.argv[2].strip()

    entry_start, entry_end = STRATEGY["entry_window"]
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    start_dt = datetime.strptime(f"{today_str} {entry_start}", "%Y-%m-%d %H:%M")
    end_dt = datetime.strptime(f"{today_str} {entry_end}", "%Y-%m-%d %H:%M")

    if now < start_dt:
        wait_min = (start_dt - now).total_seconds() / 60
        print(f"⏳ 等待進場窗口 ({entry_start}~{entry_end})，約再等 {wait_min:.0f} 分鐘...")
        while datetime.now() < start_dt:
            time.sleep(5)
        print("⏰ 進場窗口到了！")
    elif now > end_dt:
        print(f"⚠️  已過進場窗口 ({entry_start}~{entry_end})，資料可能已非尾盤報價")

    print(f"📡 正在查詢 {stock_id} 13:25 基準價...")
    ref_quote = current_price(stock_id)
    if not ref_quote or ref_quote["price"] is None:
        print("❌ 無法取得13:25基準報價")
        return
    ref_price = ref_quote["price"]
    stock_name = ref_quote["name"] or lookup_name(stock_id)
    print(f"✅ 13:25 基準價: {ref_price}")
    print(f"   昨收: {ref_quote['prev_close']}")
    print()

    now2 = datetime.now()
    if now2 < end_dt:
        remaining = (end_dt - now2).total_seconds()
        if remaining > 0:
            print(f"⏳ 等待 13:30 收盤價，約再等 {remaining:.0f} 秒...")
            time.sleep(remaining)

    print(f"📡 查詢 {stock_id} 13:30 收盤價...")
    final_quote = current_price(stock_id)
    if not final_quote or final_quote["price"] is None:
        print("❌ 無法取得13:30收盤報價")
        return
    final_price = final_quote["price"]

    day_change = round((final_price - ref_quote["prev_close"]) / ref_quote["prev_close"] * 100, 2)
    deviation = round((final_price - ref_price) / ref_price * 100, 2)

    print(f"✅ {stock_id} {stock_name}")
    print(f"   13:25 基準: {ref_price}")
    print(f"   13:30 收盤: {final_price}")
    print(f"   尾盤5分鐘偏離度: {deviation:+.2f}%")
    print(f"   今日漲跌(對昨收): {day_change:+.2f}%")
    print()

    if deviation >= 0:
        print(f"⚠️  尾盤未下跌 (偏離度 {deviation:+.2f}%)，不符合超跌條件")
        override = input("   仍想手動輸入尾盤跌幅？(輸入負值, Enter跳過): ").strip()
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
        print(f"   尾盤下跌 {deviation:.2f}%，符合超跌方向")
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
