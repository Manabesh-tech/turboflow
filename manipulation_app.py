from pathlib import Path

import pandas as pd
import streamlit as st


BASE = Path(__file__).parent


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


DEF_SPIKE = (
    "**Spike** — the 1-second price move at the exact settlement second was "
    "abnormally large compared to the prior 10s and 20s of normal trading. "
    "Measured as a z-score (how many standard deviations away from the recent baseline). "
    "Threshold: z ≥ 4.0. Tells you the price *moved unusually* at fix time."
)
DEF_SUSPICIOUS = (
    "**Suspicious** — a Spike *plus* an immediate reversal within 2 seconds. "
    "Classic manipulation signature: push the price at the fix second, then let it snap back. "
    "This is the stronger signal. A high suspicious rate means someone may be gaming the settlement."
)
COLOR_KEY = {
    "suspicious_pct": [(0, 2, "🟢 Safe"), (2, 5, "🟡 Watch"), (5, 100, "🔴 High Risk")],
    "spike_pct":      [(0, 10, "🟢 Safe"), (10, 20, "🟡 Watch"), (20, 100, "🔴 High Risk")],
    "risk":           [(0, 40, "🟢 Safe"), (40, 60, "🟡 Watch"), (60, 100, "🔴 High Risk")],
    "critical_pct":   [(0, 15, "🟢 Safe"), (15, 30, "🟡 Watch"), (30, 100, "🔴 High Risk")],
}


def _color_val(col: str, val):
    if pd.isna(val) or col not in COLOR_KEY:
        return ""
    for lo, hi, _ in COLOR_KEY[col]:
        if lo <= val < hi:
            if "Safe" in _:
                return "background-color: #2d6a2d; color: white"
            if "Watch" in _:
                return "background-color: #8a6200; color: white"
            return "background-color: #8a1a1a; color: white"
    return ""


def style_risk_table(df: pd.DataFrame) -> "pd.io.formats.style.Styler":
    """Apply traffic-light background colours to known risk columns."""
    styler = df.style
    for col in ["suspicious_pct", "spike_pct", "risk", "critical_pct"]:
        if col in df.columns:
            styler = styler.map(lambda v, c=col: _color_val(c, v), subset=[col])
    return styler


STYLE_LEGEND = (
    "🟢 **Safe** — within normal range   "
    "🟡 **Watch** — elevated, monitor closely   "
    "🔴 **High Risk** — restrict or harden settlement"
)


