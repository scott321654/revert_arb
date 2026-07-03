from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Signal:
    stock_id: str
    stock_name: str
    event: str
    expected_direction: str
    price_deviation_pct: float
    zscore: float
    threshold_met: bool
    short_interest_ratio: Optional[float] = None
    crowded_warning: bool = False
    regulated: bool = False
    notes: str = ""

    @property
    def actionable(self) -> bool:
        if self.regulated:
            return False
        if self.crowded_warning:
            return False
        if not self.threshold_met:
            return False
        if self.expected_direction != "long":
            return False
        return True


def evaluate(
    stock_id: str,
    stock_name: str,
    event: str,
    price_deviation_pct: float,
    historical_volatility: float,
    short_interest_ratio: float = None,
    regulated: bool = False,
    zscore_threshold: float = 2.5,
) -> Signal:

    zscore = abs(price_deviation_pct) / historical_volatility if historical_volatility > 0 else 0
    threshold_met = zscore >= zscore_threshold
    direction = "long" if price_deviation_pct < 0 else "short"

    crowded = False
    if short_interest_ratio is not None and short_interest_ratio > 0.25:
        crowded = True

    notes_parts = []
    if not threshold_met:
        notes_parts.append(f"偏差{zscore:.1f}σ < 門檻{zscore_threshold}σ")
    if regulated:
        notes_parts.append("處置股/注意股 → 跳過")
    if crowded:
        notes_parts.append(f"空單擁擠({short_interest_ratio:.0%}) → 跳過")

    return Signal(
        stock_id=stock_id,
        stock_name=stock_name,
        event=event,
        expected_direction=direction,
        price_deviation_pct=price_deviation_pct,
        zscore=round(zscore, 2),
        threshold_met=threshold_met,
        short_interest_ratio=short_interest_ratio,
        crowded_warning=crowded,
        regulated=regulated,
        notes="; ".join(notes_parts),
    )
