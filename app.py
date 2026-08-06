import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import datetime
import random
import string
import time
import os
import shutil
import socket
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client

# Bypassing local DNS timeouts for Supabase domain resolution
_orig_getaddrinfo = socket.getaddrinfo
def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if host == "hcccwrjngbsbftapzums.supabase.co":
        return _orig_getaddrinfo("172.64.149.246", port, family, type, proto, flags)
    return _orig_getaddrinfo(host, port, family, type, proto, flags)
socket.getaddrinfo = _patched_getaddrinfo

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
        except Exception as e:
            st.error(
                f"🚨 **Critical: Cannot connect to Supabase.**\n\n"
                f"Error: `{e}`\n\n"
                f"Please check your `.streamlit/secrets.toml` configuration."
            )
            st.stop()

    def to_df(self, response, columns=None):
        """Convert a Supabase response to a pandas DataFrame."""
        if response and hasattr(response, 'data') and response.data:
            df = pd.DataFrame(response.data)
            if columns:
                for c in columns:
                    if c not in df.columns:
                        df[c] = None
            return df
        return pd.DataFrame(columns=columns or [])


# --- DEFINE RESOURCE CACHE BEFORE CALLING ---
@st.cache_resource
def get_db():
    return DBConnection()

@st.cache_resource
def _seed_default_users(_db):
    """One-time seed check — runs only once per server lifecycle."""
    try:
        result = _db.client.table("users").select("id", count="exact").limit(0).execute()
        if result.count == 0:
            _db.client.table("users").insert([
                {"username": "ceo", "password": "ceo", "role": "CEO", "can_view_dashboard": True},
                {"username": "accountant", "password": "accountant", "role": "Accountant", "can_view_dashboard": True},
            ]).execute()
    except Exception:
        pass
    try:
        master = _db.client.table("users").select("id").eq("username", "asif.arain").execute()
        if not master.data:
            _db.client.table("users").insert({
                "username": "asif.arain", "password": "admin123", "role": "CEO", "can_view_dashboard": True
            }).execute()
    except Exception:
        pass

db = get_db()
_seed_default_users(db)
sb = db.client  # shorthand for the supabase client

# ==============================================================================
# OPTIMIZED GLOBAL CACHED READS (PARALLEL MULTI-THREADED FETCHING)
# ==============================================================================

@st.cache_data(ttl=300, show_spinner=False)
def fetch_all_table_data():
    """Fetch core tables concurrently in parallel threads for maximum speed."""
    def _fetch_table(table_name, select_str="*", order_col=None, desc=False):
        try:
            q = sb.table(table_name).select(select_str)
            if order_col:
                q = q.order(order_col, desc=desc)
            return q.execute()
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=10) as executor:
        f_ledgers = executor.submit(_fetch_table, "ledgers")
        f_vouchers = executor.submit(_fetch_table, "vouchers", "*", "id", True)
        f_advances = executor.submit(_fetch_table, "advances")
        f_spends = executor.submit(_fetch_table, "advance_spends")
        f_quotations = executor.submit(_fetch_table, "quotations", "*", "id", True)
        f_estimates = executor.submit(_fetch_table, "quotation_estimates_invoices")
        f_components = executor.submit(_fetch_table, "quotation_cost_components")
        f_companies = executor.submit(_fetch_table, "companies", "*", "name", False)
        f_projects = executor.submit(_fetch_table, "projects", "*", "name", False)
        f_users = executor.submit(_fetch_table, "users", "id, username, role, can_view_dashboard", "username", False)

    ledgers_res = f_ledgers.result()
    vouchers_res = f_vouchers.result()
    advances_res = f_advances.result()
    spends_res = f_spends.result()
    quotations_res = f_quotations.result()
    estimates_res = f_estimates.result()
    components_res = f_components.result()
    companies_res = f_companies.result()
    projects_res = f_projects.result()
    users_res = f_users.result()

    return {
        "ledgers": db.to_df(ledgers_res, columns=["id", "project_id", "type", "title", "cheque_number", "voucher_ref_id", "amount", "created_at"]),
        "vouchers": db.to_df(vouchers_res, columns=["id", "company_id", "project_id", "title", "amount", "remarks", "type", "created_by", "review_remarks", "status", "created_at"]),
        "advances": db.to_df(advances_res, columns=["id", "project_id", "person_name", "allocated_amount"]),
        "spends": db.to_df(spends_res, columns=["id", "advance_id", "item_name", "amount_spent", "created_at"]),
        "quotations": db.to_df(quotations_res, columns=["id", "company_name", "project_name", "quotation_number", "amount", "status", "lead_generator", "created_by", "notes", "created_at"]),
        "estimates": db.to_df(estimates_res, columns=["id", "quotation_id", "invoice_number", "est_material_cost", "est_labor_cost", "est_overhead_cost", "invoice_amount", "invoice_status", "updated_by", "created_at"]),
        "components": db.to_df(components_res, columns=["id", "quotation_id", "component_name", "price", "description", "actual_price", "purchaser_notes", "purchased_by", "created_by", "created_at"]),
        "companies": db.to_df(companies_res, columns=["id", "name", "site", "description"]),
        "projects": db.to_df(projects_res, columns=["id", "company_id", "name", "description"]),
        "users": db.to_df(users_res, columns=["id", "username", "role", "can_view_dashboard"])
    }

def _safe_float(value):
    if value is None or pd.isna(value):
        return 0.0
    return float(value)

def _safe_date(value, default=None):
    if default is None:
        default = datetime.date.today()
    if value is None or value is True or value is False or pd.isna(value) or isinstance(value, bool):
        return default
    try:
        if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime) and not isinstance(value, bool):
            return value
        dt = pd.to_datetime(value)
        if pd.isna(dt):
            return default
        d_val = dt.date()
        if isinstance(d_val, datetime.date) and not isinstance(d_val, bool):
            return d_val
        return default
    except Exception:
        return default

def _invalidate_data_cache():
    """Targeted cache invalidation — clears bulk data fetch and user summary cache."""
    fetch_all_table_data.clear()
    get_all_users_summary.clear()

def reset_form_states():
    """Safely reset expander and form state flags without mutating widget keys."""
    close_all_open_forms()
    st.session_state["q_form_company"] = ""
    st.session_state["q_form_project"] = ""
    st.session_state["q_form_num"] = ""
    st.session_state["q_form_amount"] = 0.0
    st.session_state["q_form_notes"] = ""

def close_all_open_forms(except_key=None):
    """Mutually exclusive form toggle — ensures only ONE company, project, quotation, or edit form is open at a time."""
    for key in list(st.session_state.keys()):
        if key == except_key:
            continue
        if key.startswith("show_add_"):
            try: st.session_state[key] = False
            except Exception: pass
        elif key in ("edit_co_id", "edit_proj_id", "active_edit_q_id"):
            try: st.session_state[key] = None
            except Exception: pass
        elif key.startswith("edit_advperson_") or key.startswith("edit_sp_") or key.startswith("edit_plan_comp_") or key.startswith("edit_income_") or key.startswith("edit_expense_") or key.startswith("edit_loan_") or key.startswith("edit_v_"):
            try: st.session_state[key] = False
            except Exception: pass

def confirm_and_rerun(message, icon="✅"):
    """Shows a toast confirmation, resets form state to automatically close active forms, clears data cache, then reruns."""
    st.toast(message, icon=icon)
    reset_form_states()
    _invalidate_data_cache()
    st.rerun()

def confirm_warn_and_rerun(message, icon="⚠️"):
    """Same as confirm_and_rerun but for warnings/declines/removals."""
    st.toast(message, icon=icon)
    reset_form_states()
    _invalidate_data_cache()
    st.rerun()

def auto_provision_project(company_name, project_name):
    if not company_name or not project_name:
        return
    co_name = company_name.strip()
    p_name = project_name.strip()
    try:
        # Check existing company
        res_co = sb.table("companies").select("id").ilike("name", co_name).execute()
        if res_co.data:
            company_id = int(res_co.data[0]["id"])
        else:
            res_ins_co = sb.table("companies").insert({"name": co_name}).execute()
            company_id = int(res_ins_co.data[0]["id"])

        # Check existing project under this company
        res_p = sb.table("projects").select("id").eq("company_id", company_id).ilike("name", p_name).execute()
        if not res_p.data:
            sb.table("projects").insert({
                "company_id": company_id,
                "name": p_name,
                "description": None
            }).execute()
        _invalidate_data_cache()
    except Exception as e:
        print(f"Auto-provisioning failed: {e}")

def _compute_all_balances(tables):
    """Single-pass batch computation of ALL project balances. Returns dict keyed by project_id."""
    _zero = {"income": 0.0, "expense": 0.0, "loans": 0.0, "advances_allocated": 0.0, "advances_spent": 0.0, "advances_remaining": 0.0, "balance": 0.0, "profit": 0.0}
    
    l_df = tables["ledgers"]
    v_df = tables["vouchers"]
    adv_df = tables["advances"]
    sp_df = tables["spends"]
    
    # Pre-convert amounts to float once
    if not l_df.empty:
        l_df = l_df.copy()
        l_df["_amt"] = l_df["amount"].apply(_safe_float)
        income_by_proj = l_df[l_df["type"] == "income"].groupby("project_id")["_amt"].sum()
        expense_by_proj = l_df[l_df["type"] == "expense"].groupby("project_id")["_amt"].sum()
        loan_by_proj = l_df[l_df["type"] == "loan"].groupby("project_id")["_amt"].sum()
    else:
        income_by_proj = expense_by_proj = loan_by_proj = pd.Series(dtype=float)

    if not v_df.empty:
        approved_v = v_df[v_df["status"] == "Approved"].copy()
        approved_v["_amt"] = approved_v["amount"].apply(_safe_float)
        voucher_by_proj = approved_v.groupby("project_id")["_amt"].sum()
    else:
        voucher_by_proj = pd.Series(dtype=float)

    if not adv_df.empty:
        adv_df_c = adv_df.copy()
        adv_df_c["_amt"] = adv_df_c["allocated_amount"].apply(_safe_float)
        alloc_by_proj = adv_df_c.groupby("project_id")["_amt"].sum()
        
        if not sp_df.empty:
            sp_df_c = sp_df.copy()
            sp_df_c["_amt"] = sp_df_c["amount_spent"].apply(_safe_float)
            # Map advance_id -> project_id
            adv_proj_map = dict(zip(adv_df_c["id"].astype(int), adv_df_c["project_id"]))
            sp_df_c["project_id"] = sp_df_c["advance_id"].astype(int).map(adv_proj_map)
            spent_by_proj = sp_df_c.dropna(subset=["project_id"]).groupby("project_id")["_amt"].sum()
        else:
            spent_by_proj = pd.Series(dtype=float)
    else:
        alloc_by_proj = spent_by_proj = pd.Series(dtype=float)

    # Collect all unique project IDs
    all_pids = set()
    for s in [income_by_proj, expense_by_proj, loan_by_proj, voucher_by_proj, alloc_by_proj, spent_by_proj]:
        all_pids.update(s.index)

    result = {}
    for pid in all_pids:
        inc = income_by_proj.get(pid, 0.0)
        exp = expense_by_proj.get(pid, 0.0)
        ln = loan_by_proj.get(pid, 0.0)
        vch = voucher_by_proj.get(pid, 0.0)
        alloc = alloc_by_proj.get(pid, 0.0)
        spent = spent_by_proj.get(pid, 0.0)
        
        total_exp = exp + vch
        balance = inc + ln - total_exp - alloc
        profit = inc - total_exp - alloc
        
        result[pid] = {
            "income": inc, "expense": total_exp, "loans": ln,
            "advances_allocated": alloc, "advances_spent": spent,
            "advances_remaining": alloc - spent, "balance": balance, "profit": profit
        }
    
    return result, _zero

def get_project_balance(project_id, _precomputed=None, _zero=None):
    """Get balance for a single project. Uses precomputed dict if available."""
    if _precomputed is not None:
        return _precomputed.get(project_id, _zero or {"income": 0.0, "expense": 0.0, "loans": 0.0, "advances_allocated": 0.0, "advances_spent": 0.0, "advances_remaining": 0.0, "balance": 0.0, "profit": 0.0})
    tables = fetch_all_table_data()
    balances, zero = _compute_all_balances(tables)
    return balances.get(project_id, zero)

def get_company_balance(company_id, _precomputed=None, _zero=None):
    """Get aggregated balance for all projects under a company."""
    projects_df = get_projects_full(company_id)
    empty_bal = {"income": 0.0, "expense": 0.0, "loans": 0.0, "advances_allocated": 0.0, "advances_spent": 0.0, "advances_remaining": 0.0, "balance": 0.0, "profit": 0.0}
    if projects_df.empty:
        return empty_bal

    if _precomputed is None:
        tables = fetch_all_table_data()
        _precomputed, _zero = _compute_all_balances(tables)

    totals = dict(empty_bal)
    for pid in projects_df["id"].astype(int).tolist():
        pb = _precomputed.get(pid, _zero or empty_bal)
        for k in totals:
            totals[k] += pb[k]
    
    # Recalculate balance and profit from aggregated values
    totals["balance"] = totals["income"] + totals["loans"] - totals["expense"] - totals["advances_allocated"]
    totals["profit"] = totals["income"] - totals["expense"] - totals["advances_allocated"]
    return totals

EXEC_TAG = "[Created in Execution(Accounts)]"

def get_all_companies(include_execution_created=True):
    tables = fetch_all_table_data()
    c_df = tables["companies"]
    if not include_execution_created and not c_df.empty and "description" in c_df.columns:
        return c_df[~c_df["description"].fillna("").str.contains(EXEC_TAG, regex=False)]
    return c_df

def get_projects_full(company_id, include_execution_created=True):
    tables = fetch_all_table_data()
    p_df = tables["projects"]
    if not p_df.empty:
        filtered = p_df[p_df["company_id"] == company_id]
        if not include_execution_created and "description" in filtered.columns:
            filtered = filtered[~filtered["description"].fillna("").str.contains(EXEC_TAG, regex=False)]
        return filtered
    return pd.DataFrame(columns=["id", "company_id", "name", "description"])

def get_projects_names(company_id, include_execution_created=True):
    projects_df = get_projects_full(company_id, include_execution_created=include_execution_created)
    if not projects_df.empty:
        return projects_df[["id", "name"]]
    return pd.DataFrame(columns=["id", "name"])

def get_users_by_role(role_name):
    all_users = get_all_users_summary()
    if not all_users.empty:
        return all_users[all_users["role"].astype(str).str.contains(role_name, case=False, na=False)]["username"].tolist()
    return []

@st.cache_data(ttl=300, show_spinner=False)
def get_all_users_summary():
    tables = fetch_all_table_data()
    u_df = tables.get("users", pd.DataFrame())
    if not u_df.empty and "username" in u_df.columns:
        return u_df[["id", "username", "role"]].copy()
    # Fallback: direct DB call if users table missing from bulk fetch
    res = sb.table("users").select("id, username, role").order("username").execute()
    return db.to_df(res, columns=["id", "username", "role"])

def get_all_vouchers_raw():
    tables = fetch_all_table_data()
    v_df = tables["vouchers"]
    c_df = tables["companies"]
    p_df = tables["projects"]

    if v_df.empty:
        return []

    c_map = dict(zip(c_df["id"].astype(int), c_df["name"])) if not c_df.empty else {}
    p_map = dict(zip(p_df["id"].astype(int), p_df["name"])) if not p_df.empty else {}

    raw_list = []
    for _, row in v_df.iterrows():
        v_dict = row.to_dict()
        cid = int(row["company_id"]) if not pd.isna(row["company_id"]) else None
        pid = int(row["project_id"]) if not pd.isna(row["project_id"]) else None
        v_dict["companies"] = {"name": c_map.get(cid, "—")} if cid else None
        v_dict["projects"] = {"name": p_map.get(pid, "—")} if pid else None
        raw_list.append(v_dict)
    return raw_list

# ==============================================================================
# 2. DESIGN & STYLING ASSETS (High Density Professional Overrides)
# ==============================================================================

