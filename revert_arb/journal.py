import json
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .signal import Signal
from .config import COST


class TradeJournal:
    def __init__(self, path: str = "trades.json"):
        self.path = Path(path)
        self.trades = []
        self._load()

    def _load(self):
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                self.trades = json.load(f)

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.trades, f, ensure_ascii=False, indent=2)

    def record_entry(self, signal: Signal, entry_price: float, shares: int):
        record = {
            "stock_id": signal.stock_id,
            "stock_name": signal.stock_name,
            "event": signal.event,
            "entry_date": str(date.today()),
            "entry_time": str(datetime.now().strftime("%H:%M")),
            "entry_price": entry_price,
            "shares": shares,
            "amount": round(entry_price * shares, 0),
            "deviation_pct": signal.price_deviation_pct,
            "zscore": signal.zscore,
            "status": "open",
        }
        self.trades.append(record)
        self._save()
        return record

    def record_exit(self, stock_id: str, exit_price: float, note: str = ""):
        for t in reversed(self.trades):
            if t["stock_id"] == stock_id and t["status"] == "open":
                entry = t["entry_price"]
                gross_ret = round((exit_price - entry) / entry * 100, 3)
                net_ret = round(gross_ret - COST, 3)
                t.update({
                    "exit_price": exit_price,
                    "exit_date": str(date.today()),
                    "exit_time": str(datetime.now().strftime("%H:%M")),
                    "gross_return_pct": gross_ret,
                    "net_return_pct": net_ret,
                    "cost_pct": COST,
                    "status": "closed",
                    "note": note,
                })
                self._save()
                return t
        return None

    def summary(self) -> str:
        closed = [t for t in self.trades if t["status"] == "closed"]
        wins = [t for t in closed if t["net_return_pct"] > 0]

        lines = [
            "=== 交易績效統計 ===",
            f"總交易次數: {len(self.trades)}",
            f"已平倉: {len(closed)}",
            f"獲利次數: {len(wins)}",
        ]
        if closed:
            rets = [t["net_return_pct"] for t in closed]
            lines.append(f"勝率: {len(wins) / len(closed) * 100:.1f}%")
            lines.append(f"平均淨報酬: {sum(rets) / len(rets):+.3f}%")
            lines.append(f"累積淨報酬: {sum(rets):+.3f}%")

        return "\n".join(lines)

    def print_open(self):
        open_trades = [t for t in self.trades if t["status"] == "open"]
        if not open_trades:
            print("目前無持倉")
            return
        print("=== 目前持倉 ===")
        for t in open_trades:
            print(f"{t['stock_id']} {t['stock_name']} | "
                  f"入場: {t['entry_price']} | 張數: {t['shares']}")
