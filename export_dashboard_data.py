"""CSV 데이터를 대시보드용 JSON으로 변환."""

import json
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

holdings = pd.read_csv(DATA_DIR / "all_holdings.csv")
prices = pd.read_csv(DATA_DIR / "all_prices.csv", index_col=0, parse_dates=True)

# 1) 종목별 메타 + 비중 시계열
ticker_data = {}
for ticker in holdings[holdings["ticker"].notna()]["ticker"].unique():
    rows = holdings[holdings["ticker"] == ticker].sort_values("date")
    name = rows.iloc[0]["name"]
    weights = rows[["date", "weight_pct"]].values.tolist()
    quantities = rows[["date", "quantity"]].values.tolist()
    quantities = [[d, int(q) if pd.notna(q) and str(q).replace('.','').replace('-','').isdigit() else 0] for d, q in quantities]

    price_series = []
    if ticker in prices.columns:
        ps = prices[ticker].dropna()
        for dt, val in ps.items():
            d = dt.strftime("%Y-%m-%d")
            if d >= weights[0][0] and d <= weights[-1][0]:
                price_series.append([d, round(val, 2)])

    ticker_data[ticker] = {
        "name": name,
        "first_date": weights[0][0],
        "last_date": weights[-1][0],
        "days_held": len(weights),
        "avg_weight": round(rows["weight_pct"].mean(), 2),
        "max_weight": round(rows["weight_pct"].max(), 2),
        "min_weight": round(rows["weight_pct"].min(), 2),
        "weights": weights,
        "prices": price_series,
        "quantities": quantities,
    }

# 2) 날짜별 스냅샷 (비중 순 정렬)
dates_available = sorted(holdings["date"].unique())
date_snapshots = {}
for d in dates_available:
    day = holdings[holdings["date"] == d].sort_values("weight_pct", ascending=False)
    items = []
    for _, r in day.iterrows():
        label = r["ticker"] if pd.notna(r["ticker"]) else ("현금" if r["is_cash"] else r["name"])
        close = None
        if pd.notna(r["ticker"]) and r["ticker"] in prices.columns:
            ts = pd.Timestamp(d)
            if ts in prices.index:
                v = prices.loc[ts, r["ticker"]]
                if pd.notna(v):
                    close = round(float(v), 2)
            else:
                mask = prices.index <= ts
                if mask.any():
                    v = prices.loc[mask, r["ticker"]].iloc[-1]
                    if pd.notna(v):
                        close = round(float(v), 2)
        items.append({
            "ticker": label,
            "name": r["name"],
            "weight": r["weight_pct"],
            "close_usd": close,
            "quantity": int(r["quantity"]) if pd.notna(r["quantity"]) and str(r["quantity"]).replace('.','').isdigit() else 0,
        })
    date_snapshots[d] = items

# 3) 요약 통계
equity_only = holdings[holdings["ticker"].notna() & (holdings["is_futures"] != True)]
count_per_day = equity_only.groupby("date").size()
cash_per_day = holdings[holdings["is_cash"] == True].groupby("date")["weight_pct"].sum()

overview = {
    "date_range": [dates_available[0], dates_available[-1]],
    "total_days": len(dates_available),
    "unique_tickers": len(ticker_data),
    "count_series": [[d, int(count_per_day.get(d, 0))] for d in dates_available],
    "cash_series": [[d, round(float(cash_per_day.get(d, 0)), 2)] for d in dates_available],
}

output = {
    "overview": overview,
    "tickers": ticker_data,
    "dates": dates_available,
    "snapshots": date_snapshots,
}

out_path = DATA_DIR / "dashboard_data.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False)

js_path = DATA_DIR / "dashboard_data.js"
with open(js_path, "w", encoding="utf-8") as f:
    f.write("const DASHBOARD_DATA = ")
    json.dump(output, f, ensure_ascii=False)
    f.write(";")

size_mb = js_path.stat().st_size / 1024 / 1024
print(f"Exported: {js_path} ({size_mb:.1f}MB)")
print(f"  {len(ticker_data)} tickers, {len(dates_available)} dates")
