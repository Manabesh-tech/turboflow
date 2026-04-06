"""
Turboflow Edge Dashboard — Streamlit wrapper.
Deploy to share.streamlit.io for a public shareable link.
"""
import streamlit as st
import subprocess, sys
from pathlib import Path

DIR       = Path(__file__).parent
HTML_FILE = DIR / 'edge_dashboard.html'

st.set_page_config(
    page_title="Turboflow Edge Dashboard",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Minimal top bar ───────────────────────────────────────────────────────────
col1, col2 = st.columns([4, 1])
with col1:
    st.markdown("## Turboflow Binary Bet Edge Analysis")
    st.caption("30s · 4 days  |  1m · 7 days  |  5m · 7 days  |  BTC + ETH  |  Breakeven = 55.56% (80% payout)")
with col2:
    refresh = st.button("⟳ Refresh Data", use_container_width=True,
                        help="Fetches latest Binance data and rebuilds the dashboard (~4 min)")

# ── Refresh logic ─────────────────────────────────────────────────────────────
if refresh:
    with st.status("Refreshing dashboard…", expanded=True) as status:
        st.write("Fetching data from Binance (30s + 1m + 5m)…")
        r = subprocess.run(
            [sys.executable, 'fetch_all_timeframes.py'],
            cwd=str(DIR), capture_output=True, text=True
        )
        if r.returncode != 0:
            status.update(label="Fetch failed", state="error")
            st.error(r.stderr[-600:])
            st.stop()

        st.write("Running strategy analysis and building dashboard…")
        r = subprocess.run(
            [sys.executable, 'build_dashboard.py'],
            cwd=str(DIR), capture_output=True, text=True
        )
        if r.returncode != 0:
            status.update(label="Build failed", state="error")
            st.error(r.stderr[-600:])
            st.stop()

        status.update(label="Done — dashboard updated!", state="complete")
    st.rerun()

# ── Render the dashboard HTML ─────────────────────────────────────────────────
if HTML_FILE.exists():
    html = HTML_FILE.read_text(encoding='utf-8')
    # Strip the localhost refresh button from embedded HTML — Streamlit button above handles it
    html = html.replace(
        'onclick="startRefresh()"',
        'onclick="alert(\'Use the Refresh button at the top of the page.\')"'
    )
    st.components.v1.html(html, height=1400, scrolling=True)
else:
    st.info("No dashboard yet. Click **⟳ Refresh Data** above to fetch live Binance data and build the dashboard.")
