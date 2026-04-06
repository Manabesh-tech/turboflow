"""
Build static HTML dashboard - pure server-side rendering, no JS framework.
"""
import csv, math, json
from collections import defaultdict
from datetime import datetime, timezone, timedelta

SGT = timezone(timedelta(hours=8))

# Per-timeframe payout rates and breakeven thresholds
TF_PAYOUTS = {
    '30s': 0.80,
    '1m':  0.83,
    '5m':  0.85,
    '10m': 0.80,
}
def tf_be(tf):     return 1 / (1 + TF_PAYOUTS[tf])   # breakeven win rate
def tf_payout(tf): return TF_PAYOUTS[tf]

# Default (used only for legacy helpers; overridden per-tf in analysis)
BREAKEVEN = tf_be('30s')
PAYOUT    = TF_PAYOUTS['30s']

def load(fname):
    with open(fname) as f:
        rows = list(csv.DictReader(f))
    data = []
    for r in rows:
        d = {
            'time':   r['time_utc'],
            'open':   float(r['open']),
            'high':   float(r['high']),
            'low':    float(r['low']),
            'close':  float(r['close']),
            'vol':    float(r['volume']),
            'trades': int(r['n_trades']),
        }
        d['body']       = abs(d['close'] - d['open'])
        d['rng']        = d['high'] - d['low']
        d['body_ratio'] = d['body'] / d['rng'] if d['rng'] > 0 else 0
        d['rng_pct']    = d['rng'] / d['close'] * 100
        d['is_flat']    = (d['open'] == d['close'])
        d['dir']        = 1 if d['close'] > d['open'] else (-1 if d['close'] < d['open'] else 0)
        dt = datetime.strptime(d['time'], '%Y-%m-%d %H:%M:%S UTC').replace(tzinfo=timezone.utc)
        dt_sgt          = dt.astimezone(SGT)
        d['hour']       = dt_sgt.hour   # SGT hour
        d['sgt_date']   = dt_sgt.strftime('%Y-%m-%d')
        d['dow']        = dt_sgt.weekday()
        data.append(d)
    return [d for d in data if not d['is_flat']]

def evf(wr, payout):  return wr * payout - (1 - wr)
def ztest(wr, n, h0=BREAKEVEN):
    if n < 20: return 0, 1
    se = math.sqrt(h0*(1-h0)/n)
    z  = (wr - h0) / se
    p  = 2*(1 - 0.5*(1 + math.erf(abs(z)/math.sqrt(2))))
    return round(z,2), round(p,4)

def evaluate(signals, data, payout):
    wins = total = 0
    for idx, direction in signals:
        if idx+1 >= len(data): continue
        actual = 1 if data[idx+1]['close'] > data[idx]['close'] else -1
        wins  += (actual == direction)
        total += 1
    if total == 0: return 0, 0, 0
    wr = wins / total
    return wr, total, evf(wr, payout)

def calc_rsi(data, period=14):
    closes = [d['close'] for d in data]
    rsi = [None]*len(closes)
    gains, losses = [], []
    for i in range(1, period+1):
        dd = closes[i]-closes[i-1]
        gains.append(max(dd,0)); losses.append(max(-dd,0))
    ag = sum(gains)/period; al = sum(losses)/period
    for i in range(period+1, len(closes)):
        dd = closes[i]-closes[i-1]
        ag = (ag*(period-1)+max(dd,0))/period
        al = (al*(period-1)+max(-dd,0))/period
        rs = ag/al if al else 100
        rsi[i] = 100-100/(1+rs)
    return rsi

