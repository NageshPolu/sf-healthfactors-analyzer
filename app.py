import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

st.set_page_config(page_title="SF Live Risk Analyzer", layout="wide")
st.title("SF Live Risk Analyzer (SFTP CSV → Blast Radius)")

st.caption("Upload the latest Integration Center CSV you see in the SFTP folder.")

uploaded = st.file_uploader("Upload Integration Center CSV", type=["csv"])

# ---------- Helpers ----------
def pick_col(cols, candidates):
    cols_l = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand.lower() in cols_l:
            return cols_l[cand.lower()]
    # fuzzy contains
    for c in cols:
        cl = c.lower()
        for cand in candidates:
            if cand.lower() in cl:
                return c
    return None

SENSITIVE_KEYWORDS = {
    "compensation": 5,
    "pay": 5,
    "salary": 5,
    "bank": 5,
    "national": 5,
    "ssn": 5,
    "personal": 4,
    "admin": 4,
    "proxy": 3,
    "permission": 3,
}

def calc_sensitivity(series):
    if series is None:
        return 0
    score = 0
    for val in series.dropna().astype(str).unique().tolist()[:500]:
        v = val.lower()
        for k, w in SENSITIVE_KEYWORDS.items():
            if k in v:
                score += w
    return min(score, 10)

def generate_pdf_bytes(title, risk_score, summary_lines, top_roles_df):
    styles = getSampleStyleSheet()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    story = []

    story.append(Paragraph(f"<b>{title}</b>", styles["Title"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"<b>Date:</b> {datetime.now().strftime('%d %b %Y %H:%M')}", styles["Normal"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph(f"<b>Go-Live Risk Score:</b> {risk_score} / 100", styles["Heading2"]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>Key Findings</b>", styles["Heading3"]))
    for line in summary_lines:
        story.append(Paragraph(f"- {line}", styles["Normal"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Top RBP Blast Radius Roles</b>", styles["Heading3"]))
    for _, r in top_roles_df.head(5).iterrows():
        story.append(Paragraph(
            f"- {r['role']} | users: {int(r['users'])} | sensitivity: {int(r['sensitivity'])}/10 | blast: {int(r['blast'])}",
            styles["Normal"]
        ))

    story.append(Spacer(1, 14))
    story.append(Paragraph(
        "<i>Generated from SuccessFactors Integration Center export. Read-only analysis. No employee personal data is required for this report.</i>",
        styles["Normal"]
    ))

    doc.build(story)
    pdf = buf.getvalue()
    buf.close()
    return pdf

# ---------- Main ----------
if not uploaded:
    st.info("Upload the CSV exported by your scheduled Integration Center job (downloaded from SFTP).")
    st.stop()

df = pd.read_csv(uploaded)
st.success(f"Loaded {len(df):,} rows, {len(df.columns)} columns")

with st.expander("Preview columns"):
    st.write(list(df.columns))
    st.dataframe(df.head(20), use_container_width=True)

# Try to detect columns (works across most exports)
role_col = pick_col(df.columns, ["role", "role name", "permission role", "permissionrole", "roleName"])
group_col = pick_col(df.columns, ["group", "permission group", "permissiongroup", "groupName"])
user_col  = pick_col(df.columns, ["user", "user id", "userid", "username", "person id", "personidexternal"])
perm_col  = pick_col(df.columns, ["permission", "permission name", "permissiontype", "permissionType", "permissionId"])

st.subheader("Detected mapping")
st.write({
    "role_col": role_col,
    "group_col": group_col,
    "user_col": user_col,
    "permission_col": perm_col
})

# Minimum requirement for blast radius: role + user (or group+user with role later)
if role_col is None:
    st.error("I couldn’t find a Role column in your CSV. In Integration Center, include Role Name/Role ID in the export.")
    st.stop()

if user_col is None and group_col is None:
    st.error("I couldn’t find a User or Group column. For blast radius we need at least User ID or Group membership exported.")
    st.stop()

# If we have role + user → direct users per role
if user_col is not None:
    role_users = df.groupby(role_col)[user_col].nunique().reset_index()
    role_users.columns = ["role", "users"]
else:
    # role + group only (no users) → can't compute blast radius; guide next
    st.warning("Your CSV has Role + Group but no Users. This can’t compute blast radius yet. Add User ID to the export.")
    st.stop()

# Sensitivity: if permission column exists, score by role
if perm_col is not None:
    sens = df.groupby(role_col)[perm_col].apply(calc_sensitivity).reset_index()
    sens.columns = ["role", "sensitivity"]
else:
    sens = pd.DataFrame({"role": role_users["role"], "sensitivity": 0})

out = role_users.merge(sens, on="role", how="left").fillna({"sensitivity": 0})

# Blast radius score (simple, defendable)
# Users drive impact; sensitivity drives severity
out["blast"] = (out["users"] * 1.5 + out["sensitivity"] * 10).clip(upper=100)

# Risk score (tenant snapshot) – simple and explainable
role_count = out["role"].nunique()
high_roles = (out["blast"] >= 70).sum()
risk_score = int(min(100, (role_count * 0.8) + (high_roles * 8)))

# Display
st.subheader("Top Blast Radius Roles")
st.dataframe(out.sort_values("blast", ascending=False).head(20), use_container_width=True)

c1, c2, c3 = st.columns(3)
c1.metric("Roles in export", f"{role_count}")
c2.metric("Critical roles (blast ≥ 70)", f"{high_roles}")
c3.metric("Go-Live Risk Score", f"{risk_score} / 100")

summary = [
    f"{high_roles} roles have CRITICAL blast radius (≥70). These are your Week-1 incident candidates.",
    "Freeze changes to CRITICAL roles before go-live; require 2-person approval for assignments.",
    "Validate sensitive permissions (comp/pay/personal/admin) for CRITICAL roles in UAT + security review."
]

# PDF
pdf_bytes = generate_pdf_bytes(
    title="SAP SuccessFactors Go-Live Health Check (RBP Blast Radius)",
    risk_score=risk_score,
    summary_lines=summary,
    top_roles_df=out.sort_values("blast", ascending=False)
)

st.download_button(
    "Download Executive PDF",
    data=pdf_bytes,
    file_name="SF_GoLive_HealthCheck_RBP_BlastRadius.pdf",
    mime="application/pdf"
)
