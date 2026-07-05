from datetime import date

from tw50_rebalance.schedule import (
    _first_friday_of_month,
    _third_friday_of_month,
    quarterly_dates,
    next_effective_date,
    is_effective_today,
)


class TestFirstFriday:
    def test_2026_03(self):
        assert _first_friday_of_month(2026, 3) == date(2026, 3, 6)

    def test_2026_06(self):
        assert _first_friday_of_month(2026, 6) == date(2026, 6, 5)

    def test_2026_09(self):
        assert _first_friday_of_month(2026, 9) == date(2026, 9, 4)

    def test_2026_12(self):
        assert _first_friday_of_month(2026, 12) == date(2026, 12, 4)


class TestThirdFriday:
    def test_2026_03(self):
        assert _third_friday_of_month(2026, 3) == date(2026, 3, 20)

    def test_2025_12(self):
        assert _third_friday_of_month(2025, 12) == date(2025, 12, 19)


class TestQuarterlyDates:
    def test_2026_has_four_quarters(self):
        dates = quarterly_dates(2026)
        assert len(dates) == 4

    def test_2026_labels(self):
        dates = quarterly_dates(2026)
        assert dates[0]["quarter"] == "2026Q1"
        assert dates[1]["quarter"] == "2026Q2"
        assert dates[2]["quarter"] == "2026Q3"
        assert dates[3]["quarter"] == "2026Q4"

    def test_2026_dates_are_ordered(self):
        dates = quarterly_dates(2026)
        for q in dates:
            assert q["review_date"] < q["effective_date"]


class TestNextEffectiveDate:
    def test_day_before(self):
        d = next_effective_date(date(2026, 3, 19))
        assert d["effective_date"] == date(2026, 3, 20)
        assert d["quarter"] == "2026Q1"

    def test_on_the_day(self):
        d = next_effective_date(date(2026, 3, 20))
        assert d["effective_date"] == date(2026, 3, 20)

    def test_day_after(self):
        d = next_effective_date(date(2026, 3, 21))
        assert d["effective_date"] == date(2026, 6, 19)
        assert d["quarter"] == "2026Q2"


class TestIsEffectiveToday:
    def test_true_on_third_friday(self):
        assert is_effective_today(date(2026, 3, 20)) is True

    def test_false_on_other_days(self):
        assert is_effective_today(date(2026, 3, 21)) is False
        assert is_effective_today(date(2026, 1, 1)) is False
