"""
Fetch all timeframes needed for dashboard:
  30s  -> use 1s candles, 4 days (~345k candles, ~4 min)
  1m   -> 7 days (~10k candles, fast)
  5m   -> 7 days (~2k candles, instant)
  10m  -> resample from 5m (Binance has no 10m interval natively)
"""
import requests, time, csv
from datetime import datetime, timezone
from collections import defaultdict

BASE = 'https://api.binance.com'

def ms_to_dt(ms):
    return datetime.fromtimestamp(ms/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

def fetch_klines(symbol, interval, days, retries=3):
    now_ms   = int(time.time() * 1000)
    start_ms = now_ms - (days * 24 * 60 * 60 * 1000)
    candles  = []
    cursor   = start_ms
    page     = 0
    while cursor < now_ms:
        for attempt in range(retries):
            try:
                r = requests.get(f'{BASE}/api/v3/klines', params={
                    'symbol': symbol, 'interval': interval,
                    'startTime': cursor, 'endTime': now_ms, 'limit': 1000
                }, timeout=30)
                r.raise_for_status()
                break
            except Exception as e:
                if attempt == retries-1: raise
                time.sleep(2)
        batch = r.json()
        if not batch: break
        candles.extend(batch)
        page += 1
        cursor = batch[-1][6] + 1
        if page % 20 == 0:
            print(f"    {symbol} {interval}: page {page:4d} | {len(candles):7,} | {ms_to_dt(batch[-1][6])}")
        if len(batch) < 1000: break
        time.sleep(0.04)
    return candles

def save_ohlcv(rows, fname):
    with open(fname, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['time_utc','open','high','low','close','volume','n_trades'])
        w.writerows(rows)
    print(f"  -> {fname}: {len(rows):,} rows")

# ── 1m: 7 days — needed for both 1m analysis and 10m resampling ──────────────
print("Fetching 1m candles (7 days)...")
raw_1m = {}
for sym in ['BTCUSDT', 'ETHUSDT']:
    candles = fetch_klines(sym, '1m', 7)
    rows = [[ms_to_dt(c[0]), float(c[1]), float(c[2]), float(c[3]),
             float(c[4]), float(c[5]), int(c[8])] for c in candles]
    save_ohlcv(rows, f"{sym.lower()}_1m_7d.csv")
    raw_1m[sym] = candles  # keep in memory for 10m resampling

# ── 5m: 7 days, ~2016 candles, instant ───────────────────────────────────────
print("\nFetching 5m candles (7 days)...")
for sym in ['BTCUSDT', 'ETHUSDT']:
    candles = fetch_klines(sym, '5m', 7)
    rows = [[ms_to_dt(c[0]), float(c[1]), float(c[2]), float(c[3]),
             float(c[4]), float(c[5]), int(c[8])] for c in candles]
    save_ohlcv(rows, f"{sym.lower()}_5m_7d.csv")

# ── 10m: resample from 1m (Binance has no 10m interval) ──────────────────────
print("\nResampling 1m -> 10m...")
for sym in ['BTCUSDT', 'ETHUSDT']:
    candles = raw_1m[sym]
    buckets = defaultdict(list)
    for c in candles:
        bts = (int(c[0]) // 600000) * 600000   # floor to 10-minute boundary
        buckets[bts].append(c)
    rows = []
    for bts in sorted(buckets.keys()):
        cs = buckets[bts]
        rows.append([ms_to_dt(bts),
                     float(cs[0][1]),                        # open  of first 1m
                     max(float(c[2]) for c in cs),           # high
                     min(float(c[3]) for c in cs),           # low
                     float(cs[-1][4]),                       # close of last 1m
                     round(sum(float(c[5]) for c in cs), 6), # total volume
                     sum(int(c[8]) for c in cs)])             # total trades
    save_ohlcv(rows, f"{sym.lower()}_10m_7d.csv")

# ── 30s: 4 days via 1s resampling (~345k candles, ~4 min) ────────────────────
print("\nFetching 1s candles for 30s resampling (4 days)...")
for sym in ['BTCUSDT', 'ETHUSDT']:
    print(f"  {sym}...")
    candles = fetch_klines(sym, '1s', 4)
    print(f"  {sym}: {len(candles):,} raw 1s candles -> resampling to 30s...")
    buckets = defaultdict(list)
    for c in candles:
        bts = (int(c[0]) // 30000) * 30000
        buckets[bts].append(c)
    rows = []
    for bts in sorted(buckets.keys()):
        cs = buckets[bts]
        rows.append([ms_to_dt(bts),
                     float(cs[0][1]), max(float(c[2]) for c in cs),
                     min(float(c[3]) for c in cs), float(cs[-1][4]),
                     round(sum(float(c[5]) for c in cs), 6), len(cs)])
    save_ohlcv(rows, f"{sym.lower()}_30s_4d.csv")

print("\nDone. All files ready.")
