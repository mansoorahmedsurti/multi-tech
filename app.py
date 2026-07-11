import streamlit as st
import pandas as pd
import numpy as np
import datetime
import random
import string
from sqlalchemy import text

st.set_page_config(
    page_title="FinLedger Pro",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==============================================================================
# 1. DATABASE CONNECTION LAYER (Dual-Mode: Supabase Postgres <-> SQLite Mock)
# ==============================================================================

class DBConnection:
    def __init__(self):
        self.mode = "sqlite"
        self.conn = None
        self.sqlite_conn = None

        # Try establishing Postgres connection first
        try:
            if "connections" in st.secrets and "postgresql" in st.secrets["connections"]:
                self.conn = st.connection("postgresql", type="sql")
                self.conn.query("SELECT 1", ttl=0)
                self.mode = "postgres"
        except Exception:
            self.mode = "sqlite"

        # Fallback to local SQLite if Postgres isn't available
        if self.mode == "sqlite":
            import sqlite3
            self.sqlite_conn = sqlite3.connect("project_ledger_auth.db", check_same_thread=False)

        # Run schema creation and migrations completely separated from connection setup
        self._init_database_schema()
        self._run_migrations()

    def execute(self, sql_str, params=None):
        if params is None:
            params = {}
        if self.mode == "postgres":
            with self.conn.session as s:
                s.execute(text(sql_str), params)
                s.commit()
        else:
            cursor = self.sqlite_conn.cursor()
            cursor.execute(sql_str, params)
            self.sqlite_conn.commit()

    def query(self, query_str, **params):
        if self.mode == "postgres":
            return self.conn.query(query_str, params=params, ttl=0)
        return pd.read_sql_query(query_str, self.sqlite_conn, params=params)

    def _init_database_schema(self):
        """Creates tables dynamically depending on the active database mode."""
        pk_type = "SERIAL PRIMARY KEY" if self.mode == "postgres" else "INTEGER PRIMARY KEY AUTOINCREMENT"

        queries = [
            f"""
            CREATE TABLE IF NOT EXISTS users (
            id {pk_type},
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('CEO', 'Accountant', 'Advance')),
            can_view_dashboard INTEGER NOT NULL DEFAULT 0,
            reset_token TEXT
            );
            """,
            f"""
            CREATE TABLE IF NOT EXISTS companies (
            id {pk_type},
            name TEXT NOT NULL UNIQUE,
            site TEXT,
            description TEXT
            );
            """,
            f"""
            CREATE TABLE IF NOT EXISTS projects (
            id {pk_type},
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            UNIQUE(company_id, name)
            );
            """,
            f"""
            CREATE TABLE IF NOT EXISTS ledgers (
            id {pk_type},
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            type TEXT NOT NULL CHECK (type IN ('expense', 'income', 'loan')),
            title TEXT NOT NULL,
            cheque_number TEXT,
            voucher_ref_id INTEGER,
            amount REAL NOT NULL DEFAULT 0.0,
            created_at TEXT NOT NULL DEFAULT CURRENT_DATE
            );
            """,
            f"""
            CREATE TABLE IF NOT EXISTS advances (
            id {pk_type},
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            person_name TEXT NOT NULL,
            allocated_amount REAL NOT NULL DEFAULT 0.0,
            UNIQUE(project_id, person_name)
            );
            """,
            f"""
            CREATE TABLE IF NOT EXISTS advance_spends (
            id {pk_type},
            advance_id INTEGER NOT NULL REFERENCES advances(id) ON DELETE CASCADE,
            item_name TEXT NOT NULL,
            amount_spent REAL NOT NULL DEFAULT 0.0,
            created_at TEXT NOT NULL DEFAULT CURRENT_DATE
            );
            """,
            f"""
            CREATE TABLE IF NOT EXISTS vouchers (
            id {pk_type},
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            amount REAL NOT NULL DEFAULT 0.0,
            remarks TEXT,
            type TEXT NOT NULL,
            created_by TEXT,
            review_remarks TEXT,
            status TEXT NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending', 'Approved', 'Declined', 'To Be Discussed')),
            created_at TEXT NOT NULL DEFAULT CURRENT_DATE
            );
            """
        ]

        for q in queries:
            self.execute(q)

        # Base user verification pipeline
        check_user_df = self.query("SELECT COUNT(*) as count FROM users")
        if not check_user_df.empty and int(check_user_df.iloc[0]["count"]) == 0:
            self.execute("INSERT INTO users (username, password, role, can_view_dashboard) VALUES ('ceo', 'ceo', 'CEO', 1);")
            self.execute("INSERT INTO users (username, password, role, can_view_dashboard) VALUES ('accountant', 'accountant', 'Accountant', 1);")

        # Automatically ensure the master user exists on startup
        check_master = self.query("SELECT id FROM users WHERE username = 'asif.arain'")
        if check_master.empty:
            self.execute("INSERT INTO users (username, password, role, can_view_dashboard) VALUES ('asif.arain', 'admin123', 'CEO', 1);")

    def _run_migrations(self):
        for table, col, col_type in [
            ("companies", "site", "TEXT"),
            ("companies", "description", "TEXT"),
            ("projects", "description", "TEXT"),
            ("ledgers", "cheque_number", "TEXT"),
            ("ledgers", "voucher_ref_id", "INTEGER"),
            ("vouchers", "created_by", "TEXT"),
            ("vouchers", "review_remarks", "TEXT"),
            ("vouchers", "project_id", "INTEGER"),
            ("users", "reset_token", "TEXT")
        ]:
            try:
                if self.mode == "postgres":
                    existing = self.conn.query(
                        f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}' AND column_name = '{col}'",
                        ttl=0,
                    )
                    if existing.empty:
                        self.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                else:
                    cursor = self.sqlite_conn.cursor()
                    cursor.execute(f"PRAGMA table_info({table})")
                    columns = {row[1] for row in cursor.fetchall()}
                    if col not in columns:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                        self.sqlite_conn.commit()
            except Exception:
                pass