def run_all(data, payout, be):
    N = len(data)
    closes = [d['close'] for d in data]
    vols   = [d['vol']   for d in data]
    trs    = [d['rng']   for d in data]
    res    = []

    def add(name, sigs, min_n=30):
        wr, n, ev_ = evaluate(sigs, data, payout)
        z, p = ztest(wr, n, h0=be)
        if n >= min_n:
            res.append(dict(name=name, wr=round(wr,5), n=n, ev=round(ev_,4),
                            z=z, p=p, edge=round(wr-be,5),
                            sig=(p<0.05 and n>=50), beats=(wr>be)))

    add('Always UP',   [(i, 1)  for i in range(N-1)])
    add('Always DOWN', [(i, -1) for i in range(N-1)])

    for lb in [1,2,3,5,10,20]:
        for mode,m in [('Momentum','mom'),('Reversion','rev')]:
            sigs = []
            for i in range(lb, N-1):
                net = sum(1 if data[j+1]['close']>data[j]['close'] else -1 for j in range(i-lb,i))
                if net==0: continue
                d = 1 if net>0 else -1
                sigs.append((i, d if m=='mom' else -d))
            add(f'{mode}({lb})', sigs)

    for sl in [2,3,4,5,6,7]:
        for mode,m in [('Streak-Mom','mom'),('Streak-Rev','rev')]:
            sigs = []
            for i in range(sl, N-1):
                moves = [1 if data[j+1]['close']>data[j]['close'] else -1 for j in range(i-sl,i)]
                if all(x==1 for x in moves):    sigs.append((i,  1 if m=='mom' else -1))
                elif all(x==-1 for x in moves): sigs.append((i, -1 if m=='mom' else  1))
            add(f'{mode}(n={sl})', sigs, min_n=15)

    for fast,slow in [(2,5),(3,10),(5,20),(10,30)]:
        sigs = []
        for i in range(slow, N-1):
            f = sum(closes[i-fast+1:i+1])/fast
            s = sum(closes[i-slow+1:i+1])/slow
            sigs.append((i, 1 if f>s else -1))
        add(f'MA({fast}x{slow})', sigs)

    for period in [7,14]:
        rsi = calc_rsi(data, period)
        for ob,os_ in [(70,30),(65,35),(60,40)]:
            sigs = []
            for i in range(period+1, N-1):
                if rsi[i] is None: continue
                if   rsi[i]>ob:   sigs.append((i,-1))
                elif rsi[i]<os_:  sigs.append((i, 1))
            add(f'RSI({period}) {ob}/{os_}', sigs, min_n=20)

    for thresh in [0.02,0.05,0.10]:
        sigs = [(i, -1 if data[i]['close']>data[i]['open'] else 1)
                for i in range(N-1) if data[i]['body_ratio']<thresh and data[i]['dir']!=0]
        add(f'Doji-Rev(<{thresh})', sigs, min_n=10)

    for thresh in [0.80,0.90,0.95]:
        for mode,m in [('Marub-Mom','mom'),('Marub-Rev','rev')]:
            sigs = [(i, data[i]['dir'] if m=='mom' else -data[i]['dir'])
                    for i in range(N-1) if data[i]['body_ratio']>=thresh and data[i]['dir']!=0]
            add(f'{mode}(>{thresh})', sigs)

    for window in [10,20]:
        for mult in [1.5,2.0,3.0]:
            for mode,m in [('Vol-Mom','mom'),('Vol-Fade','fade')]:
                sigs = []
                for i in range(window, N-1):
                    avg_v = sum(vols[i-window:i])/window
                    if vols[i]<avg_v*mult or data[i]['dir']==0: continue
                    sigs.append((i, data[i]['dir'] if m=='mom' else -data[i]['dir']))
                add(f'{mode}(>{mult}x,w={window})', sigs, min_n=20)

    for atr_p in [10,20]:
        for regime in ['High-ATR','Low-ATR']:
            for mode,m in [('Mom','mom'),('Rev','rev')]:
                sigs = []
                for i in range(atr_p, N-1):
                    atr = sum(trs[i-atr_p:i])/atr_p
                    hi  = regime=='High-ATR'
                    in_r = (trs[i]>atr) if hi else (trs[i]<atr*0.5)
                    if not in_r or data[i]['dir']==0: continue
                    sigs.append((i, data[i]['dir'] if m=='mom' else -data[i]['dir']))
                add(f'ATR({atr_p}){regime}-{mode}', sigs, min_n=20)

    for pct in [0.05,0.10,0.20,0.50]:
        sigs = []
        for i in range(1, N-1):
            pr = (data[i]['close']-data[i-1]['close'])/data[i-1]['close']*100
            if abs(pr)>=pct and data[i]['dir']!=0:
                sigs.append((i, -data[i]['dir']))
        add(f'BigMove-Fade(>={pct}%)', sigs, min_n=20)

    for window in [20,60]:
        for mode,m in [('VWAP-Mom','mom'),('VWAP-Rev','rev')]:
            sigs = []
            for i in range(window, N-1):
                seg  = data[i-window:i+1]
                tv   = sum(((d['high']+d['low']+d['close'])/3)*d['vol'] for d in seg)
                v    = sum(d['vol'] for d in seg)
                vwap = tv/v if v else data[i]['close']
                above = data[i]['close']>vwap
                sigs.append((i, 1 if (above==(m=='mom')) else -1))
            add(f'{mode}(w={window})', sigs)

    res.sort(key=lambda x: -x['wr'])
    return res

# ── Hourly analysis ───────────────────────────────────────────────────────────
def hourly_wr(data, payout, be):
    N = len(data)
    hours = []
    for h in range(24):
        sigs_u = [(i,  1) for i in range(N-1) if data[i]['hour']==h]
        sigs_d = [(i, -1) for i in range(N-1) if data[i]['hour']==h]
        wr_u, nu, _ = evaluate(sigs_u, data, payout)
        wr_d, nd, _ = evaluate(sigs_d, data, payout)
        best = max(wr_u, wr_d)
        # Bonferroni-correct for testing both directions
        if wr_u >= wr_d:
            z, p = ztest(wr_u, nu, h0=be); p = min(1.0, round(p*2, 4))
        else:
            z, p = ztest(wr_d, nd, h0=be); p = min(1.0, round(p*2, 4))
        hours.append({'h':h,'wr_u':wr_u,'wr_d':wr_d,'best':best,
                      'dir':'UP' if wr_u>=wr_d else 'DN','n':nu,'z':z,'p':p,
                      'beats': best>be})
    return hours

# ── Load & run ────────────────────────────────────────────────────────────────
CONFIGS = [
    ('BTC','30s','btcusdt_30s_2d.csv','2 days'),
    ('ETH','30s','ethusdt_30s_2d.csv','2 days'),
    ('BTC','1m', 'btcusdt_1m_7d.csv', '7 days'),
    ('ETH','1m', 'ethusdt_1m_7d.csv', '7 days'),
    ('BTC','5m', 'btcusdt_5m_7d.csv', '7 days'),
    ('ETH','5m', 'ethusdt_5m_7d.csv', '7 days'),
    ('BTC','10m','btcusdt_10m_7d.csv','7 days'),
    ('ETH','10m','ethusdt_10m_7d.csv','7 days'),
]

