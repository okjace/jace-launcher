"""Jace Social client: synced friends, chat and hosted worlds (server code in social/).

Sign-in works like joining a Minecraft server: the server hands out a one-time
id, we tell Mojang's session server we "joined" it with our Minecraft token, and
the server asks Mojang to confirm. Only the real account owner can do that, and
the Minecraft token never leaves this computer except to Mojang.

On Jace OS, with no Microsoft account selected (offline accounts can't be verified that
way), the computer's Jace account signs you in instead (jace/jaceos.py). Microsoft
accounts keep the Minecraft sign-in: a Jace sign-in could land on a different Jace
Social account than the one their Minecraft account uses.
"""
import time

from jace.accounts import accounts
from jace.config import DATA_DIR, read_json, settings, write_json
from jace.net import session

DEFAULT_URL = "https://jace-social.vercel.app"
SESSIONS_FILE = DATA_DIR / "social.json"
JACE_OS_KEY = "jace-os"            # social.json key of the Jace OS session (the others are Minecraft UUIDs)


class SocialError(Exception):
    pass


def base_url() -> str:
    return (settings.get("social_url") or DEFAULT_URL).rstrip("/")


def _sessions() -> dict:
    return read_json(SESSIONS_FILE, {})


def _key() -> str | None:
    """Which saved session belongs to what's selected: the Minecraft account's, or Jace OS's."""
    acc = accounts.current()
    if acc and acc.get("type") == "msa":
        return acc["uuid"]
    from jace import jaceos
    return JACE_OS_KEY if jaceos.enabled() else None


def current_session() -> dict | None:
    """Saved Jace Social session for the selected Minecraft account (or Jace OS), if any."""
    key = _key()
    s = _sessions().get(key) if key else None
    if s and s.get("expires_at", "") > time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()):
        return s
    return None


def _why_not() -> str | None:
    acc = accounts.current()
    if not acc:
        return "Add a Microsoft account to use friends and chat."
    if acc.get("type") != "msa":
        return "Friends and chat need a Microsoft account (offline accounts can't be verified)."
    return None


def can_sign_in() -> str | None:
    """None if Jace Social can be signed in to (Microsoft account, or Jace OS), else why not."""
    if _key() == JACE_OS_KEY:
        return None
    return _why_not()


def _sign_in_jace_os() -> dict | None:
    """Sign in with the computer's Jace account (Jace OS). None if that isn't possible."""
    from jace import jaceos
    try:
        cfg = session.get(base_url() + "/api/v1/auth/jace/os", timeout=15).json()
        tok = jaceos.token_for(cfg.get("client_id") or "", cfg.get("scope") or "profile")
        if not tok:
            return None
        r = session.post(base_url() + "/api/v1/auth/jace/os", json={"access_token": tok}, timeout=20)
        s = r.json() if r.ok else None
    except Exception:  # noqa: BLE001 - quietly fall back to the normal sign-in
        return None
    if not s or not s.get("token"):
        return None
    all_s = _sessions()
    all_s[JACE_OS_KEY] = s
    write_json(SESSIONS_FILE, all_s)
    return s


def sign_in() -> dict:
    """Sign in to Jace Social: the selected Microsoft account, or else Jace OS. Blocking."""
    if _key() == JACE_OS_KEY:
        s = _sign_in_jace_os()
        if s:
            return s
        raise SocialError(_why_not() or "Couldn't sign in to Jace Social.")
    why = can_sign_in()
    if why:
        raise SocialError(why)
    acc = accounts.ensure_fresh(accounts.current())
    start = _call("POST", "/api/v1/auth/start", auth=False)
    r = session.post("https://sessionserver.mojang.com/session/minecraft/join", timeout=20, json={
        "accessToken": acc["access_token"], "selectedProfile": acc["uuid"], "serverId": start["server_id"]})
    if r.status_code not in (200, 204):
        raise SocialError("Mojang didn't accept the sign-in. Try signing out and back in to your Microsoft account.")
    s = _call("POST", "/api/v1/auth/finish", {"name": acc["username"], "server_id": start["server_id"]}, auth=False)
    all_s = _sessions()
    all_s[acc["uuid"]] = s
    write_json(SESSIONS_FILE, all_s)
    return s


def sign_out():
    s = current_session()
    if s:
        try:
            _call("POST", "/api/v1/auth/signout", {})
        except Exception:  # noqa: BLE001 - signing out locally is what matters
            pass
        all_s = _sessions()
        all_s.pop(_key(), None)
        write_json(SESSIONS_FILE, all_s)