# --- DEFINE RESOURCE CACHE BEFORE CALLING ---
@st.cache_resource
def get_db():
    return DBConnection()

db = get_db()

# ==============================================================================
# HELPER MATHEMATICAL COEFFICIENTS
# ==============================================================================

def _safe_float(value):
    if value is None or pd.isna(value):
        return 0.0
    return float(value)

def get_project_balance(project_id):
    ledger_df = db.query("SELECT type, COALESCE(amount, 0) AS amount FROM ledgers WHERE project_id = :pid", pid=project_id)
    income = ledger_df[ledger_df["type"] == "income"]["amount"].sum() if not ledger_df.empty else 0.0
    expense = ledger_df[ledger_df["type"] == "expense"]["amount"].sum() if not ledger_df.empty else 0.0
    loans = ledger_df[ledger_df["type"] == "loan"]["amount"].sum() if not ledger_df.empty else 0.0

    v_df = db.query("SELECT COALESCE(SUM(amount), 0) AS v_total FROM vouchers WHERE project_id = :pid AND status = 'Approved'", pid=project_id)
    approved_vouchers_sum = _safe_float(v_df.iloc[0]["v_total"] if not v_df.empty else 0.0)

    adv_df = db.query("SELECT id, COALESCE(allocated_amount, 0) AS alloc FROM advances WHERE project_id = :pid", pid=project_id)
    total_allocated = adv_df["alloc"].sum() if not adv_df.empty else 0.0
    total_spent = 0.0

    if not adv_df.empty:
        a_ids = ",".join(str(int(x)) for x in adv_df["id"].tolist())
        spends_df = db.query(f"SELECT COALESCE(SUM(amount_spent), 0) AS total FROM advance_spends WHERE advance_id IN ({a_ids})")
        total_spent = _safe_float(spends_df.iloc[0]["total"] if not spends_df.empty else 0.0)

    unspent_cash_returned = total_allocated - total_spent

    balance = income + loans - expense - approved_vouchers_sum - total_allocated + unspent_cash_returned
    profit = income - expense - approved_vouchers_sum

    return {
        "income": income, "expense": expense + approved_vouchers_sum, "loans": loans,
        "advances_allocated": total_allocated, "advances_spent": total_spent,
        "advances_remaining": unspent_cash_returned, "balance": balance, "profit": profit
    }

def get_company_balance(company_id):
    project_df = db.query("SELECT id FROM projects WHERE company_id = :cid", cid=company_id)
    if project_df.empty:
        return {"income": 0.0, "expense": 0.0, "loans": 0.0, "advances_allocated": 0.0, "advances_spent": 0.0, "advances_remaining": 0.0, "balance": 0.0, "profit": 0.0}

    pids_list = project_df["id"].tolist()
    income, expense, loans, total_allocated, total_spent = 0.0, 0.0, 0.0, 0.0, 0.0

    for pid in pids_list:
        p_metrics = get_project_balance(pid)
        income += p_metrics["income"]
        expense += p_metrics["expense"]
        loans += p_metrics["loans"]
        total_allocated += p_metrics["advances_allocated"]
        total_spent += p_metrics["advances_spent"]

    unspent_cash_returned = total_allocated - total_spent
    return {
        "income": income, "expense": expense, "loans": loans,
        "advances_allocated": total_allocated, "advances_spent": total_spent, "advances_remaining": unspent_cash_returned,
        "balance": income + loans - expense - total_allocated + unspent_cash_returned,
        "profit": income - expense
    }

# ==============================================================================
# 2. DESIGN & STYLING ASSETS (High Density Professional Overrides)
# ==============================================================================

st.markdown("""
<style>
.block-container { padding-top: 0.5rem; padding-bottom: 0.5rem; }
div.stBlock { margin-bottom: 0.25rem !important; padding-bottom: 0px !important; }
.stTabs { margin-top: 0px !important; }
.stDataFrame { margin-bottom: 0.5rem !important; }
h1 { margin-top: 0px !important; padding-top: 0px !important; font-size: 1.85rem !important; }
h2 { margin-top: 0.4rem !important; font-size: 1.3rem !important; }
h3 { margin-top: 0.3rem !important; font-size: 1.1rem !important; }
div[data-testid="stForm"] { padding: 0.6rem !important; margin-bottom: 0.4rem !important; border-radius: 8px !important; }

.voucher-card {
background: rgba(30, 41, 59, 0.45) !important;
border: 1px solid #475569 !important;
border-left: 5px solid #3b82f6 !important;
border-radius: 6px;
padding: 10px 14px;
margin-bottom: 6px;
}
.voucher-card.alt {
background: rgba(15, 23, 42, 0.65) !important;
border: 1px solid #334155 !important;
border-left: 5px solid #0ea5e9 !important;
}
.voucher-title { font-size: 0.98rem; font-weight: 700; color: #f8fafc; }
.voucher-meta { font-size: 0.8rem; color: #94a3b8; margin-top: 2px; }
.voucher-remarks { font-size: 0.82rem; margin-top: 4px; padding: 4px 8px; background: rgba(0, 0, 0, 0.2); border-radius: 4px; border-left: 2px solid #64748b; color: #cbd5e1; }
</style>
""", unsafe_allow_html=True)

