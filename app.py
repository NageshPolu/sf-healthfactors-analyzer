import os
import json
import requests
import streamlit as st
from datetime import datetime, timezone
import pandas as pd
import io
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# -----------------------------
# HEALTHCHECK ENDPOINT (for FastAPI)
# -----------------------------
try:
    app = st._main._get_app()  # This will fail if not running in FastAPI context
except Exception:
    app = None

if app is None:
    try:
        app = FastAPI()
    except Exception:
        app = None

if app is not None:
    @app.get("/healthcheck")
    async def healthcheck():
        return JSONResponse(content={"status": "ok"})

# -----------------------------
# CONFIG
# -----------------------------
OWNER = st.secrets.get("GITHUB_OWNER", os.getenv("GITHUB_OWNER", "NageshPolu"))
FRONTEND_REPO = st.secrets.get("FRONTEND_REPO", os.getenv("FRONTEND_REPO", "sf-healthfactors-analyzer"))
BACKEND_REPO = st.secrets.get("BACKEND_REPO", os.getenv("BACKEND_REPO", "sf-ec-gates-backend"))
GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", os.getenv("GITHUB_TOKEN", ""))

# Your backend API endpoint (Render)
# If you already have a different endpoint, replace it here.
BACKEND_BASE = os.getenv("BACKEND_BASE", "https://sf-ec-gates-backend.onrender.com")
RUN_ENDPOINT = f"{BACKEND_BASE.rstrip('/')}/run"

# -----------------------------
# HELPERS
# -----------------------------
def gh_headers():
    if not GITHUB_TOKEN:
        return {}
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

def create_github_issue(repo: str, title: str, body: str, labels=None):
    labels = labels or []
    url = f"https://api.github.com/repos/{OWNER}/{repo}/issues"
    payload = {"title": title, "body": body, "labels": labels}
    r = requests.post(url, headers=gh_headers(), json=payload, timeout=30)

    # Helpful error message for noobs
    if r.status_code >= 300:
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text}
        raise RuntimeError(f"GitHub issue create failed ({r.status_code}): {data}")

    return r.json()

def safe_df(data):
    # Avoid importing pandas if not needed; Streamlit can render list[dict] directly.
    if isinstance(data, list) and data and isinstance(data[0], dict):
        st.dataframe(data, use_container_width=True)
    else:
        st.write(data)

def drilldown_block(title: str, rows, empty_msg: str):
    st.subheader(title)
    if not rows:
        st.info(empty_msg)
        return
    safe_df(rows)

def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()

# -----------------------------
# PAGE
# -----------------------------
st.set_page_config(page_title="SF EC Go-Live Gates", layout="wide")
st.title("SF EC Go-Live Gates (API-only)")

# -----------------------------
# SIDEBAR: AI UPDATE REQUEST
# -----------------------------
st.sidebar.header("🤖 AI Update Request (No-code)")

st.sidebar.caption(
    "Type what you want changed. This will create a GitHub Issue with label `ai-update`.\n"
    "A GitHub Action will pick it up and create a PR automatically."
)

target = st.sidebar.radio(
    "Where should the change happen?",
    ["Streamlit UI (frontend)", "Render API (backend)"],
    index=0,
)

repo_target = FRONTEND_REPO if target.startswith("Streamlit") else BACKEND_REPO

request_text = st.sidebar.text_area(
    "What do you want to add/change?",
    placeholder="Example: Add a new drilldown for inactive users, and add a CSV download button.",
    height=140,
)

extra_context = st.sidebar.text_area(
    "Optional extra context",
    placeholder="Example: Use endpoint /run; keep the UI minimal; don't show PII in PDF.",
    height=90,
)

if st.sidebar.button("Create GitHub Issue", type="primary", disabled=not request_text.strip()):
    if not GITHUB_TOKEN:
        st.sidebar.error("Missing GITHUB_TOKEN in Streamlit secrets. Add it in Streamlit → Settings → Secrets.")
    else:
        issue_title = f"AI update request: {request_text.strip()[:60]}"
        issue_body = (
            f"**Requested at (UTC):** {now_utc_iso()}\n\n"
            f"## Request\n{request_text.strip()}\n\n"
            f"## Extra context\n{extra_context.strip() or '(none)'}\n\n"
            f"## Notes\n"
            f"- Please keep responses safe (no secrets in logs).\n"
            f"- Prefer small PRs and explain what changed.\n"
        )
        try:
            issue = create_github_issue(
                repo=repo_target,
                title=issue_title,
                body=issue_body,
                labels=["ai-update"],
            )
            st.sidebar.success(f"Issue created in `{repo_target}` ✅")
            st.sidebar.markdown(f"[Open Issue]({issue.get('html_url')})")
        except Exception as e:
            st.sidebar.error(str(e))

st.sidebar.divider()
st.sidebar.caption("Live backend endpoint used:")
st.sidebar.code(RUN_ENDPOINT)

# -----------------------------
# MAIN: RUN DASHBOARD
# -----------------------------
st.info("Pulling a live snapshot from the backend API (Render)…")

colA, colB = st.columns([1, 1], gap="large")

run = st.button("Refresh snapshot")

