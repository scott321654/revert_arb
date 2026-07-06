from datetime import datetime, date, timezone, timedelta

_TZ = timezone(timedelta(hours=8))


def now():
    return datetime.now(_TZ)


def today():
    return now().date()