st.markdown("""
<style>
/* Hide default Streamlit input instructions ("Press Enter to apply") */
div[data-testid="InputInstructions"] {
    display: none !important;
}

/* === MONOCHROME DESIGN SYSTEM & DENSITY === */
body, html, .main, [data-testid="stAppViewContainer"], [data-testid="stApp"], [data-testid="stAppViewBlockContainer"], div[data-testid="stHeader"], header {
    background-color: #ffffff !important;
    background: #ffffff !important;
    color: #111111 !important;
}
div[data-testid="stDecoration"] {
    display: none !important;
}
section[data-testid="stSidebar"], [data-testid="stSidebarUserContent"], section[data-testid="stSidebar"] * {
    background-color: #f9fafb !important;
}
section[data-testid="stSidebar"], [data-testid="stSidebarUserContent"] {
    width: 14rem;
    background-color: #f9fafb !important;
    border-right: none !important;
    border: none !important;
}
section[data-testid="stSidebar"] .block-container {
    padding: 2.2rem 0.4rem 0.3rem 0.4rem !important;
    background-color: #f9fafb !important;
}
.block-container { padding: 5.5rem 0.5rem 0.15rem 0.5rem !important; max-width: 100% !important; background-color: #ffffff !important; }
div.stBlock { margin-bottom: 0px !important; padding-bottom: 0px !important; }
div[data-testid="stVerticalBlock"] > div { gap: 0.15rem !important; }
.stTabs { margin-top: 0px !important; }
.stTabs [data-baseweb="tab-list"] { gap: 0px !important; background-color: #f3f4f6 !important; border-bottom: 1px solid #d1d5db !important; }
.stTabs [data-baseweb="tab"] { font-size: 0.94rem !important; padding: 6px 10px !important; line-height: 1.3 !important; color: #4b5563 !important; background-color: transparent !important; }
.stTabs [data-baseweb="tab"][aria-selected="true"] { color: #111111 !important; font-weight: bold !important; border-bottom: 2px solid #111111 !important; background-color: #ffffff !important; }
.stDataFrame { margin-bottom: 0.15rem !important; }

/* Headings */
h1, h2, h3, h4, h5, h6 { color: #111111 !important; }
h1 { margin: 0.3rem 0 !important; font-size: 1.6rem !important; line-height: 1.5 !important; }
h2 { margin: 0.2rem 0 !important; font-size: 1.3rem !important; line-height: 1.4 !important; }
h3 { margin: 0.15rem 0 !important; font-size: 1.15rem !important; line-height: 1.4 !important; }
h4 { margin: 0.15rem 0 !important; font-size: 1.05rem !important; line-height: 1.4 !important; }
h5 { margin: 0.1rem 0 !important; font-size: 0.95rem !important; line-height: 1.3 !important; }
p, li, span, strong, code, em, small { font-size: 1.0rem !important; line-height: 1.4 !important; color: #1f2937 !important; }

/* Forms & Inputs */
div[data-testid="stForm"] { padding: 0.25rem 0.4rem !important; margin-bottom: 0.1rem !important; border-radius: 4px !important; border: 1px solid #d1d5db !important; background-color: #ffffff !important; }
label { font-size: 0.9rem !important; font-weight: 600 !important; margin-bottom: 0px !important; color: #111111 !important; }
div[data-testid="stWidgetLabel"], div[data-testid="stWidgetLabel"] *, label[data-testid="stWidgetLabel"], label[data-testid="stWidgetLabel"] * {
    margin-bottom: 0px !important;
    padding-bottom: 0px !important;
    margin-top: 0px !important;
    line-height: 1.2 !important;
}
div[data-testid="stSelectbox"] > div, div[data-testid="stTextInput"] > div, div[data-testid="stNumberInput"] > div, div[data-testid="stTextArea"] > div {
    gap: 2px !important;
}
div[data-baseweb="input"], div[data-baseweb="select"], div[data-baseweb="textarea"], div[data-baseweb="base-input"], input, select, textarea {
    min-height: 1.8rem !important;
    padding: 2px 6px !important;
    font-size: 0.95rem !important;
    border: 1.5px solid #334155 !important;
    border-radius: 5px !important;
    background-color: #ffffff !important;
    color: #0f172a !important;
}
div[data-baseweb="input"]:focus-within, div[data-baseweb="select"]:focus-within, div[data-baseweb="textarea"]:focus-within {
    border: 2px solid #2563eb !important;
    box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.2) !important;
}
div[data-baseweb="input"] input, div[data-baseweb="select"] *, div[data-baseweb="textarea"] textarea, input, select, textarea {
    color: #0f172a !important;
    background-color: transparent !important;
}
.stSelectbox, .stTextInput, .stNumberInput, .stTextArea { margin-bottom: 0.05rem !important; }

/* Dropdowns / Selectboxes: Remove blinking text caret, input box artifact & use pointer cursor */
.stSelectbox, .stSelectbox *, div[data-baseweb="select"], div[data-baseweb="select"] *, div[role="combobox"], div[role="combobox"] * {
    caret-color: transparent !important;
    cursor: pointer !important;
}
div[data-baseweb="select"] input, div[role="combobox"] input {
    caret-color: transparent !important;
    width: 0px !important;
    max-width: 0px !important;
    opacity: 0 !important;
    position: absolute !important;
    pointer-events: none !important;
}

/* Text, Digit, and Textarea fields: Keep text cursor & active blinking caret */
.stTextInput input, .stNumberInput input, .stTextArea textarea, div[data-baseweb="input"] input, div[data-baseweb="textarea"] textarea, input[type="text"], input[type="number"], textarea {
    caret-color: #111111 !important;
    cursor: text !important;
}

/* Buttons & Popovers */
.stButton button, button, div[data-testid="stPopover"] button {
    padding: 0.1rem 0.4rem !important;
    font-size: 0.9rem !important;
    min-height: 1.5rem !important;
    border-radius: 3px !important;
    background-color: #e5e7eb !important;
    color: #111111 !important;
    border: 1px solid #cbd5e1 !important;
}
.stButton button:hover, button:hover, div[data-testid="stPopover"] button:hover {
    background-color: #d1d5db !important;
    border-color: #94a3b8 !important;
    color: #000000 !important;
}

/* Metrics */
div[data-testid="stMetricValue"] { font-size: 0.82rem !important; font-weight: 700 !important; line-height: 1.2 !important; color: #111111 !important; }
div[data-testid="stMetricLabel"] { font-size: 0.7rem !important; margin-bottom: 0px !important; line-height: 1.1 !important; color: #4b5563 !important; }
div[data-testid="stMetricDelta"] { font-size: 0.58rem !important; }
div[data-testid="stMetric"] { padding: 2px 5px !important; background: #f9fafb !important; border-radius: 4px; border: 1px solid #d1d5db !important; }

/* Expanders */
div[data-testid="stExpander"] { margin-bottom: 0.1rem !important; border: 1px solid #d1d5db !important; background-color: #ffffff !important; }
div[data-testid="stExpander"] summary { font-size: 0.88rem !important; padding: 3px 6px !important; background-color: #f9fafb !important; color: #111111 !important; }
div[data-testid="stExpander"] div[data-testid="stExpanderDetails"] { padding: 0.2rem 0.4rem !important; }

/* Containers */
div[data-testid="stHorizontalBlock"] { gap: 0.25rem !important; }
div[data-testid="column"] { padding: 0 0.1rem !important; }
.stAlert { padding: 0.2rem 0.4rem !important; font-size: 0.85rem !important; margin-bottom: 0.1rem !important; background-color: #f3f4f6 !important; border: 1px solid #d1d5db !important; border-left: 4px solid #111111 !important; color: #111111 !important; }
.stAlert p { font-size: 0.85rem !important; margin: 0 !important; color: #111111 !important; }

/* Dividers */
hr { margin: 0.15rem 0 !important; border-color: #e5e7eb !important; }

/* Radio nav in sidebar */
section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] {
    gap: 6px !important;
    padding: 0px !important;
}
section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label[data-baseweb="radio"] > div:first-child {
    display: none !important;
}
section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label[data-baseweb="radio"] {
    padding: 8px 12px !important;
    margin: 0px !important;
    border-radius: 6px !important;
    background-color: transparent !important;
    border-left: none !important;
    border: none !important;
    width: 100% !important;
    display: flex !important;
    align-items: center !important;
    cursor: pointer !important;
    transition: all 0.2s ease !important;
}
section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label[data-baseweb="radio"]:hover {
    background-color: #f3f4f6 !important;
    border-left: none !important;
    border: none !important;
}
section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label[data-baseweb="radio"]:has(input[type="radio"]:checked) {
    background-color: #eff6ff !important;
    border: 1px solid #93c5fd !important;
    border-left: 5px solid #2563eb !important;
    border-radius: 6px !important;
    box-shadow: 0 1px 3px rgba(37, 99, 235, 0.12) !important;
}
section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label[data-baseweb="radio"]:has(input[type="radio"]:checked) p,
section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label[data-baseweb="radio"]:has(input[type="radio"]:checked) span {
    font-weight: 700 !important;
    color: #1e40af !important;
}

/* Popover */
div[data-testid="stPopover"] button { font-size: 0.82rem !important; padding: 0.1rem 0.35rem !important; }

/* Table zebra striping */
div[data-testid="stDataFrame"] table tbody tr:nth-child(even) {
    background-color: #f8fafc !important;
}
div[data-testid="stDataFrame"] table tbody tr:nth-child(odd) {
    background-color: #ffffff !important;
}

/* Alternating Tones for Expanders */
div[data-testid="stExpander"]:nth-of-type(3n+1) {
    background-color: #f8fafc !important;
    border-left: 5px solid #2563eb !important;
    border-radius: 6px !important;
}
div[data-testid="stExpander"]:nth-of-type(3n+2) {
    background-color: #f0fdf4 !important;
    border-left: 5px solid #059669 !important;
    border-radius: 6px !important;
}
div[data-testid="stExpander"]:nth-of-type(3n+0) {
    background-color: #faf5ff !important;
    border-left: 5px solid #7c3aed !important;
    border-radius: 6px !important;
}

/* Cards & Containers Toning */
.compact-card {
border: 1px solid #cbd5e1;
border-radius: 6px;
padding: 8px 12px;
margin-bottom: 6px;
background-color: #ffffff;
color: #111111 !important;
box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}
.compact-card:nth-of-type(3n+1) {
    background-color: #f8fafc !important;
    border-left: 5px solid #2563eb !important;
}
.compact-card:nth-of-type(3n+2) {
    background-color: #f0fdf4 !important;
    border-left: 5px solid #059669 !important;
}
.compact-card:nth-of-type(3n+0) {
    background-color: #fff7ed !important;
    border-left: 5px solid #ea580c !important;
}
.compact-card h4 { font-size: 0.88rem !important; color: #111111 !important; margin: 0 !important; }
.compact-card h3 { font-size: 0.95rem !important; color: #111111 !important; margin: 0 !important; }
.compact-card p, .compact-card span, .compact-card small, .compact-card strong, .compact-card em { font-size: 0.74rem !important; color: #4b5563 !important; }

/* Voucher cards */
.voucher-card {
background: #ffffff !important;
border: 1px solid #d1d5db !important;
border-left: 4px solid #111111 !important;
border-radius: 4px;
padding: 3px 7px;
margin-bottom: 2px;
color: #111111 !important;
}
.voucher-card.alt {
background: #f9fafb !important;
border: 1px solid #d1d5db !important;
border-left: 4px solid #374151 !important;
}
.voucher-title { font-size: 0.74rem; font-weight: 700; color: #111111 !important; }
.voucher-meta { font-size: 0.62rem; color: #4b5563 !important; margin-top: 0px; }
.voucher-remarks { font-size: 0.65rem; margin-top: 1px; padding: 1px 4px; background: #f3f4f6 !important; border-radius: 3px; border-left: 2px solid #111111; color: #1f2937 !important; }

/* Button Inner Text / Code Blocks / Overlays Color Fixes */
.stButton button *, button *, div[data-testid="stPopover"] button * {
    color: #111111 !important;
}
code {
    background-color: #f3f4f6 !important;
    color: #1f2937 !important;
    padding: 2px 4px !important;
    border-radius: 3px !important;
    font-family: monospace !important;
    font-size: 0.85rem !important;
}
div[role="listbox"], ul[role="listbox"], div[data-baseweb="menu"] {
    background-color: #ffffff !important;
    color: #111111 !important;
}
div[role="option"], li[role="option"], div[data-baseweb="menu"] * {
    background-color: #ffffff !important;
    color: #111111 !important;
}
div[role="option"]:hover, li[role="option"]:hover {
    background-color: #f3f4f6 !important;
    color: #111111 !important;
}
div[data-baseweb="calendar"] * {
    background-color: #ffffff !important;
    color: #111111 !important;
}
div[data-baseweb="calendar"] button:hover {
    background-color: #f3f4f6 !important;
}

/* Multiselect Badge / Tag – Ultra-High Specificity Override */
div[data-testid="stMultiSelect"] span[data-baseweb="tag"],
div[data-testid="stMultiSelect"] div[data-baseweb="tag"],
section[data-testid="stSidebar"] span[data-baseweb="tag"],
section[data-testid="stSidebar"] div[data-baseweb="tag"],
[data-baseweb="tag"],
div[data-baseweb="tag"],
span[data-baseweb="tag"] {
    background-color: #7c3aed !important;
    background: linear-gradient(135deg, #7c3aed 0%, #6366f1 100%) !important;
    color: #ffffff !important;
    border: 1px solid rgba(255,255,255,0.2) !important;
    border-radius: 20px !important;
    padding: 2px 8px !important;
    font-weight: 600 !important;
}

div[data-testid="stMultiSelect"] span[data-baseweb="tag"] *,
div[data-testid="stMultiSelect"] div[data-baseweb="tag"] *,
section[data-testid="stSidebar"] [data-baseweb="tag"] *,
[data-baseweb="tag"] *,
[data-baseweb="tag"] span,
[data-baseweb="tag"] div,
[data-baseweb="tag"] p {
    color: #ffffff !important;
    background-color: transparent !important;
    background: transparent !important;
    font-weight: 600 !important;
    font-size: 0.88rem !important;
}

div[data-testid="stMultiSelect"] [data-baseweb="tag"] [role="button"],
[data-baseweb="tag"] [role="button"],
[data-baseweb="tag"] svg,
[data-baseweb="tag"] path {
    fill: #ffffff !important;
    color: #ffffff !important;
    stroke: #ffffff !important;
    background: transparent !important;
}

[data-baseweb="tag"]:hover {
    background-color: #6d28d9 !important;
    background: linear-gradient(135deg, #6d28d9 0%, #4f46e5 100%) !important;
}

[data-baseweb="tag"] [role="button"]:hover {
    background-color: rgba(255,255,255,0.15) !important;
    border-radius: 50% !important;
}

/* Toast, Modals, Dialogs, Tooltips, Popovers Grayscale Color Overrides */
div[data-testid="stToast"] {
    background-color: #ffffff !important;
    background: #ffffff !important;
    border: 1px solid #cbd5e1 !important;
    color: #111111 !important;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1) !important;
}
div[data-testid="stToast"] * {
    color: #111111 !important;
}
div[data-baseweb="popover"], div[data-baseweb="popover"] * {
    background-color: #ffffff !important;
    color: #111111 !important;
}
div[role="dialog"], div[data-baseweb="modal"], div[data-baseweb="modal"] * {
    background-color: #ffffff !important;
    color: #111111 !important;
}
div[role="tooltip"], div[role="tooltip"] * {
    background-color: #f9fafb !important;
    color: #111111 !important;
    border: 1px solid #cbd5e1 !important;
}
.stAlert, .stAlert * {
    color: #111111 !important;
}

/* Print Media Stylesheet */
@media print {
    /* Hide navigation sidebar and interactive controls */
    section[data-testid="stSidebar"], 
    .stButton, 
    button, 
    form, 
    header, 
    footer,
    div[data-testid="stHeader"],
    div[data-testid="stForm"],
    div[data-testid="stExpander"] button,
    div[data-baseweb="popover"],
    div[class*="stFormSubmitButton"] { 
        display: none !important; 
    }
    
    /* Reset main layout container to full page */
    .block-container {
        padding: 0 !important;
        margin: 0 !important;
        max-width: 100% !important;
        background-color: #ffffff !important;
        color: #000000 !important;
    }
    
    /* Force page backgrounds to white and text to black */
    body, html, [data-testid="stAppViewContainer"], [data-testid="stApp"] {
        background-color: #ffffff !important;
        background: #ffffff !important;
        color: #000000 !important;
    }
    
    /* Force high contrast text on all printable items */
    p, li, span, h1, h2, h3, h4, h5, h6, strong, div, td, th, code, small, em {
        color: #000000 !important;
    }
    
    /* Print cards with a clean solid light theme instead of dark/translucent gradients */
    .compact-card, .voucher-card, .voucher-card.alt {
        background-color: #ffffff !important;
        background: #ffffff !important;
        border: 1px solid #1f2937 !important;
        border-left: 4px solid #1f2937 !important;
        color: #000000 !important;
        box-shadow: none !important;
        page-break-inside: avoid;
    }
    
    .voucher-title { color: #000000 !important; font-weight: bold; }
    .voucher-meta { color: #374151 !important; }
    .voucher-remarks { background: #f3f4f6 !important; border: 1px solid #d1d5db !important; color: #1f2937 !important; }
}
</style>
""", unsafe_allow_html=True)

def render_planning_section(role, current_user, q_df, comp_all_df):
    st.markdown("##### 📑 Amount Justification & Planning")

    if q_df.empty:
        st.caption("No quotations yet. Add quotations in the Directory first.")
        return

    # Filter bar
    plan_f1, plan_f2 = st.columns([2, 1])
    p_search = plan_f1.text_input("🔍 Search Quotation for Planning", placeholder="Search by company, project, ref #, or lead generator...", key="plan_search_in")
    
    # Lead generator dropdown filter
    all_lgs = sorted(list(set(q_df["lead_generator"].dropna().astype(str).str.strip().unique()) - {"", "None", "nan"}))
    p_lg = plan_f2.selectbox("Filter Lead Generator", ["All Lead Generators"] + all_lgs, key="plan_lg_in")

    # Only approved ("Successful") quotations move into planning
    disp_p_df = q_df[q_df["status"] == "Successful"].copy() if not q_df.empty else pd.DataFrame()
    if p_lg != "All Lead Generators":
        disp_p_df = disp_p_df[disp_p_df["lead_generator"] == p_lg]

    if p_search.strip():
        psq = p_search.strip().lower()
        disp_p_df = disp_p_df[
            disp_p_df["company_name"].astype(str).str.lower().str.contains(psq) |
            disp_p_df["project_name"].astype(str).str.lower().str.contains(psq) |
            disp_p_df["quotation_number"].astype(str).str.lower().str.contains(psq) |
            disp_p_df["lead_generator"].astype(str).str.lower().str.contains(psq)
        ]

    if disp_p_df.empty:
        st.info("ℹ️ **Only Approved ('Successful') Quotations Enter Initial Planning.** No approved quotations match the selected filters. Once a quotation is approved, it will automatically appear here for itemized cost planning.")
        return

    for idx, q_row in disp_p_df.iterrows():
        q_id = int(q_row["id"])
        q_amount = _safe_float(q_row["amount"])
        q_lg_disp = str(q_row["lead_generator"]) if q_row.get("lead_generator") and str(q_row["lead_generator"]).strip() not in ("None", "nan", "") else "Unassigned"

        q_comp_df = comp_all_df[comp_all_df["quotation_id"] == q_id] if not comp_all_df.empty else pd.DataFrame()
        total_itemized_cost = q_comp_df["price"].apply(_safe_float).sum() if not q_comp_df.empty else 0.0
        variance = q_amount - total_itemized_cost

        with st.expander(f"📑 {q_row['quotation_number']} — {q_row['company_name']} ({q_row['project_name']}) | Quoted Amount: PKR {q_amount:,.0f} | LG: {q_lg_disp}", expanded=False):
            total_purchaser_quote = q_comp_df["actual_price"].apply(_safe_float).sum() if not q_comp_df.empty else 0.0
            
            m1, m2, m3 = st.columns(3)
            m1.metric("Quoted Amount", f"PKR {q_amount:,.0f}")
            m2.metric("Initial Amount Summed", f"PKR {total_itemized_cost:,.0f}")
            m3.metric("Purchaser Market Quote", f"PKR {total_purchaser_quote:,.0f}" if total_purchaser_quote > 0 else "Pending")

            st.markdown("##### 📦 Itemized Justification Components & Purchaser Market Quotes")
            if q_comp_df.empty:
                st.caption("No cost components added yet to justify this quotation amount.")
            else:
                for _, comp_row in q_comp_df.iterrows():
                    comp_id = int(comp_row["id"])
                    planned_p = _safe_float(comp_row['price'])
                    actual_p = _safe_float(comp_row.get('actual_price'))
                    p_notes = str(comp_row.get('purchaser_notes') or '')

                    c1, c2, c3, c4 = st.columns([3, 2.5, 3.5, 0.8])
                    c1.markdown(f"📦 **{comp_row['component_name']}**\n\n<small>*{comp_row.get('description') or 'No notes'}*</small>", unsafe_allow_html=True)
                    c2.markdown(f"**Sender Planned**:<br/>PKR {planned_p:,.0f}", unsafe_allow_html=True)
                    
                    if actual_p > 0:
                        diff = planned_p - actual_p
                        diff_str = f"<span style='color: #10B981;'>(-PKR {diff:,.0f} saved)</span>" if diff >= 0 else f"<span style='color: #EF4444;'>(+PKR {-diff:,.0f} overrun)</span>"
                        c3.markdown(f"**Purchaser Quote**: PKR {actual_p:,.0f} {diff_str}<br/><small>Supplier: {p_notes if p_notes else '—'}</small>", unsafe_allow_html=True)
                    else:
                        c3.markdown("🟡 *Pending Purchaser Quote*")

                    if role != "CEO":
                        c4, c5 = st.columns([0.8, 0.8])
                        if c4.button("✏️", key=f"edit_plan_comp_btn_{comp_id}", help="Edit item"):
                            st.session_state[f"edit_plan_comp_{comp_id}"] = not st.session_state.get(f"edit_plan_comp_{comp_id}", False)
                            st.rerun()

                        if c5.button("🗑️", key=f"del_plan_comp_{comp_id}", help="Delete item"):
                            try:
                                sb.table("quotation_cost_components").delete().eq("id", comp_id).execute()
                                confirm_warn_and_rerun(f"Removed component '{comp_row['component_name']}'.", icon="🗑️")
                            except Exception as e:
                                st.error(f"Error removing item: {e}")

                    if st.session_state.get(f"edit_plan_comp_{comp_id}", False) and role != "CEO":
                        with st.form(f"form_edit_comp_{comp_id}"):
                            ec1, ec2 = st.columns([3, 2])
                            e_cname = ec1.text_input("Component Name*", value=comp_row["component_name"])
                            e_cprice = ec2.number_input("Planned Price (PKR)*", min_value=0.0, step=500.0, value=planned_p)
                            e_cdesc = st.text_area("Remarks / Notes / Specs", value=str(comp_row.get("description") or ""), height=40)
                            es1, es2 = st.columns(2)
                            save_comp = es1.form_submit_button("💾 Save", type="primary", use_container_width=True)
                            cancel_comp = es2.form_submit_button("✖️ Cancel", use_container_width=True)
                            if save_comp:
                                if e_cname.strip() and e_cprice > 0:
                                    try:
                                        sb.table("quotation_cost_components").update({
                                            "component_name": e_cname.strip(),
                                            "price": float(e_cprice),
                                            "description": e_cdesc.strip() or None
                                        }).eq("id", comp_id).execute()
                                        st.session_state[f"edit_plan_comp_{comp_id}"] = False
                                        confirm_and_rerun(f"✏️ Updated component '{e_cname.strip()}'.", icon="💾")
                                    except Exception as e:
                                        st.error(f"Cannot update component: {e}")
                                else:
                                    st.error("Please enter a valid component name and non-zero price.")
                            if cancel_comp:
                                st.session_state[f"edit_plan_comp_{comp_id}"] = False
                                st.rerun()

            if role != "CEO":
                st.markdown("---")
                with st.form(f"add_justification_form_{q_id}", clear_on_submit=True):
                    st.markdown("➕ **Add Amount Justification Component**")
                    fc1, fc2 = st.columns([3, 2])
                    comp_name_in = fc1.text_input("Component Name*", placeholder="e.g. 500m Fiber Optic Cable", key=f"pname_{q_id}")
                    comp_price_in = fc2.number_input("Price / Cost (PKR)*", value=None, min_value=0.0, step=1000.0, placeholder="Enter Price (PKR)", key=f"pprice_{q_id}")
                    comp_desc_in = st.text_area("Description / Notes", placeholder="Technical details or supplier notes...", height=40, key=f"pdesc_{q_id}")
                    
                    if st.form_submit_button("➕ Add Component & Update Sum", type="primary"):
                        if comp_name_in.strip() and comp_price_in is not None and comp_price_in > 0:
                            try:
                                sb.table("quotation_cost_components").insert({
                                    "quotation_id": q_id,
                                    "component_name": comp_name_in.strip(),
                                    "price": float(comp_price_in),
                                    "description": comp_desc_in.strip() or None,
                                    "created_by": current_user["username"]
                                }).execute()
                                confirm_and_rerun(f"➕ Added component '{comp_name_in.strip()}' (PKR {comp_price_in:,.0f}).", icon="📑")
                            except Exception as e:
                                st.error(f"Could not save component: {e}")
                        else:
                            st.error("Please enter a valid component name and non-zero price.")

def render_purchaser_analytics_view(role, current_user):
    st.markdown("### 🛍️ Purchaser Analytics & Procurement Performance")

    tables = fetch_all_table_data()
    comp_all_df = tables.get("components", pd.DataFrame())
    q_all_df = tables.get("quotations", pd.DataFrame())

    merged_df = comp_all_df.copy() if not comp_all_df.empty else pd.DataFrame()
    if not merged_df.empty and not q_all_df.empty:
        q_sub = q_all_df[["id", "quotation_number", "company_name", "project_name"]]
        merged_df = merged_df.merge(q_sub, left_on="quotation_id", right_on="id", how="left", suffixes=("", "_q"))

    if not merged_df.empty:
        merged_df["purchased_by"] = merged_df["purchased_by"].fillna("Unassigned")
        merged_df["actual_price"] = merged_df["actual_price"].apply(_safe_float)
        merged_df["price"] = merged_df["price"].apply(_safe_float)
        merged_df["savings"] = merged_df["price"] - merged_df["actual_price"]
        data_purchasers = sorted(list(set([str(p).strip() for p in merged_df["purchased_by"].unique() if p and str(p).strip() not in ("nan", "None", "", "Unassigned")])))
    else:
        data_purchasers = []

    all_purchasers = data_purchasers if data_purchasers else ["Unassigned"]

    filtered_df = merged_df.copy() if not merged_df.empty else pd.DataFrame()

    # Global KPI Metrics
    reuploaded_df = filtered_df[filtered_df["actual_price"] > 0] if not filtered_df.empty else pd.DataFrame()
    total_items = len(filtered_df)
    total_reuploaded = len(reuploaded_df)
    total_planned = filtered_df["price"].sum() if not filtered_df.empty else 0.0
    total_actual = reuploaded_df["actual_price"].sum() if not reuploaded_df.empty else 0.0
    total_planned_for_reuploaded = reuploaded_df["price"].sum() if not reuploaded_df.empty else 0.0
    total_savings = total_planned_for_reuploaded - total_actual
    savings_pct = (total_savings / total_planned_for_reuploaded * 100.0) if total_planned_for_reuploaded > 0 else 0.0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Items Tracked", f"{total_items}", f"{total_reuploaded} Re-Uploaded")
    k2.metric("Initially Planned Budget", f"PKR {total_planned:,.0f}")
    k3.metric("Purchase Amount", f"PKR {total_actual:,.0f}")
    k4.metric("Total Savings Achieved", f"PKR {total_savings:,.0f}", f"{savings_pct:.1f}% Savings", delta_color="normal" if total_savings >= 0 else "inverse")

    st.write("---")

    # Purchaser Individual Summary Performance Cards
    st.markdown("### 👤 Purchaser Performance & Savings Audit")

    if not all_purchasers or all_purchasers == ["Unassigned"]:
        st.caption("No purchaser records logged yet.")
    else:
        for p_name in all_purchasers:
            p_items = merged_df[merged_df["purchased_by"] == p_name] if not merged_df.empty else pd.DataFrame()
            p_reuploaded = p_items[p_items["actual_price"] > 0] if not p_items.empty else pd.DataFrame()
            p_tot_planned = p_reuploaded["price"].sum() if not p_reuploaded.empty else 0.0
            p_tot_actual = p_reuploaded["actual_price"].sum() if not p_reuploaded.empty else 0.0
            p_net_savings = p_tot_planned - p_tot_actual
            p_pct = (p_net_savings / p_tot_planned * 100.0) if p_tot_planned > 0 else 0.0

            with st.expander(f"👤 **{p_name}** — {len(p_reuploaded)} Items Procured | Total Savings: PKR {p_net_savings:,.0f} ({p_pct:.1f}%)", expanded=False):
                pc1, pc2, pc3, pc4 = st.columns(4)
                pc1.metric("Items Re-Uploaded", f"{len(p_reuploaded)} / {len(p_items)}")
                pc2.metric("Quoted Planned Cost", f"PKR {p_tot_planned:,.0f}")
                pc3.metric("Actual Acquired Cost", f"PKR {p_tot_actual:,.0f}")
                pc4.metric("Net Money Saved", f"PKR {p_net_savings:,.0f}", f"{p_pct:.1f}%", delta_color="normal" if p_net_savings >= 0 else "inverse")

                st.markdown("##### 📁 Procurement Breakdown by Quotation & Project")
                if p_items.empty:
                    st.caption(f"No procurement items logged for purchaser '{p_name}' yet.")
                else:
                    p_items["q_key"] = p_items["quotation_number"].astype(str) + " — " + p_items["company_name"].astype(str) + " (" + p_items["project_name"].astype(str) + ")"
                    grouped = p_items.groupby("q_key")
                    
                    for q_title, group_df in grouped:
                        g_reuploaded = group_df[group_df["actual_price"] > 0] if not group_df.empty else pd.DataFrame()
                        g_planned = g_reuploaded["price"].sum() if not g_reuploaded.empty else 0.0
                        g_actual = g_reuploaded["actual_price"].sum() if not g_reuploaded.empty else 0.0
                        g_savings = g_planned - g_actual
                        
                        st.markdown(f"**📑 {q_title}**")
                        st.caption(f"Project Subtotal: Planned PKR {g_planned:,.0f} | Actual PKR {g_actual:,.0f} | Savings: **PKR {g_savings:,.0f}**")

                        group_rows = []
                        for idx_num, i_row in enumerate(group_df.iterrows(), start=1):
                            _, row_data = i_row
                            pl_price = _safe_float(row_data["price"])
                            ac_price = _safe_float(row_data["actual_price"])
                            i_sav = pl_price - ac_price if ac_price > 0 else 0.0
                            
                            group_rows.append({
                                "#": idx_num,
                                "Item Description": row_data.get("component_name", ""),
                                "Quoted Planned Price": f"PKR {pl_price:,.0f}",
                                "Actual City Price": f"PKR {ac_price:,.0f}" if ac_price > 0 else "🟡 Pending",
                                "Net Savings / (Overrun)": f"PKR {i_sav:,.0f}" if ac_price > 0 else "—",
                                "Supplier Notes": row_data.get("purchaser_notes") or "—"
                            })
                        st.dataframe(pd.DataFrame(group_rows), hide_index=True, use_container_width=True)
                        st.write("---")

