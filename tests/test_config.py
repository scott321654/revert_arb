import pytest

from tw50_rebalance import config


class TestCalcCost:
    def test_default(self):
        assert config.COST == 0.471

    def test_no_discount(self, monkeypatch):
        monkeypatch.setitem(config.TRADE, "broker_discount", 1)
        config.calc_cost()
        assert config.COST == pytest.approx(0.585, abs=0.001)

    def test_no_tax(self, monkeypatch):
        monkeypatch.setitem(config.TRADE, "stamp_tax", 0)
        config.calc_cost()
        assert config.COST == 0.171
