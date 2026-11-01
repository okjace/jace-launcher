"""Jace OS: sign in to Jace Social with the computer's Jace account.

Jace OS ships `jace-account`: `--json` says who's signed in (no token), and
`--token-for <client_id>` gets a Jace token for another Jace app through Jace's token
exchange (official apps only). Jace Social checks that token with Jace's
/api/oauth/introspect and makes a normal session (POST /api/v1/auth/jace/os).

Everything here fails quietly (returns None): no Jace OS, not signed in, no network,
exchange refused. The caller then uses the normal sign-in. Tokens are never logged.
"""
import json
import shutil
import subprocess
import sys

from jace.config import settings


def enabled() -> bool:
    """Jace OS sign-in can be tried here: Linux, jace-account installed, setting on."""
    return (sys.platform.startswith("linux") and settings.get("jace_os_signin") is not False
            and shutil.which("jace-account") is not None)


def _run(*args) -> dict | None:
    try:
        from jace.bedrock import _clean_env       # without our AppImage's library paths
        r = subprocess.run(["jace-account", *args], capture_output=True, text=True, timeout=30,
                           env=_clean_env(), stdin=subprocess.DEVNULL)
        data = json.loads(r.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return data if r.returncode == 0 and isinstance(data, dict) and "error" not in data else None


def signed_in() -> bool:
    if not enabled():
        return False
    info = _run("--json")
    return bool(info and info.get("signed_in"))


def token_for(client_id: str, scope: str = "profile email") -> str | None:
    """A Jace access token for client_id, or None."""
    if not client_id or not signed_in():
        return None
    data = _run("--token-for", client_id, "--scope", scope)
    tok = data.get("access_token") if data else None
    return tok if isinstance(tok, str) and tok else None
