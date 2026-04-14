import numpy as np
import pandas as pd
import requests

SECONDS_PER_YEAR = 365 * 24 * 60 * 60
ANN_FACTOR = np.sqrt(SECONDS_PER_YEAR)


def fetch_binance_1s(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    limit = 1000
    rows = []
    cur = start_ms

    while cur < end_ms:
        params = {
            "symbol": symbol,
            "interval": "1s",
            "startTime": cur,
            "endTime": end_ms,
            "limit": limit,
        }
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        rows.extend(data)
        cur = int(data[-1][0]) + 1000
        if len(data) < limit:
            break

    if not rows:
        raise RuntimeError("No 1s data returned")

    out = pd.DataFrame(rows)
    out = out[[0, 4]]
    out.columns = ["open_time_ms", "close"]
    out["time_utc"] = pd.to_datetime(out["open_time_ms"], unit="ms", utc=True)
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.dropna(subset=["time_utc", "close"]).sort_values("time_utc").reset_index(drop=True)
    return out


def main() -> None:
    events = pd.read_csv("fix_spike_events.csv")
    events["fix_time_utc"] = pd.to_datetime(events["fix_time_utc"], utc=True, errors="coerce")
    events = events.dropna(subset=["fix_time_utc"]).copy()

    # Decision timestamp: blackout is triggered at T-5, so decision must be ready at T-6.
    events["decision_time_utc"] = events["fix_time_utc"] - pd.Timedelta(seconds=6)

    start_ms = int((events["decision_time_utc"].min() - pd.Timedelta(seconds=20)).timestamp() * 1000)
    end_ms = int((events["decision_time_utc"].max() + pd.Timedelta(seconds=2)).timestamp() * 1000)

    px = fetch_binance_1s("BTCUSDT", start_ms, end_ms)
    s = px.set_index("time_utc").sort_index()

    # Build an exact 1-second grid and forward-fill like the production detector.
    full_idx = pd.date_range(s.index.min(), s.index.max(), freq="1s", tz="UTC")
    s = s.reindex(full_idx)
    s["close"] = s["close"].ffill()
    s["ret_1s"] = np.log(s["close"] / s["close"].shift(1))

    # At decision second t=T-6, use 10 one-second returns from t-9..t
    # which corresponds to prices T-16..T-6.
    s["vol10_ann_pct_t6"] = s["ret_1s"].rolling(10).std() * ANN_FACTOR * 100

    events["vol10_ann_pct_t6"] = s["vol10_ann_pct_t6"].reindex(events["decision_time_utc"]).values
    data = events.dropna(subset=["vol10_ann_pct_t6"]).copy()

    # Quartile summary.
    rank = data["vol10_ann_pct_t6"].rank(method="first")
    data["quartile"] = pd.qcut(rank, 4, labels=["Q1 Low", "Q2 Med-Low", "Q3 Med-High", "Q4 High"])
    quart = (
        data.groupby("quartile", observed=True)
        .agg(
            n=("suspicious_flag", "size"),
            avg_vol=("vol10_ann_pct_t6", "mean"),
            min_vol=("vol10_ann_pct_t6", "min"),
            max_vol=("vol10_ann_pct_t6", "max"),
            spike_pct=("spike_flag", "mean"),
            suspicious_pct=("suspicious_flag", "mean"),
        )
        .assign(
            spike_pct=lambda d: d["spike_pct"] * 100,
            suspicious_pct=lambda d: d["suspicious_pct"] * 100,
        )
        .reset_index()
        .rename(columns={
            "quartile": "Volatility Group",
            "n": "Fix Windows",
            "avg_vol": "Avg Realized Volatility (Ann. %)",
            "min_vol": "Min Realized Volatility (Ann. %)",
            "max_vol": "Max Realized Volatility (Ann. %)",
        })
    )

    # Decile summary.
    rank_d = data["vol10_ann_pct_t6"].rank(method="first")
    data["decile"] = pd.qcut(rank_d, 10, labels=[f"D{i}" for i in range(1, 11)])
    dec = (
        data.groupby("decile", observed=True)
        .agg(
            n=("suspicious_flag", "size"),
            avg_vol=("vol10_ann_pct_t6", "mean"),
            min_vol=("vol10_ann_pct_t6", "min"),
            max_vol=("vol10_ann_pct_t6", "max"),
            spike_pct=("spike_flag", "mean"),
            suspicious_pct=("suspicious_flag", "mean"),
        )
        .assign(
            spike_pct=lambda d: d["spike_pct"] * 100,
            suspicious_pct=lambda d: d["suspicious_pct"] * 100,
        )
        .reset_index()
        .rename(columns={
            "decile": "Volatility Decile",
            "n": "Fix Windows",
            "avg_vol": "Avg Realized Volatility (Ann. %)",
            "min_vol": "Min Realized Volatility (Ann. %)",
            "max_vol": "Max Realized Volatility (Ann. %)",
        })
    )

    corr_spike = data["vol10_ann_pct_t6"].corr(data["spike_flag"])
    corr_susp = data["vol10_ann_pct_t6"].corr(data["suspicious_flag"])

    # Operational bands requested by user.
    data["band"] = pd.cut(
        data["vol10_ann_pct_t6"],
        bins=[0, 1, 5, 7, 15, 24, np.inf],
        labels=["<1%", "1-5%", "5-7%", "7-15%", "15-24%", ">24%"],
    )
    bands = (
        data.groupby("band", observed=True)
        .agg(
            n=("suspicious_flag", "size"),
            spike_pct=("spike_flag", "mean"),
            suspicious_pct=("suspicious_flag", "mean"),
        )
        .assign(
            spike_pct=lambda d: d["spike_pct"] * 100,
            suspicious_pct=lambda d: d["suspicious_pct"] * 100,
        )
        .reset_index()
    )

    p25 = float(np.percentile(data["vol10_ann_pct_t6"], 25))
    p50 = float(np.percentile(data["vol10_ann_pct_t6"], 50))
    p75 = float(np.percentile(data["vol10_ann_pct_t6"], 75))

    print("=== T-6 VOL CALIBRATION (window prices T-16..T-6) ===")
    print(f"Rows analyzed: {len(data)}")
    print(f"Corr(vol_t6, spike_flag):      {corr_spike:.4f}")
    print(f"Corr(vol_t6, suspicious_flag): {corr_susp:.4f}")
    print(f"P25={p25:.4f}% | P50={p50:.4f}% | P75={p75:.4f}%")
    print()
    print("=== Quartiles ===")
    print(quart.to_string(index=False))
    print()
    print("=== Deciles ===")
    print(dec.to_string(index=False))
    print()
    print("=== User Bands ===")
    print(bands.to_string(index=False))

    quart.to_csv("fix_volatility_10s_t6_quartile_summary.csv", index=False)
    dec.to_csv("fix_volatility_10s_t6_decile_summary.csv", index=False)
    bands.to_csv("fix_volatility_10s_t6_band_summary.csv", index=False)
    data[["fix_time_utc", "decision_time_utc", "vol10_ann_pct_t6", "spike_flag", "suspicious_flag"]].to_csv(
        "fix_spike_events_with_t6_vol.csv", index=False
    )


if __name__ == "__main__":
    main()