if run or "snapshot" not in st.session_state:
    try:
        r = requests.post(RUN_ENDPOINT, json={}, timeout=120)
        # If backend returns text error, show it
        if r.status_code >= 300:
            st.error(f"Backend error {r.status_code}: {r.text}")
            st.stop()
        st.session_state.snapshot = r.json()
    except Exception as e:
        st.error(f"Failed to call backend: {e}")
        st.stop()

snap = st.session_state.snapshot

# Support both shapes:
# - backend returns {"metrics": {...}} or directly {...}
metrics = snap.get("metrics", snap)

snapshot_time = metrics.get("snapshot_time_utc") or metrics.get("snapshotTimeUtc") or "Unknown"
st.caption(f"Last snapshot (UTC): {snapshot_time}")

active_users = int(metrics.get("active_users", metrics.get("activeUsers", 0)) or 0)
missing_mgr_count = int(metrics.get("missing_manager_count", metrics.get("missingManagerCount", 0)) or 0)
missing_mgr_pct = metrics.get("missing_manager_pct", metrics.get("missingManagerPct", 0)) or 0
invalid_org_count = int(metrics.get("invalid_org_count", metrics.get("invalidOrgCount", 0)) or 0)
invalid_org_pct = metrics.get("invalid_org_pct", metrics.get("invalidOrgPct", 0)) or 0
risk_score = int(metrics.get("risk_score", metrics.get("riskScore", 0)) or 0)

# Email hygiene
missing_email_count = int(metrics.get("missing_email_count", metrics.get("missingEmailCount", 0)) or 0)
duplicate_email_count = int(metrics.get("duplicate_email_count", metrics.get("duplicateEmailCount", 0)) or 0)

# New: Inactive employee and contingent worker counts
inactive_employee_count = int(metrics.get("inactive_employee_count", metrics.get("inactiveEmployeeCount", 0)) or 0)
contingent_worker_count = int(metrics.get("contingent_worker_count", metrics.get("contingentWorkerCount", 0)) or 0)

# KPI row
k1, k2, k3, k4 = st.columns(4)
k1.metric("Active users", f"{active_users}")
k2.metric("Missing managers", f"{missing_mgr_count} ({missing_mgr_pct}%)")
k3.metric("Invalid org", f"{invalid_org_count} ({invalid_org_pct}%)")
k4.metric("Go-Live Risk Score", f"{risk_score} / 100")

# Email KPIs
e1, e2 = st.columns(2)
e1.metric("Missing emails", f"{missing_email_count}")
e2.metric("Duplicate emails", f"{duplicate_email_count}")

# New: Show inactive employee and contingent worker counts
c_inactive, c_contingent = st.columns(2)
c_inactive.metric("Inactive employees", f"{inactive_employee_count}")
c_contingent.metric("Contingent workers", f"{contingent_worker_count}")

st.header("Drilldowns")

# Org drilldowns
invalid_org_sample = metrics.get("invalid_org_sample") or metrics.get("invalidOrgSample") or []
missing_manager_sample = metrics.get("missing_manager_sample") or metrics.get("missingManagerSample") or []
org_missing_field_counts = metrics.get("org_missing_field_counts") or metrics.get("orgMissingFieldCounts") or {}

c1, c2 = st.columns(2)
with c1:
    drilldown_block(
        "Invalid Org — sample rows",
        invalid_org_sample,
        "No invalid-org sample returned (or count is 0).",
    )
with c2:
    drilldown_block(
        "Missing Manager — sample rows",
        missing_manager_sample,
        "No missing-manager sample returned (or count is 0).",
    )

st.subheader("Which org fields are missing most?")
if isinstance(org_missing_field_counts, dict) and org_missing_field_counts:
    # Convert to table-friendly list
    rows = [{"field": k, "missingCount": v} for k, v in org_missing_field_counts.items()]
    rows.sort(key=lambda x: x["missingCount"], reverse=True)
    st.dataframe(rows, use_container_width=True)
else:
    st.info("No org field stats returned.")

# Email drilldowns
st.subheader("Email hygiene — sample rows")

missing_email_sample = metrics.get("missing_email_sample") or metrics.get("missingEmailSample") or []
duplicate_email_sample = metrics.get("duplicate_email_sample") or metrics.get("duplicateEmailSample") or []

c3, c4 = st.columns(2)
with c3:
    drilldown_block(
        "Missing Email — sample rows",
        missing_email_sample,
        "No missing-email sample returned (or count is 0).",
    )
    # CSV download button for Missing Email sample
    if missing_email_sample:
        df_missing_email = pd.DataFrame(missing_email_sample)
        csv_buffer = io.StringIO()
        df_missing_email.to_csv(csv_buffer, index=False)
        st.download_button(
            label="Download Missing Email sample as CSV",
            data=csv_buffer.getvalue(),
            file_name="missing_email_sample.csv",
            mime="text/csv"
        )
with c4:
    drilldown_block(
        "Duplicate Email — sample rows",
        duplicate_email_sample,
        "No duplicate-email sample returned (or count is 0).",
    )

st.divider()
st.caption("Tip: Use the sidebar 🤖 box to request new metrics or UI changes without manually editing code.")
