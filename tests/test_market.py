import pytest

from tw50_rebalance.market import _mid_price, _parse_day_all


class TestMidPrice:
    def test_both_ask_and_bid(self):
        m = {"a": "100.50_10", "b": "100.00_5"}
        assert _mid_price(m) == 100.25

    def test_ask_only(self):
        m = {"a": "100.50_10", "b": "-"}
        assert _mid_price(m) == 100.50

    def test_bid_only(self):
        m = {"a": "-", "b": "100.00_5"}
        assert _mid_price(m) == 100.00

    def test_both_dash(self):
        m = {"a": "-", "b": "-"}
        assert _mid_price(m) is None

    def test_both_empty(self):
        m = {"a": "", "b": ""}
        assert _mid_price(m) is None

    def test_ask_with_underscore_format(self):
        m = {"a": "150.00_3", "b": "149.50_7"}
        assert _mid_price(m) == 149.75


class TestParseDayAll:
    def test_parses_valid_data(self):
        data = [
            {"Code": "2330", "ClosingPrice": "100.00", "Change": "+1.50"},
            {"Code": "2317", "ClosingPrice": "50.00", "Change": "-0.50"},
        ]
        result = _parse_day_all(data)
        assert result["2330"]["price"] == 100.0
        assert result["2330"]["change"] == 1.5
        assert result["2330"]["change_pct"] == pytest.approx(1.52, abs=0.01)
        assert result["2317"]["price"] == 50.0
        assert result["2317"]["change"] == -0.5
        assert result["2317"]["change_pct"] == pytest.approx(-0.99, abs=0.01)

    def test_negative_change(self):
        data = [{"Code": "2330", "ClosingPrice": "90.00", "Change": "-10.00"}]
        result = _parse_day_all(data)
        prev = 90 - (-10)  # = 100
        expected_pct = round(-10 / 100 * 100, 2)  # = -10.0
        assert result["2330"]["change_pct"] == -10.0

    def test_zero_change(self):
        data = [{"Code": "2330", "ClosingPrice": "100.00", "Change": "0"}]
        result = _parse_day_all(data)
        assert result["2330"]["change_pct"] == 0.0

    def test_skips_invalid_rows(self):
        data = [{"Code": "2330", "ClosingPrice": "abc", "Change": "0"}]
        result = _parse_day_all(data)
        assert result == {}

    def test_empty_code_still_parsed(self):
        data = [{"Code": "", "ClosingPrice": "100.00", "Change": "0"}]
        result = _parse_day_all(data)
        assert "" in result
        assert result[""]["price"] == 100.0