ALL = {}
for sym, tf, fname, period in CONFIGS:
    key    = f"{sym} {tf}"
    payout = tf_payout(tf)
    be     = tf_be(tf)
    print(f"  Analysing {key} ({period}) | payout={payout*100:.0f}% | BE={be*100:.3f}%...")
    data = load(fname)
    N = len(data)
    up_pct = sum(1 for i in range(N-1) if data[i+1]['close']>data[i]['close'])/(N-1)
    strats = run_all(data, payout, be)
    hours  = hourly_wr(data, payout, be)
    ALL[key] = {
        'sym': sym, 'tf': tf, 'period': period,
        'payout': payout, 'be': be,
        'n': N,
        'up_pct': round(up_pct, 4),
        'price_start': round(data[0]['close'], 2),
        'price_end':   round(data[-1]['close'], 2),
        'date_start':  data[0]['sgt_date'],
        'date_end':    data[-1]['sgt_date'],
        'strats': strats,
        'hours':  hours,
        'n_beats': sum(1 for s in strats if s['beats']),
        'n_sig':   sum(1 for s in strats if s['sig'] and s['beats']),
    }

# ── HTML helpers ──────────────────────────────────────────────────────────────
CSS = """
<style>
:root{--bg:#0f1117;--card:#1a1d27;--border:#2a2d3a;--text:#e2e8f0;--muted:#64748b;
      --green:#22c55e;--red:#ef4444;--yellow:#eab308;--blue:#60a5fa;--accent:#6366f1;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--text);font-family:system-ui,sans-serif;font-size:13px;line-height:1.5;}
a{color:var(--accent);text-decoration:none;}
.header{background:linear-gradient(135deg,#1e1b4b 0%,#0f1117 100%);padding:22px 32px;
        border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;}
.header h1{font-size:22px;font-weight:700;}
.header p{color:var(--muted);font-size:12px;margin-top:4px;}
.badge{background:var(--accent);color:#fff;padding:2px 10px;border-radius:99px;font-size:11px;font-weight:600;margin-left:10px;}
nav{background:#13151f;border-bottom:1px solid var(--border);padding:0 32px;display:flex;gap:2px;}
nav a{display:block;padding:11px 16px;color:var(--muted);font-size:12px;font-weight:500;
      border-bottom:2px solid transparent;transition:.15s;}
nav a:hover{color:var(--text);}
nav a.active{color:var(--text);border-bottom-color:var(--accent);}
.page{padding:28px 32px;}
.section{margin-bottom:32px;}
h2{font-size:16px;font-weight:600;margin-bottom:14px;}
h3{font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px;}
.grid{display:grid;gap:14px;}
.g2{grid-template-columns:1fr 1fr;}
.g3{grid-template-columns:1fr 1fr 1fr;}
.g6{grid-template-columns:repeat(6,1fr);}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:18px;}
.stat{font-size:28px;font-weight:700;line-height:1;}
.sub{font-size:11px;color:var(--muted);margin-top:4px;}
table{width:100%;border-collapse:collapse;font-size:12px;}
thead tr{background:#13151f;}
th{padding:9px 10px;text-align:left;color:var(--muted);font-weight:500;
   border-bottom:1px solid var(--border);white-space:nowrap;}
td{padding:7px 10px;border-bottom:1px solid #1a1d27;white-space:nowrap;}
tr:last-child td{border-bottom:none;}
tr:hover td{background:#1e2130;}
.g{color:var(--green);} .r{color:var(--red);} .y{color:var(--yellow);} .b{color:var(--blue);}
.pill{display:inline-block;padding:1px 8px;border-radius:99px;font-size:10px;font-weight:600;}
.pg{background:#14532d;color:#86efac;} .pr{background:#450a0a;color:#fca5a5;}
.py{background:#422006;color:#fde68a;} .pb{background:#1e3a5f;color:#93c5fd;}
.pm{background:#1e2130;color:#94a3b8;}
.verdict{border-radius:10px;padding:14px 18px;border-left:4px solid;}
.vs{background:#052e16;border-color:var(--green);}
.vw{background:#422006;border-color:var(--yellow);}
.vd{background:#450a0a;border-color:var(--red);}
.divider{border:none;border-top:1px solid var(--border);margin:16px 0;}
.heat{display:grid;grid-template-columns:repeat(24,1fr);gap:2px;margin-top:8px;}
.hcell{padding:6px 2px;border-radius:3px;text-align:center;font-size:9px;font-weight:700;}
.footnote{color:var(--muted);font-size:11px;margin-top:8px;font-style:italic;}
.tf-label{display:inline-block;padding:2px 10px;border-radius:6px;font-size:11px;
          font-weight:600;background:#1e3a5f;color:#93c5fd;margin-right:6px;}
</style>
"""

def pill(wr, be=BREAKEVEN, n=None):
    txt = f"{wr*100:.2f}%"
    if n is not None and n < 50:
        return f'<span class="pill pm">{txt}</span>'
    if wr > be:      return f'<span class="pill pg">{txt}</span>'
    if wr > be-0.02: return f'<span class="pill py">{txt}</span>'
    return f'<span class="pill pr">{txt}</span>'

def status(s):
    if s['sig'] and s['beats']: return '<span class="pill pg">SIG + EDGE</span>'
    if s['beats']:              return '<span class="pill py">Beats BE</span>'
    if s['sig']:                return '<span class="pill pb">Sig only</span>'
    return '<span class="pill pm">–</span>'

def evcolor(v):
    cls = 'g' if v > 0 else 'r'
    return f'<span class="{cls}">{v:+.4f}</span>'