st.sidebar.markdown("### 💎 FinLedger Pro")
if db.mode == "sqlite":
    st.sidebar.warning("Local SQL Mode Active", icon="🔌")
else:
    st.sidebar.success("Live Supabase Synced", icon="⚡")

# ==============================================================================
# 3. AUTHENTICATION CONTROLLER (With Mock Email Pass Reset Flow)
# ==============================================================================

if "user" not in st.session_state:
    st.session_state["user"] = None
if "auth_mode" not in st.session_state:
    st.session_state["auth_mode"] = "login"

if st.session_state["user"] is None:
    if st.session_state["auth_mode"] == "login":
        st.markdown("<h2 style='text-align: center;'>💎 FinLedger Pro Sign In</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            with st.form("login_form"):
                u_name = st.text_input("Username")
                p_word = st.text_input("Password", type="password")
                if st.form_submit_button("Login", type="primary", use_container_width=True):
                    res = db.query("SELECT id, username, password, role, can_view_dashboard FROM users WHERE LOWER(username) = LOWER(:u)", u=u_name.strip())
                    if not res.empty and res.iloc[0]["password"] == p_word:
                        st.session_state["user"] = {
                            "id": int(res.iloc[0]["id"]), "username": res.iloc[0]["username"],
                            "role": res.iloc[0]["role"], "can_view_dashboard": bool(res.iloc[0]["can_view_dashboard"])
                        }
                        st.rerun()
                    else:
                        st.error("Invalid credentials.")

            if st.button("Forgot Password?", use_container_width=True):
                st.session_state["auth_mode"] = "forgot"
                st.rerun()

    elif st.session_state["auth_mode"] == "forgot":
        st.markdown("<h2 style='text-align: center;'>🔑 Reset Workspace Access</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            with st.form("forgot_form"):
                st.write("Enter your ID to simulate receiving a master verification link.")
                reset_user = st.text_input("Username / ID Key")
                if st.form_submit_button("Generate Reset Token Link", type="primary", use_container_width=True):
                    res = db.query("SELECT id FROM users WHERE LOWER(username) = LOWER(:u)", u=reset_user.strip())
                    if not res.empty:
                        mock_token = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                        db.execute("UPDATE users SET reset_token = :t WHERE LOWER(username) = LOWER(:u)", {"t": mock_token, "u": reset_user.strip()})
                        st.info(f"📬 **Simulated System Email Outflow:**\n\nTo: `{reset_user.strip()}@company.com`\nSubject: Password Reset Token\n\nUse security token: **`{mock_token}`** to complete changes below.")
                    else:
                        st.error("Account identity not found.")

            with st.form("verify_reset_form"):
                st.write("📈 Complete Update via Token")
                v_user = st.text_input("Confirm Username")
                v_token = st.text_input("Security Token")
                v_pass = st.text_input("New System Password", type="password")
                if st.form_submit_button("Overwrite Password Security Structure", use_container_width=True):
                    chk = db.query("SELECT reset_token FROM users WHERE LOWER(username) = LOWER(:u)", u=v_user.strip())
                    if not chk.empty and chk.iloc[0]["reset_token"] == v_token.strip() and v_token.strip() != "":
                        db.execute("UPDATE users SET password = :p, reset_token = NULL WHERE LOWER(username) = LOWER(:u)", {"p": v_pass.strip(), "u": v_user.strip()})
                        st.success("Access updated! You can log in now.")
                    else:
                        st.error("Token invalid or expired.")

            if st.button("⬅️ Return to Main Sign In Screen", use_container_width=True):
                st.session_state["auth_mode"] = "login"
                st.rerun()
    st.stop()

current_user = st.session_state["user"]
role = current_user["role"]

st.sidebar.markdown(f"👤 **{current_user['username']}** ({role})")

menu_options = []
if role != "Advance":
    menu_options.append("📊 Dashboard")
menu_options.append("🏢 Workspace")
menu_options.append("✍️ Voucher Portal")

if role == "CEO":
    menu_options.append("⚙️ Settings")

menu = st.sidebar.radio("Navigation Workspaces", menu_options, label_visibility="collapsed")
if st.sidebar.button("🚪 Log out", use_container_width=True):
    st.session_state["user"] = None
    st.session_state["auth_mode"] = "login"
    st.rerun()

# ==============================================================================
# VIEW A: MAIN EXECUTIVE DATE-FILTERED DASHBOARD
# ==============================================================================

if menu == "📊 Dashboard":
    if role == "Advance" or not current_user["can_view_dashboard"]:
        st.error("🔒 Unauthorized: Access to executive dashboard scopes restricted.")
        st.stop()

    st.title("📊 Financial Scope Overview")
    time_filter = st.selectbox("Statistics Scope Range", ["All Time", "Last 30 Days", "This Month"])

    today = datetime.date.today()
    date_limit = None
    if time_filter == "Last 30 Days": date_limit = today - datetime.timedelta(days=30)
    elif time_filter == "This Month": date_limit = today.replace(day=1)

    ledgers_df = db.query("SELECT type, amount, created_at FROM ledgers")
    advances_df = db.query("SELECT id, allocated_amount FROM advances")

    if ledgers_df.empty:
        overall_bal, total_loans, net_profit, unspent_advances = 0.0, 0.0, 0.0, 0.0
        inc, exp, loans, alloc_adv = 0.0, 0.0, 0.0, 0.0
    else:
        ledgers_df["created_at"] = pd.to_datetime(ledgers_df["created_at"]).dt.date
        if date_limit: ledgers_df = ledgers_df[ledgers_df["created_at"] >= date_limit]

        inc = ledgers_df[ledgers_df["type"] == "income"]["amount"].sum()
        exp = ledgers_df[ledgers_df["type"] == "expense"]["amount"].sum()
        loans = ledgers_df[ledgers_df["type"] == "loan"]["amount"].sum()

        alloc_adv = advances_df["allocated_amount"].sum() if not advances_df.empty else 0.0
        spent_adv = 0.0
        if not advances_df.empty:
            a_ids = ",".join(str(int(x)) for x in advances_df["id"].tolist())
            spends_df = db.query(f"SELECT amount_spent FROM advance_spends WHERE advance_id IN ({a_ids})")
            if not spends_df.empty: spent_adv = spends_df["amount_spent"].sum()

        unspent_advances = alloc_adv - spent_adv
        overall_bal = inc + loans - exp - alloc_adv + unspent_advances
        net_profit = inc - exp
        total_loans = loans

    m1, m2, m3 = st.columns(3)
    m1.metric("Company Balance", f"PKR{overall_bal:,.2f}" if overall_bal else "—")
    m2.metric("Total Loans", f"PKR{total_loans:,.2f}" if total_loans else "—")
    m3.metric("Net Profit", f"PKR{net_profit:,.2f}" if net_profit else "—")

    with st.expander(f"Details ({time_filter})"):
        st.markdown(f"""
* **Revenue Inflow (Income)**: `PKR{inc:,.2f}`
* **Capital Infusions (Loans)**: `+ PKR{total_loans:,.2f}`
* **Direct Clearances (Expenses)**: `- PKR{exp:,.2f}`
* **Petty Cash Advanced**: `- PKR{alloc_adv:,.2f}`
* **Unspent Saved Cash Retained**: `+ PKR{unspent_advances:,.2f}`
---
* **Total Liquid Asset Balance**: **`PKR{overall_bal:,.2f}`**
""")

# ==============================================================================
# VIEW B: COMPANY & PROJECT WORKSPACE (INTEGRATED SINGLE-CARD PERFECTION)
# ==============================================================================

elif menu == "🏢 Workspace":
    st.title("🏢 Business Portfolio Workspace")
    is_read_only = (role == "Advance")

    st.markdown("""
    <style>
    div[data-testid="stMetricValue"] { font-size: 1.15rem !important; font-weight: 700 !important; }
    div[data-testid="stMetricLabel"] { font-size: 0.8rem !important; }
    .compact-header { font-size: 1.2rem !important; font-weight: bold !important; margin: 0px !important; }
    .project-title { font-size: 1.1rem !important; font-weight: bold !important; color: #3b82f6; }
    </style>
    """, unsafe_allow_html=True)

    if is_read_only:
        st.info("👁️ Read-Only Mode: View access granted. Log modifications are restricted.")

    companies_df = db.query("SELECT * FROM companies ORDER BY name")

    st.subheader("🏢 Corporate Portfolios")

    for idx, r in companies_df.iterrows():
        c_id = int(r["id"])
        c_bal = get_company_balance(c_id)

        with st.container(border=True):
            col_name, col_bal, col_prof, col_loan, col_btn = st.columns([2, 2.5, 2.5, 2.5, 1.5])
            col_name.markdown(f"<p class='compact-header'>{r['name']}</p>", unsafe_allow_html=True)
            col_bal.metric("Balance", f"PKR {c_bal['balance']:,.2f}")
            col_prof.metric("Net Profit", f"PKR {c_bal['profit']:,.2f}")
            col_loan.metric("Active Loans", f"PKR {c_bal['loans']:,.2f}")

            is_active = st.session_state.get("sel_co_id") == c_id
            btn_label = "🔒 Close" if is_active else "📂 Open"

            if col_btn.button(btn_label, key=f"btn_co_{c_id}", use_container_width=True, type="primary" if is_active else "secondary"):
                st.session_state["sel_co_id"] = None if is_active else c_id
                st.session_state["sel_proj_id"] = None
                st.rerun()

            if is_active:
                st.write("---")
                st.markdown(f"### 📁 Active Projects Node Panel — {r['name']}")

                projects_df = db.query("SELECT id, name, description FROM projects WHERE company_id = :cid ORDER BY name", cid=c_id)

                if projects_df.empty:
                    st.caption("No registered projects found under this entity structure.")
                else:
                    p_labels = [p["name"] for _, p in projects_df.iterrows()]
                    p_map = {p["name"]: int(p["id"]) for _, p in projects_df.iterrows()}

                    chosen_p_label = st.selectbox("📂 Switch Active Project Target Tab:", p_labels, key=f"p_pop_select_{c_id}")
                    pid = p_map[chosen_p_label]

                    active_project_row = projects_df[projects_df["id"] == pid].iloc[0]
                    p_description_content = active_project_row["description"]

                    p_bal = get_project_balance(pid)

                    m_c1, m_c2, m_c3 = st.columns(3)
                    m_c1.metric("Project Balance", f"PKR {p_bal['balance']:,.2f}")
                    m_c2.metric("Project Profit", f"PKR {p_bal['profit']:,.2f}")
                    m_c3.metric("Active Project Loans", f"PKR {p_bal['loans']:,.2f}")

                    if p_description_content and not pd.isna(p_description_content):
                        st.caption(f"📝 **Scope Details:** {p_description_content}")

                    st.write("---")

                    exp_data = db.query("SELECT id, title, amount FROM ledgers WHERE project_id = :pid AND type = 'expense'", pid=pid)
                    inc_data = db.query("SELECT id, title, amount FROM ledgers WHERE project_id = :pid AND type = 'income'", pid=pid)
                    loan_data = db.query("SELECT id, title, amount FROM ledgers WHERE project_id = :pid AND type = 'loan'", pid=pid)
                    adv_data = db.query("SELECT id, person_name as title, allocated_amount as amount FROM advances WHERE project_id = :pid", pid=pid)

                    t1, t2, t3, t4 = st.tabs(["🔴 Expenses", "🟢 Income", "🔵 Loans", "💳 Staff Advances"])

                    def render_simple_form_tab(data_df, ledger_type, label_name):
                        if not data_df.empty:
                            st.dataframe(
                                data_df[["title", "amount"]],
                                column_config={
                                    "title": st.column_config.TextColumn(f"{label_name} Description"),
                                    "amount": st.column_config.NumberColumn("Amount (PKR)", format="PKR %,.2f")
                                },
                                use_container_width=True, hide_index=True
                            )
                        else:
                            st.caption("No records logged.")

                        if not is_read_only:
                            with st.form(f"add_entry_{ledger_type}_{pid}", clear_on_submit=True):
                                f_col1, f_col2 = st.columns(2)
                                new_title = f_col1.text_input("Concept Description", key=f"t_in_{ledger_type}_{pid}")
                                new_amount = f_col2.number_input("Value Amount (PKR)", min_value=0.0, step=500.0, key=f"a_in_{ledger_type}_{pid}")

                                if st.form_submit_button("➕ Add Record Row", use_container_width=True):
                                    if new_title.strip() and new_amount > 0:
                                        if ledger_type == "advance":
                                            try:
                                                db.execute("INSERT INTO advances (project_id, person_name, allocated_amount) VALUES (:pid, :n, :a)", {"pid": pid, "n": new_title.strip(), "a": float(new_amount)})
                                                st.toast(f"💳 Advanced Cash Allocation Granted to {new_title.strip()}!", icon="💵")
                                                st.rerun()
                                            except Exception as e:
                                                st.error(f"Row already exists. ({e})")
                                        else:
                                            db.execute("INSERT INTO ledgers (project_id, type, title, amount) VALUES (:pid, :t, :title, :amount)", {"pid": pid, "t": ledger_type, "title": new_title.strip(), "amount": float(new_amount)})
                                            st.toast(f"📈 New {ledger_type.capitalize()} Component Logged Seamlessly!", icon="📊")
                                            st.rerun()

                    with t1: render_simple_form_tab(exp_data, "expense", "Expense")
                    with t2: render_simple_form_tab(inc_data, "income", "Income")
                    with t3: render_simple_form_tab(loan_data, "loan", "Loan")
                    with t4: render_simple_form_tab(adv_data, "advance", "Staff Advance")

                if not is_read_only:
                    st.write("---")
                    with st.expander("➕ Create New Project Node", expanded=False):
                        with st.form(f"add_p_form_{c_id}", clear_on_submit=True):
                            p_name = st.text_input("New Project Title*")
                            p_desc = st.text_area("Project Description / Scope Notes (Optional)", height=70)

                            if st.form_submit_button("Save Project Node"):
                                if p_name.strip():
                                    try:
                                        db.execute(
                                            "INSERT INTO projects (company_id, name, description) VALUES (:cid, :n, :d)",
                                            {"cid": c_id, "n": p_name.strip(), "d": p_desc.strip() if p_desc else None}
                                        )
                                        st.toast(f"✅ Project '{p_name.strip()}' Created Successfully!", icon="📁")
                                        st.success(f"📁 Project '{p_name.strip()}' saved under corporate entity cluster.")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Cannot save project: {e}")
        if not is_read_only:
            with st.expander("➕ Add New Company Entity", expanded=False):
                with st.form("add_company_form", clear_on_submit=True):
                    row1_1, row1_2 = st.columns(2)
                    c_name = row1_1.text_input("Company Name")
                    c_site = row1_2.text_input("Location / Site")
                    if st.form_submit_button("Save Company Entity", type="primary", use_container_width=True):
                        if c_name.strip():
                            try:
                                db.execute("INSERT INTO companies (name, site) VALUES (:n, :s)", {"n": c_name.strip(), "s": c_site.strip() or None})
                                st.toast(f"🏢 Company Corporate Entity '{c_name.strip()}' Provisioned!", icon="💼")
                                st.success(f"💼 Corporate entity portfolio '{c_name.strip()}' successfully committed to registry files.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Cannot save company: {e}")
# ==============================================================================
# VIEW C: VOUCHER WORKFLOW
# ==============================================================================

elif menu == "✍️ Voucher Portal":
    st.title("✍️ Corporate Voucher Portal Log")

    if "v_form_title" not in st.session_state: st.session_state["v_form_title"] = ""
    if "v_form_amount" not in st.session_state: st.session_state["v_form_amount"] = 0.0
    if "v_form_type" not in st.session_state: st.session_state["v_form_type"] = ""
    if "v_form_remarks" not in st.session_state: st.session_state["v_form_remarks"] = ""

    vouchers_all = db.query(
        """
        SELECT v.id, v.title, v.amount, v.remarks, v.type, v.status, v.created_by, v.review_remarks, v.created_at, v.project_id,
        c.name as company_name, p.name as project_name
        FROM vouchers v
        JOIN companies c ON v.company_id = c.id
        LEFT JOIN projects p ON v.project_id = p.id
        ORDER BY v.id DESC
        """
    )

    def draw_voucher_ui_node(v_row, idx):
        shading = "alt" if idx % 2 == 0 else ""
        p_name_display = f" → {v_row['project_name']}" if v_row['project_name'] else ""

        status_lower = str(v_row['status']).lower()
        if "approved" in status_lower:
            amount_color = "#10B981" 
        elif "declined" in status_lower:
            amount_color = "#EF4444" 
        else:
            amount_color = "#94A3B8" 

        return f"""
<div class="voucher-card {shading}">
<div style="display: flex; justify-content: space-between; align-items: center;">
<span class="voucher-title">📄 {v_row['title']}</span>
<span style="font-weight: 800; color: {amount_color}; font-size: 1.05rem;">PKR{v_row['amount']:,.2f}</span>
</div>
<div class="voucher-meta">
🏛️ Portfolio: <b>{v_row['company_name']}{p_name_display}</b> |
👤 Origin: <b>{v_row['created_by'] if v_row['created_by'] else '—'}</b> |
⚡ Status: <b style="color: {amount_color}; text-transform: uppercase; font-size: 0.75rem;">{v_row['status']}</b>
</div>
{"<div class='voucher-remarks'>📝 Notes: " + str(v_row['remarks']) + "</div>" if v_row['remarks'] else ""}
{"<div class='voucher-remarks' style='border-left: 3px solid " + amount_color + "; background: rgba(255,255,255,0.03); color: #f8fafc;'>🧾 <b>Executive Response: " + str(v_row['review_remarks']) + "</b></div>" if v_row['review_remarks'] else ""}
</div>
"""

    if role == "CEO":
        p_v = vouchers_all[vouchers_all["status"] == "Pending"] if not vouchers_all.empty else pd.DataFrame()
        d_v = vouchers_all[vouchers_all["status"] == "To Be Discussed"] if not vouchers_all.empty else pd.DataFrame()
        h_v = vouchers_all[vouchers_all["status"].isin(["Approved", "Declined"])] if not vouchers_all.empty else pd.DataFrame()

        t_pend, t_disc, t_hist = st.tabs([f"⏳ Pending Queue ({len(p_v)})", f"💬 Discussion ({len(d_v)})", f"🗂️ Voucher History ({len(h_v)})"])

        with t_pend:
            if p_v.empty: st.caption("Pending pipeline currently clear.")
            for idx, r in p_v.iterrows():
                st.markdown(draw_voucher_ui_node(r, idx), unsafe_allow_html=True)
                note = st.text_input("Review Remark / Direction", key=f"note_p_{r['id']}")
                b1, b2, b3 = st.columns(3)

                if b1.button("Approve Voucher Request", key=f"app_p_{r['id']}", type="primary"):
                    check_status = db.query("SELECT status FROM vouchers WHERE id = :id", id=int(r['id']))
                    if not check_status.empty and check_status.iloc[0]['status'] == 'Pending':
                        db.execute("UPDATE vouchers SET status='Approved', review_remarks='Approved' WHERE id=:id", {"id": int(r['id'])})
                        if r['project_id'] and not pd.isna(r['project_id']):
                            db.execute(
                                "INSERT INTO ledgers (project_id, type, title, amount, voucher_ref_id) VALUES (:pid, 'expense', :title, :amount, :vref)",
                                {"pid": int(r['project_id']), "title": f"Voucher: {r['title']}", "amount": float(r['amount']), "vref": int(r['id'])}
                            )
                        st.toast("✅ Voucher Payout Approved & Ledger Pool Aggregated!", icon="💸")
                        st.success("Voucher Approved and Ledger balance updated!")
                        st.rerun()
                if b2.button("Decline Voucher Request", key=f"dec_p_{r['id']}"):
                    db.execute("UPDATE vouchers SET status='Declined', review_remarks=:n WHERE id=:id", {"n": note or "Declined", "id": int(r['id'])})
                    st.toast("🛑 Voucher Payout Request Declined Safely.", icon="❌")
                    st.rerun()
                if b3.button("Flag To Be Discussed", key=f"tbd_p_{r['id']}", type="secondary"):
                    db.execute("UPDATE vouchers SET status='To Be Discussed', review_remarks=:n WHERE id=:id", {"n": note or "Flagged for audit discussion", "id": int(r['id'])})
                    st.toast("💬 Voucher Pipeline Item Flagged for Strategic Audit Discussion", icon="🔍")
                    st.rerun()

        with t_disc:
            if d_v.empty: st.caption("No vouchers requiring discussion.")
            for idx, r in d_v.iterrows():
                st.markdown(draw_voucher_ui_node(r, idx), unsafe_allow_html=True)
                note = st.text_input("Review Remark / Direction", key=f"note_d_{r['id']}")
                b1, b2 = st.columns(2)
                if b1.button("Resolve & Approve", key=f"app_d_{r['id']}", type="primary"):
                    check_status = db.query("SELECT status FROM vouchers WHERE id = :id", id=int(r['id']))
                    if not check_status.empty and check_status.iloc[0]['status'] == 'To Be Discussed':
                        db.execute("UPDATE vouchers SET status='Approved', review_remarks='Approved after strategic session' WHERE id=:id", {"id": int(r['id'])})
                        if r['project_id'] and not pd.isna(r['project_id']):
                            db.execute(
                                "INSERT INTO ledgers (project_id, type, title, amount, voucher_ref_id) VALUES (:pid, 'expense', :title, :amount, :vref)",
                                {"pid": int(r['project_id']), "title": f"Voucher: {r['title']}", "amount": float(r['amount']), "vref": int(r['id'])}
                            )
                        st.toast("✅ Voucher Payout Approved & Ledger Pool Aggregated!", icon="💸")
                        st.rerun()
                if b2.button("Resolve & Decline", key=f"dec_d_{r['id']}"):
                    db.execute("UPDATE vouchers SET status='Declined', review_remarks=:n WHERE id=:id", {"n": note or "Declined", "id": int(r['id'])})
                    st.toast("🛑 Voucher Payout Request Declined Safely.", icon="❌")
                    st.rerun()

    else:
        companies_df = db.query("SELECT * FROM companies ORDER BY name")
        if not companies_df.empty:
            st.subheader("Submit New Voucher Request")

            v_filter_row = st.columns(2)
            target_company = v_filter_row[0].selectbox("Associated Company Entity", companies_df["name"])
            target_co_id = int(companies_df[companies_df["name"] == target_company].iloc[0]["id"])

            projects_df = db.query("SELECT id, name FROM projects WHERE company_id = :cid ORDER BY name", cid=target_co_id)
            project_options = ["— No Specific Project Linkage —"]
            project_id_map = {}

            if not projects_df.empty:
                for _, p_row in projects_df.iterrows():
                    project_options.append(p_row["name"])
                    project_id_map[p_row["name"]] = int(p_row["id"])

            with st.form("voucher_submission_form"):
                target_project_label = st.selectbox("Assign Allocation Project Target*", project_options)
                chosen_project_id = project_id_map.get(target_project_label, None)

                v_row2_c1, v_row2_c2 = st.columns(2)
                st.session_state["v_form_title"] = v_row2_c1.text_input("Voucher Title*", value=st.session_state["v_form_title"])
                st.session_state["v_form_amount"] = v_row2_c2.number_input("Requested Payout Amount (PKR)*", min_value=0.0, step=10.0, value=float(st.session_state["v_form_amount"]))

                v_row3_c1, v_row3_c2 = st.columns(2)
                st.session_state["v_form_type"] = v_row3_c1.text_input(" Type / Department (Optional)", value=st.session_state["v_form_type"])
                st.session_state["v_form_remarks"] = st.text_area("Remarks (Optional)", value=st.session_state["v_form_remarks"], height=68)
                
                if st.form_submit_button("File Voucher Entry", type="primary", use_container_width=True):
                    if st.session_state["v_form_title"].strip() and st.session_state["v_form_amount"] > 0:
                        db.execute(
                            """
                            INSERT INTO vouchers (company_id, project_id, title, amount, remarks, type, created_by, status)
                            VALUES (:cid, :pid, :t, :a, :rem, :type, :user, 'Pending')
                            """,
                            {
                                "cid": target_co_id, "pid": chosen_project_id, "t": st.session_state["v_form_title"].strip(), "a": float(st.session_state["v_form_amount"]),
                                "rem": st.session_state["v_form_remarks"].strip() or None, "type": st.session_state["v_form_type"].strip() or "General",
                                "user": current_user["username"]
                            }
                        )
                        st.session_state["v_form_title"] = ""
                        st.session_state["v_form_amount"] = 0.0
                        st.session_state["v_form_type"] = ""
                        st.session_state["v_form_remarks"] = ""
                        st.toast("📄 Voucher Payout Request Lodged into Pending Queue!", icon="📥")
                        st.success("Voucher Request Lodged Successfully.")
                        st.rerun()
                    else:
                        st.error("Please enter a Valid Title and non-zero Amount.")

        if role == "Accountant":
            my_v = vouchers_all if not vouchers_all.empty else pd.DataFrame()
        else:
            my_v = vouchers_all[vouchers_all["created_by"] == current_user["username"]] if not vouchers_all.empty else pd.DataFrame()

        m_act = my_v[my_v["status"].isin(["Pending", "To Be Discussed"])] if not my_v.empty else pd.DataFrame()
        m_disc = my_v[my_v["status"] == "To Be Discussed"] if not my_v.empty else pd.DataFrame()
        m_hist = my_v[my_v["status"].isin(["Approved", "Declined"])] if not my_v.empty else pd.DataFrame()

        st.write("---")
        st.subheader("User Tracking Registry Pipeline")
        ta1, ta2, ta3 = st.tabs([f"📌 Active Requests ({len(m_act)})", f"💬 Discussion Pending ({len(m_disc)})", f"🗂️ Filed History Ledger ({len(m_hist)})"])

        with ta1:
            if m_act.empty: st.caption("No active items.")
            for idx, r in m_act.iterrows(): st.markdown(draw_voucher_ui_node(r, idx), unsafe_allow_html=True)
        with ta2:
            if m_disc.empty: st.caption("No vouchers currently flagged for review discussion.")
            for idx, r in m_disc.iterrows(): st.markdown(draw_voucher_ui_node(r, idx), unsafe_allow_html=True)
        with ta3:
            if m_hist.empty: st.caption("No absolute historical records recorded.")
            for idx, r in m_hist.iterrows(): st.markdown(draw_voucher_ui_node(r, idx), unsafe_allow_html=True)

# ==============================================================================
# VIEW D: SETTINGS (CEO ONLY) - ADVANCED ADMINISTRATIVE CONTROLS
# ==============================================================================

elif menu == "⚙️ Settings" and role == "CEO":
    st.title("⚙️ Workspace Configurations")

    st_tabs = st.tabs(["➕ Add User Workspace", "🛠️ Manage Existing Users Structure"])

    with st_tabs[0]:
        with st.form("create_acct", clear_on_submit=True):
            st.markdown("**Add New Account Credentials**")
            acct_id = st.text_input("Username / ID")
            acct_pw = st.text_input("Password", type="password")
            acct_role = st.selectbox("Assign System Role", ["Accountant", "Advance", "CEO"])

            if st.form_submit_button("Create Account", type="primary"):
                if acct_id.strip() and acct_pw.strip():
                    try:
                        dash_flag = 1 if acct_role in ["Accountant", "CEO"] else 0
                        db.execute(
                            "INSERT INTO users (username, password, role, can_view_dashboard) VALUES (:u, :p, :r, :d)",
                            {"u": acct_id.strip(), "p": acct_pw.strip(), "r": acct_role, "d": dash_flag}
                        )
                        st.toast(f"👤 Account User '{acct_id.strip()}' Created Successfully!", icon="🔑")
                        st.success(f"Access Node Granted for '{acct_id.strip()}' as {acct_role}.")
                        st.rerun()
                    except Exception:
                        st.error(f"Cannot provision user: The ID key '{acct_id.strip()}' already exists.")
                else:
                    st.error("Both fields are strictly mandatory.")

    with st_tabs[1]:
        all_users_df = db.query("SELECT id, username, role FROM users ORDER BY username")

        if not all_users_df.empty:
            st.markdown("**Modify or Revoke Workspace Permissions**")

            selected_username = st.selectbox("Select Target Workspace Account", all_users_df["username"])
            user_row = all_users_df[all_users_df["username"] == selected_username].iloc[0]
            target_user_id = int(user_row["id"])
            current_target_role = user_row["role"]

            st.info(f"Targeting: **{selected_username}** | Active Role: `{current_target_role}`")

            with st.form(f"change_role_form_{target_user_id}"):
                st.markdown("🔄 **Update Account Role Assignment**")
                role_options = ["Accountant", "Advance", "CEO"]

                try:
                    default_role_idx = role_options.index(current_target_role)
                except ValueError:
                    default_role_idx = 0

                new_assigned_role = st.selectbox("Select New Workspace Role", role_options, index=default_role_idx)

                if st.form_submit_button("Save New Role Matrix"):
                    dash_flag = 1 if new_assigned_role in ["Accountant", "CEO"] else 0
                    db.execute(
                        "UPDATE users SET role = :r, can_view_dashboard = :d WHERE id = :id",
                        {"r": new_assigned_role, "d": dash_flag, "id": target_user_id}
                    )
                    st.toast(f"🔄 Account Role Updated for {selected_username}!", icon="🛡️")
                    st.success(f"Role updated successfully for '{selected_username}' to {new_assigned_role}.")
                    st.rerun()

            with st.form(f"change_pass_form_{target_user_id}", clear_on_submit=True):
                st.markdown("🔒 **Administrative Security Key Reset**")
                new_pass = st.text_input("Assign New Security Key / Password", type="password")

                if st.form_submit_button("Force Overwrite Password"):
                    if new_pass.strip():
                        db.execute("UPDATE users SET password = :p WHERE id = :id", {"p": new_pass.strip(), "id": target_user_id})
                        st.success(f"Password updated for user '{selected_username}' successfully.")
                    else:
                        st.error("Password string empty.")

            st.markdown("⚠️ **Danger Zone**")
            if st.button(f"🚨 Permanently Revoke Access for '{selected_username}'", use_container_width=True, type="secondary"):
                if selected_username == current_user["username"]:
                    st.error("Operation Denied: You cannot delete your own session account identity while logged in.")
                else:
                    db.execute("DELETE FROM users WHERE id = :id", {"id": target_user_id})
                    st.toast(f"❌ Account Workspace Access Revoked for '{selected_username}'", icon="🚨")
                    st.warning(f"User account node '{selected_username}' has been dropped from database registry files.")
                    st.rerun()
        else:
            st.caption("No registered member accounts loaded.")
