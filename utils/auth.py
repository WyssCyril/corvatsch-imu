"""Password gate for the Streamlit app.

No password is stored in the code or the repo. Passwords live only in the Streamlit secrets
(share.streamlit.io → app → Settings → Secrets, locally .streamlit/secrets.toml, which is git-ignored):

    APP_PASSWORDS = ["password-coach-a", "password-coach-b"]

or, if the plain passwords should not be visible in the secrets either, as salted SHA-256 hashes
(hash of "corvatsch-imu:<password>"):

    APP_PASSWORDS_SHA256 = ["<hash>", "<hash>"]

Without any configured password the app stays locked (fail closed).
"""
import hashlib
import hmac

import streamlit as st

_SALT = "corvatsch-imu:"


def hash_password(pw: str) -> str:
    return hashlib.sha256((_SALT + pw).encode()).hexdigest()


def _as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    return [str(x) for x in v if str(x).strip()]


def expected_hashes(secrets) -> list[str]:
    """All accepted password hashes from the secrets (plain passwords are hashed here)."""
    try:
        plain = _as_list(secrets.get("APP_PASSWORDS")) + _as_list(secrets.get("APP_PASSWORD"))
        hashed = _as_list(secrets.get("APP_PASSWORDS_SHA256")) + _as_list(secrets.get("APP_PASSWORD_SHA256"))
    except Exception:  # no secrets.toml
        return []
    return [hash_password(p) for p in plain] + [h.lower() for h in hashed]


def check(pw: str, hashes: list[str]) -> bool:
    if not pw or not hashes:
        return False
    h = hash_password(pw)
    return any(hmac.compare_digest(h, e) for e in hashes)


def require_login() -> None:
    """Show a login form and stop the script until a correct password was entered."""
    if st.session_state.get("authenticated"):
        return
    hashes = expected_hashes(st.secrets)
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown("### Login")
        if not hashes:
            st.error("No password is configured for this app yet. Add APP_PASSWORDS to the Streamlit secrets.")
            st.stop()
        with st.form("login", clear_on_submit=True):
            pw = st.text_input("Password", type="password")
            ok = st.form_submit_button("Log in", type="primary")
        if ok:
            if check(pw, hashes):
                st.session_state["authenticated"] = True
                st.rerun()
            st.error("Wrong password.")
    st.stop()