def heatcolor(wr, be=BREAKEVEN):
    # green if above BE, red if below, yellow in between
    if wr > be:
        intensity = min(1, (wr - BREAKEVEN) / 0.08)
        r = int(34  + intensity * 40)
        g = int(197 - intensity * 50)
        b = int(94  - intensity * 60)
    else:
        intensity = min(1, (be - wr) / 0.08)
        r = int(239 - intensity * 50)
        g = int(68  - intensity * 30)
        b = int(68  - intensity * 30)
    return f"rgb({r},{g},{b})"

def strat_table(strats, be=BREAKEVEN, limit=None, only_beats=False):
    rows = [s for s in strats if (not only_beats or s['beats'])]
    if limit: rows = rows[:limit]
    if not rows:
        return '<p style="color:var(--muted);padding:12px;">No results.</p>'
    h = '''<table><thead><tr>
        <th>#</th><th>Strategy</th><th>Win Rate</th><th>Edge vs BE</th>
        <th>n bets</th><th>EV/$1</th><th>z-score</th><th>p-value</th><th>Status</th>
    </tr></thead><tbody>'''
    for i, s in enumerate(rows):
        edge = (s['wr'] - be) * 100
        ec   = 'g' if edge >= 0 else 'r'
        pc   = 'g' if s['p'] < 0.05 else ''
        h += f'''<tr>
            <td style="color:var(--muted);">{i+1}</td>
            <td style="font-family:monospace;color:var(--blue);">{s["name"]}</td>
            <td>{pill(s["wr"], be, s["n"])}</td>
            <td><span class="{ec}">{edge:+.2f}pp</span></td>
            <td>{s["n"]:,}</td>
            <td>{evcolor(s["ev"])}</td>
            <td style="color:var(--muted);">{s["z"]:+.2f}</td>
            <td class="{pc}">{s["p"]}</td>
            <td>{status(s)}</td>
        </tr>'''
    h += '</tbody></table>'
    return h

def hour_heatmap(hours, be=BREAKEVEN):
    h = '<div class="heat">'
    for hr in hours:
        bg   = heatcolor(hr['best'], be)
        beat = '▲' if hr['best'] > be else ''
        h += f'<div class="hcell" style="background:{bg};color:#fff;" title="{hr["h"]:02d}:00 SGT — WR {hr["best"]*100:.1f}% n={hr["n"]}">'
        h += f'<div>{hr["h"]:02d}</div><div>{hr["best"]*100:.1f}</div><div style="font-size:8px;">{hr["dir"]}{beat}</div></div>'
    h += '</div>'
    h += '''<table style="margin-top:12px;font-size:11px;"><thead><tr>
        <th>Hour (SGT)</th><th>Best Dir</th><th>Best WR</th><th>WR UP</th><th>WR DN</th>
        <th>n</th><th>z</th><th>p (adj)</th><th>WR &gt; BE?</th></tr></thead><tbody>'''
    for hr in hours:
        dc  = 'r' if hr['dir']=='DN' else 'g'
        bst = hr['beats']
        pc  = 'g' if hr['p'] < 0.05 else ''
        h += f'''<tr>
            <td><b>{hr["h"]:02d}:00</b></td>
            <td><span class="{dc}">{hr["dir"]}</span></td>
            <td>{pill(hr["best"], be)}</td>
            <td class="g">{hr["wr_u"]*100:.2f}%</td>
            <td class="r">{hr["wr_d"]*100:.2f}%</td>
            <td>{hr["n"]}</td>
            <td>{hr["z"]:+.2f}</td>
            <td class="{pc}">{hr["p"]}</td>
            <td>{"<span class='pill pg'>YES</span>" if bst else "<span class='pill pm'>no</span>"}</td>
        </tr>'''
    h += '</tbody></table>'
    return h

