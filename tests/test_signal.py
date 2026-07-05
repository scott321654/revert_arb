from tw50_rebalance.signal import evaluate, Signal


class TestEvaluate:
    def test_long_actionable(self):
        s = evaluate("2330", "台積電", "被剔除", -5.0, 2.0)
        assert s.zscore == 2.5
        assert s.expected_direction == "long"
        assert s.threshold_met is True
        assert s.actionable is True

    def test_short_not_actionable_long_only(self):
        s = evaluate("2330", "台積電", "被剔除", 5.0, 2.0)
        assert s.zscore == 2.5
        assert s.expected_direction == "short"
        assert s.threshold_met is True
        assert s.actionable is False

    def test_below_threshold(self):
        s = evaluate("2330", "台積電", "被剔除", -1.0, 2.0)
        assert s.zscore == 0.5
        assert s.threshold_met is False
        assert s.actionable is False

    def test_zero_volatility(self):
        s = evaluate("2330", "台積電", "被剔除", -5.0, 0)
        assert s.zscore == 0
        assert s.threshold_met is False
        assert s.actionable is False

    def test_regulated_skipped(self):
        s = evaluate("2330", "台積電", "被剔除", -5.0, 2.0, regulated=True)
        assert s.actionable is False
        assert "處置" in s.notes

    def test_crowded_skipped(self):
        s = evaluate("2330", "台積電", "被剔除", -5.0, 2.0, short_interest_ratio=0.3)
        assert s.crowded_warning is True
        assert s.actionable is False
        assert "擁擠" in s.notes

    def test_no_crowded_warning_when_none(self):
        s = evaluate("2330", "台積電", "被剔除", -5.0, 2.0, short_interest_ratio=None)
        assert s.crowded_warning is False
        assert s.actionable is True


class TestSignalDataclass:
    def test_actionable_all_true(self):
        s = Signal("2330", "台積電", "被剔除", "long", -5.0, 2.5, threshold_met=True)
        assert s.actionable is True

    def test_not_actionable_regulated(self):
        s = Signal("2330", "台積電", "被剔除", "long", -5.0, 2.5, threshold_met=True, regulated=True)
        assert s.actionable is False

    def test_not_actionable_crowded(self):
        s = Signal("2330", "台積電", "被剔除", "long", -5.0, 2.5, threshold_met=True, crowded_warning=True)
        assert s.actionable is False

    def test_not_actionable_below_threshold(self):
        s = Signal("2330", "台積電", "被剔除", "long", -5.0, 1.0, threshold_met=False)
        assert s.actionable is False

    def test_not_actionable_short_direction(self):
        s = Signal("2330", "台積電", "被剔除", "short", 5.0, 2.5, threshold_met=True)
        assert s.actionable is False
