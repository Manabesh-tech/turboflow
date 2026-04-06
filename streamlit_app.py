"""
Turboflow Edge Dashboard — Streamlit wrapper.
Serves the pre-built edge_dashboard.html as a public shareable link.

To refresh data:
  1. Run locally: python server.py
  2. Open http://localhost:8765/edge_dashboard.html and click Refresh Data
  3. Upload the new edge_dashboard.html to GitHub
  4. Streamlit auto-deploys within ~1 minute
"""
import streamlit as st
from pathlib import Path

DIR       = Path(__file__).parent
HTML_FILE = DIR / 'edge_dashboard.html'

st.set_page_config(
    page_title="Turboflow Edge Dashboard",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Hide Streamlit menu and footer for clean look
st.markdown("""
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
.stAppDeployButton {visibility: hidden;}
header {visibility: hidden;}
.block-container {padding-top: 0rem; padding-bottom: 0rem; padding-left: 0rem; padding-right: 0rem;}
</style>
""", unsafe_allow_html=True)

if HTML_FILE.exists():
    html = HTML_FILE.read_text(encoding='utf-8')
    st.components.v1.html(html, height=900, scrolling=True)
else:
    st.warning("Dashboard not built yet. Run build_dashboard.py locally and upload edge_dashboard.html to GitHub.")
