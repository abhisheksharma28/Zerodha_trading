"""Curated index constituent lists for the market scanner.

Membership metadata (symbol → name → sector), not price data. NIFTY 50 is
kept inline because it changes only at the semi-annual index review; refresh
it from NSE's ``ind_nifty50list.csv`` when the index is rebalanced. Sector
labels follow NSE's broad sector buckets.
"""

from __future__ import annotations

# (tradingsymbol, company name, sector)
NIFTY_50: list[tuple[str, str, str]] = [
    ("ADANIENT", "Adani Enterprises", "Metals & Mining"),
    ("ADANIPORTS", "Adani Ports & SEZ", "Infrastructure"),
    ("APOLLOHOSP", "Apollo Hospitals", "Healthcare"),
    ("ASIANPAINT", "Asian Paints", "Consumer"),
    ("AXISBANK", "Axis Bank", "Bank"),
    ("BAJAJ-AUTO", "Bajaj Auto", "Automobile"),
    ("BAJFINANCE", "Bajaj Finance", "Financial Services"),
    ("BAJAJFINSV", "Bajaj Finserv", "Financial Services"),
    ("BEL", "Bharat Electronics", "Capital Goods"),
    ("BHARTIARTL", "Bharti Airtel", "Telecom"),
    ("CIPLA", "Cipla", "Pharma"),
    ("COALINDIA", "Coal India", "Oil Gas & Energy"),
    ("DRREDDY", "Dr Reddy's Labs", "Pharma"),
    ("EICHERMOT", "Eicher Motors", "Automobile"),
    ("ETERNAL", "Eternal (Zomato)", "Consumer"),
    ("GRASIM", "Grasim Industries", "Cement"),
    ("HCLTECH", "HCL Technologies", "IT"),
    ("HDFCBANK", "HDFC Bank", "Bank"),
    ("HDFCLIFE", "HDFC Life Insurance", "Financial Services"),
    ("HEROMOTOCO", "Hero MotoCorp", "Automobile"),
    ("HINDALCO", "Hindalco Industries", "Metals & Mining"),
    ("HINDUNILVR", "Hindustan Unilever", "FMCG"),
    ("ICICIBANK", "ICICI Bank", "Bank"),
    ("INDUSINDBK", "IndusInd Bank", "Bank"),
    ("INFY", "Infosys", "IT"),
    ("ITC", "ITC", "FMCG"),
    ("JIOFIN", "Jio Financial Services", "Financial Services"),
    ("JSWSTEEL", "JSW Steel", "Metals & Mining"),
    ("KOTAKBANK", "Kotak Mahindra Bank", "Bank"),
    ("LT", "Larsen & Toubro", "Infrastructure"),
    ("M&M", "Mahindra & Mahindra", "Automobile"),
    ("MARUTI", "Maruti Suzuki", "Automobile"),
    ("NESTLEIND", "Nestle India", "FMCG"),
    ("NTPC", "NTPC", "Power"),
    ("ONGC", "Oil & Natural Gas Corp", "Oil Gas & Energy"),
    ("POWERGRID", "Power Grid Corp", "Power"),
    ("RELIANCE", "Reliance Industries", "Oil Gas & Energy"),
    ("SBILIFE", "SBI Life Insurance", "Financial Services"),
    ("SBIN", "State Bank of India", "Bank"),
    ("SHRIRAMFIN", "Shriram Finance", "Financial Services"),
    ("SUNPHARMA", "Sun Pharma", "Pharma"),
    ("TATACONSUM", "Tata Consumer Products", "FMCG"),
    ("TATAMOTORS", "Tata Motors", "Automobile"),
    ("TATASTEEL", "Tata Steel", "Metals & Mining"),
    ("TCS", "Tata Consultancy Services", "IT"),
    ("TECHM", "Tech Mahindra", "IT"),
    ("TITAN", "Titan Company", "Consumer"),
    ("TRENT", "Trent", "Consumer"),
    ("ULTRACEMCO", "UltraTech Cement", "Cement"),
    ("WIPRO", "Wipro", "IT"),
]

# Broad-market and sectoral NSE indices to snapshot. Kept as exact Kite
# tradingsymbols; the service drops any that aren't in the instrument master.
BROAD_INDICES: list[str] = [
    "NIFTY 50", "NIFTY BANK", "NIFTY FIN SERVICE", "NIFTY NEXT 50",
    "NIFTY MIDCAP 100", "NIFTY SMALLCAP 100", "NIFTY 100", "NIFTY 500",
    "INDIA VIX",
]

SECTOR_INDICES: list[str] = [
    "NIFTY IT", "NIFTY AUTO", "NIFTY PHARMA", "NIFTY FMCG", "NIFTY METAL",
    "NIFTY ENERGY", "NIFTY REALTY", "NIFTY MEDIA", "NIFTY PSU BANK",
    "NIFTY PVT BANK", "NIFTY INFRA", "NIFTY CONSR DURBL", "NIFTY OIL AND GAS",
    "NIFTY HEALTHCARE", "NIFTY CONSUMPTION", "NIFTY COMMODITIES",
]

UNIVERSES: dict[str, list[tuple[str, str, str]]] = {
    "nifty50": NIFTY_50,
}
