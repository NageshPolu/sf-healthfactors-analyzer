from urllib.parse import urlparse
import re

def normalize_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if not u.startswith("http://") and not u.startswith("https://"):
        u = "https://" + u
    u = u.rstrip("/")
    return u

def derive_sf_api_base(instance_url: str) -> str:
    """
    Best-effort SuccessFactors API host derivation.
    Examples:
      salesdemo2.successfactors.eu  -> https://apisalesdemo2.successfactors.eu
      https://salesdemo2.successfactors.eu -> https://apisalesdemo2.successfactors.eu
      https://apisalesdemo2.successfactors.eu -> https://apisalesdemo2.successfactors.eu
      https://performancemanager5.successfactors.com -> https://api5.successfactors.com (legacy pattern)
    """
    u = normalize_url(instance_url)
    if not u:
        return ""

    p = urlparse(u)
    host = p.netloc.lower()

    # If already an API host, keep it
    if host.startswith("api"):
        return f"{p.scheme}://{host}"

    # Legacy pattern: performancemanager5.successfactors.com -> api5.successfactors.com
    m = re.match(r"^performancemanager(\d+)\.successfactors\.com$", host)
    if m:
        return f"{p.scheme}://api{m.group(1)}.successfactors.com"

    # Common tenant pattern: <tenant>.successfactors.<tld> -> api<tenant>.successfactors.<tld>
    if ".successfactors." in host:
        parts = host.split(".")
        if parts and not parts[0].startswith("api"):
            parts[0] = "api" + parts[0]
            return f"{p.scheme}://{'.'.join(parts)}"

    # Fallback: use same host
    return f"{p.scheme}://{host}"