def render_purchase_procurement_section(role, current_user, q_df, comp_all_df):
    st.markdown("##### 🛒 Procurement & City Market Re-Upload")

    if q_df.empty:
        st.caption("No quotation items yet. Senders must add planned items first.")
        return

    # Filter bar
    pur_f1, pur_f2 = st.columns([2, 1])
    p_search = pur_f1.text_input("🔍 Search Quotation for Procurement", placeholder="Search company, project, quotation # or lead generator...", key="pur_search_in")
    all_lgs = sorted(list(set(q_df["lead_generator"].dropna().astype(str).str.strip().unique()) - {"", "None", "nan"}))
    p_lg = pur_f2.selectbox("Filter Lead Generator", ["All Lead Generators"] + all_lgs, key="pur_lg_in")

    # Only approved ("Successful") quotations move into procurement
    disp_p_df = q_df[q_df["status"] == "Successful"].copy() if not q_df.empty else pd.DataFrame()
    if p_lg != "All Lead Generators":
        disp_p_df = disp_p_df[disp_p_df["lead_generator"] == p_lg]

    if p_search.strip():
        psq = p_search.strip().lower()
        disp_p_df = disp_p_df[
            disp_p_df["company_name"].astype(str).str.lower().str.contains(psq) |
            disp_p_df["project_name"].astype(str).str.lower().str.contains(psq) |
            disp_p_df["quotation_number"].astype(str).str.lower().str.contains(psq) |
            disp_p_df["lead_generator"].astype(str).str.lower().str.contains(psq)
        ]

    if disp_p_df.empty:
        st.warning("No quotation projects found matching the procurement filter.")
        return

    for idx, q_row in disp_p_df.iterrows():
        q_id = int(q_row["id"])
        q_amount = _safe_float(q_row["amount"])
        q_lg_disp = str(q_row["lead_generator"]) if q_row.get("lead_generator") and str(q_row["lead_generator"]).strip() not in ("None", "nan", "") else "Unassigned"

        q_comp_df = comp_all_df[comp_all_df["quotation_id"] == q_id] if not comp_all_df.empty else pd.DataFrame()
        total_sender_planned = q_comp_df["price"].apply(_safe_float).sum() if not q_comp_df.empty else 0.0
        total_purchaser_actual = q_comp_df["actual_price"].apply(_safe_float).sum() if not q_comp_df.empty else 0.0
        net_savings = total_sender_planned - total_purchaser_actual

        with st.expander(f"🛒 {q_row['quotation_number']} — {q_row['company_name']} ({q_row['project_name']}) | Agreed Value: PKR {q_amount:,.0f}", expanded=False):
            pm1, pm2, pm3 = st.columns(3)
            pm1.metric("Sender Planned Cost Sum", f"PKR {total_sender_planned:,.0f}")
            pm2.metric("Purchaser Market Quote Sum", f"PKR {total_purchaser_actual:,.0f}" if total_purchaser_actual > 0 else "—")
            pm3.metric("Net Procurement Savings", f"PKR {net_savings:,.0f}" if total_purchaser_actual > 0 else "—", delta_color="normal" if net_savings >= 0 else "inverse")

            st.markdown("##### 🛒 Planned Items & City Market Re-Upload")
            if q_comp_df.empty:
                st.caption("No planned cost items submitted by quotation sender yet.")
            else:
                # Hoist purchaser user list lookup ONCE for whole page (not per-component)
                pur_users = get_users_by_role("Purchaser")
                if not pur_users:
                    all_u_df = get_all_users_summary()
                    pur_users = all_u_df["username"].tolist() if not all_u_df.empty else []
                if current_user["username"] not in pur_users:
                    pur_users = [current_user["username"]] + pur_users

                for _, comp_row in q_comp_df.iterrows():
                    comp_id = int(comp_row["id"])
                    planned_price = _safe_float(comp_row["price"])
                    actual_price = _safe_float(comp_row.get("actual_price"))
                    p_notes_val = str(comp_row.get("purchaser_notes") or "").strip()
                    
                    item_savings = planned_price - actual_price if actual_price > 0 else 0.0
                    
                    curr_p_by = comp_row.get("purchased_by") or current_user["username"]
                    p_index = pur_users.index(curr_p_by) if curr_p_by in pur_users else 0

                    if actual_price > 0:
                        rc1, rc2, rc3, rc4, rc5 = st.columns([2.5, 2, 3, 2.5, 1.2], vertical_alignment="bottom")
                        rc1.markdown(f"📦 **{comp_row['component_name']}**\n\n<small>Sender Notes: *{comp_row.get('description') or 'None'}*</small>", unsafe_allow_html=True)
                        rc2.markdown(f"**Sender Planned**:<br/>PKR {planned_price:,.0f}", unsafe_allow_html=True)
                        
                        savings_badge = f"<span style='color: #10B981; font-weight: bold;'>(-PKR {item_savings:,.0f} saved)</span>" if item_savings >= 0 else f"<span style='color: #EF4444; font-weight: bold;'>(+PKR {-item_savings:,.0f} overrun)</span>"
                        rc3.markdown(f"**Purchaser Quote**: PKR {actual_price:,.0f} {savings_badge}<br/><small>Purchaser: **{curr_p_by}**</small>", unsafe_allow_html=True)
                        
                        if p_notes_val:
                            rc4.markdown(f"<small><strong>Notes:</strong> {p_notes_val}</small>", unsafe_allow_html=True)
                        else:
                            rc4.write("")

                        with rc5:
                            with st.popover("✏️ Edit"):
                                with st.form(key=f"edit_price_form_{comp_id}"):
                                    st.markdown(f"**Edit Market Price**: {comp_row['component_name']}")
                                    sel_purchaser = st.selectbox("Assign Purchaser / Person*", pur_users, index=p_index, key=f"sel_pur_{comp_id}")
                                    new_act_price = st.number_input("City Re-Upload Price (PKR)*", value=actual_price, min_value=0.0, step=500.0)
                                    new_pur_notes = st.text_input("Notes", value=p_notes_val, placeholder="e.g. Al-Madina Hardware")
                                    
                                    if st.form_submit_button("💾 Save Changes", type="primary"):
                                        if new_act_price > 0:
                                            try:
                                                sb.table("quotation_cost_components").update({
                                                    "actual_price": float(new_act_price),
                                                    "purchaser_notes": new_pur_notes.strip() or None,
                                                    "purchased_by": sel_purchaser
                                                }).eq("id", comp_id).execute()
                                                confirm_and_rerun(f"💾 Updated market price for '{comp_row['component_name']}' by {sel_purchaser} (PKR {new_act_price:,.0f}).", icon="🛒")
                                            except Exception as e:
                                                st.error(f"Cannot update market price: {e}")
                                        else:
                                            st.error("Please enter a valid price.")
                    else:
                        with st.form(key=f"inline_reupload_form_{comp_id}"):
                            rc1, rc2, rc3, rc4, rc5, rc6 = st.columns([2, 1.5, 1.8, 1.5, 1.8, 1.1], vertical_alignment="bottom")
                            rc1.markdown(f"📦 **{comp_row['component_name']}**\n\n<small>Sender Notes: *{comp_row.get('description') or 'None'}*</small>", unsafe_allow_html=True)
                            rc2.markdown(f"**Sender Planned**:<br/>PKR {planned_price:,.0f}", unsafe_allow_html=True)

                            in_price = rc3.number_input("City Re-Upload Price (PKR)*", value=None, min_value=0.0, step=500.0, placeholder="Enter City Price (PKR)", key=f"in_p_{comp_id}")
                            in_pur = rc4.selectbox("Purchaser Person*", pur_users, index=p_index, key=f"in_pur_{comp_id}")
                            in_notes = rc5.text_input("Notes", placeholder="e.g. Al-Madina Hardware", key=f"in_notes_{comp_id}")
                            save_inline = rc6.form_submit_button("💾 Save Price", type="primary", use_container_width=True)

                            if save_inline:
                                if in_price is not None and in_price > 0:
                                    try:
                                        sb.table("quotation_cost_components").update({
                                            "actual_price": float(in_price),
                                            "purchaser_notes": in_notes.strip() or None,
                                            "purchased_by": in_pur
                                        }).eq("id", comp_id).execute()
                                        confirm_and_rerun(f"💾 Saved market price for '{comp_row['component_name']}' by {in_pur} (PKR {in_price:,.0f}).", icon="🛒")
                                    except Exception as e:
                                        st.error(f"Cannot save price: {e}")
                                else:
                                    st.error("Please enter a valid price.")

# Clean URL query params to prevent URL tampering or session impersonation
if st.query_params:
    st.query_params.clear()

if "user" not in st.session_state:
    st.session_state["user"] = None

