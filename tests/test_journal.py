import pytest

from tw50_rebalance.journal import TradeJournal
from tw50_rebalance.signal import Signal


@pytest.fixture
def signal():
    return Signal(
        stock_id="2330",
        stock_name="台積電",
        event="被剔除",
        expected_direction="long",
        price_deviation_pct=-5.0,
        zscore=2.5,
        threshold_met=True,
    )


class TestRecordEntry:
    def test_creates_open_record(self, tmp_path, signal):
        j = TradeJournal(str(tmp_path / "trades.json"))
        rec = j.record_entry(signal, 100.0, 10)

        assert rec["stock_id"] == "2330"
        assert rec["stock_name"] == "台積電"
        assert rec["entry_price"] == 100.0
        assert rec["shares"] == 10
        assert rec["amount"] == 1000.0
        assert rec["status"] == "open"
        assert rec["deviation_pct"] == -5.0
        assert rec["zscore"] == 2.5

    def test_persists_entry(self, tmp_path, signal):
        p = tmp_path / "trades.json"
        j = TradeJournal(str(p))
        j.record_entry(signal, 100.0, 10)

        j2 = TradeJournal(str(p))
        assert len(j2.trades) == 1
        assert j2.trades[0]["stock_id"] == "2330"


class TestRecordExit:
    def test_closes_open_trade(self, tmp_path, signal):
        j = TradeJournal(str(tmp_path / "trades.json"))
        j.record_entry(signal, 100.0, 10)
        result = j.record_exit("2330", 110.0)

        assert result is not None
        assert result["exit_price"] == 110.0
        assert result["status"] == "closed"
        assert result["gross_return_pct"] == 10.0
        assert result["net_return_pct"] == pytest.approx(9.586, abs=0.001)
        assert result["cost_pct"] == 0.414

    def test_closes_latest_entry_only(self, tmp_path):
        j = TradeJournal(str(tmp_path / "trades.json"))
        s1 = Signal("2330", "台積電", "被剔除", "long", -5.0, 2.5, True)
        s2 = Signal("2330", "台積電", "被剔除", "long", -3.0, 1.5, False)
        j.record_entry(s1, 100.0, 10)
        j.record_entry(s2, 95.0, 5)

        result = j.record_exit("2330", 100.0)
        assert result["entry_price"] == 95.0  # closes the latest
        assert result["gross_return_pct"] == pytest.approx(5.263, abs=0.001)

    def test_loss_calculation(self, tmp_path, signal):
        j = TradeJournal(str(tmp_path / "trades.json"))
        j.record_entry(signal, 100.0, 10)
        result = j.record_exit("2330", 90.0)

        assert result["gross_return_pct"] == -10.0
        assert result["net_return_pct"] == pytest.approx(-10.414, abs=0.001)

    def test_returns_none_if_no_open_trade(self, tmp_path):
        j = TradeJournal(str(tmp_path / "trades.json"))
        assert j.record_exit("2330", 100.0) is None

    def test_ignores_already_closed_trades(self, tmp_path, signal):
        j = TradeJournal(str(tmp_path / "trades.json"))
        j.record_entry(signal, 100.0, 10)
        j.record_exit("2330", 110.0)
        assert j.record_exit("2330", 120.0) is None


class TestSummary:
    def test_empty(self, tmp_path):
        j = TradeJournal(str(tmp_path / "trades.json"))
        s = j.summary()
        assert "總交易次數: 0" in s
        assert "已平倉: 0" in s
        assert "獲利次數: 0" in s

    def test_win_rate_100(self, tmp_path, signal):
        j = TradeJournal(str(tmp_path / "trades.json"))
        j.record_entry(signal, 100.0, 10)
        j.record_exit("2330", 110.0)
        s = j.summary()
        assert "勝率: 100.0%" in s
        assert "平均淨報酬" in s

    def test_win_rate_0(self, tmp_path, signal):
        j = TradeJournal(str(tmp_path / "trades.json"))
        j.record_entry(signal, 100.0, 10)
        j.record_exit("2330", 90.0)
        s = j.summary()
        assert "勝率: 0.0%" in s
