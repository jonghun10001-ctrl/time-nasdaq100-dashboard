"""
CLI 진입점 — TIME 미국나스닥100 ETF 보유종목 분석

사용법:
  python3 run_analysis.py                    # 전체 분석 (스캔 + 종가 + 리포트)
  python3 run_analysis.py --date 2026-05-27  # 특정일 포트폴리오
  python3 run_analysis.py --compare 2026-04-01 2026-05-27  # 두 날짜 비교
  python3 run_analysis.py --track NVDA       # 종목 비중 추이
  python3 run_analysis.py --refresh          # 캐시 무시, 전체 재스캔
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

from etf_analyzer import (
    HOLDINGS_CACHE_PATH, PRICES_CACHE_PATH,
    scan_all_holdings, fetch_all_prices,
    build_portfolio_snapshot, compare_dates,
    weight_timeseries, top_holdings_over_time,
    summary_stats, OUTPUT_DIR,
)


def load_data(refresh=False):
    if not refresh and HOLDINGS_CACHE_PATH.exists() and PRICES_CACHE_PATH.exists():
        holdings = pd.read_csv(HOLDINGS_CACHE_PATH)
        prices = pd.read_csv(PRICES_CACHE_PATH, index_col=0, parse_dates=True)
        print(f"Loaded cached data: {holdings['date'].nunique()} dates, {len(prices.columns)} tickers")
    else:
        holdings = scan_all_holdings(resume=not refresh, delay=0.15)
        prices = fetch_all_prices(holdings, resume=not refresh)
    return holdings, prices


def cmd_snapshot(holdings, prices, date_str):
    snap = build_portfolio_snapshot(date_str, holdings, prices)
    if snap.empty:
        dates = sorted(holdings["date"].unique())
        close = min(dates, key=lambda d: abs(pd.Timestamp(d) - pd.Timestamp(date_str)))
        print(f"No data for {date_str}. Closest: {close}")
        snap = build_portfolio_snapshot(close, holdings, prices)
        date_str = close

    print(f"\n{'='*70}")
    print(f"  TIME 미국나스닥100 포트폴리오 — {date_str}")
    print(f"{'='*70}")

    snap["is_cash"] = snap["is_cash"].fillna(False).astype(bool)
    snap["is_futures"] = snap["is_futures"].fillna(False).astype(bool)
    equity = snap[snap["ticker"].notna() & ~snap["is_futures"] & ~snap["is_cash"]]
    cash = snap[snap["is_cash"]]
    futures = snap[snap["is_futures"]]

    print(f"\n주식 {len(equity)}종목 (합산 {equity['weight_pct'].sum():.1f}%)")
    print(f"{'Ticker':8s} {'종목명':35s} {'비중':>7s} {'종가(USD)':>12s} {'수량':>6s}")
    print("-" * 70)
    for _, r in equity.iterrows():
        close = f"${r['close_usd']:.2f}" if pd.notna(r["close_usd"]) else "N/A"
        print(f"{r['ticker']:8s} {str(r['name'])[:35]:35s} {r['weight_pct']:6.2f}% {close:>12s} {int(r['quantity']):6d}")

    if not cash.empty:
        print(f"\n현금: {cash['weight_pct'].sum():.2f}%")
    if not futures.empty:
        print(f"선물: {futures['weight_pct'].sum():.2f}% ({futures.iloc[0]['name']})")

    out = OUTPUT_DIR / f"snapshot_{date_str}.csv"
    snap.to_csv(out, index=False)
    print(f"\n저장: {out}")


def cmd_compare(holdings, date1, date2):
    comp = compare_dates(date1, date2, holdings)
    col1, col2 = f"weight_{date1}", f"weight_{date2}"

    print(f"\n{'='*70}")
    print(f"  비중 변화: {date1} → {date2}")
    print(f"{'='*70}")

    new = comp[comp["status"] == "NEW"]
    exited = comp[comp["status"] == "EXIT"]
    holds = comp[comp["status"] == "hold"].sort_values("change", ascending=False)

    if not new.empty:
        print(f"\n신규 편입 ({len(new)}종목):")
        for _, r in new.iterrows():
            print(f"  + {r['ticker']:8s} {str(r['name'])[:30]:30s} → {r[col2]:.2f}%")

    if not exited.empty:
        print(f"\n제외 ({len(exited)}종목):")
        for _, r in exited.iterrows():
            print(f"  - {r['ticker']:8s} {str(r['name'])[:30]:30s} {r[col1]:.2f}% →")

    print(f"\n비중 증가 TOP 10:")
    for _, r in holds.head(10).iterrows():
        t = r["ticker"] if pd.notna(r["ticker"]) else "현금/선물"
        print(f"  ↑ {t:8s} {r[col1]:5.2f}% → {r[col2]:5.2f}% ({r['change']:+.2f}%)")

    print(f"\n비중 감소 TOP 10:")
    for _, r in holds.tail(10).iterrows():
        t = r["ticker"] if pd.notna(r["ticker"]) else "현금/선물"
        print(f"  ↓ {t:8s} {r[col1]:5.2f}% → {r[col2]:5.2f}% ({r['change']:+.2f}%)")

    out = OUTPUT_DIR / f"compare_{date1}_vs_{date2}.csv"
    comp.to_csv(out, index=False)
    print(f"\n저장: {out}")


def cmd_track(holdings, prices, ticker):
    ts = weight_timeseries(ticker, holdings)
    if ts.empty:
        print(f"종목 {ticker}을 보유 이력에서 찾을 수 없습니다.")
        return

    name = ts.iloc[0]["name"]
    print(f"\n{'='*70}")
    print(f"  {ticker} ({name}) 비중 추이")
    print(f"{'='*70}")
    print(f"  보유 기간: {ts['date'].min().strftime('%Y-%m-%d')} ~ {ts['date'].max().strftime('%Y-%m-%d')}")
    print(f"  보유 일수: {len(ts)}일")
    print(f"  평균 비중: {ts['weight_pct'].mean():.2f}%")
    print(f"  최대 비중: {ts['weight_pct'].max():.2f}% ({ts.loc[ts['weight_pct'].idxmax(), 'date'].strftime('%Y-%m-%d')})")
    print(f"  최소 비중: {ts['weight_pct'].min():.2f}% ({ts.loc[ts['weight_pct'].idxmin(), 'date'].strftime('%Y-%m-%d')})")

    price_col = prices[ticker] if ticker in prices.columns else None
    if price_col is not None:
        ts_merged = ts.set_index("date").join(price_col.rename("close_usd"), how="left")
        first_price = ts_merged["close_usd"].dropna().iloc[0] if ts_merged["close_usd"].notna().any() else None
        last_price = ts_merged["close_usd"].dropna().iloc[-1] if ts_merged["close_usd"].notna().any() else None
        if first_price and last_price:
            ret = (last_price / first_price - 1) * 100
            print(f"  보유 기간 수익률: {ret:+.1f}% (${first_price:.2f} → ${last_price:.2f})")

    print(f"\n최근 20일:")
    print(f"  {'날짜':12s} {'비중':>7s}")
    for _, r in ts.tail(20).iterrows():
        print(f"  {r['date'].strftime('%Y-%m-%d'):12s} {r['weight_pct']:6.2f}%")

    out = OUTPUT_DIR / f"track_{ticker}.csv"
    ts.to_csv(out, index=False)
    print(f"\n저장: {out}")


def cmd_full_report(holdings, prices):
    stats = summary_stats(holdings)
    dates = sorted(holdings["date"].unique())

    print(f"\n{'='*70}")
    print(f"  TIME 미국나스닥100 액티브 ETF (426030) — 전체 분석 리포트")
    print(f"{'='*70}")
    print(f"  기간: {stats['date_range']}")
    print(f"  총 {stats['total_dates']}일 데이터")
    print(f"  고유 종목 수: {stats['unique_tickers']}개")
    print(f"  일평균 보유종목: {stats['avg_holdings_per_day']:.1f}개")
    print(f"  평균 현금 비중: {stats['avg_cash_pct']:.2f}%")

    print(f"\n{'─'*70}")
    print(f"  상위 보유 종목 (전체 기간 출현 빈도)")
    print(f"{'─'*70}")
    for t, c in stats["most_frequent_tickers"].items():
        avg_w = holdings[holdings["ticker"] == t]["weight_pct"].mean()
        print(f"  {t:8s} {c:4d}일 ({c/stats['total_dates']*100:4.0f}%)  평균비중 {avg_w:.2f}%")

    print(f"\n{'─'*70}")
    print(f"  종목 수 변화 추이 (분기별)")
    print(f"{'─'*70}")
    holdings_c = holdings.copy()
    holdings_c["date_dt"] = pd.to_datetime(holdings_c["date"])
    holdings_c["quarter"] = holdings_c["date_dt"].dt.to_period("Q").astype(str)

    count_per_date = holdings_c.groupby(["quarter", "date"]).size().reset_index(name="cnt")
    avg_count = count_per_date.groupby("quarter")["cnt"].mean()

    cash_rows = holdings_c[holdings_c["is_cash"]]
    avg_cash = cash_rows.groupby("quarter")["weight_pct"].mean() if not cash_rows.empty else pd.Series(dtype=float)

    for q in sorted(avg_count.index):
        cnt = avg_count.get(q, 0)
        cash = avg_cash.get(q, 0) if q in avg_cash.index else 0
        print(f"  {q}  종목수 {cnt:.0f}개  현금 {cash:.1f}%")

    latest = dates[-1]
    d_1m = dates[-22] if len(dates) > 22 else dates[0]
    d_3m = dates[-66] if len(dates) > 66 else dates[0]
    d_6m = dates[-132] if len(dates) > 132 else dates[0]
    d_1y = dates[-252] if len(dates) > 252 else dates[0]

    for label, d in [("1개월", d_1m), ("3개월", d_3m), ("6개월", d_6m), ("1년", d_1y)]:
        comp = compare_dates(d, latest, holdings)
        new_cnt = (comp["status"] == "NEW").sum()
        exit_cnt = (comp["status"] == "EXIT").sum()
        avg_chg = comp[comp["status"] == "hold"]["change"].abs().mean()
        print(f"\n  {label} 변화 ({d} → {latest}): +{new_cnt} 편입, -{exit_cnt} 제외, 평균|변동| {avg_chg:.2f}%p")
        top_up = comp[comp["status"] == "hold"].nlargest(3, "change")
        top_dn = comp[comp["status"] == "hold"].nsmallest(3, "change")
        for _, r in top_up.iterrows():
            t = r["ticker"] if pd.notna(r["ticker"]) else "현금"
            print(f"    ↑ {t:8s} {r['change']:+.2f}%p")
        for _, r in top_dn.iterrows():
            t = r["ticker"] if pd.notna(r["ticker"]) else "현금"
            print(f"    ↓ {t:8s} {r['change']:+.2f}%p")


def main():
    parser = argparse.ArgumentParser(description="TIME 미국나스닥100 ETF 보유종목 분석기")
    parser.add_argument("--date", help="특정일 포트폴리오 스냅샷 (YYYY-MM-DD)")
    parser.add_argument("--compare", nargs=2, metavar=("DATE1", "DATE2"), help="두 날짜 비중 비교")
    parser.add_argument("--track", help="특정 종목 비중 추이 (티커)")
    parser.add_argument("--refresh", action="store_true", help="캐시 무시, 전체 재스캔")
    args = parser.parse_args()

    holdings, prices = load_data(refresh=args.refresh)

    if args.date:
        cmd_snapshot(holdings, prices, args.date)
    elif args.compare:
        cmd_compare(holdings, args.compare[0], args.compare[1])
    elif args.track:
        cmd_track(holdings, prices, args.track)
    else:
        cmd_full_report(holdings, prices)


if __name__ == "__main__":
    main()