if st.session_state["user"] is None:
    st.markdown("<div style='margin-top: 2rem;'></div>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        logo_login_path = "logo.png" if os.path.exists("logo.png") else ("logo.jpeg" if os.path.exists("logo.jpeg") else ("logo.jpg" if os.path.exists("logo.jpg") else None))
        if logo_login_path:
            st.image(logo_login_path, use_container_width=True)
        else:
            st.markdown("<h2 style='text-align: center;'>Multi Tech Engineering Group Sign In</h2>", unsafe_allow_html=True)

        with st.form("login_form", clear_on_submit=False):
            u_name = st.text_input("Username", key="auth_u_name")
            p_word = st.text_input("Password", type="password", key="auth_p_word")
            submit_login = st.form_submit_button("Sign In", type="primary", use_container_width=True)
            if submit_login:
                if u_name.strip() and p_word.strip():
                    try:
                        res = sb.table("users").select("id, username, password, role, can_view_dashboard").ilike("username", u_name.strip()).execute()
                        if res.data and res.data[0]["password"] == p_word:
                            u = res.data[0]
                            st.session_state["user"] = {
                                "id": int(u["id"]), "username": u["username"],
                                "role": u["role"], "can_view_dashboard": bool(u["can_view_dashboard"])
                            }
                            st.query_params.clear()
                            st.rerun()
                            st.stop()
                        else:
                            st.error("Invalid credentials.")
                    except Exception as e:
                        st.error(f"Sign in error: {e}")
                else:
                    st.error("Username and password are required.")
    st.stop()

# --- Render sidebar elements ONLY when authenticated ---
logo_path = "logo.png" if os.path.exists("logo.png") else ("logo.jpeg" if os.path.exists("logo.jpeg") else ("logo.jpg" if os.path.exists("logo.jpg") else None))
if logo_path:
    st.sidebar.image(logo_path, use_container_width=True)

current_user = st.session_state["user"]

# Live-refresh user record from cached data so role updates reflect without logout
if st.session_state.get("user"):
    u_id = st.session_state["user"].get("id")
    if u_id:
        try:
            _cached_users = fetch_all_table_data().get("users", pd.DataFrame())
            if not _cached_users.empty:
                _u_match = _cached_users[_cached_users["id"] == u_id]
                if not _u_match.empty:
                    u_fresh = _u_match.iloc[0]
                    st.session_state["user"] = {
                        "id": int(u_fresh["id"]), "username": str(u_fresh["username"]),
                        "role": str(u_fresh["role"]), "can_view_dashboard": bool(u_fresh.get("can_view_dashboard", False))
                    }
                    current_user = st.session_state["user"]
        except Exception:
            pass

ROLE_MAP = {
    "ceo": "CEO",
    "acc": "Accountant",
    "accountant": "Accountant",
    "accounts": "Accountant",
    "lg": "Lead Generator",
    "lead generator": "Lead Generator",
    "pur": "Quotation Sender",
    "purchase": "Quotation Sender",
    "purchaser": "Quotation Sender",
    "quotation sender": "Quotation Sender",
    "sender": "Quotation Sender",
    "adv": "Quotation Sender",
    "advance": "Quotation Sender"
}

# Parse & normalize roles list
raw_roles = [r.strip() for r in str(current_user.get("role", "")).split(",")] if current_user.get("role") else []
user_roles = []
for r in raw_roles:
    norm_r = ROLE_MAP.get(r.lower(), r)
    if norm_r and norm_r not in user_roles:
        user_roles.append(norm_r)

if not user_roles:
    user_roles = ["Quotation Sender"]

if len(user_roles) > 1:
    role_options = ["All Assigned Roles"] + user_roles if "CEO" not in user_roles else user_roles
    if "active_role" not in st.session_state or st.session_state["active_role"] not in role_options:
        st.session_state["active_role"] = role_options[0]
    role = st.sidebar.selectbox("Active Role Mode", role_options, index=role_options.index(st.session_state["active_role"]), key="sidebar_role_select")
    st.session_state["active_role"] = role
else:
    role = user_roles[0]

st.sidebar.markdown(f"👤 **{current_user['username']}** (`{current_user['role']}`)")

active_roles_to_check = user_roles if role in ("All Assigned Roles", "All Roles") else [role]

menu_options = []
if "CEO" in active_roles_to_check or "Accountant" in active_roles_to_check:
    if current_user.get("can_view_dashboard", True) and "📊 Dashboard" not in menu_options:
        menu_options.append("📊 Dashboard")
    for item in ["📋 Quotation & Planning", "🛒 Purchase", "🎫 Voucher", "💳 Staff Advances", "🏢 Execution(Accounts)", "⚙️ Settings"]:
        if item not in menu_options: menu_options.append(item)
else:
    for item in ["📋 Quotation & Planning", "🛒 Purchase", "🎫 Voucher"]:
        if item not in menu_options: menu_options.append(item)

menu = st.sidebar.radio("Navigation Workspaces", menu_options, label_visibility="collapsed")
if st.sidebar.button("🚪 Log out", use_container_width=True):
    st.query_params.clear()
    st.session_state["user"] = None
    st.rerun()
    st.stop()

# ==============================================================================
# VIEW A: MAIN EXECUTIVE DATE-FILTERED DASHBOARD
# ==============================================================================

def render_monthly_report_view():
    st.subheader("📅 Monthly Report")
    
    def _parse_sp_item(item_val):
        t_str = str(item_val).strip()
        if t_str.startswith("[") and "]" in t_str:
            cat_part = t_str[1:t_str.index("]")].strip()
            desc_part = t_str[t_str.index("]") + 1:].strip()
            return cat_part, desc_part
        return None, t_str
    
    # 1. Fetch tables
    tables = fetch_all_table_data()
    ledgers_df = tables["ledgers"].copy()
    advances_df = tables["advances"].copy()
    spends_df = tables["spends"].copy()
    companies_df = tables["companies"].copy()
    projects_df = tables["projects"].copy()
    vouchers_df = tables.get("vouchers", pd.DataFrame()).copy()
    quotations_df = tables.get("quotations", pd.DataFrame()).copy()
    
    # Build dictionaries for easy lookups
    proj_map = {}
    if not projects_df.empty:
        for _, p_r in projects_df.iterrows():
            try:
                p_id = int(p_r["id"])
                proj_map[p_id] = {
                    "name": p_r["name"],
                    "company_id": int(p_r["company_id"]) if p_r.get("company_id") and not pd.isna(p_r["company_id"]) else None
                }
            except Exception:
                pass
                
    comp_map = {}
    if not companies_df.empty:
        for _, c_r in companies_df.iterrows():
            try:
                c_id = int(c_r["id"])
                comp_map[c_id] = c_r["name"]
            except Exception:
                pass
                
    adv_map = {}
    if not advances_df.empty:
        for _, a_r in advances_df.iterrows():
            try:
                adv_id = int(a_r["id"])
                adv_map[adv_id] = {
                    "person_name": a_r["person_name"],
                    "project_id": int(a_r["project_id"]) if a_r.get("project_id") and not pd.isna(a_r["project_id"]) else None
                }
            except Exception:
                pass

    # 2. Extract unique months for selection
    months_set = set()
    current_month_str = datetime.date.today().strftime("%B %Y")
    months_set.add(current_month_str)
    
    def get_month_year_str(val):
        if val is None or pd.isna(val):
            return None
        try:
            dt = pd.to_datetime(val)
            return dt.strftime("%B %Y")
        except Exception:
            return None
            
    if not ledgers_df.empty:
        for val in ledgers_df["created_at"]:
            m_str = get_month_year_str(val)
            if m_str:
                months_set.add(m_str)
                
    if not spends_df.empty:
        for val in spends_df["created_at"]:
            m_str = get_month_year_str(val)
            if m_str:
                months_set.add(m_str)

    if not vouchers_df.empty:
        for val in vouchers_df["created_at"]:
            m_str = get_month_year_str(val)
            if m_str:
                months_set.add(m_str)

    if not quotations_df.empty:
        for val in quotations_df["created_at"]:
            m_str = get_month_year_str(val)
            if m_str:
                months_set.add(m_str)
                
    month_options = sorted(list(months_set), key=lambda x: datetime.datetime.strptime(x, "%B %Y"), reverse=True)
    
    sc1, sc2 = st.columns([6, 4])
    sel_month = sc1.selectbox("Choose Month", month_options, index=0, key="report_month_selectbox")
    
    # 3. Filter entries by month
    sel_dt = datetime.datetime.strptime(sel_month, "%B %Y")
    sel_year = sel_dt.year
    sel_month_num = sel_dt.month
    
    filt_ledgers = []
    if not ledgers_df.empty:
        for _, l_r in ledgers_df.iterrows():
            try:
                l_dt = pd.to_datetime(l_r["created_at"])
                if l_dt.year == sel_year and l_dt.month == sel_month_num:
                    filt_ledgers.append(l_r.to_dict())
            except Exception:
                pass
                
    filt_spends = []
    if not spends_df.empty:
        for _, s_r in spends_df.iterrows():
            try:
                s_dt = pd.to_datetime(s_r["created_at"])
                if s_dt.year == sel_year and s_dt.month == sel_month_num:
                    filt_spends.append(s_r.to_dict())
            except Exception:
                pass

    # Print action button
    print_triggered = sc2.button("🖨️ Print Report", use_container_width=True, type="primary")

    # Inject print styling (always present, but only takes effect on window.print())
    st.markdown("""
        <style>
        @media print {
            /* Hide Streamlit sidebar, top navigation, parameters selectboxes, and footer */
            section[data-testid="stSidebar"],
            header,
            footer,
            div[data-testid="stHeader"],
            div.stButton,
            div[data-testid="stElementToolbar"],
            iframe {
                display: none !important;
            }
            /* Reset Block Container Padding and Max-Width */
            div.block-container {
                padding-top: 1rem !important;
                padding-bottom: 1rem !important;
                padding-left: 1rem !important;
                padding-right: 1rem !important;
                max-width: 100% !important;
            }
            /* Clean table formatting for paper */
            table {
                width: 100% !important;
                border-collapse: collapse !important;
            }
            th, td {
                border: 1px solid #cbd5e1 !important;
                padding: 6px 8px !important;
                font-size: 10pt !important;
            }
            h1, h2, h3, h4, h5 {
                color: #000000 !important;
                font-family: Arial, sans-serif !important;
                page-break-after: avoid;
            }
            /* Avoid breaking in the middle of a project/company block */
            div.company-print-block, div.project-print-block {
                page-break-inside: avoid !important;
            }
        }
        </style>
    """, unsafe_allow_html=True)
    
    if print_triggered:
        st.components.v1.html("""
            <script>
                parent.window.print();
            </script>
        """, height=0, width=0)

    # 4. Group data
    grouped_data = {}
    
    def get_company_project_for_pid(p_id):
        p_id = int(p_id) if p_id is not None else None
        p_info = proj_map.get(p_id) if p_id else None
        p_name = p_info["name"] if p_info else "General Workspace"
        c_id = p_info["company_id"] if p_info else None
        c_name = comp_map.get(c_id) if c_id else "General Workspace"
        return c_name, p_name

    # Determine all project IDs active or created in the selected month
    active_project_ids = set()
    
    # 1) Projects with ledger transactions in the selected month
    for l in filt_ledgers:
        pid = int(l["project_id"]) if l.get("project_id") and not pd.isna(l["project_id"]) else None
        if pid:
            active_project_ids.add(pid)
            
    # 2) Projects with staff spends logged in the selected month
    for s in filt_spends:
        adv_id = int(s["advance_id"]) if s.get("advance_id") and not pd.isna(s["advance_id"]) else None
        adv_info = adv_map.get(adv_id) if adv_id else None
        pid = adv_info["project_id"] if adv_info else None
        if pid:
            active_project_ids.add(pid)
            
    # 3) Projects with vouchers created in the selected month
    if not vouchers_df.empty:
        for _, v_r in vouchers_df.iterrows():
            try:
                v_dt = pd.to_datetime(v_r["created_at"])
                if v_dt.year == sel_year and v_dt.month == sel_month_num:
                    pid = int(v_r["project_id"]) if v_r.get("project_id") and not pd.isna(v_r["project_id"]) else None
                    if pid:
                        active_project_ids.add(pid)
            except Exception:
                pass

    # 4) Projects with quotations created in the selected month
    if not quotations_df.empty:
        for _, q_r in quotations_df.iterrows():
            try:
                q_dt = pd.to_datetime(q_r["created_at"])
                if q_dt.year == sel_year and q_dt.month == sel_month_num:
                    q_pname = str(q_r["project_name"]).strip().lower()
                    q_cname = str(q_r["company_name"]).strip().lower()
                    for p_id, p_info in proj_map.items():
                        p_name = p_info["name"].strip().lower()
                        c_id = p_info["company_id"]
                        c_name = comp_map.get(c_id, "").strip().lower()
                        if p_name == q_pname and c_name == q_cname:
                            active_project_ids.add(p_id)
            except Exception:
                pass

    # Initialize all active/created projects in grouped_data
    for p_id in active_project_ids:
        c_name, p_name = get_company_project_for_pid(p_id)
        if c_name not in grouped_data:
            grouped_data[c_name] = {}
        if p_name not in grouped_data[c_name]:
            grouped_data[c_name][p_name] = []

    # Monthly wide totals
    total_income = 0.0
    total_expense = 0.0
    total_loans = 0.0

    # Process Ledgers
    for l in filt_ledgers:
        pid = int(l["project_id"]) if l.get("project_id") and not pd.isna(l["project_id"]) else None
        c_name, p_name = get_company_project_for_pid(pid)
        
        if c_name not in grouped_data:
            grouped_data[c_name] = {}
        if p_name not in grouped_data[c_name]:
            grouped_data[c_name][p_name] = []
            
        amt = _safe_float(l["amount"])
        l_type = l["type"]
        if l_type == "income":
            total_income += amt
        elif l_type == "expense":
            total_expense += amt
        elif l_type == "loan":
            total_loans += amt
            
        grouped_data[c_name][p_name].append({
            "date": pd.to_datetime(l["created_at"]).strftime("%Y-%m-%d"),
            "type": l_type.upper(),
            "title": l["title"],
            "cheque": l.get("cheque_number") or "—",
            "amount": amt
        })

    # Process Spends
    for s in filt_spends:
        adv_id = int(s["advance_id"]) if s.get("advance_id") and not pd.isna(s["advance_id"]) else None
        adv_info = adv_map.get(adv_id) if adv_id else None
        pid = adv_info["project_id"] if adv_info else None
        c_name, p_name = get_company_project_for_pid(pid)
        person = adv_info["person_name"] if adv_info else "Staff"
        
        if c_name not in grouped_data:
            grouped_data[c_name] = {}
        if p_name not in grouped_data[c_name]:
            grouped_data[c_name][p_name] = []
            
        amt = _safe_float(s["amount_spent"])
        total_expense += amt
        
        grouped_data[c_name][p_name].append({
            "date": pd.to_datetime(s["created_at"]).strftime("%Y-%m-%d"),
            "type": "SPEND",
            "title": f"{s['item_name']} (Staff: {person})",
            "cheque": "—",
            "amount": amt
        })

    # Display overall monthly metrics card
    
    
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Income", f"PKR {total_income:,.0f}")
    mc2.metric("Expense", f"PKR {total_expense:,.0f}")
    mc3.metric("Loans", f"PKR {total_loans:,.0f}")
    net_change = total_income + total_loans - total_expense
    mc4.metric("Profit", f"PKR {net_change:,.0f}")
    
    st.write("---")

    if not grouped_data:
        st.info(f"No transactions recorded for {sel_month}.")
        return

    # Render data grouped by Company and Project
    for c_name, projects_dict in sorted(grouped_data.items()):
        c_income = 0.0
        c_expense = 0.0
        c_loans = 0.0
        
        # Company Header Box
        st.markdown(f"<div class='company-print-block'>", unsafe_allow_html=True)
        st.markdown(f"#### 🏢 Company: **{c_name}**")
        
        for p_name, tx_list in sorted(projects_dict.items()):
            p_income = 0.0
            p_expense = 0.0
            p_loans = 0.0
            
            tx_rows = []
            
            # 1. Income entries (individual)
            project_income_list = [t for t in tx_list if t["type"] == "INCOME"]
            for tx in sorted(project_income_list, key=lambda x: x["date"]):
                amt = tx["amount"]
                p_income += amt
                tx_rows.append({
                    "Date": tx["date"],
                    "Type": "🟢 INCOME",
                    "Description": tx["title"],
                    "Reference": tx["cheque"],
                    "Amount (PKR)": f"PKR {amt:,.0f}"
                })
                
            # 2. Loan entries (individual)
            project_loan_list = [t for t in tx_list if t["type"] == "LOAN"]
            for tx in sorted(project_loan_list, key=lambda x: x["date"]):
                amt = tx["amount"]
                p_loans += amt
                tx_rows.append({
                    "Date": tx["date"],
                    "Type": "🔵 LOAN",
                    "Description": tx["title"],
                    "Reference": tx["cheque"],
                    "Amount (PKR)": f"PKR {amt:,.0f}"
                })

            # 3. Expenses (Direct Expenses + Staff Spends)
            direct_expenses = [t for t in tx_list if t["type"] == "EXPENSE"]
            staff_spends = [t for t in tx_list if t["type"] == "SPEND"]
            
            # Group staff spends by category
            categorized_spends = {}  # {category: sum_amount}
            standalone_spends = []   # list of spends
            
            for s in staff_spends:
                cat, desc = _parse_sp_item(s["title"])
                if cat:
                    categorized_spends[cat] = categorized_spends.get(cat, 0.0) + s["amount"]
                else:
                    s_copy = dict(s)
                    s_copy["title"] = desc  # Clean title
                    standalone_spends.append(s_copy)
            
            # Add categorized spends as grouped category rows
            for cat, cat_amt in sorted(categorized_spends.items()):
                p_expense += cat_amt
                tx_rows.append({
                    "Date": "—",
                    "Type": "📂 EXPENSE (CAT)",
                    "Description": f"Category: {cat}",
                    "Reference": "—",
                    "Amount (PKR)": f"PKR {cat_amt:,.0f}"
                })
                
            # Add standalone spends individually
            for s in sorted(standalone_spends, key=lambda x: x["date"]):
                amt = s["amount"]
                p_expense += amt
                tx_rows.append({
                    "Date": s["date"],
                    "Type": "🧾 EXPENSE (SPEND)",
                    "Description": s["title"],
                    "Reference": "—",
                    "Amount (PKR)": f"PKR {amt:,.0f}"
                })
                
            # Add direct ledger expenses individually
            for e in sorted(direct_expenses, key=lambda x: x["date"]):
                amt = e["amount"]
                p_expense += amt
                tx_rows.append({
                    "Date": e["date"],
                    "Type": "🧾 EXPENSE (DIRECT)",
                    "Description": e["title"],
                    "Reference": e["cheque"],
                    "Amount (PKR)": f"PKR {amt:,.0f}"
                })
                
            # Project Header Box and Table
            st.markdown(f"<div class='project-print-block' style='margin-left: 20px; margin-top: 15px;'>", unsafe_allow_html=True)
            st.markdown(f"##### 📁 Project: **{p_name}**")
            
            if tx_rows:
                df_tx = pd.DataFrame(tx_rows)
                df_tx.insert(0, "#", range(1, len(df_tx) + 1))
                st.table(df_tx)
            else:
                st.caption("No transaction entries logged this month.")
                
            st.markdown(
                f"<p style='font-size:0.9rem; font-weight:600; text-align:right; margin-top:-10px; margin-bottom:15px;'>"
                f"Project Subtotals &rarr; Inflow: <span style='color:#10B981;'>PKR {p_income:,.0f}</span> | "
                f"Outflow: <span style='color:#EF4444;'>PKR {p_expense:,.0f}</span> | "
                f"Loan: <span style='color:#3B82F6;'>PKR {p_loans:,.0f}</span>"
                f"</p>",
                unsafe_allow_html=True
            )
            st.markdown("</div>", unsafe_allow_html=True)
            
            c_income += p_income
            c_expense += p_expense
            c_loans += p_loans

        st.markdown(
            f"<p style='font-size:0.95rem; font-weight:600; text-align:right; margin-top:5px; margin-bottom:20px;'>"
            f"🏢 {c_name} Subtotals &rarr; "
            f"Income: <span style='color:#10B981;'>PKR {c_income:,.0f}</span> | "
            f"Outcome/Spends: <span style='color:#EF4444;'>PKR {c_expense:,.0f}</span> | "
            f"Loans: <span style='color:#3B82F6;'>PKR {c_loans:,.0f}</span>"
            f"</p>",
            unsafe_allow_html=True
        )
        st.markdown("</div>", unsafe_allow_html=True)
        st.write("---")

if menu == "📊 Dashboard":
    if role not in ("CEO", "Accountant") or not current_user.get("can_view_dashboard", True):
        st.error("🔒 Unauthorized: Access to executive dashboard scopes restricted.")
        st.stop()

    if "show_monthly_report" not in st.session_state:
        st.session_state["show_monthly_report"] = False

    t_col1, t_col2 = st.columns([7, 3])
    t_col2_btn_lbl = "📈 Back to Dashboard" if st.session_state["show_monthly_report"] else "📅 Monthly Report"
    
    if t_col2.button(t_col2_btn_lbl, key="toggle_monthly_report", use_container_width=True):
        st.session_state["show_monthly_report"] = not st.session_state["show_monthly_report"]
        st.rerun()

    if st.session_state["show_monthly_report"]:
        t_col1.image("logo.png", width=120)
        render_monthly_report_view()
        st.stop()
    else:
        t_col1.title("📊 Financial Scope Overview")
        time_filter = st.selectbox("Statistics Scope Range", ["All Time", "Today", "This Month", "Last 30 Days"])

    today = datetime.date.today()
    date_limit = None
    if time_filter == "Today": date_limit = today
    elif time_filter == "Last 30 Days": date_limit = today - datetime.timedelta(days=30)
    elif time_filter == "This Month": date_limit = today.replace(day=1)

    tables = fetch_all_table_data()
    ledgers_df = tables["ledgers"].copy()
    advances_df = tables["advances"].copy()
    spends_df = tables["spends"].copy()

    if ledgers_df.empty and advances_df.empty:
        overall_bal, total_loans, net_profit, unspent_advances = 0.0, 0.0, 0.0, 0.0
        inc, exp, loans, alloc_adv, spent_adv = 0.0, 0.0, 0.0, 0.0, 0.0
    else:
        if not ledgers_df.empty:
            ledgers_df["created_at"] = pd.to_datetime(ledgers_df["created_at"]).dt.date
            if date_limit: ledgers_df = ledgers_df[ledgers_df["created_at"] >= date_limit]
            inc = ledgers_df[ledgers_df["type"] == "income"]["amount"].apply(_safe_float).sum()
            exp = ledgers_df[ledgers_df["type"] == "expense"]["amount"].apply(_safe_float).sum()
            loans = ledgers_df[ledgers_df["type"] == "loan"]["amount"].apply(_safe_float).sum()
        else:
            inc, exp, loans = 0.0, 0.0, 0.0

        if not advances_df.empty:
            alloc_adv = advances_df["allocated_amount"].apply(_safe_float).sum()
        else:
            alloc_adv = 0.0

        if not spends_df.empty:
            if date_limit and "created_at" in spends_df.columns:
                spends_df["created_at_dt"] = pd.to_datetime(spends_df["created_at"]).dt.date
                filt_spends = spends_df[spends_df["created_at_dt"] >= date_limit]
                spent_adv = filt_spends["amount_spent"].apply(_safe_float).sum()
            else:
                spent_adv = spends_df["amount_spent"].apply(_safe_float).sum()
        else:
            spent_adv = 0.0

        unspent_advances = alloc_adv - spent_adv
        overall_bal = inc + loans - exp - spent_adv
        net_profit = inc - exp - spent_adv
        total_loans = loans

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Company Balance", f"PKR {overall_bal:,.0f}" if overall_bal else "PKR 0")
    m2.metric("Total Income", f"PKR {inc:,.0f}" if inc else "PKR 0")
    m3.metric("Field Worker Expenses", f"PKR {spent_adv:,.0f}" if spent_adv else "PKR 0", delta=f"{spent_adv:,.0f} Logged Spends", delta_color="inverse")
    m4.metric("Net Profit", f"PKR {net_profit:,.0f}" if net_profit else "PKR 0")

    with st.expander(f"📊 Detailed Financial Outflows & Advances Audit ({time_filter})"):
        st.markdown(f"""
* **Revenue Inflow (Income)**: `PKR {inc:,.0f}`
* **Capital Infusions (Loans)**: `+ PKR {total_loans:,.0f}`
* **Direct Expenses**: `- PKR {exp:,.0f}`
* **Field Worker Expenses Logged**: `- PKR {spent_adv:,.0f}`
* **Field Advances Allocated**: `PKR {alloc_adv:,.0f}` *(Unspent Balance: PKR {unspent_advances:,.0f})*
---
* **Total Net Liquid Balance**: **`PKR {overall_bal:,.0f}`**
""")
        if not advances_df.empty:
            st.markdown("##### 💳 Field Worker Staff Expense Audit Table")
            adv_dash_rows = []
            for _, a_r in advances_df.iterrows():
                adv_id_val = int(a_r["id"])
                w_sp = spends_df[spends_df["advance_id"] == adv_id_val] if not spends_df.empty else pd.DataFrame()
                w_spent_tot = float(w_sp["amount_spent"].sum()) if not w_sp.empty else 0.0
                w_alloc_tot = float(a_r["allocated_amount"])
                adv_dash_rows.append({
                    "Field Worker": a_r["person_name"],
                    "Allocated Advance": f"PKR {w_alloc_tot:,.0f}",
                    "Itemized Expenses Logged": f"PKR {w_spent_tot:,.0f}",
                    "Unspent Balance": f"PKR {(w_alloc_tot - w_spent_tot):,.0f}"
                })
            disp_adv_dash = pd.DataFrame(adv_dash_rows)
            disp_adv_dash.insert(0, "#", range(1, len(disp_adv_dash) + 1))
            st.dataframe(disp_adv_dash, hide_index=True, use_container_width=True)

    st.markdown("---")
    st.markdown(f"### 📊 Quotation Conversion & Performance Metrics ({time_filter})")
    q_df = tables.get("quotations", pd.DataFrame()).copy()
    
    if date_limit and not q_df.empty:
        q_df["created_at_dt"] = pd.to_datetime(q_df["created_at"]).dt.date
        q_df = q_df[q_df["created_at_dt"] >= date_limit]

    total_q = len(q_df) if not q_df.empty else 0
    total_q_val = q_df["amount"].apply(_safe_float).sum() if not q_df.empty else 0.0

    succ_q_df = q_df[q_df["status"] == "Successful"] if not q_df.empty else pd.DataFrame()
    succ_count = len(succ_q_df)
    succ_val = succ_q_df["amount"].apply(_safe_float).sum() if not succ_q_df.empty else 0.0

    sent_q_df = q_df[q_df["status"] == "Sent"] if not q_df.empty else pd.DataFrame()
    sent_count = len(sent_q_df)
    sent_val = sent_q_df["amount"].apply(_safe_float).sum() if not sent_q_df.empty else 0.0

    declined_q_df = q_df[q_df["status"] == "Declined"] if not q_df.empty else pd.DataFrame()
    declined_count = len(declined_q_df)
    declined_val = declined_q_df["amount"].apply(_safe_float).sum() if not declined_q_df.empty else 0.0

    win_rate = (succ_count / total_q * 100) if total_q > 0 else 0.0
    pending_rate = (sent_count / total_q * 100) if total_q > 0 else 0.0
    declined_rate = (declined_count / total_q * 100) if total_q > 0 else 0.0

    qc1, qc2, qc3, qc4 = st.columns(4)
    qc1.metric("Total Quotations Sent", f"PKR {total_q_val:,.0f}", f"{total_q} Total Records", delta_color="off")
    qc2.metric("Successful (Approved)", f"PKR {succ_val:,.0f}", f"{succ_count} Records ({win_rate:.1f}% Win Rate)", delta_color="normal")
    qc3.metric("Only Sent (Pending)", f"PKR {sent_val:,.0f}", f"{sent_count} Records ({pending_rate:.1f}% Pending)", delta_color="off")
    qc4.metric("Declined", f"PKR {declined_val:,.0f}", f"{declined_count} Records ({declined_rate:.1f}% Declined)", delta_color="inverse")

    st.markdown("##### 📁 Quotation Record Breakdown by Status & Lead Generator")
    q_dash_tabs = st.tabs([
        f"🟢 Approved ({succ_count})", 
        f"🟡 Pending ({sent_count})", 
        f"🔴 Declined ({declined_count})",
        "👤 Lead Generator Analytics"
    ])

    with q_dash_tabs[0]:
        if succ_q_df.empty:
            st.caption("No approved/successful quotations recorded for this period.")
        else:
            disp_succ = succ_q_df[["quotation_number", "company_name", "project_name", "lead_generator", "amount", "created_at"]].copy()
            disp_succ.columns = ["Quotation #", "Company Name", "Project Name", "Lead Generator", "Amount (PKR)", "Date Sent"]
            disp_succ["Amount (PKR)"] = disp_succ["Amount (PKR)"].apply(lambda x: f"PKR {_safe_float(x):,.0f}")
            disp_succ.insert(0, "#", range(1, len(disp_succ) + 1))
            st.dataframe(disp_succ, hide_index=True, use_container_width=True)

    with q_dash_tabs[1]:
        if sent_q_df.empty:
            st.caption("No pending/sent quotations recorded for this period.")
        else:
            disp_sent = sent_q_df[["quotation_number", "company_name", "project_name", "lead_generator", "amount", "created_at"]].copy()
            disp_sent.columns = ["Quotation #", "Company Name", "Project Name", "Lead Generator", "Amount (PKR)", "Date Sent"]
            disp_sent["Amount (PKR)"] = disp_sent["Amount (PKR)"].apply(lambda x: f"PKR {_safe_float(x):,.0f}")
            disp_sent.insert(0, "#", range(1, len(disp_sent) + 1))
            st.dataframe(disp_sent, hide_index=True, use_container_width=True)

    with q_dash_tabs[2]:
        if declined_q_df.empty:
            st.caption("No declined quotations recorded for this period.")
        else:
            disp_dec = declined_q_df[["quotation_number", "company_name", "project_name", "lead_generator", "amount", "created_at"]].copy()
            disp_dec.columns = ["Quotation #", "Company Name", "Project Name", "Lead Generator", "Amount (PKR)", "Date Sent"]
            disp_dec["Amount (PKR)"] = disp_dec["Amount (PKR)"].apply(lambda x: f"PKR {_safe_float(x):,.0f}")
            disp_dec.insert(0, "#", range(1, len(disp_dec) + 1))
            st.dataframe(disp_dec, hide_index=True, use_container_width=True)

    with q_dash_tabs[3]:
        if q_df.empty:
            st.caption("No quotation records found for lead generator analytics.")
        else:
            lg_summary_rows = []
            all_lgs = sorted([l for l in q_df["lead_generator"].dropna().unique() if str(l).strip() not in ("nan", "None", "")])
            if not all_lgs:
                all_lgs = ["Unassigned"]

            for lg_user in all_lgs:
                lg_q = q_df[q_df["lead_generator"] == lg_user] if lg_user != "Unassigned" else q_df[q_df["lead_generator"].isna() | (q_df["lead_generator"] == "")]
                lg_tot = len(lg_q)
                lg_tot_val = lg_q["amount"].apply(_safe_float).sum()
                
                lg_succ = len(lg_q[lg_q["status"] == "Successful"])
                lg_succ_val = lg_q[lg_q["status"] == "Successful"]["amount"].apply(_safe_float).sum()
                
                lg_sent = len(lg_q[lg_q["status"] == "Sent"])
                lg_sent_val = lg_q[lg_q["status"] == "Sent"]["amount"].apply(_safe_float).sum()

                lg_dec = len(lg_q[lg_q["status"] == "Declined"])
                lg_dec_val = lg_q[lg_q["status"] == "Declined"]["amount"].apply(_safe_float).sum()

                lg_win_rate = (lg_succ / lg_tot * 100.0) if lg_tot > 0 else 0.0

                lg_summary_rows.append({
                    "Lead Generator": lg_user,
                    "Total Quotations": lg_tot,
                    "Total Quoted Value": f"PKR {lg_tot_val:,.0f}",
                    "Approved Records": f"{lg_succ} (PKR {lg_succ_val:,.0f})",
                    "Pending Records": f"{lg_sent} (PKR {lg_sent_val:,.0f})",
                    "Declined Records": f"{lg_dec} (PKR {lg_dec_val:,.0f})",
                    "Win Rate %": f"{lg_win_rate:.1f}%"
                })

            lg_df_out = pd.DataFrame(lg_summary_rows)
            lg_df_out.insert(0, "#", range(1, len(lg_df_out) + 1))
            st.dataframe(lg_df_out, hide_index=True, use_container_width=True)

    st.markdown("---")
    st.markdown(f"### 🛒 Overall Purchase & Procurement Overview ({time_filter})")
    comp_all_df = tables.get("components", pd.DataFrame()).copy()
    q_all_df = tables.get("quotations", pd.DataFrame()).copy()

    merged_comp = comp_all_df.copy() if not comp_all_df.empty else pd.DataFrame()
    if not merged_comp.empty and not q_all_df.empty:
        q_sub = q_all_df[["id", "quotation_number", "company_name", "project_name", "created_at"]]
        merged_comp = merged_comp.merge(q_sub, left_on="quotation_id", right_on="id", how="left", suffixes=("", "_q"))

    if date_limit and not merged_comp.empty and "created_at" in merged_comp:
        merged_comp["created_at_dt"] = pd.to_datetime(merged_comp["created_at"]).dt.date
        merged_comp = merged_comp[merged_comp["created_at_dt"] >= date_limit]

    if merged_comp.empty:
        st.caption("No procurement or purchase cost items logged for this period.")
    else:
        merged_comp["actual_price"] = merged_comp["actual_price"].apply(_safe_float)
        merged_comp["price"] = merged_comp["price"].apply(_safe_float)
        merged_comp["savings"] = merged_comp["price"] - merged_comp["actual_price"]
        merged_comp["purchased_by"] = merged_comp["purchased_by"].fillna("Unassigned")

        p_reuploaded = merged_comp[merged_comp["actual_price"] > 0]
        p_pending = merged_comp[merged_comp["actual_price"] == 0]

        d_tot_items = len(merged_comp)
        d_reup_items = len(p_reuploaded)
        d_planned_sum = p_reuploaded["price"].sum() if not p_reuploaded.empty else 0.0
        d_actual_sum = p_reuploaded["actual_price"].sum() if not p_reuploaded.empty else 0.0
        d_net_savings = d_planned_sum - d_actual_sum
        d_savings_pct = (d_net_savings / d_planned_sum * 100.0) if d_planned_sum > 0 else 0.0

        pk1, pk2, pk3, pk4 = st.columns(4)
        pk1.metric("Items Procured / Tracked", f"{d_reup_items} / {d_tot_items}", f"{len(p_pending)} Pending", delta_color="off")
        pk2.metric("Initially Planned Budget", f"PKR {d_planned_sum:,.0f}")
        pk3.metric("Purchase Amount", f"PKR {d_actual_sum:,.0f}")
        pk4.metric("Total Procurement Savings", f"PKR {d_net_savings:,.0f}", f"{d_savings_pct:.1f}% Savings", delta_color="normal" if d_net_savings >= 0 else "inverse")

        st.markdown("##### 📁 Procurement Breakdown & Purchaser Savings Summary")
        p_dash_tabs = st.tabs([
            f"🛍️ Purchaser Performance ({len(merged_comp['purchased_by'].unique())})",
            f"📦 Procured Items ({d_reup_items})",
            f"🟡 Pending Re-Uploads ({len(p_pending)})"
        ])

        with p_dash_tabs[0]:
            all_dash_purchasers = sorted(list(set([str(p).strip() for p in merged_comp["purchased_by"].unique() if p and str(p).strip() not in ("nan", "None", "", "Unassigned")])))
            if not all_dash_purchasers:
                st.caption("No purchaser assignments recorded for this period.")
            else:
                pur_summary_rows = []
                for p_user in all_dash_purchasers:
                    p_user_items = merged_comp[merged_comp["purchased_by"] == p_user]
                    p_user_reup = p_user_items[p_user_items["actual_price"] > 0]
                    p_u_planned = p_user_reup["price"].sum()
                    p_u_actual = p_user_reup["actual_price"].sum()
                    p_u_savings = p_u_planned - p_u_actual
                    p_u_pct = (p_u_savings / p_u_planned * 100.0) if p_u_planned > 0 else 0.0

                    pur_summary_rows.append({
                        "Purchaser Person": p_user,
                        "Items Procured": f"{len(p_user_reup)} / {len(p_user_items)}",
                        "Initially Planned Budget": f"PKR {p_u_planned:,.0f}",
                        "Purchase Amount": f"PKR {p_u_actual:,.0f}",
                        "Net Money Saved": f"PKR {p_u_savings:,.0f}",
                        "Savings %": f"{p_u_pct:.1f}%"
                    })
                pur_df_out = pd.DataFrame(pur_summary_rows)
                pur_df_out.insert(0, "#", range(1, len(pur_df_out) + 1))
                st.dataframe(pur_df_out, hide_index=True, use_container_width=True)

        with p_dash_tabs[1]:
            if p_reuploaded.empty:
                st.caption("No items with market price re-uploads found.")
            else:
                disp_reup = p_reuploaded[["quotation_number", "company_name", "project_name", "component_name", "price", "actual_price", "savings", "purchased_by", "purchaser_notes"]].copy()
                disp_reup.columns = ["Quotation #", "Company Name", "Project Name", "Item Description", "Planned Budget (PKR)", "Purchase Amount (PKR)", "Savings (PKR)", "Purchaser", "Notes"]
                disp_reup["Planned Budget (PKR)"] = disp_reup["Planned Budget (PKR)"].apply(lambda x: f"PKR {_safe_float(x):,.0f}")
                disp_reup["Purchase Amount (PKR)"] = disp_reup["Purchase Amount (PKR)"].apply(lambda x: f"PKR {_safe_float(x):,.0f}")
                disp_reup["Savings (PKR)"] = disp_reup["Savings (PKR)"].apply(lambda x: f"PKR {_safe_float(x):,.0f}")
                disp_reup["Notes"] = disp_reup["Notes"].fillna("—")
                disp_reup.insert(0, "#", range(1, len(disp_reup) + 1))
                st.dataframe(disp_reup, hide_index=True, use_container_width=True)

        with p_dash_tabs[2]:
            if p_pending.empty:
                st.caption("All procurement items have been re-uploaded! No pending items.")
            else:
                disp_pend = p_pending[["quotation_number", "company_name", "project_name", "component_name", "price", "description"]].copy()
                disp_pend.columns = ["Quotation #", "Company Name", "Project Name", "Item Description", "Planned Budget (PKR)", "Sender Notes"]
                disp_pend["Planned Budget (PKR)"] = disp_pend["Planned Budget (PKR)"].apply(lambda x: f"PKR {_safe_float(x):,.0f}")
                disp_pend["Sender Notes"] = disp_pend["Sender Notes"].fillna("—")
                disp_pend.insert(0, "#", range(1, len(disp_pend) + 1))
                st.dataframe(disp_pend, hide_index=True, use_container_width=True)

# ==============================================================================
# VIEW G: STAFF ADVANCES REPORTING SCOPE
# ==============================================================================

elif menu == "💳 Staff Advances":
    if role not in ("CEO", "Accountant"):
        st.error("🔒 Unauthorized: Access restricted.")
        st.stop()
        
    st.title("💳 Staff Advances Ledger Report")
    
    tables = fetch_all_table_data()
    adv_all = tables["advances"]
    sp_all = tables["spends"]
    proj_all = tables["projects"]
    comp_all = tables["companies"]
    
    if role == "Advance":
        target_workers = [current_user["username"]]
        st.caption("👁️ Personal Advance Balance and Spendings Breakdown")
    else:
        # CEO or Accountant can see all workers
        advance_users = get_users_by_role("Accountant") + get_users_by_role("Quotation Sender") + get_users_by_role("Lead Generator") + get_users_by_role("Advance")
        active_advances_users = list(adv_all["person_name"].unique()) if not adv_all.empty else []
        target_workers = sorted(list(set(advance_users + active_advances_users)))
        st.caption("📋 Administrative Summary of all Field Worker Cash Allocations")
        
    # Pre-calculate totals for the selected target_workers
    total_allocated = 0.0
    total_spent = 0.0
    
    worker_data = []
    
    for worker in target_workers:
        # Get allocations
        w_adv = adv_all[adv_all["person_name"] == worker] if not adv_all.empty else pd.DataFrame()
        w_alloc = w_adv["allocated_amount"].apply(_safe_float).sum() if not w_adv.empty else 0.0
        
        # Get spends
        w_spend = 0.0
        w_adv_breakdown = []
        
        if not w_adv.empty:
            adv_ids = w_adv["id"].tolist()
            w_sp_df = sp_all[sp_all["advance_id"].isin(adv_ids)] if not sp_all.empty else pd.DataFrame()
            w_spend = w_sp_df["amount_spent"].apply(_safe_float).sum() if not w_sp_df.empty else 0.0
            
            # Project by project breakdown for this worker
            for _, adv in w_adv.iterrows():
                adv_id = int(adv["id"])
                proj_id = int(adv["project_id"])
                
                # Fetch project name
                proj_row = proj_all[proj_all["id"] == proj_id] if not proj_all.empty else pd.DataFrame()
                proj_name = proj_row.iloc[0]["name"] if not proj_row.empty else f"Project ID: {proj_id}"
                
                # Fetch company name if possible
                comp_name = ""
                if not proj_row.empty:
                    comp_id = proj_row.iloc[0]["company_id"]
                    comp_row = comp_all[comp_all["id"] == comp_id] if not comp_all.empty else pd.DataFrame()
                    comp_name = comp_row.iloc[0]["name"] if not comp_row.empty else ""
                
                adv_alloc_amt = _safe_float(adv["allocated_amount"])
                adv_spends = sp_all[sp_all["advance_id"] == adv_id] if not sp_all.empty else pd.DataFrame()
                adv_spent_amt = adv_spends["amount_spent"].apply(_safe_float).sum() if not adv_spends.empty else 0.0
                adv_bal = adv_alloc_amt - adv_spent_amt
                
                # Spent details list
                spent_items = []
                if not adv_spends.empty:
                    for _, sp in adv_spends.sort_values("id", ascending=False).iterrows():
                        spent_items.append({
                            "item": sp["item_name"],
                            "amount": _safe_float(sp["amount_spent"]),
                            "date": sp["created_at"]
                        })
                
                w_adv_breakdown.append({
                    "project_name": proj_name,
                    "company_name": comp_name,
                    "allocated": adv_alloc_amt,
                    "spent": adv_spent_amt,
                    "balance": adv_bal,
                    "spends": spent_items
                })
        
        w_bal = w_alloc - w_spend
        total_allocated += w_alloc
        total_spent += w_spend
        
        worker_data.append({
            "name": worker,
            "allocated": w_alloc,
            "spent": w_spend,
            "balance": w_bal,
            "breakdown": w_adv_breakdown
        })
        
    total_balance = total_allocated - total_spent
    
    # Display top summary metrics
    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("Total Cash Allocated", f"PKR {total_allocated:,.0f}")
    mc2.metric("Total Spent", f"PKR {total_spent:,.0f}")
    mc3.metric("Remaining Balance", f"PKR {total_balance:,.0f}")
    st.write("---")
    
    if not worker_data:
        st.info("No staff advance records found in the database.")
    else:
        for wd in worker_data:
            with st.container(border=True):
                # Header with name and totals
                c1, c2 = st.columns([3.5, 2.5])
                c1.markdown(f"### 👤 **{wd['name']}**")
                
                c2.markdown(
                    f"<p style='font-size:0.95rem; margin:0; text-align:right; color:#475569;'>"
                    f"Allocated: <span style='font-weight:600;'>PKR {wd['allocated']:,.0f}</span> | "
                    f"Spent: <span style='color:#ef4444; font-weight:600;'>PKR {wd['spent']:,.0f}</span> | "
                    f"Bal: <span style='color:#10B981; font-weight:600;'>PKR {wd['balance']:,.0f}</span>"
                    f"</p>", 
                    unsafe_allow_html=True
                )
                
                # Expander for project details
                if wd["breakdown"]:
                    with st.expander(f"📁 View Project-wise Allocation Details for {wd['name']}", expanded=True if len(target_workers) == 1 else False):
                        for p_idx, b in enumerate(wd["breakdown"]):
                            st.markdown(f"##### 📁 **{b['project_name']}**" + (f" *({b['company_name']})*" if b['company_name'] else ""))
                            
                            pc1, pc2, pc3 = st.columns(3)
                            pc1.markdown(f"<small>Allocated:</small><br/>**PKR {b['allocated']:,.0f}**", unsafe_allow_html=True)
                            pc2.markdown(f"<small>Spent:</small><br/>**PKR {b['spent']:,.0f}**", unsafe_allow_html=True)
                            pc3.markdown(f"<small>Remaining:</small><br/>**PKR {b['balance']:,.0f}**", unsafe_allow_html=True)
                            
                            # Spent concept list for this project
                            if b["spends"]:
                                st.markdown("<small>Expense Ledgers Logged:</small>", unsafe_allow_html=True)
                                spend_rows = []
                                for item in b["spends"]:
                                    spend_rows.append(f"• **PKR {item['amount']:,.0f}** — *{item['item']}* <span style='color:#64748b; font-size:0.75rem;'>({item['date']})</span>")
                                st.markdown("<br/>".join(spend_rows), unsafe_allow_html=True)
                            else:
                                st.markdown("<small style='color:#94a3b8;'>No expenditures logged for this project allocation yet.</small>", unsafe_allow_html=True)
                            
                            if p_idx < len(wd["breakdown"]) - 1:
                                st.write("---")
                else:
                    st.caption("No project allocations made to this worker yet.")

# ==============================================================================
# VIEW B: COMPANY & PROJECT WORKSPACE (INTEGRATED SINGLE-CARD PERFECTION)
# ==============================================================================

elif menu == "🏢 Execution(Accounts)":
    if role not in ("CEO", "Accountant"):
        st.error("🔒 Unauthorized: Access restricted.")
        st.stop()
    st.title("🏢 Execution(Accounts) Workspace")
    is_read_only = role in ("Advance", "CEO")

    if role == "CEO":
        st.caption("👁️ Executive Observer Mode")
    elif role == "Advance":
        st.caption("👁️ Read-Only Mode")

    companies_df = get_all_companies()
    tables = fetch_all_table_data()
    _all_balances, _zero_bal = _compute_all_balances(tables)

    for idx, r in companies_df.iterrows():
        c_id = int(r["id"])
        company_name = r["name"]
        c_bal = get_company_balance(c_id, _precomputed=_all_balances, _zero=_zero_bal)

        bg_palette = [
            ("background-color: #f8fafc; border-left: 5px solid #2563eb;", "#1e40af"),
            ("background-color: #f0fdf4; border-left: 5px solid #059669;", "#065f46"),
            ("background-color: #faf5ff; border-left: 5px solid #7c3aed;", "#5b21b6"),
            ("background-color: #fff7ed; border-left: 5px solid #ea580c;", "#9a3412")
        ]
        curr_bg, curr_text_color = bg_palette[idx % len(bg_palette)]

        st.markdown(f'<div style="{curr_bg} border-radius: 6px; padding: 8px 12px; margin-bottom: 6px; border-top: 1px solid #e2e8f0; border-right: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0;"><strong style="font-size: 1.05rem; color: {curr_text_color};">🏛️ {r["name"]}</strong></div>', unsafe_allow_html=True)
        with st.container(border=True):
            col_name, col_bal, col_prof, col_loan, col_edit, col_btn = st.columns([1.8, 2.2, 2.2, 2.2, 1.6, 1.3])
            col_name.markdown(f"**{r['name']}**")
            col_bal.metric("Balance", f"PKR {c_bal['balance']:,.0f}")
            col_prof.metric("Net Profit", f"PKR {c_bal['profit']:,.0f}")
            col_loan.metric("Active Loans", f"PKR {c_bal['loans']:,.0f}")

            is_editing_co = st.session_state.get("edit_co_id") == c_id
            if not is_read_only:
                edit_c1, edit_c2 = col_edit.columns(2)
                if edit_c1.button("✏️", key=f"edit_co_btn_{c_id}", use_container_width=True, help="Edit company details"):
                    next_co_edit = None if is_editing_co else c_id
                    close_all_open_forms(except_key="edit_co_id")
                    st.session_state["edit_co_id"] = next_co_edit
                    st.rerun()
                if edit_c2.button("🗑️", key=f"del_co_btn_{c_id}", use_container_width=True, help="Delete company entity"):
                    try:
                        sb.table("companies").delete().eq("id", c_id).execute()
                        confirm_warn_and_rerun(f"Deleted company '{r['name']}'.", icon="🗑️")
                    except Exception as e:
                        st.error(f"Cannot delete company: {e}")

            is_active = st.session_state.get("sel_co_id") == c_id
            btn_label = "🔒 Close" if is_active else "📂 Open"

            if col_btn.button(btn_label, key=f"btn_co_{c_id}", use_container_width=True, type="primary" if is_active else "secondary"):
                next_sel = None if is_active else c_id
                close_all_open_forms(except_key="sel_co_id")
                st.session_state["sel_co_id"] = next_sel
                st.session_state["sel_proj_id"] = None
                st.rerun()

            if is_editing_co and not is_read_only:
                with st.form(f"edit_co_form_{c_id}"):
                    st.markdown("**✏️ Edit Company Details**")
                    ec1, ec2 = st.columns(2)
                    edit_name = ec1.text_input("Company Name", value=r["name"])
                    edit_site = ec2.text_input("Location / Site", value=r["site"] if not pd.isna(r["site"]) else "")
                    edit_desc = st.text_area("Description", value=r["description"] if not pd.isna(r["description"]) else "", height=45)
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

                projects_df = get_projects_full(c_id)

                if projects_df.empty:
                    st.caption("No registered projects found under this entity structure.")
                    if not is_read_only:
                        if st.button("➕ Create New Project Node", key=f"add_p_empty_{c_id}", type="primary"):
                            st.session_state[f"show_add_proj_{c_id}"] = True
                            st.rerun()
                else:
                    p_labels = [p["name"] for _, p in projects_df.iterrows()]
                    p_map = {p["name"]: int(p["id"]) for _, p in projects_df.iterrows()}

                    p_lbl_col, p_sel_col, p_edit_col = st.columns([1.2, 4.2, 1.8], vertical_alignment="center")
                    p_lbl_col.markdown("<h3 style='margin:0;'>Projects</h3>", unsafe_allow_html=True)
                    chosen_p_label = p_sel_col.selectbox("Projects", p_labels, key=f"p_pop_select_{c_id}", label_visibility="collapsed")
                    pid = p_map[chosen_p_label]

                    active_project_row = projects_df[projects_df["id"] == pid].iloc[0]
                    p_description_content = active_project_row["description"]

                    is_editing_proj = st.session_state.get("edit_proj_id") == pid
                    is_adding_proj = st.session_state.get(f"show_add_proj_{c_id}", False)
                    if not is_read_only:
                        pe_col1, pe_col2, pe_col3 = p_edit_col.columns([1, 1, 1])
                        if pe_col1.button("➕", key=f"add_proj_btn_{c_id}", use_container_width=True, help="Create New Project"):
                            next_add = not is_adding_proj
                            close_all_open_forms(except_key=f"show_add_proj_{c_id}")
                            st.session_state[f"show_add_proj_{c_id}"] = next_add
                            st.rerun()
                        if pe_col2.button("✏️", key=f"edit_proj_btn_{pid}", use_container_width=True, help="Edit Project"):
                            next_p_edit = None if is_editing_proj else pid
                            close_all_open_forms(except_key="edit_proj_id")
                            st.session_state["edit_proj_id"] = next_p_edit
                            st.rerun()
                        if pe_col3.button("🗑️", key=f"del_proj_btn_{pid}", use_container_width=True, help="Delete Project"):
                            try:
                                sb.table("projects").delete().eq("id", pid).execute()
                                confirm_warn_and_rerun(f"Deleted project '{active_project_row['name']}'.", icon="🗑️")
                            except Exception as e:
                                st.error(f"Cannot delete project: {e}")

                    if is_editing_proj and not is_read_only:
                        with st.form(f"edit_proj_form_{pid}"):
                            st.markdown("**✏️ Edit Project Details**")
                            edit_p_name = st.text_input("Project Title", value=active_project_row["name"])
                            edit_p_desc = st.text_area("Project Description / Scope Notes", value=p_description_content if not pd.isna(p_description_content) else "", height=45)
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

                    p_bal = get_project_balance(pid, _precomputed=_all_balances, _zero=_zero_bal)

                    m_c1, m_c2, m_c3 = st.columns(3)
                    m_c1.metric("Project Balance", f"PKR {p_bal['balance']:,.0f}")
                    m_c2.metric("Project Profit", f"PKR {p_bal['profit']:,.0f}")
                    m_c3.metric("Active Project Loans", f"PKR {p_bal['loans']:,.0f}")

                    if p_description_content and not pd.isna(p_description_content):
                        clean_desc = str(p_description_content).replace(EXEC_TAG, "").strip()
                        if clean_desc and clean_desc != "Auto-provisioned from Approved Quotation":
                            st.caption(f"📝 **Scope Details:** {clean_desc}")

                    st.write("---")

                    # Fast In-Memory Ledgers Extraction
                    l_all = tables["ledgers"]
                    p_ledgers = l_all[l_all["project_id"] == pid] if not l_all.empty else pd.DataFrame()

                    exp_data = p_ledgers[p_ledgers["type"] == "expense"][["id", "title", "amount", "cheque_number"]] if not p_ledgers.empty else pd.DataFrame()
                    inc_data = p_ledgers[p_ledgers["type"] == "income"][["id", "title", "amount", "cheque_number"]] if not p_ledgers.empty else pd.DataFrame()
                    loan_data = p_ledgers[p_ledgers["type"] == "loan"][["id", "title", "amount", "cheque_number"]] if not p_ledgers.empty else pd.DataFrame()

                    # ==========================================
                    # END-TO-END PROJECT AUDIT & SUMMARY EXPANDER
                    # ==========================================
                    with st.expander("📊 End-to-End Project Audit & Summary (Quotation to Execution)", expanded=False):
                        # 1. Quotation Lookup
                        all_q_df = tables.get("quotations", pd.DataFrame())
                        q_match = pd.DataFrame()
                        if not all_q_df.empty:
                            q_match = all_q_df[
                                (all_q_df["project_name"].astype(str).str.strip().str.lower() == str(active_project_row["name"]).strip().lower()) &
                                (all_q_df["company_name"].astype(str).str.strip().str.lower() == str(company_name).strip().lower())
                            ]
                            if q_match.empty:
                                q_match = all_q_df[all_q_df["project_name"].astype(str).str.strip().str.lower() == str(active_project_row["name"]).strip().lower()]

                        q_row = q_match.iloc[0] if not q_match.empty else None

                        # Quoted Justifications
                        q_components_df = pd.DataFrame()
                        all_qc_df = tables.get("components", pd.DataFrame())
                        if q_row is not None and not all_qc_df.empty:
                            q_components_df = all_qc_df[all_qc_df["quotation_id"] == int(q_row["id"])]

                        planned_cost_total = float(q_components_df["price"].sum()) if not q_components_df.empty else 0.0
                        quoted_val = float(q_row["amount"]) if q_row is not None else 0.0

                        # 2. Execution Totals
                        inc_audit_df = inc_data
                        exp_audit_df = exp_data
                        loan_audit_df = loan_data

                        tot_income = float(inc_audit_df["amount"].sum()) if not inc_audit_df.empty else 0.0
                        tot_expense = float(exp_audit_df["amount"].sum()) if not exp_audit_df.empty else 0.0
                        tot_loan = float(loan_audit_df["amount"].sum()) if not loan_audit_df.empty else 0.0

                        # Staff Advances & Spends
                        adv_all = tables.get("advances", pd.DataFrame())
                        p_adv_df = adv_all[adv_all["project_id"] == pid] if not adv_all.empty else pd.DataFrame()
                        tot_adv_alloc = float(p_adv_df["allocated_amount"].sum()) if not p_adv_df.empty else 0.0

                        spends_all = tables.get("advance_spends", pd.DataFrame())
                        p_adv_ids = p_adv_df["id"].tolist() if not p_adv_df.empty else []
                        p_spends_df = spends_all[spends_all["advance_id"].isin(p_adv_ids)] if (not spends_all.empty and p_adv_ids) else pd.DataFrame()
                        tot_adv_spends = float(p_spends_df["amount_spent"].sum()) if not p_spends_df.empty else 0.0

                        # Vouchers Outflow
                        vouchers_all = tables.get("vouchers", pd.DataFrame())
                        p_vouchers_df = vouchers_all[
                            (vouchers_all["project_id"] == pid) & (vouchers_all["status"] == "Approved")
                        ] if not vouchers_all.empty else pd.DataFrame()
                        tot_vouchers = float(p_vouchers_df["amount"].sum()) if not p_vouchers_df.empty else 0.0

                        tot_actual_outflow = tot_expense + tot_adv_spends + tot_vouchers
                        net_profit = tot_income - tot_actual_outflow
                        profit_margin = (net_profit / tot_income * 100.0) if tot_income > 0 else 0.0
                        cost_variance = planned_cost_total - (tot_expense + tot_adv_spends)

                        # 3. Purchasing Total
                        purchasing_total = float(q_components_df[q_components_df["actual_price"].apply(_safe_float) > 0]["actual_price"].apply(_safe_float).sum()) if not q_components_df.empty else 0.0

                        # Top Audit Metrics - Key Project Amounts
                        st.markdown("##### 📊 Key Project Amounts")
                        km1, km2, km3, km4 = st.columns(4)
                        km1.metric("Quotation Amount", f"PKR {quoted_val:,.0f}", f"Ref: {q_row['quotation_number']}" if q_row is not None else "No Quotation")
                        km2.metric("Planning Amount", f"PKR {planned_cost_total:,.0f}")
                        km3.metric("Purchasing Amount", f"PKR {purchasing_total:,.0f}" if purchasing_total > 0 else "🟡 Pending")
                        km4.metric("Execution Amount", f"PKR {tot_actual_outflow:,.0f}", f"PKR {net_profit:,.0f} Profit" if net_profit >= 0 else f"PKR {net_profit:,.0f} Loss", delta_color="normal" if net_profit >= 0 else "inverse")

                        # Printable Report Expander
                        with st.expander("🖨️ Printable Project Financial & Component Audit Report", expanded=False):
                            comp_html_rows = ""
                            if not q_components_df.empty:
                                for idx_c, (_, c_r) in enumerate(q_components_df.iterrows(), start=1):
                                    pl_amt = _safe_float(c_r["price"])
                                    ac_amt = _safe_float(c_r["actual_price"])
                                    sav_amt = pl_amt - ac_amt if ac_amt > 0 else 0.0
                                    comp_html_rows += f"""
                                    <tr>
                                        <td>{idx_c}</td>
                                        <td><strong>{c_r['component_name']}</strong></td>
                                        <td>PKR {pl_amt:,.0f}</td>
                                        <td>{'PKR ' + f'{ac_amt:,.0f}' if ac_amt > 0 else '<span style="color:#d97706;">Pending</span>'}</td>
                                        <td>{'PKR ' + f'{sav_amt:,.0f}' if ac_amt > 0 else '—'}</td>
                                        <td>{c_r.get('purchased_by') or 'Unassigned'}</td>
                                        <td>{c_r.get('purchaser_notes') or c_r.get('description') or '—'}</td>
                                    </tr>
                                    """
                            else:
                                comp_html_rows = "<tr><td colspan='7' style='text-align:center; color:#64748b;'>No components logged.</td></tr>"

                            inc_html_rows = ""
                            if not inc_audit_df.empty:
                                for idx_i, (_, i_r) in enumerate(inc_audit_df.iterrows(), start=1):
                                    inc_html_rows += f"<tr><td>{idx_i}</td><td>{i_r['title']}</td><td>PKR {_safe_float(i_r['amount']):,.0f}</td><td>{i_r.get('cheque_number') or '—'}</td></tr>"
                            else:
                                inc_html_rows = "<tr><td colspan='4' style='text-align:center; color:#64748b;'>No income receipts logged.</td></tr>"

                            exp_html_rows = ""
                            if not exp_audit_df.empty:
                                for idx_e, (_, e_r) in enumerate(exp_audit_df.iterrows(), start=1):
                                    exp_html_rows += f"<tr><td>{idx_e}</td><td>{e_r['title']}</td><td>PKR {_safe_float(e_r['amount']):,.0f}</td></tr>"
                            else:
                                exp_html_rows = "<tr><td colspan='3' style='text-align:center; color:#64748b;'>No direct expenses.</td></tr>"

                            vouch_html_rows = ""
                            if not p_vouchers_df.empty:
                                for idx_v, (_, v_r) in enumerate(p_vouchers_df.iterrows(), start=1):
                                    vouch_html_rows += f"<tr><td>{idx_v}</td><td>{v_r['voucher_number']}</td><td>{v_r['title']}</td><td>PKR {_safe_float(v_r['amount']):,.0f}</td><td>{v_r.get('type') or 'General'}</td></tr>"
                            else:
                                vouch_html_rows = "<tr><td colspan='5' style='text-align:center; color:#64748b;'>No approved vouchers linked.</td></tr>"

                            # Base64 logo for clean printing
                            logo_b64 = ""
                            logo_file = "logo.png" if os.path.exists("logo.png") else ("logo.jpeg" if os.path.exists("logo.jpeg") else ("logo.jpg" if os.path.exists("logo.jpg") else None))
                            if logo_file:
                                try:
                                    import base64
                                    with open(logo_file, "rb") as f_img:
                                        b64_data = base64.b64encode(f_img.read()).decode("utf-8")
                                        mime_type = "image/png" if logo_file.endswith(".png") else "image/jpeg"
                                        logo_b64 = f"data:{mime_type};base64,{b64_data}"
                                except Exception:
                                    logo_b64 = ""

                            html_report_doc = f"""
                            <!DOCTYPE html>
                            <html>
                            <head>
                            <style>
                                body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #0f172a; padding: 15px; margin: 0; background: #ffffff; }}
                                .header-box {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #2563eb; padding-bottom: 10px; margin-bottom: 15px; }}
                                .title {{ font-size: 1.25rem; font-weight: bold; color: #1e3a8a; }}
                                .subtitle {{ font-size: 0.85rem; color: #475569; }}
                                .amounts-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin-bottom: 20px; }}
                                .card {{ background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px; text-align: center; }}
                                .card-label {{ font-size: 0.72rem; font-weight: 600; text-transform: uppercase; color: #64748b; margin-bottom: 3px; }}
                                .card-val {{ font-size: 1.05rem; font-weight: 700; color: #0f172a; }}
                                table {{ width: 100%; border-collapse: collapse; margin-top: 10px; margin-bottom: 20px; font-size: 0.85rem; }}
                                th {{ background: #f1f5f9; color: #1e293b; text-align: left; padding: 8px; border: 1px solid #cbd5e1; font-weight: 600; }}
                                td {{ padding: 7px 8px; border: 1px solid #e2e8f0; color: #334155; }}
                                .sec-title {{ font-size: 0.95rem; font-weight: bold; color: #1e293b; margin-top: 15px; margin-bottom: 5px; border-left: 3px solid #2563eb; padding-left: 8px; }}
                                .btn-print {{ background: #2563eb; color: #ffffff; padding: 8px 16px; border: none; border-radius: 5px; font-weight: bold; cursor: pointer; font-size: 0.9rem; margin-bottom: 15px; }}
                                .btn-print:hover {{ background: #1d4ed8; }}
                                @media print {{
                                    .btn-print {{ display: none !important; }}
                                    body {{ padding: 0; }}
                                }}
                            </style>
                            </head>
                            <body>
                                <button class="btn-print" onclick="window.print()">🖨️ Print Report / Save PDF</button>
                                <div class="header-box">
                                    <div style="display: flex; align-items: center; gap: 14px;">
                                        {f'<img src="{logo_b64}" style="max-height: 58px; width: auto; object-fit: contain;" />' if logo_b64 else ''}
                                        <div>
                                            <div class="subtitle" style="font-size: 1rem; font-weight: 700; color: #1e3a8a;">Project Financial Audit & Component Summary Report</div>
                                            <div style="font-size: 0.85rem; color: #2563eb; font-weight: bold; margin-top: 2px;">Quotation Reference #: {q_row['quotation_number'] if q_row is not None else 'N/A'}</div>
                                        </div>
                                    </div>
                                    <div style="text-align: right;">
                                        <div><strong>Company:</strong> {company_name}</div>
                                        <div><strong>Project:</strong> {active_project_row['name']}</div>
                                        <div><small>Printed On: {datetime.date.today()}</small></div>
                                    </div>
                                </div>

                                <div class="amounts-grid">
                                    <div class="card">
                                        <div class="card-label">Quotation Amount</div>
                                        <div class="card-val" style="color:#2563eb;">PKR {quoted_val:,.0f}</div>
                                    </div>
                                    <div class="card">
                                        <div class="card-label">Planning Amount</div>
                                        <div class="card-val" style="color:#475569;">PKR {planned_cost_total:,.0f}</div>
                                    </div>
                                    <div class="card">
                                        <div class="card-label">Purchasing Amount</div>
                                        <div class="card-val" style="color:#059669;">PKR {purchasing_total:,.0f}</div>
                                    </div>
                                    <div class="card">
                                        <div class="card-label">Execution Amount</div>
                                        <div class="card-val" style="color:#dc2626;">PKR {tot_actual_outflow:,.0f}</div>
                                    </div>
                                    <div class="card" style="background: {'#f0fdf4' if net_profit >= 0 else '#fef2f2'}; border-color: {'#86efac' if net_profit >= 0 else '#fca5a5'};">
                                        <div class="card-label" style="color: {'#166534' if net_profit >= 0 else '#991b1b'};">Net Executed Profit</div>
                                        <div class="card-val" style="color: {'#15803d' if net_profit >= 0 else '#b91c1c'};">PKR {net_profit:,.0f}</div>
                                        <div style="font-size: 0.72rem; color: {'#166534' if net_profit >= 0 else '#991b1b'};">{profit_margin:.1f}% Margin</div>
                                    </div>
                                </div>

                                <div class="sec-title">📦 Itemized Components & Purchaser Quotes</div>
                                <table>
                                    <thead>
                                        <tr>
                                            <th style="width: 5%;">#</th>
                                            <th>Item Description</th>
                                            <th>Planned Price</th>
                                            <th>Purchaser Quote</th>
                                            <th>Savings / Overrun</th>
                                            <th>Purchaser</th>
                                            <th>Notes</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {comp_html_rows}
                                    </tbody>
                                </table>

                                <div class="sec-title">🟢 Income Receipts Collected</div>
                                <table>
                                    <thead>
                                        <tr>
                                            <th style="width: 5%;">#</th>
                                            <th>Payment Description</th>
                                            <th>Amount Received</th>
                                            <th>Cheque / Ref #</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {inc_html_rows}
                                    </tbody>
                                </table>

                                <div style="display: flex; gap: 15px;">
                                    <div style="flex: 1;">
                                        <div class="sec-title">🔴 Direct Expenses</div>
                                        <table>
                                            <thead>
                                                <tr>
                                                    <th style="width: 8%;">#</th>
                                                    <th>Expense Description</th>
                                                    <th>Amount</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {exp_html_rows}
                                            </tbody>
                                        </table>
                                    </div>
                                    <div style="flex: 1;">
                                        <div class="sec-title">🎫 Approved Vouchers Payouts</div>
                                        <table>
                                            <thead>
                                                <tr>
                                                    <th style="width: 8%;">#</th>
                                                    <th>Voucher #</th>
                                                    <th>Title</th>
                                                    <th>Amount</th>
                                                    <th>Type</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {vouch_html_rows}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            </body>
                            </html>
                            """
                            components.html(html_report_doc, height=500, scrolling=True)

                        st.write("---")

                        # Detailed Breakdown Tabs inside Summary
                        sum_t1, sum_t2, sum_t3, sum_t4, sum_t5 = st.tabs([
                            "📋 Quotation Baseline",
                            "🛒 Procurement & Purchasing",
                            "🟢 Income Receipts",
                            "🔴 Expenses & Outflows",
                            "💳 Staff Advances Audit"
                        ])

                        with sum_t1:
                            if q_row is not None:
                                st.markdown(f"**Quotation Ref**: `{q_row['quotation_number']}` | **Status**: `{q_row['status']}` | **Lead Gen**: `{q_row.get('lead_generator', 'N/A')}`")
                                if q_row.get("notes"):
                                    st.caption(f"**Quotation Scope Notes:** {q_row['notes']}")

                                st.markdown("##### 📝 Planned Cost Justifications")
                                if not q_components_df.empty:
                                    disp_qc = q_components_df[["component_name", "price", "description", "created_by"]].copy()
                                    disp_qc.columns = ["Component Title", "Planned Price (PKR)", "Notes / Specs", "Quoted By"]
                                    disp_qc["Planned Price (PKR)"] = disp_qc["Planned Price (PKR)"].apply(lambda x: f"PKR {_safe_float(x):,.0f}")
                                    disp_qc["Notes / Specs"] = disp_qc["Notes / Specs"].fillna("—")
                                    disp_qc.insert(0, "#", range(1, len(disp_qc) + 1))
                                    st.dataframe(disp_qc, hide_index=True, use_container_width=True)
                                    st.info(f"Total Quoted Planned Cost: **PKR {planned_cost_total:,.0f}** | Execution Cost Variance: **PKR {cost_variance:,.0f}** " + ("(🟢 Under Budget)" if cost_variance >= 0 else "(🔴 Over Budget)"))
                                else:
                                    st.caption("No itemized cost justification components logged in quotation.")
                            else:
                                st.caption("No matching initial quotation found for this execution project.")

                        with sum_t2:
                            st.markdown("##### 🛒 City Market Procurement & Purchaser Quotes")
                            if q_components_df.empty:
                                st.caption("No procurement or purchasing cost items logged for this project.")
                            else:
                                pur_comp_df = q_components_df.copy()
                                pur_comp_df["price"] = pur_comp_df["price"].apply(_safe_float)
                                pur_comp_df["actual_price"] = pur_comp_df["actual_price"].apply(_safe_float)

                                reup_df = pur_comp_df[pur_comp_df["actual_price"] > 0]
                                p_planned_total = pur_comp_df["price"].sum()
                                p_actual_total = reup_df["actual_price"].sum() if not reup_df.empty else 0.0
                                p_savings_total = reup_df["price"].sum() - p_actual_total if not reup_df.empty else 0.0

                                pk1, pk2, pk3 = st.columns(3)
                                pk1.metric("Initially Planned Cost", f"PKR {p_planned_total:,.0f}")
                                pk2.metric("Actual Purchase Amount", f"PKR {p_actual_total:,.0f}" if p_actual_total > 0 else "🟡 Pending")
                                pk3.metric("Net Money Saved", f"PKR {p_savings_total:,.0f}" if p_actual_total > 0 else "—", delta_color="normal" if p_savings_total >= 0 else "inverse")

                                st.markdown("**Itemized Procurement & Purchaser Log**")
                                pur_rows = []
                                for idx_p, (_, p_row) in enumerate(pur_comp_df.iterrows(), start=1):
                                    pl_p = p_row["price"]
                                    ac_p = p_row["actual_price"]
                                    p_sav = pl_p - ac_p if ac_p > 0 else 0.0
                                    pur_rows.append({
                                        "#": idx_p,
                                        "Item Description": p_row["component_name"],
                                        "Initially Planned Budget": f"PKR {pl_p:,.0f}",
                                        "Actual Purchase Amount": f"PKR {ac_p:,.0f}" if ac_p > 0 else "🟡 Pending",
                                        "Net Savings / (Overrun)": f"PKR {p_sav:,.0f}" if ac_p > 0 else "—",
                                        "Purchaser": p_row.get("purchased_by") or "Unassigned",
                                        "Notes": p_row.get("purchaser_notes") or "—"
                                    })
                                st.dataframe(pd.DataFrame(pur_rows), hide_index=True, use_container_width=True)

                        with sum_t3:
                            st.markdown("##### 🟢 All Client Payment Inflows Received")
                            if not inc_data.empty:
                                disp_inc = inc_data[["title", "amount", "cheque_number"]].copy()
                                disp_inc.columns = ["Payment Description", "Amount Received (PKR)", "Cheque / Reference #"]
                                disp_inc["Amount Received (PKR)"] = disp_inc["Amount Received (PKR)"].apply(lambda x: f"PKR {_safe_float(x):,.0f}")
                                disp_inc["Cheque / Reference #"] = disp_inc["Cheque / Reference #"].fillna("—")
                                disp_inc.insert(0, "#", range(1, len(disp_inc) + 1))
                                st.dataframe(disp_inc, hide_index=True, use_container_width=True)
                            else:
                                st.caption("No income receipts logged yet.")

                        with sum_t4:
                            st.markdown("##### 🔴 Complete Outflows Breakdown")
                            sum_col1, sum_col2 = st.columns(2)
                            with sum_col1:
                                st.markdown("**Direct Project Expenses**")
                                if not exp_data.empty:
                                    disp_exp = exp_data[["title", "amount"]].copy()
                                    disp_exp.columns = ["Expense Title", "Amount (PKR)"]
                                    disp_exp["Amount (PKR)"] = disp_exp["Amount (PKR)"].apply(lambda x: f"PKR {_safe_float(x):,.0f}")
                                    disp_exp.insert(0, "#", range(1, len(disp_exp) + 1))
                                    st.dataframe(disp_exp, hide_index=True, use_container_width=True)
                                else:
                                    st.caption("No direct expenses logged.")
                            with sum_col2:
                                st.markdown("**Approved Vouchers Payouts**")
                                if not p_vouchers_df.empty:
                                    disp_v = p_vouchers_df[["voucher_number", "title", "amount", "type"]].copy()
                                    disp_v.columns = ["Voucher #", "Title", "Amount (PKR)", "Department"]
                                    disp_v["Amount (PKR)"] = disp_v["Amount (PKR)"].apply(lambda x: f"PKR {_safe_float(x):,.0f}")
                                    disp_v.insert(0, "#", range(1, len(disp_v) + 1))
                                    st.dataframe(disp_v, hide_index=True, use_container_width=True)
                                else:
                                    st.caption("No approved vouchers linked.")

                        with sum_t5:
                            st.markdown("##### 💳 Staff Field Advances Audit")
                            if not p_adv_df.empty:
                                adv_summary_rows = []
                                for _, a_row in p_adv_df.iterrows():
                                    a_id = int(a_row["id"])
                                    worker_spends = p_spends_df[p_spends_df["advance_id"] == a_id] if not p_spends_df.empty else pd.DataFrame()
                                    w_spent = float(worker_spends["amount_spent"].sum()) if not worker_spends.empty else 0.0
                                    w_alloc = float(a_row["allocated_amount"])
                                    adv_summary_rows.append({
                                        "Field Worker": a_row["person_name"],
                                        "Allocated (PKR)": f"PKR {w_alloc:,.0f}",
                                        "Spent Logged (PKR)": f"PKR {w_spent:,.0f}",
                                        "Unspent Balance (PKR)": f"PKR {(w_alloc - w_spent):,.0f}"
                                    })
                                disp_adv = pd.DataFrame(adv_summary_rows)
                                disp_adv.insert(0, "#", range(1, len(disp_adv) + 1))
                                st.dataframe(disp_adv, hide_index=True, use_container_width=True)

                                if not p_spends_df.empty:
                                    st.markdown("**Itemized Field Spend Receipts**")
                                    disp_sp = p_spends_df[["item_name", "amount_spent"]].copy()
                                    disp_sp.columns = ["Item Description", "Amount (PKR)"]
                                    disp_sp["Amount (PKR)"] = disp_sp["Amount (PKR)"].apply(lambda x: f"PKR {_safe_float(x):,.0f}")
                                    disp_sp.insert(0, "#", range(1, len(disp_sp) + 1))
                                    st.dataframe(disp_sp, hide_index=True, use_container_width=True)
                            else:
                                st.caption("No staff field advances provisioned for this project.")

                    t1, t2, t3 = st.tabs(["🟢 Income", "🔵 Loans", "💳 Staff Advances"])

                    def render_simple_form_tab(data_df, ledger_type, label_name, sub_p_name=None):
                        has_nature = (ledger_type == "income")
                        
                    def render_simple_form_tab(data_df, ledger_type, label_name, has_nature=False):
                        target_data_df = data_df.copy() if not data_df.empty else pd.DataFrame()

                        if not target_data_df.empty:
                            for _, row in target_data_df.iterrows():
                                row_id = int(row["id"])
                                edit_key = f"edit_{ledger_type}_{row_id}"
                                is_editing_row = st.session_state.get(edit_key, False)
                                nature_val = row.get("cheque_number") if not pd.isna(row.get("cheque_number")) else None

                                with st.container(border=True):
                                    rc1, rc2, rc3 = st.columns([4, 2.5, 1.8])
                                    title_display = str(row["title"])
                                    if has_nature and nature_val:
                                        title_display += f"  \n🏷️ Payment Nature: `{nature_val}`"
                                    rc1.markdown(f"**{title_display}**")
                                    rc2.markdown(f"PKR {_safe_float(row['amount']):,.0f}")
                                    if not is_read_only:
                                        ed_col1, ed_col2 = rc3.columns(2)
                                        if ed_col1.button("✏️", key=f"btn_{edit_key}", use_container_width=True, help="Edit"):
                                            next_row_edit = not is_editing_row
                                            close_all_open_forms(except_key=edit_key)
                                            st.session_state[edit_key] = next_row_edit
                                            st.rerun()
                                        if ed_col2.button("🗑️", key=f"del_{ledger_type}_{row_id}", use_container_width=True, help="Delete"):
                                            try:
                                                sb.table("ledgers").delete().eq("id", row_id).execute()
                                                confirm_warn_and_rerun(f"Deleted {ledger_type} entry.", icon="🗑️")
                                            except Exception as e:
                                                st.error(f"Cannot delete record: {e}")

                                    if is_editing_row and not is_read_only:
                                        with st.form(f"form_{edit_key}"):
                                            fe1, fe2, fe3 = st.columns([2, 1.5, 1.5])
                                            edit_title = fe1.text_input(f"{label_name} Description", value=str(row["title"]))
                                            edit_amount = fe2.number_input("Amount (PKR)", min_value=0.0, step=500.0, value=float(row["amount"]))
                                            row_dt_val = _safe_date(row.get("created_at"))
                                            edit_date = fe3.date_input("Record Date", value=row_dt_val)
                                            
                                            edit_nature = st.text_input("Payment Nature", value=str(nature_val or "")) if has_nature else None
                                            fs1, fs2 = st.columns(2)
                                            save_row = fs1.form_submit_button("💾 Save", type="primary", use_container_width=True)
                                            cancel_row = fs2.form_submit_button("✖️ Cancel", use_container_width=True)
                                            if save_row:
                                                if edit_title.strip() and edit_amount > 0:
                                                    try:
                                                        update_data = {
                                                            "title": edit_title.strip(),
                                                            "amount": float(edit_amount),
                                                            "created_at": str(edit_date)
                                                        }
                                                        if has_nature:
                                                            update_data["cheque_number"] = edit_nature.strip() if edit_nature else None
                                                        sb.table("ledgers").update(update_data).eq("id", row_id).execute()
                                                        st.session_state[edit_key] = False
                                                        confirm_and_rerun(f"✏️ {label_name} record updated.", icon="💾")
                                                    except Exception as e:
                                                        st.error(f"Cannot update record: {e}")
                                                else:
                                                    st.error("Please enter a valid description and non-zero amount.")
                                            if cancel_row:
                                                st.session_state[edit_key] = False
                                                st.rerun()
                        else:
                            st.caption(f"No {label_name.lower()} records logged yet.")

                        if not is_read_only:
                            with st.form(f"add_entry_{ledger_type}_{pid}", clear_on_submit=True):
                                st.markdown(f"➕ **Add New {label_name} Entry**")
                                if has_nature:
                                    f_col1, f_col2, f_col3, f_col4, f_col5 = st.columns([2.2, 1.8, 1.8, 1.8, 1.4], vertical_alignment="bottom")
                                    new_title = f_col1.text_input("Component Description*", key=f"t_in_{ledger_type}_{pid}")
                                    new_amount = f_col2.number_input("Value Amount (PKR)*", value=None, min_value=0.0, step=500.0, placeholder="Amount (PKR)", key=f"a_in_{ledger_type}_{pid}")
                                    new_date = f_col3.date_input("Record Date", value=datetime.date.today(), key=f"d_in_{ledger_type}_{pid}")
                                    new_nature = f_col4.text_input("Payment Nature", placeholder="e.g. Cash, Online Transfer, Cheque #", key=f"c_in_{ledger_type}_{pid}")
                                    submit_rec = f_col5.form_submit_button("➕ Add Row", use_container_width=True)
                                else:
                                    f_col1, f_col2, f_col3, f_col4 = st.columns([2.5, 2, 2, 1.5], vertical_alignment="bottom")
                                    new_title = f_col1.text_input("Component Description*", key=f"t_in_{ledger_type}_{pid}")
                                    new_amount = f_col2.number_input("Value Amount (PKR)*", value=None, min_value=0.0, step=500.0, placeholder="Amount (PKR)", key=f"a_in_{ledger_type}_{pid}")
                                    new_date = f_col3.date_input("Record Date", value=datetime.date.today(), key=f"d_in_{ledger_type}_{pid}")
                                    new_nature = None
                                    submit_rec = f_col4.form_submit_button("➕ Add Row", use_container_width=True)

                                if submit_rec:
                                    if new_title.strip() and new_amount is not None and new_amount > 0:
                                        try:
                                            insert_data = {
                                                "project_id": pid,
                                                "type": ledger_type,
                                                "title": new_title.strip(),
                                                "amount": float(new_amount),
                                                "created_at": str(new_date)
                                            }
                                            if has_nature:
                                                insert_data["cheque_number"] = new_nature.strip() if new_nature else None
                                            sb.table("ledgers").insert(insert_data).execute()
                                            confirm_and_rerun(f"📈 New {ledger_type.capitalize()} record '{new_title.strip()}' added (PKR {new_amount:,.0f}).", icon="📊")
                                        except Exception as e:
                                            st.error(f"Database insertion failed: {e}")
                                    else:
                                        st.error("Please enter a valid component description and non-zero amount.")

                    def render_advances_tab(pid):
                        # 1. Fetch available advance personas for the selection dropdown
                        advance_usernames = sorted(list(set(
                            get_users_by_role("Accountant") + 
                            get_users_by_role("Quotation Sender") + 
                            get_users_by_role("Lead Generator") + 
                            get_users_by_role("Advance")
                        )))
                        if not advance_usernames:
                            all_u = get_all_users_summary()
                            advance_usernames = all_u["username"].tolist() if not all_u.empty else []

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
                                        f"Bal: <span style='color:#10B981; font-weight:600;'>PKR {remaining:,.0f}</span> | "
                                        f"Spend: <span style='color:#ef4444; font-weight:600;'>PKR {spent_total:,.0f}</span>"
                                        f"</p>", 
                                        unsafe_allow_html=True
                                    )

                                    can_manage = role in ("CEO", "Accountant")
                                    edit_key = f"edit_advperson_{adv_id}"
                                    
                                    if can_manage:
                                        ec1, ec2 = st.columns(2)
                                        if ec1.button("✏️ Edit Allocation", key=f"btn_{edit_key}", use_container_width=True):
                                            st.session_state[edit_key] = not st.session_state.get(edit_key, False)
                                            st.rerun()
                                        if ec2.button("🗑️ Delete Allocation", key=f"del_adv_{adv_id}", use_container_width=True):
                                            try:
                                                sb.table("advances").delete().eq("id", adv_id).execute()
                                                confirm_warn_and_rerun(f"Deleted advance allocation for {adv['person_name']}.", icon="🗑️")
                                            except Exception as e:
                                                st.error(f"Cannot delete allocation: {e}")

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
                                        # --- Parse items into standalone vs categorized ---
                                        def _parse_sp_item(item_val):
                                            t_str = str(item_val).strip()
                                            if t_str.startswith("[") and "]" in t_str:
                                                cat_part = t_str[1:t_str.index("]")].strip()
                                                desc_part = t_str[t_str.index("]") + 1:].strip()
                                                return cat_part, desc_part
                                            return None, t_str

                                        standalone_items = []
                                        cat_groups = {}  # {category_name: [list of spend dicts]}
                                        all_category_names = []

                                        if not spends_df.empty:
                                            for _, sp in spends_df.iterrows():
                                                cat, desc = _parse_sp_item(sp["item_name"])
                                                sp_dict = sp.to_dict()
                                                sp_dict["_category"] = cat
                                                sp_dict["_description"] = desc
                                                if cat:
                                                    if cat not in cat_groups:
                                                        cat_groups[cat] = []
                                                        all_category_names.append(cat)
                                                    cat_groups[cat].append(sp_dict)
                                                else:
                                                    standalone_items.append(sp_dict)

                                        can_act = is_owner or role in ("CEO", "Accountant")

                                        # --- Helper: render a single component row with edit/delete ---
                                        def _render_component_row(sp_dict, category_context=None):
                                            sp_id = int(sp_dict["id"])
                                            sp_edit_key = f"edit_sp_{sp_id}"
                                            is_editing_sp = st.session_state.get(sp_edit_key, False)

                                            with st.container(border=True):
                                                rc1, rc2, rc3 = st.columns([4.5, 2.5, 1.5])
                                                rc1.markdown(f"🧾 {sp_dict['_description']}")
                                                rc2.markdown(f"**PKR {_safe_float(sp_dict['amount_spent']):,.0f}**")

                                                if can_act:
                                                    bc1, bc2 = rc3.columns(2)
                                                    if bc1.button("✏️", key=f"btn_edit_sp_{sp_id}", use_container_width=True, help="Edit"):
                                                        next_val = not is_editing_sp
                                                        close_all_open_forms(except_key=sp_edit_key)
                                                        st.session_state[sp_edit_key] = next_val
                                                        st.rerun()
                                                    if bc2.button("🗑️", key=f"btn_del_sp_{sp_id}", use_container_width=True, help="Delete"):
                                                        try:
                                                            sb.table("advance_spends").delete().eq("id", sp_id).execute()
                                                            confirm_warn_and_rerun("Deleted spend entry.", icon="🗑️")
                                                        except Exception as e:
                                                            st.error(f"Cannot delete: {e}")

                                            if is_editing_sp and can_act:
                                                with st.form(f"form_edit_sp_{sp_id}"):
                                                    # Category reassignment dropdown
                                                    move_opts = ["(No Category — Standalone)"] + [f"📂 {c}" for c in all_category_names]
                                                    current_cat = sp_dict["_category"]
                                                    if current_cat and f"📂 {current_cat}" in move_opts:
                                                        default_idx = move_opts.index(f"📂 {current_cat}")
                                                    else:
                                                        default_idx = 0
                                                    move_to = st.selectbox("Move to Category", move_opts, index=default_idx, key=f"move_cat_{sp_id}")

                                                    edit_desc = st.text_input("Description", value=sp_dict["_description"], key=f"ed_desc_{sp_id}")
                                                    edit_amt = st.number_input("Amount (PKR)", min_value=0.0, step=100.0, value=float(sp_dict["amount_spent"]), key=f"ed_amt_{sp_id}")
                                                    sc1, sc2 = st.columns(2)
                                                    save_btn = sc1.form_submit_button("💾 Save", type="primary", use_container_width=True)
                                                    cancel_btn = sc2.form_submit_button("✖️ Cancel", use_container_width=True)
                                                    if save_btn:
                                                        if edit_desc.strip() and edit_amt > 0:
                                                            new_remaining = remaining + float(sp_dict["amount_spent"]) - edit_amt
                                                            if new_remaining < 0:
                                                                st.error("Cannot update: exceeds remaining advance limit.")
                                                            else:
                                                                try:
                                                                    if move_to == "(No Category — Standalone)":
                                                                        item_fmt = edit_desc.strip()
                                                                    else:
                                                                        chosen_cat = move_to.replace("📂 ", "").strip()
                                                                        item_fmt = f"[{chosen_cat}] {edit_desc.strip()}"
                                                                    sb.table("advance_spends").update({
                                                                        "item_name": item_fmt,
                                                                        "amount_spent": float(edit_amt)
                                                                    }).eq("id", sp_id).execute()
                                                                    st.session_state[sp_edit_key] = False
                                                                    confirm_and_rerun("Updated spend entry.", icon="💾")
                                                                except Exception as e:
                                                                    st.error(f"Cannot save: {e}")
                                                        else:
                                                            st.error("Please enter a valid description and non-zero amount.")
                                                    if cancel_btn:
                                                        st.session_state[sp_edit_key] = False
                                                        st.rerun()

                                        # --- Render standalone components first ---
                                        if standalone_items:
                                            for sp_dict in standalone_items:
                                                _render_component_row(sp_dict)

                                        if not standalone_items and not cat_groups:
                                            st.caption("No spend items logged yet.")

                                        # --- Render category groups as nested expanders ---
                                        for cat_name in all_category_names:
                                            cat_items = cat_groups[cat_name]
                                            cat_total = sum(_safe_float(x["amount_spent"]) for x in cat_items)
                                            cat_rename_key = f"rename_cat_{adv_id}_{cat_name}"
                                            is_renaming = st.session_state.get(cat_rename_key, False)

                                            with st.expander(f"📂 {cat_name}  ·  {len(cat_items)} item{'s' if len(cat_items) != 1 else ''}  ·  PKR {cat_total:,.0f}"):
                                                # Category management buttons (rename / delete)
                                                if can_act:
                                                    mgmt_c1, mgmt_c2, mgmt_c3 = st.columns([5, 2, 2])
                                                    mgmt_c1.markdown(f"**📂 {cat_name}**")
                                                    if mgmt_c2.button("✏️ Rename", key=f"btn_rename_cat_{adv_id}_{cat_name}", use_container_width=True):
                                                        st.session_state[cat_rename_key] = not is_renaming
                                                        st.rerun()
                                                    if mgmt_c3.button("🗑️ Remove", key=f"btn_del_cat_{adv_id}_{cat_name}", use_container_width=True, help="Remove category — components become standalone"):
                                                        try:
                                                            for ci in cat_items:
                                                                sb.table("advance_spends").update({
                                                                    "item_name": ci["_description"]
                                                                }).eq("id", int(ci["id"])).execute()
                                                            confirm_warn_and_rerun(f"Category '{cat_name}' removed. {len(cat_items)} component(s) moved to standalone.", icon="📦")
                                                        except Exception as e:
                                                            st.error(f"Cannot remove category: {e}")

                                                    if is_renaming:
                                                        with st.form(f"form_rename_cat_{adv_id}_{cat_name}"):
                                                            new_cat_name = st.text_input("New Category Name", value=cat_name, key=f"inp_rename_{adv_id}_{cat_name}")
                                                            rc1, rc2 = st.columns(2)
                                                            if rc1.form_submit_button("💾 Rename", type="primary", use_container_width=True):
                                                                if new_cat_name.strip() and new_cat_name.strip() != cat_name:
                                                                    try:
                                                                        for ci in cat_items:
                                                                            sb.table("advance_spends").update({
                                                                                "item_name": f"[{new_cat_name.strip()}] {ci['_description']}"
                                                                            }).eq("id", int(ci["id"])).execute()
                                                                        st.session_state[cat_rename_key] = False
                                                                        confirm_and_rerun(f"Category renamed to '{new_cat_name.strip()}'.", icon="✏️")
                                                                    except Exception as e:
                                                                        st.error(f"Rename failed: {e}")
                                                                else:
                                                                    st.error("Please enter a different name.")
                                                            if rc2.form_submit_button("✖️ Cancel", use_container_width=True):
                                                                st.session_state[cat_rename_key] = False
                                                                st.rerun()

                                                st.write("---")

                                                # Render components inside this category
                                                for sp_dict in cat_items:
                                                    _render_component_row(sp_dict, category_context=cat_name)

                                                # Add component form inside this category
                                                if can_act:
                                                    with st.form(f"form_add_in_cat_{adv_id}_{cat_name}", clear_on_submit=True):
                                                        st.markdown(f"➕ **Add Component to {cat_name}**")
                                                        ic1, ic2 = st.columns(2)
                                                        cat_new_desc = ic1.text_input("Description*", placeholder="e.g. USB Cable, Fuel", key=f"cat_desc_{adv_id}_{cat_name}")
                                                        cat_new_amt = ic2.number_input("Amount (PKR)*", value=None, min_value=0.0, step=100.0, key=f"cat_amt_{adv_id}_{cat_name}")
                                                        if st.form_submit_button("➕ Add", type="primary", use_container_width=True):
                                                            if cat_new_desc.strip() and cat_new_amt is not None and cat_new_amt > 0:
                                                                if cat_new_amt > remaining + 0.001:
                                                                    st.error(f"Exceeds remaining balance of PKR {remaining:,.0f}.")
                                                                else:
                                                                    try:
                                                                        sb.table("advance_spends").insert({
                                                                            "advance_id": adv_id,
                                                                            "item_name": f"[{cat_name}] {cat_new_desc.strip()}",
                                                                            "amount_spent": float(cat_new_amt)
                                                                        }).execute()
                                                                        confirm_and_rerun(f"Added '{cat_new_desc.strip()}' to {cat_name}.", icon="🧾")
                                                                    except Exception as e:
                                                                        st.error(f"Insert failed: {e}")
                                                            else:
                                                                st.error("Enter a valid description and non-zero amount.")

                                        # --- Bottom action buttons: Add Category + Add Component ---
                                        if can_act:
                                            st.write("---")
                                            btn_c1, btn_c2 = st.columns(2)
                                            add_cat_key = f"show_add_cat_{adv_id}"
                                            add_comp_key = f"show_add_comp_{adv_id}"

                                            if btn_c1.button("📂 Add Category", key=f"btn_add_cat_{adv_id}", use_container_width=True):
                                                st.session_state[add_cat_key] = not st.session_state.get(add_cat_key, False)
                                                st.session_state[add_comp_key] = False
                                                st.rerun()
                                            if btn_c2.button("🧾 Add Component", key=f"btn_add_comp_{adv_id}", use_container_width=True):
                                                st.session_state[add_comp_key] = not st.session_state.get(add_comp_key, False)
                                                st.session_state[add_cat_key] = False
                                                st.rerun()

                                            # --- Add Category form ---
                                            if st.session_state.get(add_cat_key, False):
                                                with st.form(f"form_new_cat_{adv_id}", clear_on_submit=True):
                                                    st.markdown("📂 **Create New Category**")
                                                    new_cat_name = st.text_input("Category Name*", placeholder="e.g. Accessories, Transport, Safety Gear", key=f"new_cat_{adv_id}")
                                                    nc1, nc2 = st.columns(2)
                                                    first_desc = nc1.text_input("First Component (Optional)", placeholder="e.g. USB Cable", key=f"first_desc_{adv_id}")
                                                    first_amt = nc2.number_input("Amount (PKR)", value=None, min_value=0.0, step=100.0, key=f"first_amt_{adv_id}")
                                                    if st.form_submit_button("📂 Create Category", type="primary", use_container_width=True):
                                                        if new_cat_name.strip():
                                                            if new_cat_name.strip() in all_category_names:
                                                                st.error(f"Category '{new_cat_name.strip()}' already exists.")
                                                            elif first_desc.strip() and first_amt is not None and first_amt > 0:
                                                                if first_amt > remaining + 0.001:
                                                                    st.error(f"Exceeds remaining balance of PKR {remaining:,.0f}.")
                                                                else:
                                                                    try:
                                                                        sb.table("advance_spends").insert({
                                                                            "advance_id": adv_id,
                                                                            "item_name": f"[{new_cat_name.strip()}] {first_desc.strip()}",
                                                                            "amount_spent": float(first_amt)
                                                                        }).execute()
                                                                        st.session_state[add_cat_key] = False
                                                                        confirm_and_rerun(f"Category '{new_cat_name.strip()}' created with first component.", icon="📂")
                                                                    except Exception as e:
                                                                        st.error(f"Insert failed: {e}")
                                                            else:
                                                                # Create an empty category marker (zero-amount placeholder)
                                                                try:
                                                                    sb.table("advance_spends").insert({
                                                                        "advance_id": adv_id,
                                                                        "item_name": f"[{new_cat_name.strip()}] (Category created)",
                                                                        "amount_spent": 0.0
                                                                    }).execute()
                                                                    st.session_state[add_cat_key] = False
                                                                    confirm_and_rerun(f"Category '{new_cat_name.strip()}' created. Add components inside it.", icon="📂")
                                                                except Exception as e:
                                                                    st.error(f"Insert failed: {e}")
                                                        else:
                                                            st.error("Please enter a category name.")

                                            # --- Add standalone Component form ---
                                            if st.session_state.get(add_comp_key, False):
                                                with st.form(f"form_new_comp_{adv_id}", clear_on_submit=True):
                                                    st.markdown("🧾 **Add Standalone Component** *(no category)*")
                                                    sc1, sc2 = st.columns(2)
                                                    comp_desc = sc1.text_input("Description*", placeholder="e.g. Miscellaneous, Parking", key=f"comp_desc_{adv_id}")
                                                    comp_amt = sc2.number_input("Amount (PKR)*", value=None, min_value=0.0, step=100.0, key=f"comp_amt_{adv_id}")
                                                    if st.form_submit_button("➕ Add Component", type="primary", use_container_width=True):
                                                        if comp_desc.strip() and comp_amt is not None and comp_amt > 0:
                                                            if comp_amt > remaining + 0.001:
                                                                st.error(f"Exceeds remaining balance of PKR {remaining:,.0f}.")
                                                            else:
                                                                try:
                                                                    sb.table("advance_spends").insert({
                                                                        "advance_id": adv_id,
                                                                        "item_name": comp_desc.strip(),
                                                                        "amount_spent": float(comp_amt)
                                                                    }).execute()
                                                                    st.session_state[add_comp_key] = False
                                                                    confirm_and_rerun(f"Logged standalone spend '{comp_desc.strip()}'.", icon="🧾")
                                                                except Exception as e:
                                                                    st.error(f"Insert failed: {e}")
                                                        else:
                                                            st.error("Enter a valid description and non-zero amount.")

                    with t1: render_simple_form_tab(inc_data, "income", "Income", has_nature=True)
                    with t2: render_simple_form_tab(loan_data, "loan", "Loan", has_nature=False)
                    with t3:
                        render_advances_tab(pid)

                        a_all_adv = tables["advances"]
                        adv_rows = a_all_adv[a_all_adv["project_id"] == pid].sort_values("person_name") if not a_all_adv.empty else pd.DataFrame()
                        advance_usernames = sorted(list(set(
                            get_users_by_role("Accountant") + 
                            get_users_by_role("Quotation Sender") + 
                            get_users_by_role("Lead Generator") + 
                            get_users_by_role("Advance")
                        )))
                        if not advance_usernames:
                            all_u = get_all_users_summary()
                            advance_usernames = all_u["username"].tolist() if not all_u.empty else []

                        if role in ("CEO", "Accountant"):
                            st.write("---")
                            with st.expander("➕ Allocate New Staff Advance", expanded=adv_rows.empty):
                                if not advance_usernames:
                                    st.warning("⚠️ No users with the 'Advance' role exist in database registry settings yet.")
                                else:
                                    with st.form(f"global_allocate_advance_{pid}", clear_on_submit=True):
                                        new_person = st.selectbox("Select Target Advance Field Worker", advance_usernames)
                                        new_alloc = st.number_input("Initial Allocation Amount (PKR)", value=None, min_value=0.0, step=1000.0, placeholder="Allocation Amount (PKR)", key=f"new_alloc_adv_{pid}")
                                        
                                        if st.form_submit_button("➕ Provision Advanced Balance Outflow", use_container_width=True):
                                            if new_person and new_alloc is not None and new_alloc > 0:
                                                try:
                                                    sb.table("advances").insert({
                                                        "project_id": pid,
                                                        "person_name": new_person,
                                                        "allocated_amount": float(new_alloc)
                                                    }).execute()
                                                    confirm_and_rerun(f"💳 Advanced PKR {new_alloc:,.0f} allocated to {new_person}.", icon="✅")
                                                except Exception as e:
                                                    st.error(f"Database insertion failed: {e}")
                                            else:
                                                st.error("Please assign a valid numerical allowance metric.")

    if not is_read_only:
        with st.expander("➕ Add New Company Entity", expanded=False):
            with st.form("add_company_form", clear_on_submit=True):
                row1_1, row1_2 = st.columns(2)
                c_name = row1_1.text_input("Company Name", key="new_c_name")
                c_site = row1_2.text_input("Location / Site", key="new_c_site")
                if st.form_submit_button("Save Company Entity", type="primary", use_container_width=True):
                    if c_name.strip():
                        try:
                            sb.table("companies").insert({"name": c_name.strip(), "site": c_site.strip() or None, "description": EXEC_TAG}).execute()
                            confirm_and_rerun(f"💼 Company '{c_name.strip()}' created successfully.", icon="🏢")
                        except Exception as e:
                            st.error(f"Cannot save company: {e}")

