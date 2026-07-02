from datetime import date, timedelta


def _first_friday_of_month(y: int, m: int) -> date:
    d = date(y, m, 1)
    days_ahead = 4 - d.weekday()
    if days_ahead < 0:
        days_ahead += 7
    return d + timedelta(days=days_ahead)


def _third_friday_of_month(y: int, m: int) -> date:
    first = _first_friday_of_month(y, m)
    return first + timedelta(weeks=2)


def quarterly_dates(year: int):
    months = [3, 6, 9, 12]
    result = []
    for m in months:
        result.append({
            "review_date": _first_friday_of_month(year, m),
            "effective_date": _third_friday_of_month(year, m),
            "quarter": f"{year}Q{m // 3}",
        })
    return result


def next_effective_date(from_date: date = None) -> dict:
    if from_date is None:
        from_date = date.today()

    for y in range(from_date.year, from_date.year + 2):
        for q in quarterly_dates(y):
            if q["effective_date"] >= from_date:
                return q
    return {}


def is_effective_today(today: date = None) -> bool:
    if today is None:
        today = date.today()

    for y in range(today.year - 1, today.year + 2):
        for q in quarterly_dates(y):
            if q["effective_date"] == today:
                return True
    return False
