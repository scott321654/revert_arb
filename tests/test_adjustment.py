from tw50_rebalance.adjustment import AdjustmentList


class TestAdjustmentList:
    def test_init_empty(self, tmp_path):
        adj = AdjustmentList(str(tmp_path / "adj.json"))
        assert adj.data == {"quarter": "", "removed": [], "added": [], "reweight": []}

    def test_get_event_none_when_empty(self, tmp_path):
        adj = AdjustmentList(str(tmp_path / "adj.json"))
        assert adj.get_event("2330") is None
        assert adj.has("2330") is False

    def test_set_and_get_event(self, tmp_path):
        adj = AdjustmentList(str(tmp_path / "adj.json"))
        adj.set("2026Q1", ["2330"], ["6669"], ["2454"])

        assert adj.get_event("2330") == "被剔除"
        assert adj.get_event("6669") == "被納入"
        assert adj.get_event("2454") == "權重調降"
        assert adj.get_event("9999") is None

        assert adj.has("2330") is True
        assert adj.has("9999") is False

    def test_persists_to_disk(self, tmp_path):
        p = tmp_path / "adj.json"
        adj = AdjustmentList(str(p))
        adj.set("2026Q1", ["2330"], ["6669"])

        adj2 = AdjustmentList(str(p))
        assert adj2.data["quarter"] == "2026Q1"
        assert adj2.get_event("2330") == "被剔除"
        assert adj2.get_event("6669") == "被納入"

    def test_set_overwrites_previous(self, tmp_path):
        adj = AdjustmentList(str(tmp_path / "adj.json"))
        adj.set("2026Q1", ["2330"], [])
        adj.set("2026Q2", ["2317"], ["6669"])

        assert adj.get_event("2330") is None  # no longer in removed
        assert adj.get_event("2317") == "被剔除"
        assert adj.get_event("6669") == "被納入"

    def test_summary_when_empty(self, tmp_path):
        adj = AdjustmentList(str(tmp_path / "adj.json"))
        assert "尚未設定" in adj.summary()

    def test_summary_with_data(self, tmp_path):
        adj = AdjustmentList(str(tmp_path / "adj.json"))
        adj.set("2026Q1", ["2330", "2317"], ["6669"])
        s = adj.summary()
        assert "2026Q1" in s
        assert "2330" in s
        assert "2317" in s
        assert "6669" in s

    def test_reweight_omitted_in_summary_when_empty(self, tmp_path):
        adj = AdjustmentList(str(tmp_path / "adj.json"))
        adj.set("2026Q1", ["2330"], ["6669"])
        assert "權重調降" not in adj.summary()

    def test_reweight_included_in_summary_when_present(self, tmp_path):
        adj = AdjustmentList(str(tmp_path / "adj.json"))
        adj.set("2026Q1", ["2330"], ["6669"], ["2454"])
        assert "權重調降" in adj.summary()