# ==============================================================================
# VIEW C: PURCHASE WORKFLOW
# ==============================================================================

elif menu == "🛒 Purchase":
    if role in ("Advance", "Lead Generator"):
        st.error("🔒 Unauthorized: Access is restricted.")
        st.stop()
        
    st.title("🛒 Purchase Expenses & Procurement Portal")

    tables = fetch_all_table_data()
    q_df = tables.get("quotations", pd.DataFrame())
    if not q_df.empty:
        q_df = q_df[q_df["status"] == "Successful"]
    comp_all_df = tables.get("components", pd.DataFrame())
    render_purchase_procurement_section(role, current_user, q_df, comp_all_df)

# ==============================================================================
# VIEW C2: VOUCHER WORKFLOW
# ==============================================================================

elif menu == "🎫 Voucher":
    st.title("🎫 Voucher Requests & Log")

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
<span style="font-weight: 800; color: {amount_color}; font-size: 1.05rem;">PKR {v_row['amount']:,.0f}</span>
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

    if role in ("CEO", "Accountant"):
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
            else:
                H_PAGE = 25
                h_total_pages = max(1, (len(h_v) + H_PAGE - 1) // H_PAGE)
                h_page = st.number_input("History Page", min_value=1, max_value=h_total_pages, value=1, key="v_hist_page") if h_total_pages > 1 else 1
                h_start = (h_page - 1) * H_PAGE
                h_slice = h_v.iloc[h_start:h_start + H_PAGE]
                for idx, r in h_slice.iterrows():
                    st.markdown(draw_voucher_ui_node(r, idx), unsafe_allow_html=True)

    else:
        companies_df = get_all_companies(include_execution_created=False)
        if not companies_df.empty:
            if "show_new_voucher_form" not in st.session_state:
                st.session_state["show_new_voucher_form"] = False
            
            if st.button("➕ Add New Voucher Request", type="primary" if not st.session_state["show_new_voucher_form"] else "secondary", use_container_width=True):
                st.session_state["show_new_voucher_form"] = not st.session_state["show_new_voucher_form"]
                st.rerun()

            if st.session_state["show_new_voucher_form"]:
                v_filter_row = st.columns(2)
                target_company = v_filter_row[0].selectbox("Associated Company Entity", companies_df["name"])
                target_co_id = int(companies_df[companies_df["name"] == target_company].iloc[0]["id"])

                projects_df = get_projects_names(target_co_id, include_execution_created=False)
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
                    v_amt_val = float(st.session_state["v_form_amount"]) if st.session_state.get("v_form_amount") else None
                    st.session_state["v_form_title"] = v_row2_c1.text_input("Voucher Title*", value=st.session_state["v_form_title"])
                    st.session_state["v_form_amount"] = v_row2_c2.number_input("Requested Payout Amount (PKR)*", value=v_amt_val, min_value=0.0, step=10.0, placeholder="Requested Amount (PKR)")

                    v_row3_c1, v_row3_c2 = st.columns(2)
                    st.session_state["v_form_type"] = v_row3_c1.text_input("Type / Department (Optional)", value=st.session_state["v_form_type"])
                    st.session_state["v_form_remarks"] = st.text_area("Remarks (Optional)", value=st.session_state["v_form_remarks"], height=45)
                    
                    if st.form_submit_button("File Voucher Entry", type="primary", use_container_width=True):
                        if st.session_state["v_form_title"].strip() and st.session_state["v_form_amount"] is not None and st.session_state["v_form_amount"] > 0:
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
                            st.session_state["show_new_voucher_form"] = False
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
            can_edit = (role in ("CEO", "Accountant") or r["created_by"] == current_user["username"]) and (str(r["status"]) in ("Pending", "To Be Discussed"))
            if can_edit:
                eb1, eb2 = st.columns(2)
                edit_key = f"edit_voucher_{int(r['id'])}"
                if eb1.button("✏️ Edit Request", key=f"btn_{edit_key}", use_container_width=True):
                    st.session_state[edit_key] = not st.session_state.get(edit_key, False)
                    st.rerun()
                if eb2.button("🗑️ Delete Request", key=f"del_voucher_{int(r['id'])}", use_container_width=True):
                    try:
                        sb.table("vouchers").delete().eq("id", int(r['id'])).execute()
                        confirm_warn_and_rerun(f"Deleted voucher request '{r['title']}'.", icon="🗑️")
                    except Exception as e:
                        st.error(f"Cannot delete voucher: {e}")

                if st.session_state.get(edit_key, False):
                    with st.form(f"form_{edit_key}"):
                        ve1, ve2, ve3 = st.columns([2, 1.5, 1.5])
                        ve_title = ve1.text_input("Voucher Title*", value=r["title"])
                        ve_amount = ve2.number_input("Requested Payout Amount (PKR)*", min_value=0.0, step=10.0, value=float(r["amount"]))
                        v_dt_val = _safe_date(r.get("created_at"))
                        ve_date = ve3.date_input("Voucher Date", value=v_dt_val)
                        ve_remarks = st.text_area("Remarks", value=r["remarks"] if not pd.isna(r["remarks"]) else "", height=45)
                        vs1, vs2 = st.columns(2)
                        save_v = vs1.form_submit_button("💾 Save Changes", type="primary", use_container_width=True)
                        cancel_v = vs2.form_submit_button("✖️ Cancel", use_container_width=True)
                        if save_v:
                            if ve_title.strip() and ve_amount > 0:
                                sb.table("vouchers").update({
                                    "title": ve_title.strip(),
                                    "amount": float(ve_amount),
                                    "remarks": ve_remarks.strip() or None,
                                    "created_at": str(ve_date)
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

elif menu == "⚙️ Settings" and role in ("CEO", "Accountant"):
    st.title("⚙️ Workspace Configurations")

    st_tabs = st.tabs(["➕ Add User Workspace", "🛠️ Manage Existing Users Structure"])

    with st_tabs[0]:
        with st.form("create_acct", clear_on_submit=True):
            st.markdown("**Add New Account Credentials**")
            acct_id = st.text_input("Username / ID", key="new_user_acct_id")
            acct_pw = st.text_input("Password", type="password", key="new_user_acct_pw")
            acct_roles = st.multiselect("Assign System Roles", ["CEO", "Accountant", "Quotation Sender", "Lead Generator"], default=["Quotation Sender"])

            if st.form_submit_button("Create Account", type="primary"):
                if not acct_roles:
                    st.error("Please assign at least one system role.")
                elif acct_id.strip() and acct_pw.strip():
                    try:
                        dash_flag = any(r in ["Accountant", "CEO"] for r in acct_roles)
                        role_str = ", ".join(acct_roles)
                        sb.table("users").insert({
                            "username": acct_id.strip(), "password": acct_pw.strip(),
                            "role": role_str, "can_view_dashboard": dash_flag
                        }).execute()
                        confirm_and_rerun(f"👤 Account '{acct_id.strip()}' created as {role_str}.", icon="🔑")
                    except Exception as e:
                        if "users_role_check" in str(e) or "23514" in str(e):
                            st.error("⚠️ **Database Constraint Error**: Supabase table `users` check constraint prevents multi-roles.")
                            st.code("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;\nALTER TABLE users ALTER COLUMN role TYPE VARCHAR(255);", language="sql")
                        else:
                            st.error(f"Cannot provision user: {e}")
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
                role_options = ["CEO", "Accountant", "Quotation Sender", "Lead Generator"]

                # Parse current roles for default values
                current_roles = [r.strip() for r in current_target_role.split(",")] if current_target_role else []
                default_roles = [r for r in current_roles if r in role_options]

                new_assigned_roles = st.multiselect("Select New Workspace Roles", role_options, default=default_roles)

                if st.form_submit_button("Save New Role Matrix"):
                    if not new_assigned_roles:
                        st.error("Please assign at least one system role.")
                    else:
                        try:
                            dash_flag = any(r in ["Accountant", "CEO"] for r in new_assigned_roles)
                            role_str = ", ".join(new_assigned_roles)
                            sb.table("users").update({
                                "role": role_str, "can_view_dashboard": dash_flag
                            }).eq("id", target_user_id).execute()
                            confirm_and_rerun(f"🛡️ Role updated for '{selected_username}' to {role_str}.", icon="🔄")
                        except Exception as e:
                            if "users_role_check" in str(e) or "23514" in str(e):
                                st.error("⚠️ **Database Constraint Error**: Supabase table `users` check constraint prevents multi-roles. Please run the SQL command below in your Supabase SQL Editor.")
                                st.code("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;\nALTER TABLE users ALTER COLUMN role TYPE VARCHAR(255);", language="sql")
                            else:
                                st.error(f"Cannot update role: {e}")
            
            # --- FORM 2: PASSWORD OVERWRITE ---
            with st.form(f"change_pass_form_{target_user_id}", clear_on_submit=True):
                st.markdown("🔒 **Administrative Security Key Reset**")
                new_pass = st.text_input("Assign New Security Key / Password", type="password", key=f"reset_pw_{target_user_id}")

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
# ==============================================================================
# VIEW F: QUOTATIONS PORTAL (WITH LEAD GENERATOR ALLOTMENT & ANALYTICS)
# ==============================================================================

elif menu == "📋 Quotation & Planning":
    if role == "Advance":
        st.error("🔒 Unauthorized: Access restricted.")
        st.stop()

    st.title("📋 Quotation & Planning Portal")

    if role == "CEO":
        st.caption("👁️ Executive Observer Mode")

    tables = fetch_all_table_data()
    q_df = tables.get("quotations", pd.DataFrame())
    
    # Lead generator only sees their own leads
    if role == "Lead Generator":
        q_df = q_df[q_df["lead_generator"] == current_user["username"]] if not q_df.empty else pd.DataFrame()
        
    comp_all_df = tables.get("components", pd.DataFrame())
    comp_df = get_all_companies(include_execution_created=False)

    # Fetch registered system users
    try:
        all_users_df = get_all_users_summary()
        registered_users = all_users_df["username"].tolist() if not all_users_df.empty else []
    except Exception:
        registered_users = []

    lead_gen_users = get_users_by_role("Lead Generator")
    existing_lgs = sorted(list(set(q_df["lead_generator"].dropna().astype(str).str.strip().unique()) - {"", "None", "nan"})) if not q_df.empty else []
    lg_options = sorted(list(set(lead_gen_users + existing_lgs)))

    if "q_form_company" not in st.session_state: st.session_state["q_form_company"] = ""
    if "q_form_project" not in st.session_state: st.session_state["q_form_project"] = ""
    if "q_form_num" not in st.session_state: st.session_state["q_form_num"] = ""
    if "q_form_amount" not in st.session_state: st.session_state["q_form_amount"] = 0.0
    if "q_form_notes" not in st.session_state: st.session_state["q_form_notes"] = ""
    if "q_form_has_error" not in st.session_state: st.session_state["q_form_has_error"] = False

    if role == "Quotation Sender":
        q_tabs = st.tabs(["📜 Quotation Directory", "⏰ Nearing Expiry & Pending Follow-Ups"])
        q_tab1 = q_tabs[0]
        q_tab2 = None
        q_tab3 = q_tabs[1]
    else:
        q_tabs = st.tabs(["📜 Quotation Directory", "📑 Initial Planning & Justification Tab", "⏰ Nearing Expiry & Pending Follow-Ups"])
        q_tab1 = q_tabs[0]
        q_tab2 = q_tabs[1]
        q_tab3 = q_tabs[2]

    with q_tab1:
        # Expiring Quotation Reminders (> 14 days pending)
        if not q_df.empty:
            q_df_check = q_df.copy()
            q_df_check["created_at_dt"] = pd.to_datetime(q_df_check["created_at"]).dt.date
            today_dt = datetime.date.today()
            expiring_q = q_df_check[(q_df_check["status"] == "Sent") & (q_df_check["created_at_dt"] <= (today_dt - datetime.timedelta(days=14)))]
            if not expiring_q.empty:
                st.warning(f"⏰ **Expiring Quotation Reminder**: {len(expiring_q)} pending quotation(s) sent over 14 days ago require review or follow-up!")
                with st.expander("🔔 View Expiring Quotations List", expanded=False):
                    for _, ex_q in expiring_q.iterrows():
                        st.markdown(f"• **{ex_q['quotation_number']}** — {ex_q['company_name']} ({ex_q['project_name']}) | PKR {_safe_float(ex_q['amount']):,.0f} | Sent on {ex_q['created_at']}")

        total_q = len(q_df) if not q_df.empty else 0

        if role != "CEO":
            has_error = st.session_state.get("q_form_has_error", False)
            with st.expander("➕ Add New Quotation", expanded=has_error):
                comp_mode = st.radio("Company Type", ["Existing Company", "New Company"], horizontal=True, key="q_comp_type_radio")
                
                with st.form("add_new_quotation_form", clear_on_submit=False):
                    st.markdown("#### Add New Quotation")
                    
                    col_a, col_b = st.columns(2)
                    with col_a:
                        company_opts = comp_df["name"].tolist() if not comp_df.empty else []
                        if comp_mode == "Existing Company" and company_opts:
                            q_company = st.selectbox("Company Name", company_opts)
                        else:
                            q_company = st.text_input("New Company Name", value=st.session_state.get("q_form_company", ""), placeholder="e.g. Apex Holdings")

                        q_project = st.text_input("Quotation Project Name", value=st.session_state.get("q_form_project", ""), placeholder="e.g. Solar Power Installation Phase 1")
                        
                        next_num = st.session_state.get("q_form_num", "") or f"QT-2026-{(total_q + 1):03d}"
                        q_num = st.text_input("Quotation Reference Number", value=next_num)

                    with col_b:
                        q_amt_default = float(st.session_state.get("q_form_amount", 0.0))
                        q_amt_val = q_amt_default if q_amt_default > 0 else None
                        q_amount = st.number_input("Quotation Amount (PKR)", value=q_amt_val, min_value=0.0, step=5000.0, format="%.0f", placeholder="Enter Quotation Amount (PKR)")
                        q_status = "Sent"
                        qd_c1, qd_c2 = st.columns(2)
                        q_date = qd_c1.date_input("Date Sent", value=datetime.date.today())
                        q_validity_date = qd_c2.date_input("Validity / Expiry Date", value=datetime.date.today() + datetime.timedelta(days=30))
                        
                        # Lead Generator Allotment
                        if role == "Quotation Sender":
                            q_lead_gen = current_user["username"]
                        else:
                            st.markdown("**👤 Allot Lead Generator**")
                            lg_select_opts = ["-- Select Lead Generator --"] + lg_options
                            selected_lg_option = st.selectbox("Lead Generator Assignment", lg_select_opts, key="q_add_lg_selectbox")
                            if selected_lg_option != "-- Select Lead Generator --":
                                q_lead_gen = selected_lg_option
                            else:
                                q_lead_gen = ""

                        q_notes = st.text_area("Scope / Remarks", value=st.session_state.get("q_form_notes", ""), placeholder="Key deliverables or conditions...", height=40)

                    if st.form_submit_button("➕ Add Quotation", type="primary"):
                        company_final = q_company.strip() if q_company else ""
                        project_final = q_project.strip() if q_project else ""

                        st.session_state["q_form_company"] = company_final
                        st.session_state["q_form_project"] = project_final
                        st.session_state["q_form_num"] = q_num.strip()
                        st.session_state["q_form_amount"] = float(q_amount) if q_amount is not None else 0.0
                        st.session_state["q_form_notes"] = q_notes.strip()

                        if not company_final or not project_final:
                            st.session_state["q_form_has_error"] = True
                            st.error("Company Name and Quotation Project Name are mandatory.")
                        elif q_amount is None or q_amount <= 0:
                            st.session_state["q_form_has_error"] = True
                            st.error("Quotation Amount must be greater than 0.")
                        else:
                            try:
                                sb.table("quotations").insert({
                                    "company_name": company_final,
                                    "project_name": project_final,
                                    "quotation_number": q_num.strip() or next_num,
                                    "amount": float(q_amount),
                                    "status": q_status,
                                    "lead_generator": q_lead_gen.strip() or None,
                                    "created_by": current_user["username"],
                                    "notes": q_notes.strip() or None,
                                    "created_at": str(q_date)
                                }).execute()
                                
                                if q_status == "Successful":
                                    auto_provision_project(company_final, project_final)

                                st.session_state["q_form_company"] = ""
                                st.session_state["q_form_project"] = ""
                                st.session_state["q_form_num"] = ""
                                st.session_state["q_form_amount"] = 0.0
                                st.session_state["q_form_notes"] = ""
                                st.session_state["q_form_has_error"] = False

                                confirm_and_rerun(f"📋 Quotation '{q_num}' added successfully!", icon="✅")
                            except Exception as e:
                                st.session_state["q_form_has_error"] = True
                                st.error(f"Could not save quotation: {e}\n\n*Your typed details have been safely retained above.*")

        st.markdown("### Quotations")
        
        # Search bar alongside Lead Generator drop down
        if role == "Lead Generator":
            search_query = ""
            lg_filter = current_user["username"]
            status_filter = "All Statuses"
            q_date_filter = "All Time"
            custom_date_target = None
        else:
            filter_c1, filter_c2, filter_c3, filter_c4 = st.columns([1.5, 1.2, 1.0, 1.0])
            with filter_c1:
                search_query = st.text_input("🔍 Search Bar", placeholder="Search Company, Project, Ref #, or Lead Gen...", key="q_main_search_bar")
            with filter_c2:
                lg_filter = st.selectbox("👤 Lead Generator Scope", ["All Lead Generators"] + lg_options, key="q_lg_scope_dropdown")
            with filter_c3:
                status_filter = st.selectbox("Filter Status", ["All Statuses", "Sent (Only Sent)", "Successful (Approved)", "Declined"])
            with filter_c4:
                q_date_filter = st.selectbox("Date Scope", ["All Time", "Today", "This Month", "Last 30 Days", "Custom Date"])

            custom_date_target = None
            if q_date_filter == "Custom Date":
                c_date_col1, _ = st.columns([2.0, 8.0])
                custom_date_target = c_date_col1.date_input("Pinpoint Selected Date", value=datetime.date.today(), key="q_custom_date_pinpoint")

        # Display how much each / selected Lead Generator has brought
        if lg_filter != "All Lead Generators":
            lg_df = q_df[q_df["lead_generator"] == lg_filter] if not q_df.empty else pd.DataFrame()
            lg_count = len(lg_df)
            lg_total_val = lg_df["amount"].apply(_safe_float).sum() if not lg_df.empty else 0.0
            lg_won_val = lg_df[lg_df["status"] == "Successful"]["amount"].apply(_safe_float).sum() if not lg_df.empty else 0.0
            
            st.caption(f"👤 **{lg_filter}**: {lg_count} quotations | Total: PKR {lg_total_val:,.0f} | Won: PKR {lg_won_val:,.0f}")
        else:
            tot_count = len(q_df) if not q_df.empty else 0
            tot_val = q_df["amount"].apply(_safe_float).sum() if not q_df.empty else 0.0
            tot_won = q_df[q_df["status"] == "Successful"]["amount"].apply(_safe_float).sum() if not q_df.empty else 0.0
            
            st.caption(f"📈 **Total Overview across all Lead Generators**: {tot_count} Quotations lodged | Total Value: PKR {tot_val:,.0f} | Approved Value: PKR {tot_won:,.0f}")

        if q_date_filter == "Custom Date" and custom_date_target:
            date_q_df = q_df.copy() if not q_df.empty else pd.DataFrame()
            if not date_q_df.empty:
                date_q_df["created_at_dt"] = pd.to_datetime(date_q_df["created_at"]).dt.date
                date_q_df = date_q_df[date_q_df["created_at_dt"] == custom_date_target]
            day_count = len(date_q_df)
            day_val = date_q_df["amount"].apply(_safe_float).sum() if not date_q_df.empty else 0.0
            st.info(f"📅 **On {custom_date_target}**: {day_count} quotations were sent totaling **PKR {day_val:,.0f}**")

        display_q_df = q_df.copy() if not q_df.empty else pd.DataFrame()
        
        if not display_q_df.empty:
            if lg_filter != "All Lead Generators":
                display_q_df = display_q_df[display_q_df["lead_generator"] == lg_filter]

            if status_filter == "Sent (Only Sent)":
                display_q_df = display_q_df[display_q_df["status"] == "Sent"]
            elif status_filter == "Successful (Approved)":
                display_q_df = display_q_df[display_q_df["status"] == "Successful"]
            elif status_filter == "Declined":
                display_q_df = display_q_df[display_q_df["status"] == "Declined"]

            if q_date_filter != "All Time":
                display_q_df["created_at_dt"] = pd.to_datetime(display_q_df["created_at"]).dt.date
                if q_date_filter == "Custom Date":
                    display_q_df = display_q_df[display_q_df["created_at_dt"] == custom_date_target]
                else:
                    q_today = datetime.date.today()
                    if q_date_filter == "Today":
                        q_limit = q_today
                    elif q_date_filter == "This Month":
                        q_limit = q_today.replace(day=1)
                    elif q_date_filter == "Last 30 Days":
                        q_limit = q_today - datetime.timedelta(days=30)
                    display_q_df = display_q_df[display_q_df["created_at_dt"] >= q_limit]

            if search_query.strip():
                sq = search_query.strip().lower()
                display_q_df = display_q_df[
                    display_q_df["company_name"].astype(str).str.lower().str.contains(sq) |
                    display_q_df["project_name"].astype(str).str.lower().str.contains(sq) |
                    display_q_df["quotation_number"].astype(str).str.lower().str.contains(sq) |
                    display_q_df["lead_generator"].astype(str).str.lower().str.contains(sq)
                ]

        if display_q_df.empty:
            st.caption("No quotations match selected filters.")
        else:
            # Pagination: show 20 items per page to avoid rendering hundreds of widget-heavy cards
            PAGE_SIZE = 20
            total_pages = max(1, (len(display_q_df) + PAGE_SIZE - 1) // PAGE_SIZE)
            q_page = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1, key="q_dir_page") if total_pages > 1 else 1
            page_start = (q_page - 1) * PAGE_SIZE
            page_slice = display_q_df.iloc[page_start:page_start + PAGE_SIZE]
            st.caption(f"Showing {page_start+1}–{min(page_start+PAGE_SIZE, len(display_q_df))} of {len(display_q_df)} quotations")

            for idx, q_row in page_slice.iterrows():
                q_id = int(q_row["id"])
                status_curr = str(q_row["status"])
                badge = "🟢 Successful" if status_curr == "Successful" else ("🟡 Only Sent" if status_curr == "Sent" else "🔴 Declined")
                lg_display = str(q_row["lead_generator"]) if q_row.get("lead_generator") and str(q_row["lead_generator"]).strip() not in ("None", "nan", "") else "Unassigned"
                
                with st.container():
                    st.markdown(f"""
                    <div class="compact-card">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <h4 style="margin: 0; color: #1f2937;">{q_row['quotation_number']} — {q_row['project_name']}</h4>
                                <p style="margin: 2px 0 0 0; font-size: 0.82rem; color: #4b5563;">🏢 <strong>{q_row['company_name']}</strong> | Date: {q_row['created_at']} | Created By: <code>{q_row['created_by']}</code> | 👤 <strong>Lead Generator: {lg_display}</strong></p>
                                {f'<p style="margin: 2px 0 0 0; font-size: 0.78rem; color: #6b7280;"><em>{q_row["notes"]}</em></p>' if q_row.get("notes") else ''}
                            </div>
                            <div style="text-align: right;">
                                <h3 style="margin: 0; color: #111111;">PKR {_safe_float(q_row['amount']):,.0f}</h3>
                                <span style="font-size: 0.78rem; font-weight: 600; color: #374151;">{badge}</span>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    if role != "CEO":
                        btn_col1, btn_col2, btn_col3, btn_col4 = st.columns([1.8, 1.8, 1.2, 1.2])
                        
                        if status_curr == "Sent":
                            with btn_col1:
                                if st.button(f"✅ Approve", key=f"approve_q_{q_id}", type="primary", use_container_width=True):
                                    try:
                                        sb.table("quotations").update({"status": "Successful"}).eq("id", q_id).execute()
                                        auto_provision_project(str(q_row['company_name']), str(q_row['project_name']))
                                        confirm_and_rerun(f"🎉 Quotation '{q_row['quotation_number']}' Approved!", icon="✅")
                                    except Exception as e:
                                        st.error(f"Error approving quotation: {e}")
 
                            with btn_col2:
                                if st.button(f"❌ Decline", key=f"decline_q_{q_id}", use_container_width=True):
                                    try:
                                        sb.table("quotations").update({"status": "Declined"}).eq("id", q_id).execute()
                                        confirm_warn_and_rerun(f"Quotation '{q_row['quotation_number']}' marked as Declined.", icon="⚠️")
                                    except Exception as e:
                                        st.error(f"Error declining quotation: {e}")
 
                        with btn_col3:
                            with st.popover("✏️ Edit", use_container_width=True):
                                with st.form(f"edit_q_form_{q_id}"):
                                    edit_company = st.text_input("Company Name", value=str(q_row["company_name"]))
                                    edit_proj = st.text_input("Project Name", value=str(q_row["project_name"]))
                                    edit_amt = st.number_input("Amount (PKR)", value=_safe_float(q_row["amount"]))
                                    
                                    if role == "Lead Generator":
                                        edit_lg_val = current_user["username"]
                                    else:
                                        edit_lg_select_opts = ["-- Keep Current: " + str(q_row.get("lead_generator") or "Unassigned") + " --"] + lg_options + ["➕ Assign New Lead Generator"]
                                        edit_lg_opt = st.selectbox("Lead Generator Credit", edit_lg_select_opts, key=f"edit_lg_select_{q_id}")
                                        if edit_lg_opt == "➕ Assign New Lead Generator":
                                            edit_lg_val = st.text_input("New Lead Generator Name", placeholder="e.g. Agent Jane", key=f"edit_lg_text_{q_id}")
                                        elif edit_lg_opt.startswith("-- Keep Current"):
                                            edit_lg_val = str(q_row.get("lead_generator") or "")
                                        else:
                                            edit_lg_val = edit_lg_opt
                                            
                                    edit_st = st.selectbox("Status", ["Sent", "Successful", "Declined"], index=["Sent", "Successful", "Declined"].index(status_curr) if status_curr in ["Sent", "Successful", "Declined"] else 0)
                                    q_dt_val = _safe_date(q_row.get("created_at"))
                                    edit_q_date = st.date_input("Date Sent", value=q_dt_val, key=f"edit_q_date_{q_id}")
                                    edit_notes = st.text_area("Notes", value=str(q_row["notes"] or ""))

                                    if st.form_submit_button("Save Changes"):
                                        sb.table("quotations").update({
                                            "company_name": edit_company.strip(),
                                            "project_name": edit_proj.strip(),
                                            "amount": float(edit_amt),
                                            "lead_generator": edit_lg_val.strip() or None,
                                            "status": edit_st,
                                            "created_at": str(edit_q_date),
                                            "notes": edit_notes.strip() or None
                                        }).eq("id", q_id).execute()
                                        if edit_st == "Successful":
                                            auto_provision_project(edit_company.strip(), edit_proj.strip())
                                        confirm_and_rerun(f"Updated quotation #{q_id}.", icon="💾")
 
                        with btn_col4:
                            if st.button("🗑️ Delete", key=f"del_q_{q_id}", use_container_width=True):
                                sb.table("quotations").delete().eq("id", q_id).execute()
                                confirm_warn_and_rerun(f"Deleted quotation #{q_id}.", icon="🗑️")

    if q_tab2:
        with q_tab2:
            render_planning_section(role, current_user, q_df, comp_all_df)

    if q_tab3:
        with q_tab3:
            st.markdown("##### ⏰ Nearing Expiry & Pending Follow-Ups Portal")
            if q_df.empty:
                st.caption("No quotations logged in database.")
            else:
                q_pending_df = q_df[q_df["status"] == "Sent"].copy()
                if q_pending_df.empty:
                    st.success("🎉 All pending quotations are cleared and up to date! No pending or expiring quotations.")
                else:
                    q_pending_df["sent_dt"] = pd.to_datetime(q_pending_df["created_at"]).dt.date
                    today_d = datetime.date.today()
                    q_pending_df["days_pending"] = q_pending_df["sent_dt"].apply(lambda d: (today_d - d).days if d else 0)
                    q_pending_df = q_pending_df.sort_values("days_pending", ascending=False)

                    st.info(f"📋 **{len(q_pending_df)} Pending Quotation(s)** awaiting decision/approval.")

                    for idx_exp, (_, ex_row) in enumerate(q_pending_df.iterrows(), start=1):
                        q_ex_id = int(ex_row["id"])
                        days_p = ex_row["days_pending"]
                        urgency_badge = f"<span style='color: #ef4444; font-weight: bold;'>⚠️ {days_p} Days Pending (Needs Immediate Follow-up)</span>" if days_p >= 14 else f"<span style='color: #f59e0b;'>⏳ {days_p} Days Pending</span>"

                        with st.container(border=True):
                            exp_c1, exp_c2, exp_c3 = st.columns([4, 2.5, 2])
                            exp_c1.markdown(f"**{ex_row['quotation_number']}** — **{ex_row['company_name']}** ({ex_row['project_name']})\n\n<small>Lead Gen: <strong>{ex_row.get('lead_generator') or 'Unassigned'}</strong> | Date Sent: {ex_row['created_at']}</small>", unsafe_allow_html=True)
                            exp_c2.markdown(f"**PKR {_safe_float(ex_row['amount']):,.0f}**<br/>{urgency_badge}", unsafe_allow_html=True)
                            
                            if role in ("CEO", "Accountant"):
                                ex_b1, ex_b2 = exp_c3.columns(2)
                                if ex_b1.button("✅ Approve", key=f"app_exp_{q_ex_id}", type="primary", use_container_width=True):
                                    sb.table("quotations").update({"status": "Successful"}).eq("id", q_ex_id).execute()
                                    auto_provision_project(str(ex_row['company_name']), str(ex_row['project_name']))
                                    confirm_and_rerun(f"🎉 Approved quotation '{ex_row['quotation_number']}'.", icon="✅")
                                if ex_b2.button("❌ Decline", key=f"dec_exp_{q_ex_id}", use_container_width=True):
                                    sb.table("quotations").update({"status": "Declined"}).eq("id", q_ex_id).execute()
                                    confirm_warn_and_rerun(f"Declined quotation '{ex_row['quotation_number']}'.", icon="❌")
