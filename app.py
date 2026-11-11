import json
import os
import re
import sqlite3
import sqlparse
import streamlit as st
from google.genai import types
from google.adk.agents import Agent
from google.adk.models import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

# ==============================================================================
# 1. Page Configuration
# ==============================================================================
st.set_page_config(
    page_title="MCP Banking Virtual Analyst",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==============================================================================
# 2. Safe Secret Resolution (Streamlit Cloud Friendly)
# ==============================================================================
api_key = ""
try:
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
except Exception:
    # Graceful fallback if secrets.toml is not present locally
    api_key = os.environ.get("GOOGLE_API_KEY", "")

if api_key:
    os.environ["GOOGLE_API_KEY"] = api_key

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")

DB_FILE = "bank11.sqlite"
SCHEMA_FILE = "bank_schema.txt"

# Guardrail for missing key in Streamlit Cloud
if not os.environ.get("GOOGLE_API_KEY"):
    st.error(
        "⚠️ **GOOGLE_API_KEY is not configured!**\n\n"
        "Please go to your Streamlit Cloud Dashboard: **App Settings** -> **Secrets**, "
        "and add:\n```toml\nGOOGLE_API_KEY = \"your_gemini_api_key_here\"\n```"
    )
    st.stop()

# ==============================================================================
# 3. Database Bootstrap (Ensures App Runs Immediately on Fresh Repos)
# ==============================================================================
def ensure_database_and_schema():
    if not os.path.exists(DB_FILE):
        conn = sqlite3.connect(DB_FILE)
        cur = conn.
