import json
from pathlib import Path
from typing import Optional


_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "adjustment.json"


class AdjustmentList:
    def __init__(self, path: str = None):
        self.path = Path(path) if path else _DEFAULT_PATH
        self.data = {"quarter": "", "removed": [], "added": [], "reweight": []}
        self._load()

    def _load(self):
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def set(self, quarter: str, removed: list, added: list, reweight: list = None):
        self.data = {
            "quarter": quarter,
            "removed": removed,
            "added": added,
            "reweight": reweight or [],
        }
        self._save()

    def get_event(self, stock_id: str) -> Optional[str]:
        if stock_id in self.data["removed"]:
            return "被剔除"
        if stock_id in self.data["added"]:
            return "被納入"
        if stock_id in self.data["reweight"]:
            return "權重調降"
        return None

    def has(self, stock_id: str) -> bool:
        return self.get_event(stock_id) is not None

    def summary(self) -> str:
        d = self.data
        if not d["quarter"]:
            return "尚未設定本次調整名單"
        lines = [
            f"季度: {d['quarter']}",
            f"剔除 ({len(d['removed'])}): {', '.join(d['removed']) or '無'}",
            f"納入 ({len(d['added'])}): {', '.join(d['added']) or '無'}",
        ]
        if d["reweight"]:
            lines.append(f"權重調降 ({len(d['reweight'])}): {', '.join(d['reweight'])}")
        return "\n".join(lines)
