STRATEGY = {
    "direction": "long_only",
    "entry_window": ("13:25", "13:30"),
    "exit_window": ("09:00", "09:15"),
    "exit_method": "vwap",
    "zscore_threshold": 2.5,
}

TRADE = {
    "broker_discount": 0.6,
    "stamp_tax": 0.003,
    "commission": 0.001425,
    "net_cost": None,
}

COST = None


def calc_cost():
    global COST
    c = TRADE["commission"] * (1 - TRADE["broker_discount"])
    t = TRADE["stamp_tax"]
    COST = round((2 * c + t) * 100, 3)


calc_cost()