# ── Build HTML sections ───────────────────────────────────────────────────────
def section_overview():
    # Summary cards
    h = '<div class="grid g6" style="margin-bottom:24px;">'
    for key, d in ALL.items():
        pch = (d['price_end']-d['price_start'])/d['price_start']*100
        pc  = 'g' if pch>=0 else 'r'
        dn  = (1-d['up_pct'])*100
        h += f'''<div class="card">
            <h3>{d["sym"]} <span class="tf-label">{d["tf"]}</span></h3>
            <div class="stat">{d["n"]:,}</div>
            <div class="sub">active candles &bull; {d["period"]}</div>
            <div class="sub" style="margin-top:8px;">{d["date_start"]} → {d["date_end"]}</div>
            <hr class="divider">
            <div class="sub">Price change: <span class="{pc}">{pch:+.2f}%</span></div>
            <div class="sub">DOWN bias: <b>{dn:.2f}%</b></div>
            <div class="sub">Payout: <b>{d["payout"]*100:.0f}%</b> &bull; BE: <b>{d["be"]*100:.3f}%</b></div>
            <div class="sub" style="margin-top:6px;">
                Beats BE: <b style="color:{"var(--green)" if d["n_sig"]>0 else "var(--text)"}">
                {d["n_sig"]} sig</b> / {d["n_beats"]} total
            </div>
        </div>'''
    h += '</div>'

    # All significant findings
    sig_all = []
    for key, d in ALL.items():
        for s in d['strats']:
            if s['sig'] and s['beats']:
                sig_all.append({**s, 'asset': key})
    sig_all.sort(key=lambda x: -x['wr'])

    h += '<div class="grid g2">'

    # Sig table
    h += '<div class="card"><h3>Statistically Significant Edges (p&lt;0.05, WR&gt;breakeven, n&#8805;50)</h3>'
    if sig_all:
        h += '''<table><thead><tr><th>Asset/TF</th><th>Strategy</th><th>Payout</th><th>Win Rate</th>
                <th>BE</th><th>Edge</th><th>n</th><th>EV/$100</th><th>p-val</th></tr></thead><tbody>'''
        for s in sig_all[:15]:
            be   = ALL[s['asset']]['be']
            edge = (s['wr'] - be)*100
            h += f'''<tr>
                <td><b>{s["asset"]}</b></td>
                <td style="font-family:monospace;color:var(--blue);">{s["name"]}</td>
                <td>{ALL[s["asset"]]["payout"]*100:.0f}%</td>
                <td>{pill(s["wr"], be)}</td>
                <td style="color:var(--muted);">{be*100:.3f}%</td>
                <td class="g">+{edge:.2f}pp</td>
                <td>{s["n"]:,}</td>
                <td class="g">+${s["ev"]*100:.2f}</td>
                <td class="g">{s["p"]}</td></tr>'''
        h += '</tbody></table>'
    else:
        h += '<div class="verdict vs" style="margin-top:8px;"><b>No exploitable edges found.</b><br><span style="color:var(--muted);font-size:12px;">No strategy beats breakeven with statistical significance across any timeframe.</span></div>'
    h += '</div>'

    # Market bias table
    h += '<div class="card"><h3>Market Direction Bias</h3>'
    h += '''<table><thead><tr><th>Asset</th><th>TF</th><th>Period</th><th>UP%</th>
            <th>DOWN%</th><th>Down Bias vs 50%</th><th>Candles</th></tr></thead><tbody>'''
    for key, d in ALL.items():
        up  = d['up_pct']*100
        dn  = (1-d['up_pct'])*100
        bias = dn - 50
        bc  = 'g' if bias > 0 else 'r'
        h += f'''<tr>
            <td><b>{d["sym"]}</b></td>
            <td><span class="pill pb">{d["tf"]}</span></td>
            <td>{d["period"]}</td>
            <td class="g">{up:.2f}%</td>
            <td class="r">{dn:.2f}%</td>
            <td><span class="{bc}">{bias:+.2f}pp</span></td>
            <td>{d["n"]:,}</td></tr>'''
    h += '</tbody></table>'
    h += '<p class="footnote">Note: Even 52-53% DOWN bias is far below the 55.56% breakeven needed to profit.</p>'
    h += '</div></div>'

    return h

def section_all_strategies():
    h = ''
    for key, d in ALL.items():
        h += f'<div class="section"><h2>{key} — All Strategies <span class="tf-label">{d["period"]}</span></h2>'
        h += f'<p class="footnote" style="margin-bottom:10px;">{d["n"]:,} active candles | {d["date_start"]} to {d["date_end"]} | Payout: {d["payout"]*100:.0f}% | BE: {d["be"]*100:.3f}% | {d["n_beats"]} beat BE | {d["n_sig"]} statistically significant</p>'
        h += '<div class="card">' + strat_table(d["strats"], d["be"]) + '</div></div>'
    return h

def section_hourly():
    h = ''
    for key, d in ALL.items():
        beats = sum(1 for hr in d['hours'] if hr['beats'])
        h += f'<div class="section"><h2>{key} — Hourly Win Rate Heatmap</h2>'
        h += f'<p class="footnote" style="margin-bottom:10px;">{beats}/24 hours beat breakeven ({d["be"]*100:.3f}% at {d["payout"]*100:.0f}% payout) &bull; All times in Singapore Time (SGT = UTC+8)</p>'
        h += '<div class="card">' + hour_heatmap(d['hours'], d['be']) + '</div></div>'
    return h

def section_streaks():
    h = ''
    for key, d in ALL.items():
        streak_strats = [s for s in d['strats'] if 'Streak' in s['name']]
        if not streak_strats: continue
        h += f'<div class="section"><h2>{key} Streaks</h2>'
        h += '<div class="card">' + strat_table(streak_strats, d['be']) + '</div></div>'
    return h

def section_rsi():
    h = '<div class="card" style="margin-bottom:20px;"><h3>RSI Strategy Results — All Timeframes</h3>'
    h += '''<table><thead><tr><th>Asset/TF</th><th>Payout</th><th>BE</th><th>RSI Period</th><th>OB/OS</th>
            <th>Win Rate</th><th>n</th><th>EV/$1</th><th>z</th><th>p-val</th><th>Status</th>
            </tr></thead><tbody>'''
    for key, d in ALL.items():
        rsi_rows = [s for s in d['strats'] if s['name'].startswith('RSI')]
        for s in rsi_rows:
            pc = 'g' if s['p'] < 0.05 else ''
            h += f'''<tr>
                <td><b>{key}</b></td>
                <td>{d["payout"]*100:.0f}%</td>
                <td style="color:var(--muted);">{d["be"]*100:.3f}%</td>
                <td>{"14" if "14" in s["name"] else "7"}</td>
                <td style="font-family:monospace;">{s["name"].split(")")[1].strip()}</td>
                <td>{pill(s["wr"], d["be"], s["n"])}</td>
                <td>{s["n"]:,}</td>
                <td>{evcolor(s["ev"])}</td>
                <td>{s["z"]:+.2f}</td>
                <td class="{pc}">{s["p"]}</td>
                <td>{status(s)}</td></tr>'''
    h += '</tbody></table></div>'

    sig_rsi = [s for key, d in ALL.items() for s in d['strats'] if s['name'].startswith('RSI') and s['sig'] and s['beats']]
    if sig_rsi:
        h += '<div class="verdict vd">'
        h += f'<b>RSI Edge Detected on {len(sig_rsi)} combination(s)</b><ul style="margin-top:8px;margin-left:16px;color:var(--muted);">'
        for s in sig_rsi:
            h += f'<li>{s["name"]} — WR={s["wr"]*100:.2f}%  EV/bet={s["ev"]:+.4f}  p={s["p"]}</li>'
        h += '</ul></div>'
    else:
        h += '<div class="verdict vs"><b>RSI: No Significant Edge Found</b><br><span style="color:var(--muted);font-size:12px;">RSI does not consistently beat the breakeven threshold with statistical significance across any timeframe.</span></div>'
    return h

