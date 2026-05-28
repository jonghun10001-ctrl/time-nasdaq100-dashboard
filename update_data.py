"""
매일 자동 실행되는 데이터 업데이트 스크립트.
GitHub Actions에서 호출: python update_data.py

1) timeetf.co.kr에서 신규 영업일 보유종목 스캔
2) yfinance로 신규 종목 종가 수집
3) dashboard_data.js 재생성
"""

import json
import sys
from pathlib import Path

import pandas as pd

from etf_analyzer import (
    scan_all_holdings, fetch_all_prices,
    HOLDINGS_CACHE_PATH, PRICES_CACHE_PATH,
    DATA_DIR,
)


def export_dashboard_data(holdings: pd.DataFrame, prices: pd.DataFrame):
    """CSV 데이터를 대시보드용 JSON/JS로 변환."""
    ticker_data = {}
    for ticker in holdings[holdings["ticker"].notna()]["ticker"].unique():
        rows = holdings[holdings["ticker"] == ticker].sort_values("date")
        name = rows.iloc[0]["name"]
        weights = rows[["date", "weight_pct"]].values.tolist()
        quantities = rows[["date", "quantity"]].values.tolist()
        quantities = [
            [d, int(q) if pd.notna(q) and str(q).replace(".", "").replace("-", "").isdigit() else 0]
            for d, q in quantities
        ]

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
                "quantity": int(r["quantity"]) if pd.notna(r["quantity"]) and str(r["quantity"]).replace(".", "").isdigit() else 0,
            })
        date_snapshots[d] = items

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

    json_path = DATA_DIR / "dashboard_data.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)

    js_path = DATA_DIR / "dashboard_data.js"
    with open(js_path, "w", encoding="utf-8") as f:
        f.write("const DASHBOARD_DATA = ")
        json.dump(output, f, ensure_ascii=False)
        f.write(";")

    size_mb = js_path.stat().st_size / 1024 / 1024
    print(f"Exported: {js_path} ({size_mb:.1f}MB)")
    print(f"  {len(ticker_data)} tickers, {len(dates_available)} dates")


def main():
    print("=" * 60)
    print("  TIME 나스닥100 ETF — 일일 데이터 업데이트")
    print("=" * 60)

    print("\n[1/3] 보유종목 스캔 (신규 날짜만)...")
    holdings = scan_all_holdings(resume=True, delay=0.15)
    if holdings.empty:
        print("ERROR: No holdings data.")
        sys.exit(1)

    print(f"\n[2/3] 종가 수집 (신규 종목만)...")
    prices = fetch_all_prices(holdings, resume=True)

    print(f"\n[3/3] 대시보드 데이터 생성...")
    export_dashboard_data(holdings, prices)

    latest = sorted(holdings["date"].unique())[-1]
    n_tickers = holdings[holdings["date"] == latest]["ticker"].notna().sum()
    print(f"\nDone. Latest: {latest}, {n_tickers} tickers")


if __name__ == "__main__":
    main()
