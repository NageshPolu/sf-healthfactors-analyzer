import os
import json
import re
import time
from pathlib import Path
import requests

# --------- Settings (safe allowlist) ----------
ALLOWED_FILES = [
    "app.py",
    "gates.py",
    "main.py",
    "requirements.txt",
    "README.md",
]
MAX_FILE_CHARS = 30_000  # keep prompts small
MAX_RETRIES = 5
# ---------------------------------------------


def pick_env(*names: str) -> str | None:
    for n in names:
        v = os.getenv(n)
        if v and v.strip():
            return v.strip()
    return None


def require_token(raw: str | None, name: str) -> str:
    if not raw or not raw.strip():
        raise RuntimeError(f"Missing {name}.")
    tok = raw.strip()
    # Guard: tokens must be single-line (newlines often come from pasted 'NAME=token' mistakes)
    if "\n" in tok or "\r" in tok:
        raise RuntimeError(
            f"{name} contains newlines. In GitHub Secrets, store ONLY the token value (no NAME=, no extra lines)."
        )
    return tok


def gh_api_get(url: str, token: str) -> dict:
    r = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def extract_json(text: str) -> dict:
    """Extract the first JSON object from model output."""
    try:
        return json.loads(text)
    except Exception:
        pass

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
            continue
        if content is None or not isinstance(content, str):
            continue

        Path(path).write_text(content, encoding="utf-8")
        touched.append(path)
    return touched


def sanity_check_python(files: list[str]) -> None:
    import py_compile
    for f in files:
        if f.endswith(".py"):
            py_compile.compile(f, doraise=True)


def call_github_models(token: str, model: str, system: str, user_payload: dict) -> str:
    """
    Calls GitHub Models (OpenAI-compatible chat completions endpoint hosted by GitHub).
    Uses GITHUB_TOKEN for auth.
    """
    url = os.getenv("GITHUB_MODELS_URL") or "https://models.github.ai/inference/chat/completions"

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_payload)},
        ],
        "temperature": 0.2,
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=120)
            # Retry on transient failures
            if r.status_code in (429, 500, 502, 503, 504):
                last_err = RuntimeError(f"GitHub Models HTTP {r.status_code}: {r.text[:500]}")
                time.sleep(min(2 ** attempt, 20))
                continue

            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            last_err = e
            time.sleep(min(2 ** attempt, 20))

    raise RuntimeError(f"GitHub Models request failed after {MAX_RETRIES} retries: {last_err}")


def load_issue_context(gh_token: str) -> tuple[str, int, str, str, str]:
    """
    Returns: repo, issue_number, title, body, html_url
    Uses env vars if present, otherwise falls back to the GitHub event payload.
    """
    repo = pick_env("REPO", "GITHUB_REPOSITORY")
    if not repo:
        raise RuntimeError("Missing REPO/GITHUB_REPOSITORY.")

    issue_number = pick_env("ISSUE_NUMBER")
    title = os.getenv("ISSUE_TITLE") or ""
    body = os.getenv("ISSUE_BODY") or ""
    html_url = os.getenv("ISSUE_URL") or ""

    # If missing, read from event payload
    if not issue_number or not title:
        event_path = os.getenv("GITHUB_EVENT_PATH")
        if event_path and Path(event_path).exists():
            payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
            issue = payload.get("issue") or {}
            issue_number = issue_number or str(issue.get("number") or "")
            title = title or (issue.get("title") or "")
            body = body or (issue.get("body") or "")
            html_url = html_url or (issue.get("html_url") or "")

    if not issue_number:
        raise RuntimeError("Missing ISSUE_NUMBER (not found in env or event payload).")

    # Also fetch full issue from API to be safe/consistent
    issue = gh_api_get(f"https://api.github.com/repos/{repo}/issues/{int(issue_number)}", gh_token)
    title = issue.get("title", title) or ""
    body = (issue.get("body", body) or "")
    html_url = issue.get("html_url", html_url) or ""

    return repo, int(issue_number), title, body, html_url


def main():
    # Use GitHub's built-in token from workflow env
    gh_token = require_token(pick_env("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_AUTH_TOKEN"), "GITHUB_TOKEN")

    # GitHub Models model name (set in workflow env; default ok)
    model = os.getenv("GITHUB_MODELS_MODEL") or "openai/gpt-4.1"

    repo, issue_number, title, body, html_url = load_issue_context(gh_token)
    repo_files = read_repo_files()

    system = (
        "You are a senior Python engineer.\n"
        "Task: Update the repository code based on the GitHub issue request.\n"
        "Rules:\n"
        f"1) Only modify files in this allowlist: {', '.join(ALLOWED_FILES)}\n"
        "2) Return STRICT JSON only.\n"
        '3) JSON format: { "changes":[{"path":"app.py","content":"..."}], "notes":"short summary" }\n'
        "4) Do NOT include secrets, keys, tokens, or credentials.\n"
        "5) Keep changes minimal and working.\n"
    )

    user_payload = {
        "issue_title": title,
        "issue_body": body,
        "issue_url": html_url,
        "repo": repo,
        "issue_number": issue_number,
        "repo_files": repo_files,
    }

    out_text = call_github_models(gh_token, model, system, user_payload)
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
