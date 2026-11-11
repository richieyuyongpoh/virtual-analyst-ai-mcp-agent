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
    api_key = os.environ.get("GOOGLE_API_KEY", "")

if api_key:
    os.environ["GOOGLE_API_KEY"] = api_key

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")

DB_FILE = "bank11.sqlite"
SCHEMA_FILE = "bank_schema.txt"

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
        cur = conn.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS branches (
            branch_id TEXT PRIMARY KEY,
            branch_name TEXT NOT NULL,
            city TEXT NOT NULL,
            state TEXT NOT NULL,
            region TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS customers (
            customer_id TEXT PRIMARY KEY,
            branch_id TEXT NOT NULL,
            full_name TEXT NOT NULL,
            customer_segment TEXT NOT NULL,
            join_date TEXT NOT NULL,
            FOREIGN KEY (branch_id) REFERENCES branches(branch_id)
        );

        CREATE TABLE IF NOT EXISTS accounts (
            account_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            account_type TEXT NOT NULL,
            balance REAL NOT NULL,
            currency TEXT DEFAULT 'MYR',
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        );

        CREATE TABLE IF NOT EXISTS loan_applications (
            application_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            loan_type TEXT NOT NULL,
            applied_amount REAL NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        );

        INSERT OR IGNORE INTO branches VALUES 
            ('BR_001', 'Petaling Jaya Main', 'Petaling Jaya', 'Selangor', 'Central'),
            ('BR_002', 'Kepong Metro Prima', 'Kuala Lumpur', 'W.P. Kuala Lumpur', 'Central'),
            ('BR_003', 'KLCC Corporate Banking', 'Kuala Lumpur', 'W.P. Kuala Lumpur', 'Central'),
            ('BR_004', 'Georgetown Heritage', 'George Town', 'Penang', 'Northern'),
            ('BR_005', 'Johor Bahru City Square', 'Johor Bahru', 'Johor', 'Southern');

        INSERT OR IGNORE INTO customers VALUES
            ('CUST_901', 'BR_001', 'Tan Wei Ming', 'Premier Banking', '2023-01-15'),
            ('CUST_902', 'BR_001', 'Ahmad Farhan', 'Mass Affluent', '2023-03-22'),
            ('CUST_903', 'BR_001', 'Siti Nurhaliza', 'Mass Retail', '2024-06-10'),
            ('CUST_904', 'BR_001', 'Kavitha Pillai', 'Premier Banking', '2024-08-01'),
            ('CUST_905', 'BR_002', 'Chong Chee Keong', 'Mass Retail', '2022-11-05'),
            ('CUST_906', 'BR_002', 'Faridah binti Osman', 'Mass Affluent', '2023-09-19'),
            ('CUST_907', 'BR_002', 'Lee Kuan Yew', 'Premier Banking', '2024-02-14'),
            ('CUST_908', 'BR_003', 'Goh Chok Tong', 'Private Wealth', '2021-05-18'),
            ('CUST_909', 'BR_003', 'Zainal Abidin', 'Corporate Banking', '2022-04-30'),
            ('CUST_910', 'BR_004', 'Lim Guan Eng', 'Mass Affluent', '2023-07-09');

        INSERT OR IGNORE INTO accounts VALUES
            ('ACC_1001', 'CUST_901', 'Savings', 45200.50, 'MYR'),
            ('ACC_1002', 'CUST_902', 'Current', 12340.00, 'MYR'),
            ('ACC_1003', 'CUST_903', 'Savings', 6800.75, 'MYR'),
            ('ACC_1004', 'CUST_904', 'Fixed Deposit', 150000.00, 'MYR'),
            ('ACC_1005', 'CUST_905', 'Savings', 3200.00, 'MYR'),
            ('ACC_1006', 'CUST_906', 'Current', 28900.20, 'MYR'),
            ('ACC_1007', 'CUST_907', 'Fixed Deposit', 300000.00, 'MYR'),
            ('ACC_1008', 'CUST_908', 'Investment', 1250000.00, 'MYR'),
            ('ACC_1009', 'CUST_909', 'Corporate Current', 489000.00, 'MYR'),
            ('ACC_1010', 'CUST_910', 'Savings', 9800.00, 'MYR');

        INSERT OR IGNORE INTO loan_applications VALUES
            ('LOAN_801', 'CUST_901', 'Car Loan', 85000.00, 'APPROVED'),
            ('LOAN_802', 'CUST_902', 'Mortgage', 520000.00, 'UNDER_REVIEW'),
            ('LOAN_803', 'CUST_903', 'Personal Loan', 15000.00, 'APPROVED'),
            ('LOAN_804', 'CUST_905', 'Car Loan', 65000.00, 'APPROVED'),
            ('LOAN_805', 'CUST_906', 'SME Business Loan', 250000.00, 'REJECTED');
        """)
        conn.commit()
        conn.close()

    if not os.path.exists(SCHEMA_FILE):
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        ddl = [row[0] for row in cur.fetchall() if row[0]]
        conn.close()
        with open(SCHEMA_FILE, "w", encoding="utf-8") as f:
            f.write("\n\n".join(ddl))

ensure_database_and_schema()

# ==============================================================================
# 4. MCP Protocol Primitives & Security Guardrails
# ==============================================================================
def is_sql_mutation(sql_query: str) -> bool:
    """AST-based parser that rejects any DDL/DML mutation statement."""
    cleaned = sql_query.strip().strip(";")
    parsed = sqlparse.parse(cleaned)
    if not parsed:
        return False
    forbidden = {
        'DROP', 'DELETE', 'UPDATE', 'INSERT', 'ALTER', 'TRUNCATE',
        'PRAGMA', 'REPLACE', 'CREATE', 'RENAME', 'ATTACH', 'DETACH'
    }
    for stmt in parsed:
        if stmt.get_type() != 'SELECT':
            return True
        for token in stmt.flatten():
            if token.value.upper() in forbidden:
                return True
    return False

def anonymize_text(text: str) -> str:
    """Masks banking primary/foreign keys to comply with PDPA."""
    text = re.sub(r'\b(CUST_)[0-9A-Za-z]+([0-9A-Za-z]{2})\b', r'\1***\2', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(BR_)[0-9A-Za-z]+([0-9A-Za-z]{2})\b', r'\1***\2', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(ACC_)[0-9A-Za-z]+([0-9A-Za-z]{2})\b', r'\1***\2', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(LOAN_)[0-9A-Za-z]+([0-9A-Za-z]{2})\b', r'\1***\2', text, flags=re.IGNORECASE)
    return text

def mcp_list_tables() -> str:
    """MCP Tool: Discovers all accessible data tables in the core banking database."""
    try:
        conn = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = [row[0] for row in cur.fetchall()]
        conn.close()
        return json.dumps({"status": "success", "tables": tables})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

def mcp_describe_table(table_name: str) -> str:
    """MCP Tool: Retrieves schema column definitions and primary keys for a specified table."""
    cleaned = table_name.strip().strip("'").strip('"')
    try:
        conn = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({cleaned});")
        cols = [{"cid": r[0], "name": r[1], "type": r[2], "notnull": r[3], "pk": r[5]} for r in cur.fetchall()]
        conn.close()
        if not cols:
            return json.dumps({"status": "error", "message": f"Table '{cleaned}' not found."})
        return json.dumps({"status": "success", "table": cleaned, "columns": cols})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

def mcp_read_query(sql_query: str) -> str:
    """MCP Tool: Executes a read-only SELECT query against the core banking database."""
    if is_sql_mutation(sql_query):
        return json.dumps({
            "status": "blocked",
            "error": "🛡️ [MCP PROTOCOL ENFORCEMENT]: Mutation operations (DROP, DELETE, UPDATE) are strictly forbidden."
        })
    try:
        conn = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute(sql_query.strip())
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        conn.close()
        return json.dumps({
            "status": "success",
            "columns": columns,
            "rows": [list(r) for r in rows[:50]],
            "count": len(rows)
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

def before_model_guardrail(callback_context, llm_request):
    """Short-circuits destructive or prompt-injection attempts before calling the LLM."""
    last_text = ""
    if llm_request.contents and llm_request.contents[-1].parts:
        last_text = (llm_request.contents[-1].parts[0].text or "").lower()
    destructive = ["delete", "drop table", "truncate", "modify data", "remove branch", "wipe"]
    if any(k in last_text for k in destructive):
        return LlmResponse(content=types.Content(
            role="model",
            parts=[types.Part(
                text="🛡️ **[GUARDRAIL INTERVENTION]**: Request blocked by Banking Safety Policy. "
                     "Operations are strictly read-only. Data modifications are not permitted."
            )]
        ))
    return None

# ==============================================================================
# 5. Agent Initialization (Cached Resource)
# ==============================================================================
@st.cache_resource
def get_mcp_agent():
    schema_ref = ""
    if os.path.exists(SCHEMA_FILE):
        with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
            schema_ref = f.read()

    return Agent(
        name="bank_mcp_analyst",
        model="gemini-2.5-flash",
        description="Virtual Banking Analyst utilizing Model Context Protocol.",
        instruction=(
            "You are an enterprise Virtual Banking Data Analyst operating through the Model Context Protocol (MCP).\n"
            "Use mcp_list_tables, mcp_describe_table, and mcp_read_query to inspect and query data.\n\n"
            f"Known Schema Reference (may evolve via mcp_list_tables):\n{schema_ref}\n\n"
            "RULES:\n"
            "1. When asked about data, check table structure if unsure, then execute queries via 'mcp_read_query'.\n"
            "2. If asked general questions (e.g. 'Who are you?'), introduce yourself clearly.\n"
            "3. Summarize findings into concise business insights.\n"
            "4. NEVER attempt or suggest mutation queries (DROP, DELETE, UPDATE).\n"
        ),
        tools=[mcp_list_tables, mcp_describe_table, mcp_read_query],
        before_model_callback=before_model_guardrail
    )

# ==============================================================================
# 6. Streamlit Session State & Runner Setup
# ==============================================================================
if "session_service" not in st.session_state:
    st.session_state.session_service = InMemorySessionService()
    st.session_state.session_id = "cloud_mcp_session_001"
    st.session_state.session_service.create_session(
        app_name="mcp_bank_cloud_app",
        user_id="st_cloud_officer",
        session_id=st.session_state.session_id
    )
    st.session_state.runner = Runner(
        agent=get_mcp_agent(),
        app_name="mcp_bank_cloud_app",
        session_service=st.session_state.session_service,
        auto_create_session=True
    )
    st.session_state.messages = []

# ==============================================================================
# 7. Sidebar Navigation & Suggested Prompts
# ==============================================================================
with st.sidebar:
    st.title("🏦 Bank Analyst Portal")
    st.markdown("**AI-Powered Banking Analytics (MCP Architecture)**")
    st.markdown("---")

    st.subheader("💡 Suggested Questions")
    sample_questions = [
        "List all branches.",
        "Provide a list of branches and the number of customers at each.",
        "What is the branch with the highest count of customers?",
        "Where is 'petaling jaya' branch located?",
