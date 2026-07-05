import os

from tw50_rebalance import stocks


class TestGetAllStocks:
    def test_returns_dict(self):
        result = stocks.get_all_stocks()
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_contains_major_stocks(self):
        result = stocks.get_all_stocks()
        assert "2330" in result

    def test_fallback_when_cache_missing_and_network_fails(self, monkeypatch):
        monkeypatch.setattr(stocks, "STOCK_CACHE", "_nonexistent_test_cache.json")
        cache_path = os.path.join(os.path.dirname(stocks.__file__), "_nonexistent_test_cache.json")
        if os.path.exists(cache_path):
            os.remove(cache_path)
        monkeypatch.setattr(stocks, "_fetch_json", lambda url: None)
        result = stocks.get_all_stocks()
        assert "2330" in result
        assert result["2330"] == "台積電"


class TestLookupName:
    def test_found(self, monkeypatch):
        monkeypatch.setattr(stocks, "get_all_stocks", lambda: {"2330": "台積電"})
        assert stocks.lookup_name("2330") == "台積電"

    def test_not_found(self, monkeypatch):
        monkeypatch.setattr(stocks, "get_all_stocks", lambda: {"2330": "台積電"})
        assert stocks.lookup_name("99999") == ""


class TestRefreshStocks:
    def test_returns_none_on_network_failure(self, monkeypatch):
        monkeypatch.setattr(stocks, "_fetch_json", lambda url: None)
        assert stocks.refresh_stocks() is None

    def test_returns_dict_on_success(self, monkeypatch):
        mock_data = [{"Code": "2330", "Name": "台積電"}, {"Code": "2317", "Name": "鴻海"}]
        monkeypatch.setattr(stocks, "_fetch_json", lambda url: mock_data)
        monkeypatch.setattr(stocks, "STOCK_CACHE", "_test_refresh_cache.json")
        cache_path = os.path.join(os.path.dirname(stocks.__file__), "_test_refresh_cache.json")
        if os.path.exists(cache_path):
            os.remove(cache_path)
        try:
            result = stocks.refresh_stocks()
            assert result == {"2330": "台積電", "2317": "鴻海"}
        finally:
            if os.path.exists(cache_path):
                os.remove(cache_path)
