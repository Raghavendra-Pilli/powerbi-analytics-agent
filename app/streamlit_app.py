"""Streamlit chat UI for the Power BI Analytics Agent."""

import streamlit as st
from pathlib import Path
import sys
import json

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pbi_agent.config import load_config
from pbi_agent.logging import setup_logger
from pbi_agent.orchestrator import Orchestrator


# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Power BI Analytics Agent",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Power BI Analytics Agent")
st.caption("Connect, inspect, review, and export Power BI projects")


# ── Session state init ───────────────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []

if "orchestrator" not in st.session_state:
    try:
        config = load_config()
        setup_logger(level=config.logging.level, console=False)
        st.session_state.orchestrator = Orchestrator(config)
        st.session_state.config = config
    except Exception as e:
        st.error(f"Failed to initialize agent: {e}")
        st.stop()


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Project Settings")

    # PBIP path
    pbip_path = st.text_input(
        "PBIP Project Path",
        value=st.session_state.get("pbip_path", ""),
        placeholder="C:\\path\\to\\your\\project.pbip",
        help="Path to your Power BI project folder",
    )
    if pbip_path and pbip_path != st.session_state.get("pbip_path", ""):
        st.session_state.pbip_path = pbip_path
        orch = st.session_state.orchestrator
        result = orch.set_pbip_path(pbip_path)
        st.success(result)

    st.divider()

    # Quick actions
    st.header("Quick Actions")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("🔍 Inspect Model", use_container_width=True):
            if st.session_state.get("pbip_path"):
                st.session_state.pending_action = "Inspect the semantic model"
            else:
                st.warning("Set a PBIP path first")

        if st.button("📦 Export Package", use_container_width=True):
            if st.session_state.get("pbip_path"):
                st.session_state.pending_action = "Export the project as a package"
            else:
                st.warning("Set a PBIP path first")

    with col2:
        if st.button("📋 Review Report", use_container_width=True):
            if st.session_state.get("pbip_path"):
                st.session_state.pending_action = "Review the report health"
            else:
                st.warning("Set a PBIP path first")

        if st.button("📤 Export PBIX", use_container_width=True):
            if st.session_state.get("pbip_path"):
                st.session_state.pending_action = "Export to PBIX"
            else:
                st.warning("Set a PBIP path first")

    st.divider()

    # Session info
    st.header("Session Info")
    orch = st.session_state.orchestrator
    state = orch.session.state.value
    st.write(f"**State:** {state}")
    if orch.session.pbip_path:
        st.write(f"**Project:** {Path(orch.session.pbip_path).name}")
    if orch.session.connected_source:
        src = orch.session.connected_source
        st.write(f"**Source:** {src.get('source_type', 'N/A')}")

    if st.button("🗑️ Clear Chat"):
        st.session_state.messages = []
        st.rerun()


# ── Chat display ─────────────────────────────────────────────────────────────

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])


# ── Handle pending quick actions ─────────────────────────────────────────────

if "pending_action" in st.session_state:
    action = st.session_state.pop("pending_action")
    st.session_state.messages.append({"role": "user", "content": action})
    with st.chat_message("user"):
        st.markdown(action)

    with st.chat_message("assistant"):
        with st.spinner("Processing..."):
            response = st.session_state.orchestrator.process(action)
        st.markdown(response)
    st.session_state.messages.append({"role": "assistant", "content": response})
    st.rerun()


# ── Chat input ───────────────────────────────────────────────────────────────

if prompt := st.chat_input("Ask me about your Power BI project..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            response = st.session_state.orchestrator.process(prompt)
        st.markdown(response)

    st.session_state.messages.append({"role": "assistant", "content": response})


# ── Welcome message ──────────────────────────────────────────────────────────

if not st.session_state.messages:
    with st.chat_message("assistant"):
        st.markdown("""**Welcome to the Power BI Analytics Agent!**

Here's what I can help you with:

1. **Connect** to data sources (CSV, Excel, SQL Server)
2. **Inspect** your semantic model (tables, measures, relationships)
3. **Review** report health and quality
4. **Export** to PBIX or create a handoff package

**To get started:**
- Set your PBIP project path in the sidebar
- Or just describe what you want in the chat below

Example commands:
- *"Inspect the semantic model"*
- *"Review the report"*
- *"Export to PBIX"*
- *"Connect to my sales.csv file"*
""")