st.set_page_config(
    page_title="TurboFlow Manipulation Monitor",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("TurboFlow Binary Trading Manipulation Monitor")
st.caption("1-second fix spike detection + volatility risk profiling  |  All times in Singapore Time (SGT, UTC+8)")
st.info("Volatility Patterns tab defaults to T-6 decision-time model (window ends at T-6s before fix).")

with st.sidebar:
    st.header("Data Sources")
    spike_events_file = st.text_input("Spike events", value="fix_spike_events.csv")
    spike_hour_file = st.text_input("Spike risk by hour", value="fix_spike_risk_by_hour_utc.csv")
    spike_day_file = st.text_input("Spike risk by day", value="fix_spike_risk_by_day.csv")
    volatility_hour_file = st.text_input("Volatility risk by hour", value="fix_risk_by_hour_utc.csv")
    volatility_day_file = st.text_input("Volatility risk by day", value="fix_risk_by_day.csv")
    volatility_quartile_file = st.text_input("Volatility quartile summary", value="fix_volatility_10s_t6_quartile_summary.csv")
    volatility_decile_file = st.text_input("Volatility decile summary", value="fix_volatility_10s_t6_decile_summary.csv")
    st.markdown("---")
    st.write("Refresh analysis files before loading dashboard:")
    st.code(
        '& "./.venv/Scripts/python.exe" "binary trading manipulation.py" '
        '--polymarket polymarket_btc_5min_168h_2026-04-13.csv --symbol BTCUSDT --z-thresh 4.0 --outdir .'
    )

events = load_csv(BASE / spike_events_file)
by_hour_spike = load_csv(BASE / spike_hour_file)
by_day_spike = load_csv(BASE / spike_day_file)
by_hour_volatility = load_csv(BASE / volatility_hour_file)
by_day_volatility = load_csv(BASE / volatility_day_file)
by_volatility_quartile = load_csv(BASE / volatility_quartile_file)
by_volatility_decile = load_csv(BASE / volatility_decile_file)

if events.empty:
    st.error("No spike events file found. Run the detector script first.")
    st.stop()

events["fix_time_utc"] = pd.to_datetime(events["fix_time_utc"], utc=True, errors="coerce")
events = events.dropna(subset=["fix_time_utc"]).copy()

for col in ["spike_flag", "suspicious_flag", "reversal_2s", "is_weekend"]:
    if col in events.columns:
        events[col] = events[col].astype(str).str.lower().isin(["true", "1"])

# Convert all timestamps to Singapore Time (UTC+8)
SGT = "Asia/Singapore"
events["fix_time_sgt"] = events["fix_time_utc"].dt.tz_convert(SGT)
events["hour_sgt"] = events["fix_time_sgt"].dt.hour
events["dow_sgt"] = events["fix_time_sgt"].dt.day_name()
events["is_weekend_sgt"] = events["fix_time_sgt"].dt.dayofweek >= 5

total_fixes = len(events)
spike_pct = events["spike_flag"].mean() * 100
suspicious_pct = events["suspicious_flag"].mean() * 100
total_suspicious_n = int(events["suspicious_flag"].sum())
weekend_mask = events["is_weekend_sgt"]
weekend_pct = events.loc[weekend_mask, "suspicious_flag"].mean() * 100
weekday_pct = events.loc[~weekend_mask, "suspicious_flag"].mean() * 100
weekend_suspicious_n = int(events.loc[weekend_mask, "suspicious_flag"].sum())
weekday_suspicious_n = int(events.loc[~weekend_mask, "suspicious_flag"].sum())

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Fix windows analyzed", f"{total_fixes:,}")
col2.metric("Total suspicious fixings", f"{total_suspicious_n:,}")
col3.metric("Suspicious rate", f"{suspicious_pct:.2f}%")
col4.metric("Weekend suspicious (SGT)", f"{weekend_suspicious_n:,}", delta=f"{weekend_pct:.1f}%")
col5.metric("Weekday suspicious (SGT)", f"{weekday_suspicious_n:,}", delta=f"{weekday_pct:.1f}%")
col6.metric("Spike incidence", f"{spike_pct:.2f}%")

with st.expander("What do these numbers mean? (click to expand)", expanded=False):
    st.markdown(DEF_SPIKE)
    st.markdown(DEF_SUSPICIOUS)
    st.markdown("---")
    st.markdown(
        "**Spike %** — out of all fix windows, what % had an abnormal 1s move (z ≥ 4). "
        "This is a broad alert.\n\n"
        "**Suspicious %** — out of all fix windows, what % had a spike AND an immediate reversal. "
        "This is the narrow, high-confidence manipulation signal.\n\n"
        "**Rule of thumb:** Suspicious rate > 5% in any single hour = tighten controls."
    )
    st.markdown("---")
    st.markdown("### How z10 and z20 are calculated")
    st.markdown(
        "At every 5-minute Polymarket settlement second, the detector measures: "
        "how unusual was the price move *right now* compared to the recent calm?"
    )
    st.latex(r"""
        z_{10} = \frac{\left| r_{\text{fix}} - \mu_{10s} \right|}{\sigma_{10s}}
        \qquad
        z_{20} = \frac{\left| r_{\text{fix}} - \mu_{20s} \right|}{\sigma_{20s}}
    """)
    st.markdown(
        "Where:\n"
        "- $r_{\\text{fix}}$ = the 1-second log return at the exact fix second (in basis points)\n"
        "- $\\mu_{10s}$ = average 1-second return over the **prior 10 seconds**\n"
        "- $\\sigma_{10s}$ = standard deviation of 1-second returns over the **prior 10 seconds**\n"
        "- $z_{20}$ = same formula but using the **prior 20 seconds** as baseline\n"
        "- **zmax** = the larger of z10 and z20 — the strongest signal wins\n\n"
        "A z-score of 4 means the move was 4 standard deviations from normal. "
        "That happens by chance less than 0.003% of the time in a normal distribution. "
        "A threshold of z \u2265 4 is therefore a very conservative filter."
    )
    st.markdown("**Worked example from your data (row 109, 2026-04-08 06:00 SGT):**")
    st.markdown(
        "| | Value |\n"
        "|---|---|\n"
        "| Fix-second move | **+16.2 bp** (~$14 on BTC) |\n"
        "| Prior 10s average move | ~0.0 bp (flat) |\n"
        "| Prior 10s std deviation | ~0.01 bp (completely still) |\n"
        "| **z10** | **(16.2 - 0) / 0.01 = 1620** |\n"
        "| Prior 20s std deviation | ~0.35 bp (slightly more active) |\n"
        "| **z20** | **46.5** |\n"
        "| **zmax** | **1620** (z10 dominates) |\n"
        "| Reversal within 2s? | Yes |\n"
        "| **Verdict** | **Suspicious** \u2014 large move out of complete stillness, immediately reversed |"
    )
    st.markdown(
        "The key insight: BTC was **completely flat** for 10 seconds, then moved sharply at "
        "the exact settlement second, then snapped back. That is the classic manipulation pattern."
    )
    st.markdown(STYLE_LEGEND)

tabs = st.tabs(["Overview", "Hour and Day", "Volatility Patterns", "Event Explorer", "Protection Policy"])

with tabs[0]:
    st.subheader("Fix-Time Behavior")
    c1, c2 = st.columns(2)

    z_series = events["zmax"].dropna()
    c1.write("Z-score distribution")
    c1.bar_chart(z_series.clip(upper=z_series.quantile(0.99)).to_frame(name="zmax"))

    c2.write("Absolute fix move (bp)")
    c2.bar_chart(events["fix_ret_1s_bp"].abs().to_frame(name="abs_fix_move_bp"))

    st.write("Top suspicious events")
    top_cols = [
        "fix_time_sgt",
        "fix_ret_1s_bp",
        "z10",
        "z20",
        "zmax",
        "spike_flag",
        "reversal_2s",
        "suspicious_flag",
        "hour_sgt",
        "dow_sgt",
    ]
    st.dataframe(
        events.sort_values("zmax", ascending=False)[top_cols].head(25),
        use_container_width=True,
    )

with tabs[1]:
    st.subheader("Temporal Risk Profile")
    st.caption(STYLE_LEGEND)

    st.markdown(
        "**spike_pct** — % of fix windows in this hour/day where the 1s settlement move was abnormally large (z ≥ 4). "
        "**suspicious_pct** — % where the spike also reversed immediately (stronger manipulation signal)."
    )

    left, right = st.columns(2)
    if not by_hour_spike.empty:
        hh = by_hour_spike.copy()
        hh["hour_sgt"] = (hh["hour_utc"] + 8) % 24
        hh = hh.sort_values("hour_sgt").drop(columns=["hour_utc"], errors="ignore")
        hh = hh.rename(columns={
            "hour_sgt": "Hour (SGT)",
            "fixes": "Fixes",
            "avg_zmax": "Avg Z-score",
            "spike_pct": "spike_pct",
            "suspicious_pct": "suspicious_pct",
            "avg_abs_fix_bp": "Avg Move (bp)",
        })
        left.write("Spike & suspicious rate by SGT hour")
        left.bar_chart(hh.set_index("Hour (SGT)")[["suspicious_pct", "spike_pct"]])
        left.dataframe(style_risk_table(hh), use_container_width=True)

    if not by_day_spike.empty:
        dd = by_day_spike.copy()
        if "dow" in dd.columns:
            dd["dow"] = pd.Categorical(
                dd["dow"],
                categories=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
                ordered=True,
            )
            dd = dd.sort_values("dow")
        dd = dd.rename(columns={
            "dow": "Day",
            "fixes": "Fixes",
            "avg_zmax": "Avg Z-score",
            "spike_pct": "spike_pct",
            "suspicious_pct": "suspicious_pct",
            "avg_abs_fix_bp": "Avg Move (bp)",
        })
        right.write("Spike & suspicious rate by day of week (SGT)")
        right.bar_chart(dd.set_index("Day")[["suspicious_pct", "spike_pct"]])
        right.dataframe(style_risk_table(dd), use_container_width=True)

    if not by_hour_volatility.empty or not by_day_volatility.empty:
        st.markdown("---")
        st.subheader("Volatility / Liquidity Risk Context")
        st.markdown(
            "**risk** — composite manipulation-risk score (0–100). "
            "High = low volatility + low liquidity = easier to push price. "
            "**critical_pct** — % of fix windows in this hour/day that fell into the top-risk quartile."
        )
        vv1, vv2 = st.columns(2)
        if not by_hour_volatility.empty:
            hv = by_hour_volatility.copy()
            hv["hour_sgt"] = (hv["hour_utc"] + 8) % 24
            hv = hv.sort_values("hour_sgt").drop(columns=["hour_utc"], errors="ignore")
            hv = hv.rename(columns={
                "hour_sgt": "Hour (SGT)",
                "samples": "Samples",
                "rv10_bp": "Realized Volatility 10m (bp)",
                "vol10": "Trading Volume 10m",
                "trades10": "Trades 10m",
                "risk": "risk",
                "critical_pct": "critical_pct",
            })
            vv1.write("Volatility risk by SGT hour")
            vv1.bar_chart(hv.set_index("Hour (SGT)")[["risk", "critical_pct"]])
            vv1.dataframe(style_risk_table(hv), use_container_width=True)
        if not by_day_volatility.empty:
            dv = by_day_volatility.copy()
            if "dow" in dv.columns:
                dv["dow"] = pd.Categorical(
                    dv["dow"],
                    categories=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
                    ordered=True,
                )
                dv = dv.sort_values("dow")
            dv = dv.rename(columns={
                "dow": "Day",
                "samples": "Samples",
                "rv10_bp": "Realized Volatility 10m (bp)",
                "vol10": "Trading Volume 10m",
                "trades10": "Trades 10m",
                "risk": "risk",
                "critical_pct": "critical_pct",
            })
            vv2.write("Volatility risk by day of week (SGT)")
            vv2.bar_chart(dv.set_index("Day")[["risk", "critical_pct"]])
            vv2.dataframe(style_risk_table(dv), use_container_width=True)

with tabs[2]:
    st.subheader("Is Manipulation Volatility-Dependent?")

    st.info(
        "**Your thesis:** High volatility makes manipulation harder.  "
        "**What the 10-second data says:** yes, and more clearly than 10-minute data. "
        "Read the findings below."
    )

    corr_spike = float("nan")
    corr_suspicious = float("nan")
    if "realized_volatility_10s_ann_pct" in events.columns:
        vv = pd.to_numeric(events["realized_volatility_10s_ann_pct"], errors="coerce")
        valid = vv.notna()
        if valid.any():
            corr_spike = vv[valid].corr(events.loc[valid, "spike_flag"].astype(float))
            corr_suspicious = vv[valid].corr(events.loc[valid, "suspicious_flag"].astype(float))

    # Correlation summary
    corr_md = """
    | Measure | Corr with Spike rate | Corr with Suspicious rate |
    |---|---|---|
    | Realized Volatility (10s, annualized %) | {corr_spike:.3f} | {corr_suspicious:.3f} |

    **Conclusion from correlations:** Short-horizon volatility has clearer signal than 10-minute volatility.
    Higher 10-second volatility generally reduces both spike incidence and suspicious reversals.
    """.format(corr_spike=corr_spike, corr_suspicious=corr_suspicious)
    with st.expander("Correlation of volatility with manipulation rates", expanded=True):
        st.markdown(corr_md)

    st.markdown("---")
    st.subheader("Suspicious Rate by Volatility Bucket")
    st.markdown(
        "The data is split into 4 equal-sized groups (quartiles) by realized 10-second volatility. "
        "All volatility values here are **annualized percentages**."
    )

    if not by_volatility_quartile.empty:
        qt = by_volatility_quartile.copy()
        qt = qt.rename(columns={
            "volatility_quartile": "Volatility Group",
            "n": "Fix Windows",
            "avg_realized_volatility_10s_ann_pct": "Avg Realized Volatility (Ann. %)",
            "min_realized_volatility_10s_ann_pct": "Min Realized Volatility (Ann. %)",
            "max_realized_volatility_10s_ann_pct": "Max Realized Volatility (Ann. %)",
            "avg_realized_volatility_bp": "Avg Realized Volatility (bp)",
            "min_realized_volatility_bp": "Min Realized Volatility (bp)",
            "max_realized_volatility_bp": "Max Realized Volatility (bp)",
            "avg_volume_10m": "Avg Trading Volume 10m",
            "avg_trades_10m": "Avg Trade Count 10m",
            "spike_pct": "spike_pct",
            "suspicious_pct": "suspicious_pct",
        })
        q1, q2 = st.columns([2, 1])
        q1.bar_chart(qt.set_index("Volatility Group")[["suspicious_pct", "spike_pct"]])
        q2.dataframe(style_risk_table(qt), use_container_width=True)

        st.markdown(
            """
            **Key finding — T-6 decision-time view:**
            - **Q1 (Lowest 10s volatility at T-6):** suspicious rate = 3.53%
            - **Q2 (Med-Low):** suspicious rate = 3.54%
            - **Q3 (Med-High):** suspicious rate = **5.05%**
            - **Q4 (Highest 10s volatility):** suspicious rate = **1.52%**

            **Interpretation:** At T-6, risk is not strictly monotonic with volatility.
            Very high volatility remains safer, while both ultra-low and mid-high pre-fix
            regimes can show elevated suspicious incidence.

            **Practical implication:** Treat T-6 volatility as a regime classifier, not a single
            low-vol-only trigger.
            """
        )
    else:
        st.warning("Run recalc_t6_thresholds.py to generate fix_volatility_10s_t6_quartile_summary.csv")

    st.markdown("---")
    st.subheader("Fine-Grain View: Suspicious Rate by Volatility Decile")
    st.caption("Deciles split all fix windows into 10 equal groups by annualized 10-second volatility, D1 = quietest, D10 = most volatile.")
    if not by_volatility_decile.empty:
        dt = by_volatility_decile.copy()
        dt = dt.rename(columns={
            "volatility_decile": "Volatility Decile",
            "n": "Fix Windows",
            "avg_realized_volatility_10s_ann_pct": "Avg Realized Volatility (Ann. %)",
            "min_realized_volatility_10s_ann_pct": "Range Low (Ann. %)",
            "max_realized_volatility_10s_ann_pct": "Range High (Ann. %)",
            "avg_realized_volatility_bp": "Avg Realized Volatility (bp)",
            "min_realized_volatility_bp": "Range Low (bp)",
            "max_realized_volatility_bp": "Range High (bp)",
            "spike_pct": "spike_pct",
            "suspicious_pct": "suspicious_pct",
        })
        st.bar_chart(dt.set_index("Volatility Decile")[["suspicious_pct", "spike_pct"]])
        st.caption(STYLE_LEGEND)
        st.dataframe(style_risk_table(dt), use_container_width=True)
        st.markdown(
            "In the T-6 decision-time view, elevated suspicious rates appear in transitional mid-high "
            "volatility deciles, while the highest-volatility deciles remain lower risk."
        )
    else:
        st.warning("Run the enrichment analysis to generate fix_volatility_10s_decile_summary.csv")

with tabs[3]:
    st.subheader("Investigate Specific Fixes")
    z_cut = st.slider("Minimum zmax", min_value=0.0, max_value=20.0, value=4.0, step=0.5)
    only_suspicious = st.checkbox("Show only suspicious flags", value=True)

    filt = events[events["zmax"] >= z_cut].copy()
    if only_suspicious:
        filt = filt[filt["suspicious_flag"]]

    st.write(f"Filtered events: {len(filt):,}")

    # Only show the columns that matter — drop all redundant bp/pct/5s/20s volatility columns.
    keep_cols = [
        c for c in [
            "fix_time_sgt",
            "fix_ret_1s_bp",
            "z10",
            "z20",
            "zmax",
            "spike_flag",
            "reversal_2s",
            "suspicious_flag",
            "realized_volatility_10s_ann_pct",
            "hour_sgt",
            "dow_sgt",
        ] if c in filt.columns
    ]
    display_df = filt.sort_values("zmax", ascending=False)[keep_cols].copy()
    display_df = display_df.rename(columns={
        "fix_time_sgt": "Fix Time (SGT)",
        "fix_ret_1s_bp": "1s Move (bp)",
        "realized_volatility_10s_ann_pct": "10s Realized Volatility (Ann. %)",
        "hour_sgt": "Hour (SGT)",
        "dow_sgt": "Day",
    })
    fmt = {}
    if "1s Move (bp)" in display_df.columns:
        fmt["1s Move (bp)"] = "{:.3f}"
    if "10s Realized Volatility (Ann. %)" in display_df.columns:
        fmt["10s Realized Volatility (Ann. %)"] = "{:.4f}%"
    for c in ["z10", "z20", "zmax"]:
        if c in display_df.columns:
            fmt[c] = "{:.2f}"
    st.dataframe(
        display_df.style.format(fmt),
        use_container_width=True,
    )

with tabs[4]:
    st.subheader("Conclusion and Blackout Policy")

    # Build recommendation inputs directly from latest event data in SGT.
    rec = events.copy()
    rec["hour_sgt"] = rec["fix_time_sgt"].dt.hour
    rec["dow_sgt"] = rec["fix_time_sgt"].dt.day_name()

    hourly = (
        rec.groupby("hour_sgt")
        .agg(
            fixes=("suspicious_flag", "size"),
            suspicious_pct=("suspicious_flag", "mean"),
            spike_pct=("spike_flag", "mean"),
        )
        .assign(
            suspicious_pct=lambda d: d["suspicious_pct"] * 100,
            spike_pct=lambda d: d["spike_pct"] * 100,
        )
        .reset_index()
    )

    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    by_day = (
        rec.groupby("dow_sgt")
        .agg(
            fixes=("suspicious_flag", "size"),
            suspicious_pct=("suspicious_flag", "mean"),
            spike_pct=("spike_flag", "mean"),
        )
        .assign(
            suspicious_pct=lambda d: d["suspicious_pct"] * 100,
            spike_pct=lambda d: d["spike_pct"] * 100,
        )
        .reindex(day_order)
        .reset_index()
        .rename(columns={"dow_sgt": "Day"})
    )

    # Annualized 10-second volatility buckets for blackout gating.
    vol_quart = pd.DataFrame()
    if "realized_volatility_10s_ann_pct" in rec.columns:
        vv = rec[["realized_volatility_10s_ann_pct", "spike_flag", "suspicious_flag"]].copy()
        vv["realized_volatility_10s_ann_pct"] = pd.to_numeric(
            vv["realized_volatility_10s_ann_pct"], errors="coerce"
        )
        vv = vv.dropna(subset=["realized_volatility_10s_ann_pct"]).copy()
        if not vv.empty:
            rank = vv["realized_volatility_10s_ann_pct"].rank(method="first")
            vv["Volatility Quartile"] = pd.qcut(
                rank,
                4,
                labels=["Q1 Low", "Q2 Med-Low", "Q3 Med-High", "Q4 High"],
            )
            vol_quart = (
                vv.groupby("Volatility Quartile", observed=True)
                .agg(
                    fixes=("suspicious_flag", "size"),
                    min_ann_pct=("realized_volatility_10s_ann_pct", "min"),
                    max_ann_pct=("realized_volatility_10s_ann_pct", "max"),
                    suspicious_pct=("suspicious_flag", "mean"),
                    spike_pct=("spike_flag", "mean"),
                )
                .assign(
                    suspicious_pct=lambda d: d["suspicious_pct"] * 100,
                    spike_pct=lambda d: d["spike_pct"] * 100,
                )
                .reset_index()
            )

    # Blackout candidate logic: require enough samples and elevated suspicious incidence.
    blackout_hours = hourly[(hourly["fixes"] >= 50) & (hourly["suspicious_pct"] >= 5.0)].sort_values("hour_sgt")
    watch_hours = hourly[(hourly["fixes"] >= 50) & (hourly["suspicious_pct"].between(3.5, 5.0, inclusive="left"))].sort_values("hour_sgt")

    high_risk_days = by_day[(by_day["fixes"] >= 50) & (by_day["suspicious_pct"] >= 3.5)].copy()

    low_vol_gate_text = "Insufficient data"
    if not vol_quart.empty:
        q1 = vol_quart[vol_quart["Volatility Quartile"] == "Q1 Low"]
        if not q1.empty:
            lo = float(q1["min_ann_pct"].iloc[0])
            hi = float(q1["max_ann_pct"].iloc[0])
            low_vol_gate_text = f"{lo:.3f}% to {hi:.3f}% annualized"

    st.success(
        "Conclusion: Use selective blackout windows, not global blackout. "
        "Risk is concentrated in specific SGT fix hours and in low annualized 10-second volatility regimes."
    )

    st.markdown("**Recommended Action Framework**")
    st.markdown(
        "1. Blackout core high-risk hours: apply entry blackout in the final 20-30 seconds before settlement for the listed high-risk SGT hours.\n"
        "2. Watch-hour partial blackout: apply a shorter 10-15 second blackout for watch hours.\n"
        "3. Volatility gate: if current annualized 10-second volatility falls in the low-volatility quartile band, escalate blackout duration by +10 seconds.\n"
        "4. Day weighting: keep stricter blackout on the listed high-risk days; loosen on lower-risk days."
    )

    c1, c2 = st.columns(2)
    c1.write("High-risk blackout hours (SGT)")
    if not blackout_hours.empty:
        show_b = blackout_hours.rename(columns={"hour_sgt": "Hour (SGT)"})
        c1.dataframe(style_risk_table(show_b), use_container_width=True)
    else:
        c1.info("No hours exceeded the blackout threshold in current sample.")

    c2.write("Watch hours (SGT)")
    if not watch_hours.empty:
        show_w = watch_hours.rename(columns={"hour_sgt": "Hour (SGT)"})
        c2.dataframe(style_risk_table(show_w), use_container_width=True)
    else:
        c2.info("No watch hours in current sample.")

    st.write("Day-of-week tilt (SGT)")
    if not high_risk_days.empty:
        st.dataframe(style_risk_table(high_risk_days), use_container_width=True)
    else:
        st.info("No day-level tilt candidates in current sample.")

    st.write("Volatility gate (annualized 10-second volatility)")
    st.markdown(
        f"Use stricter blackout when current 10-second annualized volatility is in the lowest quartile: **{low_vol_gate_text}**."
    )
    if not vol_quart.empty:
        st.dataframe(style_risk_table(vol_quart), use_container_width=True)