def _call(method: str, path: str, data=None, auth=True, params=None, _retry=True):
    headers = {}
    if auth:
        s = current_session()
        if not s:
            s = sign_in()
        headers["Authorization"] = f"Bearer {s['token']}"
    try:
        r = session.request(method, base_url() + path, json=data, params=params, headers=headers, timeout=20)
    except Exception as e:  # noqa: BLE001
        raise SocialError(f"Can't reach Jace Social ({e.__class__.__name__}). Check your internet connection.") from e
    if r.status_code == 401 and auth and _retry:      # session expired: sign in again once
        if key := _key():
            all_s = _sessions()
            all_s.pop(key, None)
            write_json(SESSIONS_FILE, all_s)
        return _call(method, path, data, auth, params, _retry=False)
    try:
        body = r.json()
    except ValueError:
        body = {}
    if not r.ok:
        raise SocialError(body.get("error") or f"Jace Social error ({r.status_code})")
    return body


# --- API ---------------------------------------------------------------------------

def friends() -> dict:
    return _call("GET", "/api/v1/friends")


def add_friend(name: str) -> dict:
    return _call("POST", "/api/v1/friends", {"name": name.strip()})


def respond(uuid: str, accept: bool):
    return _call("POST", "/api/v1/friends/respond", {"uuid": uuid, "accept": accept})


def remove_friend(uuid: str):
    return _call("DELETE", "/api/v1/friends", params={"uuid": uuid})


def messages(with_uuid: str, before: int | None = None) -> list[dict]:
    params = {"with": with_uuid}
    if before:
        params["before"] = before
    return _call("GET", "/api/v1/messages", params=params)["messages"]


def send_message(to: str, text: str) -> dict:
    return _call("POST", "/api/v1/messages", {"to": to, "body": text})["message"]


def mark_read(with_uuid: str):
    return _call("POST", "/api/v1/messages/read", {"with": with_uuid})


def set_presence(activity: dict | None, offline=False):
    return _call("POST", "/api/v1/presence", {"activity": activity, "offline": offline})


def call_signal(to: str, call_id: str, kind: str, sdp: str | None = None):
    """Voice call setup: kind is offer, answer, hangup, renegotiate or reanswer."""
    return _call("POST", "/api/v1/calls", {"to": to, "call_id": call_id, "kind": kind, "sdp": sdp})


def read_call_signal(signal_id: int) -> dict:
    return _call("GET", "/api/v1/calls", params={"id": signal_id})["signal"]


def voice_room(channel_id: str, action: str | None = None, **state) -> dict:
    """A voice room (server voice channel or group call): who's in it, or join / leave / state."""
    if action is None:
        return _call("GET", f"/api/v1/channels/{channel_id}/voice")
    return _call("POST", f"/api/v1/channels/{channel_id}/voice", {"action": action, **state})


def voice_signal(channel_id: str, to: str, kind: str, sdp: str):
    """Connection setup with someone in the same voice room: kind is offer or answer."""
    return _call("POST", "/api/v1/voice/signal", {"channel_id": channel_id, "to": to, "kind": kind, "sdp": sdp})


def read_voice_signal(signal_id: int) -> dict:
    return _call("GET", "/api/v1/voice/signal", params={"id": signal_id})["signal"]


def ice_servers() -> list[dict]:
    return _call("GET", "/api/v1/calls/ice")["ice_servers"]


def me() -> dict:
    """Your Jace Social profile, including which accounts are linked."""
    return _call("GET", "/api/v1/me")


def start_link_jace() -> dict:
    """Begin linking a Jace account -> {url, state, poll_key}. Open url in a browser, then poll."""
    return _call("POST", "/api/v1/link/jace", {})


def poll_link_jace(state: str, key: str, timeout: float = 300) -> dict:
    """Wait (blocking) until the browser part of linking is done -> {jace_name}."""
    end = time.time() + timeout
    while time.time() < end:
        r = _call("GET", "/api/v1/auth/jace/poll", params={"state": state, "key": key})
        if not r.get("pending"):
            return r
        time.sleep(2)
    raise SocialError("Linking timed out - try again")


def unlink_jace():
    return _call("DELETE", "/api/v1/link/jace")


def describe_activity(f: dict) -> str:
    """One-line status for a friend."""
    if not f.get("online"):
        if not f.get("uses_jace"):
            return "Hasn't joined Jace Launcher yet"
        return "Offline"
    a = f.get("activity") or {}
    if a.get("type") == "hosting":
        return f"Hosting “{a.get('world') or 'a world'}” · {a.get('version', '')}".strip(" ·")
    if a.get("type") == "playing":
        where = f" on {a['server']}" if a.get("server") else ""
        return f"Playing {a.get('version', 'Minecraft')}{where}"
    return "Online"


def join_address(f: dict) -> str | None:
    a = (f.get("activity") or {}) if f.get("online") else {}
    if a.get("type") == "hosting":
        return a.get("address")
    if a.get("type") == "playing":
        return a.get("server")
    return None

