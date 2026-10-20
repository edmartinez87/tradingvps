"""Forex & metals contract specs for the HotForex (HFM) bot. Prices come from Yahoo Finance until the HFM account is linked."""
SPECS = {
    "XAUUSD": dict(name="Oro", yahoo="GC=F", group="Metales", contract=100, pip=0.1, digits=2, base="XAU", quote="USD", spread=0.30),
    "XAGUSD": dict(name="Plata", yahoo="SI=F", group="Metales", contract=5000, pip=0.01, digits=3, base="XAG", quote="USD", spread=0.030),
    "EURUSD": dict(name="Euro / Dólar", yahoo="EURUSD=X", group="Mayores", contract=100000, pip=0.0001, digits=5, base="EUR", quote="USD", spread=0.00012),
    "GBPUSD": dict(name="Libra / Dólar", yahoo="GBPUSD=X", group="Mayores", contract=100000, pip=0.0001, digits=5, base="GBP", quote="USD", spread=0.00015),
    "USDJPY": dict(name="Dólar / Yen", yahoo="USDJPY=X", group="Mayores", contract=100000, pip=0.01, digits=3, base="USD", quote="JPY", spread=0.015),
    "USDCHF": dict(name="Dólar / Franco", yahoo="USDCHF=X", group="Mayores", contract=100000, pip=0.0001, digits=5, base="USD", quote="CHF", spread=0.00016),
    "USDCAD": dict(name="Dólar / Dólar canadiense", yahoo="USDCAD=X", group="Mayores", contract=100000, pip=0.0001, digits=5, base="USD", quote="CAD", spread=0.00018),
    "AUDUSD": dict(name="Dólar australiano / Dólar", yahoo="AUDUSD=X", group="Mayores", contract=100000, pip=0.0001, digits=5, base="AUD", quote="USD", spread=0.00014),
    "NZDUSD": dict(name="Dólar neozelandés / Dólar", yahoo="NZDUSD=X", group="Mayores", contract=100000, pip=0.0001, digits=5, base="NZD", quote="USD", spread=0.00018),
    "EURJPY": dict(name="Euro / Yen", yahoo="EURJPY=X", group="Cruces", contract=100000, pip=0.01, digits=3, base="EUR", quote="JPY", spread=0.020),
    "GBPJPY": dict(name="Libra / Yen", yahoo="GBPJPY=X", group="Cruces", contract=100000, pip=0.01, digits=3, base="GBP", quote="JPY", spread=0.030),
    "EURCHF": dict(name="Euro / Franco", yahoo="EURCHF=X", group="Cruces", contract=100000, pip=0.0001, digits=5, base="EUR", quote="CHF", spread=0.00020),
}
AVAILABLE = list(SPECS)
CONVERSION = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD"]
DEFAULT_SYMBOLS = AVAILABLE
CURRENCIES = ["USD", "EUR", "GBP", "CHF", "CAD", "NZD", "AUD", "JPY"]
CURRENCY_NAMES = {"USD": "Estados Unidos", "EUR": "Eurozona", "GBP": "Reino Unido", "CHF": "Suiza", "CAD": "Canadá", "NZD": "Nueva Zelanda",
                  "AUD": "Australia", "JPY": "Japón", "CNY": "China", "XAU": "Oro", "XAG": "Plata"}
CURRENCY_WORDS = {
    "USD": ["dollar", "greenback", "fed ", "fed's", "fomc", "powell", "treasury", "u.s. ", "us economy", "nonfarm", "payrolls"],
    "EUR": ["euro", "ecb", "lagarde", "eurozone", "euro zone", "germany", "german"],
    "GBP": ["pound", "sterling", "boe", "bank of england", "bailey", "uk ", "britain", "british"],
    "CHF": ["franc", "snb", "swiss", "switzerland"],
    "CAD": ["loonie", "canadian", "bank of canada", "boc", "canada", "macklem"],
    "NZD": ["kiwi", "rbnz", "new zealand"],
    "AUD": ["aussie", "rba", "australia", "australian"],
    "JPY": ["yen", "boj", "bank of japan", "japan", "ueda"],
    "XAU": ["gold", "bullion", "xau"],
    "XAG": ["silver", "xag"],
}


def spec(symbol: str) -> dict:
    return SPECS[symbol]


def currencies(symbol: str) -> tuple:
    s = SPECS[symbol]
    return s["base"], s["quote"]


def pairs_for_currency(cur: str, symbols: list) -> list:
    return [s for s in symbols if cur in currencies(s)]


def matched_currencies(text: str) -> set:
    t = f" {text.lower()} "
    return {c for c, words in CURRENCY_WORDS.items() if any(w in t for w in words)}


def relevant_pairs(text: str, symbols: list) -> list:
    m = matched_currencies(text)
    if not m:
        return []
    out = []
    for s in symbols:
        base, quote = currencies(s)
        if base in m or (quote in m and quote != "USD") or (m == {"USD"} and "USD" in (base, quote)):
            out.append(s)
    return out


def fmt_price(symbol: str, price: float) -> str:
    return f"{price:.{SPECS[symbol]['digits']}f}"


def pips(symbol: str, dist: float) -> float:
    return dist / SPECS[symbol]["pip"]
