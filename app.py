import streamlit as st
import pandas as pd
import numpy as np
import datetime
import random
import string
import time
import os
import shutil
from supabase import create_client

# Ensure logo.jpeg exists if logo.jpg is present
if os.path.exists("logo.jpg") and not os.path.exists("logo.jpeg"):
    try:
        shutil.copy("logo.jpg", "logo.jpeg")
    except Exception:
        pass

st.set_page_config(
    page_title="Multi Tech Engineering Group",
    page_icon="logo.jpeg" if os.path.exists("logo.jpeg") else "⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==============================================================================
# 1. DATABASE CONNECTION LAYER (Supabase REST API — Exclusive Backend)
# ==============================================================================

class DBConnection:
    def __init__(self):
        self.client = None

        try:
            url = st.secrets["supabase"]["url"]
            key = st.secrets["supabase"]["key"]
            self.client = create_client(url, key)

            # Test connection by hitting the users table
            self.client.table("users").select("id").limit(1).execute()
        except Exception as e:
            st.error(
                f"🚨 **Critical: Cannot connect to Supabase.**\n\n"
                f"Error: `{e}`\n\n"
                f"Please check your `.streamlit/secrets.toml` configuration."
            )
            st.stop()

        self._ensure_seed_users()

    def _ensure_seed_users(self):
        """Seed default users if the table is empty."""
        try:
            result = self.client.table("users").select("id", count="exact").limit(0).execute()
            if result.count == 0:
                self.client.table("users").insert([
                    {"username": "ceo", "password": "ceo", "role": "CEO", "can_view_dashboard": True},
                    {"username": "accountant", "password": "accountant", "role": "Accountant", "can_view_dashboard": True},
                ]).execute()
        except Exception:
            pass

        try:
            master = self.client.table("users").select("id").eq("username", "asif.arain").execute()
            if not master.data:
                self.client.table("users").insert({
                    "username": "asif.arain", "password": "admin123", "role": "CEO", "can_view_dashboard": True
                }).execute()
        except Exception:
            pass

    def to_df(self, response, columns=None):
        """Convert a Supabase response to a pandas DataFrame."""
        if response and hasattr(response, 'data') and response.data:
            return pd.DataFrame(response.data)
        return pd.DataFrame(columns=columns or [])


# --- DEFINE RESOURCE CACHE BEFORE CALLING ---
@st.cache_resource
def get_db():
    return DBConnection()

db = get_db()
sb = db.client  # shorthand for the supabase client

# ==============================================================================
# OPTIMIZED GLOBAL CACHED READS (IN-MEMORY BULK PROCESSING)
# ==============================================================================

@st.cache_data(ttl=300, show_spinner=False)
def fetch_all_table_data():
    """Fetch core tables once to perform lightning-fast in-memory filtering."""
    ledgers_res = sb.table("ledgers").select("*").execute()
    vouchers_res = sb.table("vouchers").select("*").execute()
    advances_res = sb.table("advances").select("*").execute()
    spends_res = sb.table("advance_spends").select("*").execute()

    return {
        "ledgers": db.to_df(ledgers_res, columns=["id", "project_id", "type", "title", "cheque_number", "voucher_ref_id", "amount", "created_at"]),
        "vouchers": db.to_df(vouchers_res, columns=["id", "company_id", "project_id", "title", "amount", "remarks", "type", "created_by", "review_remarks", "status", "created_at"]),
        "advances": db.to_df(advances_res, columns=["id", "project_id", "person_name", "allocated_amount"]),
        "spends": db.to_df(spends_res, columns=["id", "advance_id", "item_name", "amount_spent", "created_at"])
    }

def _safe_float(value):
    if value is None or pd.isna(value):
        return 0.0
    return float(value)

def confirm_and_rerun(message, icon="✅"):
    """Shows a toast confirmation, clears cached reads, then reruns."""
    st.toast(message, icon=icon)
    st.cache_data.clear()
    st.rerun()

def confirm_warn_and_rerun(message, icon="⚠️"):
    """Same as confirm_and_rerun but for warnings/declines/removals."""
    st.toast(message, icon=icon)
    st.cache_data.clear()
    st.rerun()

def get_project_balance(project_id):
    tables = fetch_all_table_data()
    
    # 1. Ledgers
    l_df = tables["ledgers"]
    proj_ledgers = l_df[l_df["project_id"] == project_id] if not l_df.empty else pd.DataFrame()
    income = proj_ledgers[proj_ledgers["type"] == "income"]["amount"].apply(_safe_float).sum() if not proj_ledgers.empty else 0.0
    expense = proj_ledgers[proj_ledgers["type"] == "expense"]["amount"].apply(_safe_float).sum() if not proj_ledgers.empty else 0.0
    loans = proj_ledgers[proj_ledgers["type"] == "loan"]["amount"].apply(_safe_float).sum() if not proj_ledgers.empty else 0.0

    # 2. Approved Vouchers
    v_df = tables["vouchers"]
    if not v_df.empty:
        app_v = v_df[(v_df["project_id"] == project_id) & (v_df["status"] == "Approved")]
        approved_vouchers_sum = app_v["amount"].apply(_safe_float).sum()
    else:
        approved_vouchers_sum = 0.0

    # 3. Advances & Spends
    adv_df = tables["advances"]
    sp_df = tables["spends"]
    
    proj_adv = adv_df[adv_df["project_id"] == project_id] if not adv_df.empty else pd.DataFrame()
    total_allocated = proj_adv["allocated_amount"].apply(_safe_float).sum() if not proj_adv.empty else 0.0
    total_spent = 0.0

    if not proj_adv.empty and not sp_df.empty:
        a_ids = proj_adv["id"].astype(int).tolist()
        matching_spends = sp_df[sp_df["advance_id"].isin(a_ids)]
        total_spent = matching_spends["amount_spent"].apply(_safe_float).sum()

    unspent_cash_returned = total_allocated - total_spent

    balance = income + loans - expense - approved_vouchers_sum - total_allocated
    profit = income - expense - approved_vouchers_sum - total_allocated

    return {
        "income": income, "expense": expense + approved_vouchers_sum, "loans": loans,
        "advances_allocated": total_allocated, "advances_spent": total_spent,
        "advances_remaining": unspent_cash_returned, "balance": balance, "profit": profit
    }

def get_company_balance(company_id):
    projects_df = get_projects_full(company_id)
    if projects_df.empty:
        return {"income": 0.0, "expense": 0.0, "loans": 0.0, "advances_allocated": 0.0, "advances_spent": 0.0, "advances_remaining": 0.0, "balance": 0.0, "profit": 0.0}

    pids_list = projects_df["id"].astype(int).tolist()
    tables = fetch_all_table_data()

    # Ledgers
    l_df = tables["ledgers"]
    comp_ledgers = l_df[l_df["project_id"].isin(pids_list)] if not l_df.empty else pd.DataFrame()
    income = comp_ledgers[comp_ledgers["type"] == "income"]["amount"].apply(_safe_float).sum() if not comp_ledgers.empty else 0.0
    expense = comp_ledgers[comp_ledgers["type"] == "expense"]["amount"].apply(_safe_float).sum() if not comp_ledgers.empty else 0.0
    loans = comp_ledgers[comp_ledgers["type"] == "loan"]["amount"].apply(_safe_float).sum() if not comp_ledgers.empty else 0.0

    # Approved Vouchers
    v_df = tables["vouchers"]
    if not v_df.empty:
        app_v = v_df[(v_df["project_id"].isin(pids_list)) & (v_df["status"] == "Approved")]
        approved_vouchers_sum = app_v["amount"].apply(_safe_float).sum()
    else:
        approved_vouchers_sum = 0.0
    
    expense += approved_vouchers_sum

    # Advances & Spends
    adv_df = tables["advances"]
    sp_df = tables["spends"]

    comp_adv = adv_df[adv_df["project_id"].isin(pids_list)] if not adv_df.empty else pd.DataFrame()
    total_allocated = comp_adv["allocated_amount"].apply(_safe_float).sum() if not comp_adv.empty else 0.0
    total_spent = 0.0

    if not comp_adv.empty and not sp_df.empty:
        a_ids = comp_adv["id"].astype(int).tolist()
        matching_spends = sp_df[sp_df["advance_id"].isin(a_ids)]
        total_spent = matching_spends["amount_spent"].apply(_safe_float).sum()

    unspent_cash_returned = total_allocated - total_spent

    return {
        "income": income, "expense": expense, "loans": loans,
        "advances_allocated": total_allocated, "advances_spent": total_spent, "advances_remaining": unspent_cash_returned,
        "balance": income + loans - expense - total_allocated,
        "profit": income - expense - total_allocated
    }

# --- Cached read-only lookups used at multiple call sites
@st.cache_data(ttl=300, show_spinner=False)
def get_all_companies():
    res = sb.table("companies").select("*").order("name").execute()
    return db.to_df(res, columns=["id", "name", "site", "description"])

@st.cache_data(ttl=300, show_spinner=False)
def get_projects_full(company_id):
    res = sb.table("projects").select("id, name, description").eq("company_id", company_id).order("name").execute()
    return db.to_df(res, columns=["id", "name", "description"])

@st.cache_data(ttl=300, show_spinner=False)
def get_projects_names(company_id):
    res = sb.table("projects").select("id, name").eq("company_id", company_id).order("name").execute()
    return db.to_df(res, columns=["id", "name"])

@st.cache_data(ttl=300, show_spinner=False)
def get_users_by_role(role_name):
    res = sb.table("users").select("username").eq("role", role_name).order("username").execute()
    return [r["username"] for r in res.data] if res.data else []

@st.cache_data(ttl=300, show_spinner=False)
def get_all_users_summary():
    res = sb.table("users").select("id, username, role").order("username").execute()
    return db.to_df(res, columns=["id", "username", "role"])

@st.cache_data(ttl=300, show_spinner=False)
def get_all_vouchers_raw():
    res = sb.table("vouchers").select("*, companies(name), projects(name)").order("id", desc=True).execute()
    return res.data or []

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

logo_path = "logo.jpeg" if os.path.exists("logo.jpeg") else ("logo.jpg" if os.path.exists("logo.jpg") else None)
if logo_path:
    st.sidebar.image(logo_path, use_container_width=True)
st.sidebar.markdown("### MTEG")
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
        st.markdown("<div style='margin-top: 3.5rem;'></div>", unsafe_allow_html=True)
        st.markdown("<h2 style='text-align: center;'>Multi Tech Engineering Group Sign In</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            with st.form("login_form"):
                u_name = st.text_input("Username")
                p_word = st.text_input("Password", type="password")
                if st.form_submit_button("Login", type="primary", use_container_width=True):
                    res = sb.table("users").select("id, username, password, role, can_view_dashboard").ilike("username", u_name.strip()).execute()
                    if res.data and res.data[0]["password"] == p_word:
                        u = res.data[0]
                        st.session_state["user"] = {
                            "id": int(u["id"]), "username": u["username"],
                            "role": u["role"], "can_view_dashboard": bool(u["can_view_dashboard"])
                        }
                        st.rerun()
                    else:
                        st.error("Invalid credentials.")

            #  if st.button("Forgot Password?", use_container_width=True):
            #      st.session_state["auth_mode"] = "forgot"
            #      st.rerun()

    elif st.session_state["auth_mode"] == "forgot":
        st.markdown("<div style='margin-top: 3.5rem;'></div>", unsafe_allow_html=True)
        st.markdown("<h2 style='text-align: center;'>🔑 Reset Workspace Access</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            with st.form("forgot_form"):
                st.write("Enter your ID to simulate receiving a master verification link.")
                reset_user = st.text_input("Username / ID Key")
                if st.form_submit_button("Generate Reset Token Link", type="primary", use_container_width=True):
                    res = sb.table("users").select("id").ilike("username", reset_user.strip()).execute()
                    if res.data:
                        mock_token = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                        sb.table("users").update({"reset_token": mock_token}).ilike("username", reset_user.strip()).execute()
                        st.info(f"📬 **Simulated System Email Outflow:**\n\nTo: `{reset_user.strip()}@company.com`\nSubject: Password Reset Token\n\nUse security token: **`{mock_token}`** to complete changes below.")
                    else:
                        st.error("Account identity not found.")

            with st.form("verify_reset_form"):
                st.write("📈 Complete Update via Token")
                v_user = st.text_input("Confirm Username")
                v_token = st.text_input("Security Token")
                v_pass = st.text_input("New System Password", type="password")
                if st.form_submit_button("Overwrite Password Security Structure", use_container_width=True):
                    chk = sb.table("users").select("reset_token").ilike("username", v_user.strip()).execute()
                    if chk.data and chk.data[0]["reset_token"] == v_token.strip() and v_token.strip() != "":
                        sb.table("users").update({"password": v_pass.strip(), "reset_token": None}).ilike("username", v_user.strip()).execute()
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

# Hide the Voucher Portal from the sidebar list entirely
if role != "Advance":
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

    tables = fetch_all_table_data()
    ledgers_df = tables["ledgers"].copy()
    advances_df = tables["advances"].copy()
    spends_df = tables["spends"].copy()

    if ledgers_df.empty:
        overall_bal, total_loans, net_profit, unspent_advances = 0.0, 0.0, 0.0, 0.0
        inc, exp, loans, alloc_adv = 0.0, 0.0, 0.0, 0.0
    else:
        ledgers_df["created_at"] = pd.to_datetime(ledgers_df["created_at"]).dt.date
        if date_limit: ledgers_df = ledgers_df[ledgers_df["created_at"] >= date_limit]

        inc = ledgers_df[ledgers_df["type"] == "income"]["amount"].apply(_safe_float).sum()
        exp = ledgers_df[ledgers_df["type"] == "expense"]["amount"].apply(_safe_float).sum()
        loans = ledgers_df[ledgers_df["type"] == "loan"]["amount"].apply(_safe_float).sum()

        alloc_adv = advances_df["allocated_amount"].apply(_safe_float).sum() if not advances_df.empty else 0.0
        spent_adv = spends_df["amount_spent"].apply(_safe_float).sum() if not spends_df.empty else 0.0

        unspent_advances = alloc_adv - spent_adv
        overall_bal = inc + loans - exp - alloc_adv
        net_profit = inc - exp - alloc_adv
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

    companies_df = get_all_companies()
    tables = fetch_all_table_data()

    st.subheader("🏢 Corporate Portfolios")

    for idx, r in companies_df.iterrows():
        c_id = int(r["id"])
        c_bal = get_company_balance(c_id)

        with st.container(border=True):
            col_name, col_bal, col_prof, col_loan, col_edit, col_btn = st.columns([1.8, 2.2, 2.2, 2.2, 1, 1.3])
            col_name.markdown(f"<p class='compact-header'>{r['name']}</p>", unsafe_allow_html=True)
            col_bal.metric("Balance", f"PKR {c_bal['balance']:,.2f}")
            col_prof.metric("Net Profit", f"PKR {c_bal['profit']:,.2f}")
            col_loan.metric("Active Loans", f"PKR {c_bal['loans']:,.2f}")

            is_editing_co = st.session_state.get("edit_co_id") == c_id
            if not is_read_only:
                if col_edit.button("✏️", key=f"edit_co_btn_{c_id}", use_container_width=True, help="Edit company details"):
                    st.session_state["edit_co_id"] = None if is_editing_co else c_id
                    st.rerun()

            is_active = st.session_state.get("sel_co_id") == c_id
            btn_label = "🔒 Close" if is_active else "📂 Open"

            if col_btn.button(btn_label, key=f"btn_co_{c_id}", use_container_width=True, type="primary" if is_active else "secondary"):
                st.session_state["sel_co_id"] = None if is_active else c_id
                st.session_state["sel_proj_id"] = None
                st.rerun()

            if is_editing_co and not is_read_only:
                with st.form(f"edit_co_form_{c_id}"):
                    st.markdown("**✏️ Edit Company Details**")
                    ec1, ec2 = st.columns(2)
                    edit_name = ec1.text_input("Company Name", value=r["name"])
                    edit_site = ec2.text_input("Location / Site", value=r["site"] if not pd.isna(r["site"]) else "")
                    edit_desc = st.text_area("Description", value=r["description"] if not pd.isna(r["description"]) else "", height=68)
                    sc1, sc2 = st.columns(2)
                    save_co = sc1.form_submit_button("💾 Save Changes", type="primary", use_container_width=True)
                    cancel_co = sc2.form_submit_button("✖️ Cancel", use_container_width=True)
                    if save_co:
                        if edit_name.strip():
                            try:
                                sb.table("companies").update({
                                    "name": edit_name.strip(),
                                    "site": edit_site.strip() or None,
                                    "description": edit_desc.strip() or None
                                }).eq("id", c_id).execute()
                                st.session_state["edit_co_id"] = None
                                confirm_and_rerun(f"✏️ Company updated to '{edit_name.strip()}'.", icon="💾")
                            except Exception as e:
                                st.error(f"Cannot update company: {e}")
                        else:
                            st.error("Company name cannot be empty.")
                    if cancel_co:
                        st.session_state["edit_co_id"] = None
                        st.rerun()

            if is_active:
                st.write("---")
                st.markdown(f"### 📁 Active Projects Node Panel — {r['name']}")

                projects_df = get_projects_full(c_id)

                if projects_df.empty:
                    st.caption("No registered projects found under this entity structure.")
                else:
                    p_labels = [p["name"] for _, p in projects_df.iterrows()]
                    p_map = {p["name"]: int(p["id"]) for _, p in projects_df.iterrows()}

                    p_sel_col, p_edit_col = st.columns([5, 1])
                    chosen_p_label = p_sel_col.selectbox("📂 Switch Active Project Target Tab:", p_labels, key=f"p_pop_select_{c_id}")
                    pid = p_map[chosen_p_label]

                    active_project_row = projects_df[projects_df["id"] == pid].iloc[0]
                    p_description_content = active_project_row["description"]

                    is_editing_proj = st.session_state.get("edit_proj_id") == pid
                    if not is_read_only:
                        p_edit_col.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                        if p_edit_col.button("✏️ Edit", key=f"edit_proj_btn_{pid}", use_container_width=True):
                            st.session_state["edit_proj_id"] = None if is_editing_proj else pid
                            st.rerun()

                    if is_editing_proj and not is_read_only:
                        with st.form(f"edit_proj_form_{pid}"):
                            st.markdown("**✏️ Edit Project Details**")
                            edit_p_name = st.text_input("Project Title", value=active_project_row["name"])
                            edit_p_desc = st.text_area("Project Description / Scope Notes", value=p_description_content if not pd.isna(p_description_content) else "", height=68)
                            epc1, epc2 = st.columns(2)
                            save_proj = epc1.form_submit_button("💾 Save Changes", type="primary", use_container_width=True)
                            cancel_proj = epc2.form_submit_button("✖️ Cancel", use_container_width=True)
                            if save_proj:
                                if edit_p_name.strip():
                                    try:
                                        sb.table("projects").update({
                                            "name": edit_p_name.strip(),
                                            "description": edit_p_desc.strip() or None
                                        }).eq("id", pid).execute()
                                        st.session_state["edit_proj_id"] = None
                                        confirm_and_rerun(f"✏️ Project updated to '{edit_p_name.strip()}'.", icon="💾")
                                    except Exception as e:
                                        st.error(f"Cannot update project: {e}")
                                else:
                                    st.error("Project title cannot be empty.")
                            if cancel_proj:
                                st.session_state["edit_proj_id"] = None
                                st.rerun()

                    p_bal = get_project_balance(pid)

                    m_c1, m_c2, m_c3 = st.columns(3)
                    m_c1.metric("Project Balance", f"PKR {p_bal['balance']:,.2f}")
                    m_c2.metric("Project Profit", f"PKR {p_bal['profit']:,.2f}")
                    m_c3.metric("Active Project Loans", f"PKR {p_bal['loans']:,.2f}")

                    if p_description_content and not pd.isna(p_description_content):
                        st.caption(f"📝 **Scope Details:** {p_description_content}")

                    st.write("---")

                    # Fast In-Memory Ledgers Extraction
                    l_all = tables["ledgers"]
                    p_ledgers = l_all[l_all["project_id"] == pid] if not l_all.empty else pd.DataFrame()

                    exp_data = p_ledgers[p_ledgers["type"] == "expense"][["id", "title", "amount", "cheque_number"]] if not p_ledgers.empty else pd.DataFrame()
                    inc_data = p_ledgers[p_ledgers["type"] == "income"][["id", "title", "amount", "cheque_number"]] if not p_ledgers.empty else pd.DataFrame()
                    loan_data = p_ledgers[p_ledgers["type"] == "loan"][["id", "title", "amount", "cheque_number"]] if not p_ledgers.empty else pd.DataFrame()

                    t1, t2, t3, t4 = st.tabs(["🔴 Expenses", "🟢 Income", "🔵 Loans", "💳 Staff Advances"])

                    def render_simple_form_tab(data_df, ledger_type, label_name):
                        has_cheque = (ledger_type == "income")

                        if not data_df.empty:
                            for _, row in data_df.iterrows():
                                row_id = int(row["id"])
                                edit_key = f"edit_{ledger_type}_{row_id}"
                                is_editing_row = st.session_state.get(edit_key, False)
                                cheque_val = row["cheque_number"] if "cheque_number" in row and not pd.isna(row["cheque_number"]) else ""

                                with st.container(border=True):
                                    rc1, rc2, rc3 = st.columns([4, 2.5, 1])
                                    title_display = row["title"]
                                    if has_cheque and cheque_val:
                                        title_display += f"  \n🏦 Cheque #: `{cheque_val}`"
                                    rc1.markdown(f"**{title_display}**")
                                    rc2.markdown(f"PKR {row['amount']:,.2f}")
                                    if not is_read_only:
                                        if rc3.button("✏️ Edit", key=f"btn_{edit_key}", use_container_width=True):
                                            st.session_state[edit_key] = not is_editing_row
                                            st.rerun()

                                    if is_editing_row and not is_read_only:
                                        with st.form(f"form_{edit_key}"):
                                            fe1, fe2 = st.columns(2)
                                            edit_title = fe1.text_input(f"{label_name} Description", value=row["title"])
                                            edit_amount = fe2.number_input("Amount (PKR)", min_value=0.0, step=500.0, value=float(row["amount"]))
                                            edit_cheque = st.text_input("Cheque Number (Optional)", value=cheque_val) if has_cheque else None
                                            fs1, fs2 = st.columns(2)
                                            save_row = fs1.form_submit_button("💾 Save", type="primary", use_container_width=True)
                                            cancel_row = fs2.form_submit_button("✖️ Cancel", use_container_width=True)
                                            if save_row:
                                                if edit_title.strip() and edit_amount > 0:
                                                    try:
                                                        update_data = {"title": edit_title.strip(), "amount": float(edit_amount)}
                                                        if has_cheque:
                                                            update_data["cheque_number"] = (edit_cheque.strip() or None) if edit_cheque else None
                                                        sb.table("ledgers").update(update_data).eq("id", row_id).execute()
                                                        st.session_state[edit_key] = False
                                                        confirm_and_rerun(f"✏️ {label_name} record updated to '{edit_title.strip()}'.", icon="💾")
                                                    except Exception as e:
                                                        st.error(f"Cannot update record: {e}")
                                                else:
                                                    st.error("Please enter a valid description and non-zero amount.")
                                            if cancel_row:
                                                st.session_state[edit_key] = False
                                                st.rerun()
                        else:
                            st.caption("No records logged.")

                        if not is_read_only:
                            with st.form(f"add_entry_{ledger_type}_{pid}", clear_on_submit=True):
                                f_col1, f_col2 = st.columns(2)
                                new_title = f_col1.text_input("Component", key=f"t_in_{ledger_type}_{pid}")
                                new_amount = f_col2.number_input("Value Amount (PKR)", min_value=0.0, step=500.0, key=f"a_in_{ledger_type}_{pid}")
                                new_cheque = st.text_input("Cheque Number (Optional)", key=f"c_in_{ledger_type}_{pid}") if has_cheque else None

                                if st.form_submit_button("➕ Add Record Row", use_container_width=True):
                                    if new_title.strip() and new_amount > 0:
                                        insert_data = {"project_id": pid, "type": ledger_type, "title": new_title.strip(), "amount": float(new_amount)}
                                        if has_cheque:
                                            insert_data["cheque_number"] = (new_cheque.strip() or None) if new_cheque else None
                                        sb.table("ledgers").insert(insert_data).execute()
                                        confirm_and_rerun(f"📈 New {ledger_type.capitalize()} record '{new_title.strip()}' added (PKR {new_amount:,.2f}).", icon="📊")

                    def render_advances_tab(pid):
                        # 1. Fetch available advance personas for the selection dropdown
                        advance_usernames = get_users_by_role("Advance")

                        # 2. Extract current active allocations in-memory
                        a_all = tables["advances"]
                        adv_rows = a_all[a_all["project_id"] == pid].sort_values("person_name") if not a_all.empty else pd.DataFrame()

                        if adv_rows.empty:
                            st.caption("No staff advances allocated for this project yet.")
                        else:
                            s_all = tables["spends"]
                            for _, adv in adv_rows.iterrows():
                                adv_id = int(adv["id"])
                                spends_df = s_all[s_all["advance_id"] == adv_id].sort_values("id", ascending=False) if not s_all.empty else pd.DataFrame()
                                spent_total = _safe_float(spends_df["amount_spent"].sum()) if not spends_df.empty else 0.0
                                allocated = _safe_float(adv["allocated_amount"])
                                remaining = allocated - spent_total

                                is_owner = (role == "Advance" and current_user["username"] == adv["person_name"])
                                
                                with st.container(border=True):
                                    ac1, ac2 = st.columns([3.5, 2.5])
                                    identity_text = f"👤 **{adv['person_name']}**" + (" *(You)*" if is_owner else "")
                                    ac1.markdown(identity_text)
                                    
                                    ac2.markdown(
                                        f"<p style='font-size:0.85rem; margin:0; text-align:right; color:#94a3b8;'>"
                                        f"Bal: <span style='color:#10B981; font-weight:600;'>PKR {remaining:,.2f}</span> | "
                                        f"Spend: <span style='color:#ef4444; font-weight:600;'>PKR {spent_total:,.2f}</span>"
                                        f"</p>", 
                                        unsafe_allow_html=True
                                    )

                                    can_manage = role in ("CEO", "Accountant")
                                    edit_key = f"edit_advperson_{adv_id}"
                                    
                                    if can_manage:
                                        if st.button("✏️ Edit Allocation Parameters", key=f"btn_{edit_key}", use_container_width=True):
                                            st.session_state[edit_key] = not st.session_state.get(edit_key, False)
                                            st.rerun()

                                    if can_manage and st.session_state.get(edit_key, False):
                                        with st.form(f"form_{edit_key}"):
                                            if advance_usernames:
                                                default_idx = advance_usernames.index(adv["person_name"]) if adv["person_name"] in advance_usernames else 0
                                                edit_person = st.selectbox("Advance Person", advance_usernames, index=default_idx)
                                            else:
                                                edit_person = adv["person_name"]
                                            edit_alloc = st.number_input("Allocated Amount (PKR)", min_value=0.0, step=500.0, value=allocated)
                                            fs1, fs2 = st.columns(2)
                                            save_adv = fs1.form_submit_button("💾 Save", type="primary", use_container_width=True)
                                            cancel_adv = fs2.form_submit_button("✖️ Cancel", use_container_width=True)
                                            if save_adv:
                                                try:
                                                    sb.table("advances").update({"person_name": edit_person, "allocated_amount": float(edit_alloc)}).eq("id", adv_id).execute()
                                                    st.session_state[edit_key] = False
                                                    confirm_and_rerun(f"✏️ Advance allocation updated for {edit_person}.", icon="💾")
                                                except Exception as e:
                                                    st.error(f"Cannot update advance: {e}")
                                            if cancel_adv:
                                                st.session_state[edit_key] = False
                                                st.rerun()

                                    with st.expander(f"📋 Spending Logs & Actions ({len(spends_df)} entries logged)", expanded=is_owner):
                                        if spends_df.empty:
                                            st.caption("No spend items logged yet.")
                                        else:
                                            for _, sp in spends_df.iterrows():
                                                sp_c1, sp_c2 = st.columns([4, 2])
                                                sp_c1.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;🧾 {sp['item_name']}")
                                                sp_c2.markdown(f"PKR {sp['amount_spent']:,.2f}")

                                        if is_owner:
                                            st.write("---")
                                            st.markdown("➕ **Log New Project Expense**")
                                            with st.form(f"add_spend_{adv_id}", clear_on_submit=True):
                                                sf1, sf2 = st.columns(2)
                                                new_item = sf1.text_input("Expense Description / Concept", key=f"item_{adv_id}")
                                                new_spend_amt = sf2.number_input("Amount Spent (PKR)", min_value=0.0, step=100.0, key=f"spend_amt_{adv_id}")
                                                if st.form_submit_button("➕ Submit Expense Record", use_container_width=True):
                                                    if new_item.strip() and new_spend_amt > 0:
                                                        if new_spend_amt > remaining + 0.001:
                                                            st.error(f"Action Blocked: This entry exceeds your remaining balance of PKR {remaining:,.2f}.")
                                                        else:
                                                            sb.table("advance_spends").insert({
                                                                "advance_id": adv_id, 
                                                                "item_name": new_item.strip(), 
                                                                "amount_spent": float(new_spend_amt)
                                                            }).execute()
                                                            confirm_and_rerun(f"💵 Logged spend '{new_item.strip()}' (PKR {new_spend_amt:,.2f}).", icon="🧾")
                                                    else:
                                                        st.error("Please enter a valid item concept description and non-zero layout amount.")

                        # ==========================================
                        # 3. CREATION FORM
                        # ==========================================
                        if role in ("CEO", "Accountant"):
                            st.write("---")
                            with st.expander("➕ Allocate New Staff Advance", expanded=adv_rows.empty):
                                if not advance_usernames:
                                    st.warning("⚠️ No users with the 'Advance' role exist in database registry settings yet.")
                                else:
                                    with st.form(f"global_allocate_advance_{pid}", clear_on_submit=True):
                                        new_person = st.selectbox("Select Target Advance Field Worker", advance_usernames)
                                        new_alloc = st.number_input("Initial Allocation Amount (PKR)", min_value=0.0, step=1000.0)
                                        
                                        if st.form_submit_button("➕ Provision Advanced Balance Outflow", use_container_width=True):
                                            if new_person and new_alloc > 0:
                                                try:
                                                    sb.table("advances").insert({
                                                        "project_id": pid,
                                                        "person_name": new_person,
                                                        "allocated_amount": float(new_alloc)
                                                    }).execute()
                                                    confirm_and_rerun(f"💳 Advanced PKR {new_alloc:,.2f} allocated to {new_person}.", icon="✅")
                                                except Exception as e:
                                                    st.error(f"Database insertion failed: {e}")
                                            else:
                                                st.error("Please assign a valid numerical allowance metric.")
                    with t1: render_simple_form_tab(exp_data, "expense", "Expense")
                    with t2: render_simple_form_tab(inc_data, "income", "Income")
                    with t3: render_simple_form_tab(loan_data, "loan", "Loan")
                    with t4: render_advances_tab(pid)

                if not is_read_only:
                    st.write("---")
                    with st.expander("➕ Create New Project Node", expanded=False):
                        with st.form(f"add_p_form_{c_id}", clear_on_submit=True):
                            p_name = st.text_input("New Project Title*")
                            p_desc = st.text_area("Project Description / Scope Notes (Optional)", height=70)

                            if st.form_submit_button("Save Project Node"):
                                if p_name.strip():
                                    try:
                                        sb.table("projects").insert({
                                            "company_id": c_id, "name": p_name.strip(),
                                            "description": p_desc.strip() if p_desc else None
                                        }).execute()
                                        confirm_and_rerun(f"📁 Project '{p_name.strip()}' created successfully.", icon="✅")
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
                            sb.table("companies").insert({"name": c_name.strip(), "site": c_site.strip() or None}).execute()
                            confirm_and_rerun(f"💼 Company '{c_name.strip()}' created successfully.", icon="🏢")
                        except Exception as e:
                            st.error(f"Cannot save company: {e}")

# ==============================================================================
# VIEW C: VOUCHER WORKFLOW
# ==============================================================================

elif menu == "✍️ Voucher Portal":

    if role == "Advance":
        st.error("🔒 Unauthorized: Access to the corporate voucher portal is restricted.")
        st.stop()
        
    st.title("✍️ Corporate Voucher Portal Log")
    
    if "v_form_title" not in st.session_state: st.session_state["v_form_title"] = ""
    if "v_form_amount" not in st.session_state: st.session_state["v_form_amount"] = 0.0
    if "v_form_type" not in st.session_state: st.session_state["v_form_type"] = ""
    if "v_form_remarks" not in st.session_state: st.session_state["v_form_remarks"] = ""

    vouchers_raw = get_all_vouchers_raw()
    voucher_rows = []
    for v in vouchers_raw:
        flat = {k: v[k] for k in v if k not in ("companies", "projects")}
        flat["company_name"] = v["companies"]["name"] if v.get("companies") else None
        flat["project_name"] = v["projects"]["name"] if v.get("projects") else None
        voucher_rows.append(flat)
    vouchers_all = pd.DataFrame(voucher_rows) if voucher_rows else pd.DataFrame(columns=[
        "id", "title", "amount", "remarks", "type", "status", "created_by",
        "review_remarks", "created_at", "project_id", "company_id", "company_name", "project_name"
    ])

    def get_or_create_general_project(company_id):
        existing = sb.table("projects").select("id").eq("company_id", company_id).eq("name", "General / Unassigned").execute()
        if existing.data:
            return int(existing.data[0]["id"])
        sb.table("projects").insert({
            "company_id": company_id, "name": "General / Unassigned",
            "description": "Auto-created bucket for approved vouchers not tied to a specific project."
        }).execute()
        created = sb.table("projects").select("id").eq("company_id", company_id).eq("name", "General / Unassigned").execute()
        return int(created.data[0]["id"])

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
                    check_res = sb.table("vouchers").select("status").eq("id", int(r['id'])).execute()
                    if check_res.data and check_res.data[0]['status'] == 'Pending':
                        sb.table("vouchers").update({"status": "Approved", "review_remarks": "Approved"}).eq("id", int(r['id'])).execute()
                        target_pid = int(r['project_id']) if r['project_id'] and not pd.isna(r['project_id']) else get_or_create_general_project(int(r['company_id']))
                        sb.table("ledgers").insert({
                            "project_id": target_pid, "type": "expense",
                            "title": f"Voucher: {r['title']}", "amount": float(r['amount']),
                            "voucher_ref_id": int(r['id'])
                        }).execute()
                        confirm_and_rerun(f"💸 Voucher '{r['title']}' approved — ledger updated.", icon="✅")
                if b2.button("Decline Voucher Request", key=f"dec_p_{r['id']}"):
                    sb.table("vouchers").update({"status": "Declined", "review_remarks": note or "Declined"}).eq("id", int(r['id'])).execute()
                    confirm_warn_and_rerun(f"🛑 Voucher '{r['title']}' declined.", icon="❌")
                if b3.button("Flag To Be Discussed", key=f"tbd_p_{r['id']}", type="secondary"):
                    sb.table("vouchers").update({"status": "To Be Discussed", "review_remarks": note or "Flagged for audit discussion"}).eq("id", int(r['id'])).execute()
                    confirm_and_rerun(f"💬 Voucher '{r['title']}' flagged for discussion.", icon="🔍")

        with t_disc:
            if d_v.empty: st.caption("No vouchers requiring discussion.")
            for idx, r in d_v.iterrows():
                st.markdown(draw_voucher_ui_node(r, idx), unsafe_allow_html=True)
                note = st.text_input("Review Remark / Direction", key=f"note_d_{r['id']}")
                b1, b2 = st.columns(2)
                if b1.button("Resolve & Approve", key=f"app_d_{r['id']}", type="primary"):
                    check_res = sb.table("vouchers").select("status").eq("id", int(r['id'])).execute()
                    if check_res.data and check_res.data[0]['status'] == 'To Be Discussed':
                        sb.table("vouchers").update({"status": "Approved", "review_remarks": "Approved after strategic session"}).eq("id", int(r['id'])).execute()
                        target_pid = int(r['project_id']) if r['project_id'] and not pd.isna(r['project_id']) else get_or_create_general_project(int(r['company_id']))
                        sb.table("ledgers").insert({
                            "project_id": target_pid, "type": "expense",
                            "title": f"Voucher: {r['title']}", "amount": float(r['amount']),
                            "voucher_ref_id": int(r['id'])
                        }).execute()
                        confirm_and_rerun(f"💸 Voucher '{r['title']}' approved — ledger updated.", icon="✅")
                if b2.button("Resolve & Decline", key=f"dec_d_{r['id']}"):
                    sb.table("vouchers").update({"status": "Declined", "review_remarks": note or "Declined"}).eq("id", int(r['id'])).execute()
                    confirm_warn_and_rerun(f"🛑 Voucher '{r['title']}' declined.", icon="❌")

        with t_hist:
            if h_v.empty:
                st.caption("No historical (approved/declined) vouchers recorded yet.")
            for idx, r in h_v.iterrows():
                st.markdown(draw_voucher_ui_node(r, idx), unsafe_allow_html=True)

    else:
        companies_df = get_all_companies()
        if not companies_df.empty:
            st.subheader("Submit New Voucher Request")

            v_filter_row = st.columns(2)
            target_company = v_filter_row[0].selectbox("Associated Company Entity", companies_df["name"])
            target_co_id = int(companies_df[companies_df["name"] == target_company].iloc[0]["id"])

            projects_df = get_projects_names(target_co_id)
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
                st.session_state["v_form_type"] = v_row3_c1.text_input("Type / Department (Optional)", value=st.session_state["v_form_type"])
                st.session_state["v_form_remarks"] = st.text_area("Remarks (Optional)", value=st.session_state["v_form_remarks"], height=68)
                
                if st.form_submit_button("File Voucher Entry", type="primary", use_container_width=True):
                    if st.session_state["v_form_title"].strip() and st.session_state["v_form_amount"] > 0:
                        sb.table("vouchers").insert({
                            "company_id": target_co_id, "project_id": chosen_project_id,
                            "title": st.session_state["v_form_title"].strip(),
                            "amount": float(st.session_state["v_form_amount"]),
                            "remarks": st.session_state["v_form_remarks"].strip() or None,
                            "type": st.session_state["v_form_type"].strip() or "General",
                            "created_by": current_user["username"], "status": "Pending"
                        }).execute()
                        st.session_state["v_form_title"] = ""
                        st.session_state["v_form_amount"] = 0.0
                        st.session_state["v_form_type"] = ""
                        st.session_state["v_form_remarks"] = ""
                        confirm_and_rerun("📄 Voucher request submitted and lodged into the pending queue.", icon="📥")
                    else:
                        st.error("Please enter a Valid Title and non-zero Amount.")

        if role == "Accountant":
            my_v = vouchers_all if not vouchers_all.empty else pd.DataFrame()
        else:
            my_v = vouchers_all[vouchers_all["created_by"] == current_user["username"]] if not vouchers_all.empty else pd.DataFrame()

        m_act = my_v[my_v["status"].isin(["Pending", "To Be Discussed"])] if not my_v.empty else pd.DataFrame()
        m_disc = my_v[my_v["status"] == "To Be Discussed"] if not my_v.empty else pd.DataFrame()
        m_hist = my_v[my_v["status"].isin(["Approved", "Declined"])] if not my_v.empty else pd.DataFrame()

        def render_voucher_with_edit(r, idx):
            st.markdown(draw_voucher_ui_node(r, idx), unsafe_allow_html=True)
            can_edit = (r["created_by"] == current_user["username"]) and (str(r["status"]) in ("Pending", "To Be Discussed"))
            if can_edit:
                edit_key = f"edit_voucher_{int(r['id'])}"
                if st.button("✏️ Edit Request", key=f"btn_{edit_key}", use_container_width=True):
                    st.session_state[edit_key] = not st.session_state.get(edit_key, False)
                    st.rerun()

                if st.session_state.get(edit_key, False):
                    with st.form(f"form_{edit_key}"):
                        ve1, ve2 = st.columns(2)
                        ve_title = ve1.text_input("Voucher Title*", value=r["title"])
                        ve_amount = ve2.number_input("Requested Payout Amount (PKR)*", min_value=0.0, step=10.0, value=float(r["amount"]))
                        ve_remarks = st.text_area("Remarks", value=r["remarks"] if not pd.isna(r["remarks"]) else "", height=68)
                        vs1, vs2 = st.columns(2)
                        save_v = vs1.form_submit_button("💾 Save Changes", type="primary", use_container_width=True)
                        cancel_v = vs2.form_submit_button("✖️ Cancel", use_container_width=True)
                        if save_v:
                            if ve_title.strip() and ve_amount > 0:
                                sb.table("vouchers").update({
                                    "title": ve_title.strip(), "amount": float(ve_amount),
                                    "remarks": ve_remarks.strip() or None
                                }).eq("id", int(r["id"])).execute()
                                st.session_state[edit_key] = False
                                confirm_and_rerun(f"✏️ Voucher request updated to '{ve_title.strip()}'.", icon="💾")
                            else:
                                st.error("Please enter a valid title and non-zero amount.")
                        if cancel_v:
                            st.session_state[edit_key] = False
                            st.rerun()

        st.write("---")
        st.subheader("User Tracking Registry Pipeline")
        ta1, ta2, ta3 = st.tabs([f"📌 Active Requests ({len(m_act)})", f"💬 Discussion Pending ({len(m_disc)})", f"🗂️ Filed History Ledger ({len(m_hist)})"])

        with ta1:
            if m_act.empty: st.caption("No active items.")
            for idx, r in m_act.iterrows(): render_voucher_with_edit(r, idx)
        with ta2:
            if m_disc.empty: st.caption("No vouchers currently flagged for review discussion.")
            for idx, r in m_disc.iterrows(): render_voucher_with_edit(r, idx)
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
                        dash_flag = True if acct_role in ["Accountant", "CEO"] else False
                        sb.table("users").insert({
                            "username": acct_id.strip(), "password": acct_pw.strip(),
                            "role": acct_role, "can_view_dashboard": dash_flag
                        }).execute()
                        confirm_and_rerun(f"👤 Account '{acct_id.strip()}' created as {acct_role}.", icon="🔑")
                    except Exception:
                        st.error(f"Cannot provision user: The ID key '{acct_id.strip()}' already exists.")
                else:
                    st.error("Both fields are strictly mandatory.")

    with st_tabs[1]:
        all_users_df = get_all_users_summary()

        if not all_users_df.empty:
            st.markdown("**Modify or Revoke Workspace Permissions**")

            selected_username = st.selectbox("Select Target Workspace Account", all_users_df["username"])
            user_row = all_users_df[all_users_df["username"] == selected_username].iloc[0]
            target_user_id = int(user_row["id"])
            current_target_role = user_row["role"]

            st.info(f"Targeting: **{selected_username}** | Active Role: `{current_target_role}`")

            # --- FORM 1: ROLE UPDATE ---
            with st.form(f"change_role_form_{target_user_id}"):
                st.markdown("🔄 **Update Account Role Assignment**")
                role_options = ["Accountant", "Advance", "CEO"]

                try:
                    default_role_idx = role_options.index(current_target_role)
                except ValueError:
                    default_role_idx = 0

                new_assigned_role = st.selectbox("Select New Workspace Role", role_options, index=default_role_idx)

                if st.form_submit_button("Save New Role Matrix"):
                    dash_flag = True if new_assigned_role in ["Accountant", "CEO"] else False
                    sb.table("users").update({
                        "role": new_assigned_role, "can_view_dashboard": dash_flag
                    }).eq("id", target_user_id).execute()
                    confirm_and_rerun(f"🛡️ Role updated for '{selected_username}' to {new_assigned_role}.", icon="🔄")
            
            # --- FORM 2: PASSWORD OVERWRITE ---
            with st.form(f"change_pass_form_{target_user_id}", clear_on_submit=True):
                st.markdown("🔒 **Administrative Security Key Reset**")
                new_pass = st.text_input("Assign New Security Key / Password", type="password")

                if st.form_submit_button("Force Overwrite Password"):
                    if new_pass.strip():
                        sb.table("users").update({"password": new_pass.strip()}).eq("id", target_user_id).execute()
                        confirm_and_rerun(f"🔒 Password updated for user '{selected_username}'.", icon="🔑")
                    else:
                        st.error("Password string empty.")
            st.markdown("⚠️ **Danger Zone**")
            if st.button(f"🚨 Permanently Revoke Access for '{selected_username}'", use_container_width=True, type="secondary"):
                if selected_username == current_user["username"]:
                    st.error("Operation Denied: You cannot delete your own session account identity while logged in.")
                else:
                    sb.table("users").delete().eq("id", target_user_id).execute()
                    confirm_warn_and_rerun(f"🚨 User '{selected_username}' has been removed.", icon="❌")
        else:
            st.caption("No registered member accounts loaded.")
