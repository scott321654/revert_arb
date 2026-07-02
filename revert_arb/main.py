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
from datetime import date

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
    print(f"📡 正在從證交所查詢 {stock_id} 即時報價...")

    quote = current_price(stock_id)
    if not quote or quote["price"] is None:
        print("❌ 無法取得報價，請改用 python3 run.py check 手動輸入")
        return

    stock_name = quote["name"] or lookup_name(stock_id)
    print(f"✅ {stock_id} {stock_name}")
    print(f"   現價: {quote['price']}")
    print(f"   昨收: {quote['prev_close']}")
    print(f"   今日: 開 {quote['open']} 高 {quote['high']} 低 {quote['low']}")
    print()

    day_change = round((quote["price"] - quote["prev_close"]) / quote["prev_close"] * 100, 2)
    print(f"📊 今日漲跌: {day_change:+.2f}%")
    print()

    deviation = day_change
    if deviation < 0 and abs(deviation) > 0.5:
        print(f"   今日收跌 {deviation:.2f}%，符合超跌方向")
        override = input(f"   尾盤5分鐘偏離度可手動修正 (Enter = 沿用 {deviation}%): ").strip()
        if override:
            try:
                deviation = float(override)
            except ValueError:
                pass
        print(f"   採用偏離度: {deviation:+.2f}%")
    elif deviation >= 0:
        print(f"⚠️  今日收漲，不符合超跌條件 (偏離度 {deviation:+.2f}%)")
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
