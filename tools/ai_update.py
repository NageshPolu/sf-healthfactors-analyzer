import os
import json
import re
from pathlib import Path
import requests

# OpenAI Python SDK (official)
from openai import OpenAI


# --------- Settings (safe allowlist) ----------
ALLOWED_FILES = [
    "app.py",
    "gates.py",
    "main.py",
    "requirements.txt",
    "README.md",
]
MAX_FILE_CHARS = 30_000  # keep prompts small
# ---------------------------------------------


def pick_env(*names: str) -> str | None:
    for n in names:
        v = os.getenv(n)
        if v and v.strip():
            return v.strip()
    return None


def gh_api_get(url: str, token: str) -> dict:
    r = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def extract_json(text: str) -> dict:
    """
    Tries to extract the first JSON object from model output.
    """
    # First try direct parse
    try:
        return json.loads(text)
    except Exception:
        pass

    # Try to find a JSON object in the text
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in AI output.")
    return json.loads(m.group(0))


def read_repo_files() -> dict:
    repo_data = {}
    for rel in ALLOWED_FILES:
        p = Path(rel)
        if p.exists() and p.is_file():
            content = p.read_text(encoding="utf-8", errors="replace")
            if len(content) > MAX_FILE_CHARS:
                content = content[:MAX_FILE_CHARS] + "\n\n# [TRUNCATED]"
            repo_data[rel] = content
    return repo_data


def write_changes(changes: list[dict]) -> list[str]:
    touched = []
    for ch in changes:
        path = ch.get("path")
        content = ch.get("content")

        if not path or not isinstance(path, str):
            continue
        if path not in ALLOWED_FILES:
            # Safety: ignore anything outside allowlist
            continue
        if content is None or not isinstance(content, str):
            continue

        Path(path).write_text(content, encoding="utf-8")
        touched.append(path)
    return touched


def sanity_check_python(files: list[str]) -> None:
    # Minimal syntax check
    import py_compile
    for f in files:
        if f.endswith(".py"):
            py_compile.compile(f, doraise=True)


def main():
    repo = os.environ["REPO"]  # e.g. "NageshPolu/sf-healthfactors-analyzer"
    issue_number = int(os.environ["ISSUE_NUMBER"])

    gh_token = pick_env("GITHUB_TOKEN", "GH_TOKEN")
    if not gh_token:
        raise RuntimeError("Missing GITHUB_TOKEN (Actions provides this automatically).")

    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        raise RuntimeError("Missing OPENAI_API_KEY secret.")

    model = os.getenv("OPENAI_MODEL") or "gpt-4o-mini"  # if this errors, set OPENAI_MODEL in secrets

    issue = gh_api_get(f"https://api.github.com/repos/{repo}/issues/{issue_number}", gh_token)
    title = issue.get("title", "")
    body = issue.get("body", "") or ""

    repo_files = read_repo_files()

    system = (
        "You are a senior Python engineer.\n"
        "Task: Update the repository code based on the GitHub issue request.\n"
        "Rules:\n"
        "1) Only modify files in this allowlist: " + ", ".join(ALLOWED_FILES) + "\n"
        "2) Return STRICT JSON only.\n"
        "3) JSON format:\n"
        '{ "changes":[{"path":"app.py","content":"..."}], "notes":"short summary" }\n'
        "4) Do NOT include secrets or credentials.\n"
        "5) Keep changes minimal and working.\n"
    )

    user = {
        "issue_title": title,
        "issue_body": body,
        "repo_files": repo_files,
    }

    client = OpenAI(api_key=openai_key)

    # Responses API is the recommended interface (per OpenAI docs)
    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user)},
        ],
    )

    out_text = resp.output_text
    data = extract_json(out_text)

    changes = data.get("changes", [])
    if not isinstance(changes, list) or not changes:
        raise RuntimeError("AI returned no changes. Add more detail to the issue and retry.")

    touched = write_changes(changes)
    if not touched:
        raise RuntimeError("No allowed files were modified (maybe AI tried to edit disallowed paths).")

    sanity_check_python(touched)

    notes = data.get("notes", "")
    print(f"✅ Updated files: {touched}")
    if notes:
        print(f"Notes: {notes}")


if __name__ == "__main__":
    main()