def section_risk():
    sig_all = []
    for key, d in ALL.items():
        for s in d['strats']:
            if s['sig'] and s['beats']:
                sig_all.append({**s, 'asset': key})

    risk_level = 'DANGER' if len(sig_all) >= 3 else ('WARNING' if len(sig_all) >= 1 else 'LOW')
    vc = {'DANGER':'vd','WARNING':'vw','LOW':'vs'}[risk_level]

    h = f'<div class="verdict {vc}" style="margin-bottom:24px;">'
    h += f'<b style="font-size:16px;">Overall Risk Level: {risk_level}</b>'
    h += f'<p style="color:var(--muted);margin-top:6px;">Statistically significant edges found: {len(sig_all)} strategy/timeframe combinations</p></div>'

    if sig_all:
        h += '<div class="card" style="margin-bottom:20px;"><h3>Confirmed Exploitable Strategies</h3>'
        h += '''<table><thead><tr><th>Asset/TF</th><th>Strategy</th><th>Win Rate</th>
                <th>Edge</th><th>EV per $100 bet</th><th>n bets</th><th>p-val</th></tr></thead><tbody>'''
        for s in sig_all:
            edge = (s['wr']-BREAKEVEN)*100
            h += f'''<tr>
                <td><b>{s["asset"]}</b></td>
                <td style="font-family:monospace;color:var(--blue);">{s["name"]}</td>
                <td>{pill(s["wr"])}</td>
                <td class="g">+{edge:.2f}pp</td>
                <td class="g">+${s["ev"]*100:.2f}</td>
                <td>{s["n"]:,}</td>
                <td class="g">{s["p"]}</td></tr>'''
        h += '</tbody></table></div>'

    # Payout table
    h += '<div class="card" style="margin-bottom:20px;"><h3>Breakeven Win Rate by Payout</h3>'
    h += '''<table><thead><tr><th>Payout Rate</th><th>Breakeven Win Rate</th><th>Products</th><th>Assessment</th></tr></thead><tbody>'''
    current = {80: '30s + 10m', 83: '1m', 85: '5m'}
    for po in [70,72,75,77,78,79,80,82,83,85,90]:
        be_val = 1/(1+po/100)
        prod   = current.get(po, '')
        note   = f'&#8592; {prod}' if prod else ('More protection' if po < 80 else 'Less protection')
        bold   = 'font-weight:700;' if prod else ''
        h += f'<tr style="{bold}"><td><b>{po}%</b></td><td>{be_val*100:.3f}%</td>'
        h += f'<td style="color:var(--blue);">{prod}</td><td style="color:var(--muted);">{note}</td></tr>'
    h += '</tbody></table></div>'

    # Mitigations
    h += '''<div class="card"><h3>Recommended Platform Mitigations</h3>
    <table><thead><tr><th>#</th><th>Action</th><th>Applies To</th><th>Effort</th><th>Impact</th></tr></thead><tbody>
    <tr><td>1</td><td><b>Reduce payout to 75%</b> — raises breakeven to 57.14%, adds 1.58pp buffer</td>
        <td>All products</td><td class="g">Low</td><td class="g">High</td></tr>
    <tr><td>2</td><td><b>Server-side RSI monitor</b> — detect RSI>70/&lt;30, auto-reduce max bet size by 50% when triggered</td>
        <td>ETH 1m &amp; 5m</td><td class="y">Medium</td><td class="y">Medium</td></tr>
    <tr><td>3</td><td><b>Settlement jitter</b> — add 0.5–2s random delay to close time, prevents last-second reading</td>
        <td>30s product</td><td class="g">Low</td><td class="y">Medium</td></tr>
    <tr><td>4</td><td><b>Streak-based bet cap</b> — after 5+ same-direction candles, reduce max bet to $25</td>
        <td>All products</td><td class="g">Low</td><td class="y">Medium</td></tr>
    <tr><td>5</td><td><b>Re-run this analysis weekly</b> — patterns shift, catch new edges before they compound</td>
        <td>Operations</td><td class="g">Low</td><td class="g">High</td></tr>
    <tr><td>6</td><td><b>Per-user win-rate monitoring</b> — flag users consistently winning >60% over 100+ bets</td>
        <td>Risk ops</td><td class="y">Medium</td><td class="g">High</td></tr>
    </tbody></table></div>'''
    return h

def section_guide():
    STRATS = [
        ('Baseline', [
            ('Always UP',   'Always bet the next candle closes higher. No logic — pure directional baseline.'),
            ('Always DOWN', 'Always bet the next candle closes lower. Used to measure raw market direction bias.'),
        ]),
        ('Momentum & Reversion', [
            ('Momentum(n)', 'Look at the last n candles. If the net direction was UP, bet UP. Assumes trends continue.'),
            ('Reversion(n)', 'Look at the last n candles. If the net direction was UP, bet DOWN. Assumes prices snap back. n tested: 1, 2, 3, 5, 10, 20.'),
        ]),
        ('Streaks', [
            ('Streak-Mom(n)', 'If exactly the last n candles ALL moved the same direction, bet that direction continues. e.g. 5 reds in a row → bet red again.'),
            ('Streak-Rev(n)', 'If exactly the last n candles ALL moved the same direction, bet the reversal. e.g. 5 reds → bet green. n tested: 2–7.'),
        ]),
        ('Moving Average Crossover', [
            ('MA(fast × slow)', 'Compute a fast moving average and a slow moving average of closing prices. If fast > slow, trend is up → bet UP. If fast < slow → bet DOWN. Pairs tested: (2,5), (3,10), (5,20), (10,30).'),
        ]),
        ('RSI — Relative Strength Index', [
            ('RSI(period) OB/OS', 'RSI measures momentum on a 0–100 scale. Above overbought (OB) threshold → bet DOWN (reversion). Below oversold (OS) threshold → bet UP. Periods: 7, 14. Thresholds: 70/30, 65/35, 60/40.'),
        ]),
        ('Candle Shape', [
            ('Doji-Rev(<thresh)', 'A Doji candle has open ≈ close (tiny body vs total range). Signals indecision. Strategy: bet the next candle reverses. Body ratio thresholds: <2%, <5%, <10%. Flat candles (open = close exactly) are excluded.'),
            ('Marub-Mom(>thresh)', 'A Marubozu candle has a very large body relative to range — a strong decisive move. Bet the move continues next candle. Thresholds: >80%, >90%, >95% body ratio.'),
            ('Marub-Rev(>thresh)', 'Same Marubozu detection, but bet the strong move reverses next candle.'),
        ]),
        ('Volume', [
            ('Vol-Mom(>Nx, w=W)', 'If this candle\'s volume is N times above the rolling W-candle average AND the candle has a direction, bet that direction continues. Volume spike = conviction.'),
            ('Vol-Fade(>Nx, w=W)', 'Same volume spike detection, but bet the opposite direction — the spike was the climax and price fades. Multipliers: 1.5×, 2×, 3×. Windows: 10, 20.'),
        ]),
        ('ATR — Volatility Regime', [
            ('ATR(p) High-ATR-Mom/Rev', 'ATR (Average True Range) measures how much price moves per candle. In a HIGH volatility regime (current range > ATR average), bet momentum continues or reverses.'),
            ('ATR(p) Low-ATR-Mom/Rev',  'In a LOW volatility regime (current range < 50% of ATR average), bet momentum or reversal. Periods: 10, 20.'),
        ]),
        ('VWAP — Volume Weighted Average Price', [
            ('VWAP-Mom(w=W)', 'VWAP is the average price weighted by volume over a rolling window. If current price is above VWAP → bet UP (price has upward momentum). Window: 20, 60 candles.'),
            ('VWAP-Rev(w=W)', 'If price is above VWAP → bet DOWN (price will revert to the mean). Same windows.'),
        ]),
        ('Big Move Fade', [
            ('BigMove-Fade(≥x%)', 'If a candle moved ≥x% from the previous close, bet the next candle reverses. Based on the idea that sharp moves overextend and snap back. Thresholds: 0.05%, 0.10%, 0.20%, 0.50%.'),
        ]),
    ]

    h = '<div class="card" style="margin-bottom:20px;">'
    h += '<h3>How to Read Results</h3>'
    h += ('<table><thead><tr><th>Badge</th><th>Meaning</th><th>Risk to Platform</th></tr></thead><tbody>'
          '<tr><td><span class="pill pg">SIG + EDGE</span></td>'
          '<td>Win rate &gt; 55.56% <b>and</b> statistically proven (p&lt;0.05, n&#8805;50)</td>'
          '<td class="r"><b>HIGH &#8212; exploitable</b></td></tr>'
          '<tr><td><span class="pill py">Beats BE</span></td>'
          '<td>Win rate &gt; 55.56% but may be luck &#8212; not enough data to confirm</td>'
          '<td class="y">Monitor</td></tr>'
          '<tr><td><span class="pill pb">Sig only</span></td>'
          '<td>Statistically proven pattern but win rate is <b>below</b> breakeven &#8212; a reliable loser</td>'
          '<td class="g">Good for platform</td></tr>'
          '<tr><td><span class="pill pm">&#8212;</span></td>'
          '<td>No pattern &#8212; noise</td>'
          '<td class="g">No risk</td></tr>'
          '</tbody></table>')
    h += '<p class="footnote" style="margin-top:12px;">Breakeven = 55.56% for 80% payout. Formula: 1 ÷ (1 + 0.80) = 0.5556. Any strategy consistently above this is a platform risk.</p>'
    h += '</div>'

    for group, items in STRATS:
        h += f'<div class="card" style="margin-bottom:16px;"><h3>{group}</h3>'
        h += '<table><thead><tr><th style="width:220px;">Strategy</th><th>What it does</th></tr></thead><tbody>'
        for name, desc in items:
            h += f'<tr><td style="font-family:monospace;color:var(--blue);vertical-align:top;">{name}</td><td style="color:var(--muted);">{desc}</td></tr>'
        h += '</tbody></table></div>'

    return h

# ── Assemble full HTML ────────────────────────────────────────────────────────
NAV_ITEMS = [
    ('overview',    'Overview'),
    ('strategies',  'All Strategies'),
    ('hourly',      'Hourly Heatmap'),
    ('rsi',         'RSI Analysis'),
    ('streaks',     'Streaks'),
    ('risk',        'Platform Risk'),
    ('guide',       'Strategy Guide'),
]

SECTIONS = {
    'overview':   section_overview(),
    'strategies': section_all_strategies(),
    'hourly':     section_hourly(),
    'rsi':        section_rsi(),
    'streaks':    section_streaks(),
    'risk':       section_risk(),
    'guide':      section_guide(),
}

nav_html = '<nav>'
for sid, label in NAV_ITEMS:
    active = 'active' if sid == 'overview' else ''
    nav_html += f'<a href="#{sid}" class="{active}" onclick="show(\'{sid}\')">{label}</a>'
nav_html += '</nav>'

pages_html = ''
for sid, label in NAV_ITEMS:
    display = 'block' if sid == 'overview' else 'none'
    pages_html += f'<div id="{sid}" style="display:{display};">'
    pages_html += f'<div class="page"><h2>{label}</h2>{SECTIONS[sid]}</div>'
    pages_html += '</div>'

built_at = datetime.now(SGT).strftime('%Y-%m-%d %H:%M SGT')

JS = """
<script>
function show(id) {
    var ids = ['overview','strategies','hourly','rsi','streaks','risk'];
    ids.forEach(function(i) { document.getElementById(i).style.display = 'none'; });
    document.getElementById(id).style.display = 'block';
    document.querySelectorAll('nav a').forEach(function(a) {
        a.classList.toggle('active', a.getAttribute('href') === '#'+id);
    });
    window.scrollTo(0,0);
}
document.querySelectorAll('nav a').forEach(function(a) {
    a.addEventListener('click', function(e) {
        e.preventDefault();
        show(this.getAttribute('href').substring(1));
    });
});

// ── Refresh button logic ──────────────────────────────────────────────────────
var _poll = null;

function startRefresh() {
    var btn  = document.getElementById('refresh-btn');
    var stat = document.getElementById('refresh-status');
    btn.disabled = true;
    btn.textContent = 'Refreshing...';
    btn.style.background = '#422006';
    btn.style.borderColor = '#ca8a04';
    btn.style.color = '#fde68a';
    stat.textContent = 'Connecting to server...';
    stat.style.color = '#94a3b8';

    fetch('http://localhost:8765/refresh')
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (!d.ok) { showErr(d.msg); return; }
        stat.textContent = 'Fetching data...';
        _poll = setInterval(pollStatus, 1500);
      })
      .catch(function() {
        showErr('Cannot reach server. Is server.py running?  (python server.py)');
      });
}

function pollStatus() {
    fetch('http://localhost:8765/status')
      .then(function(r) { return r.json(); })
      .then(function(d) {
        var stat = document.getElementById('refresh-status');
        stat.textContent = '[' + d.ts + '] ' + d.msg;
        if (d.status === 'done') {
            clearInterval(_poll);
            stat.style.color = '#22c55e';
            setTimeout(function() { location.reload(); }, 800);
        } else if (d.status === 'error') {
            clearInterval(_poll);
            showErr(d.msg);
        }
      })
      .catch(function() {});
}

function showErr(msg) {
    var btn  = document.getElementById('refresh-btn');
    var stat = document.getElementById('refresh-status');
    btn.disabled = false;
    btn.textContent = 'Refresh Data';
    btn.style.background = '';
    btn.style.borderColor = '';
    btn.style.color = '';
    stat.textContent = 'Error: ' + msg;
    stat.style.color = '#ef4444';
}
</script>
"""

FULL_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Turboflow — Edge Analysis Dashboard</title>
{CSS}
<style>
#refresh-btn {{
    background: #1e3a5f; border: 1px solid #3b82f6; color: #93c5fd;
    padding: 8px 20px; border-radius: 8px; font-size: 13px; font-weight: 600;
    cursor: pointer; transition: .15s; white-space: nowrap;
}}
#refresh-btn:hover:not(:disabled) {{ background: #1d4ed8; border-color: #60a5fa; color: #fff; }}
#refresh-btn:disabled {{ opacity: .6; cursor: not-allowed; }}
#refresh-status {{ font-size: 11px; color: var(--muted); margin-top: 4px; min-height: 16px; }}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>Turboflow Binary Bet Edge Analysis <span class="badge">LIVE</span></h1>
    <p>30s 80% payout (2 days) &bull; 1m 83% (7 days) &bull; 5m 85% (7 days) &bull; 10m 80% (7 days) &bull; BTC + ETH</p>
  </div>
  <div style="text-align:right;">
    <button id="refresh-btn" onclick="startRefresh()">&#8635; Refresh Data</button>
    <div id="refresh-status">Last built: {built_at}</div>
    <div style="color:var(--muted);font-size:10px;margin-top:2px;">Requires server.py running</div>
  </div>
</div>
{nav_html}
{pages_html}
{JS}
</body>
</html>"""

with open('edge_dashboard.html', 'w', encoding='utf-8') as f:
    f.write(FULL_HTML)

import os
size = os.path.getsize('edge_dashboard.html')
sig_total = sum(d['n_sig'] for d in ALL.values())
print(f"Dashboard written -> edge_dashboard.html ({size/1024:.0f} KB)")
print(f"Total significant edges found: {sig_total}")
for key, d in ALL.items():
    print(f"  {key}: {d['n']:,} candles | beats BE: {d['n_beats']} | significant: {d['n_sig']}")
