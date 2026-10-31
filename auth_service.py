import base64
import hashlib
import hmac
import os
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from .db_service import get_connection

SESSION_DAYS = 30
PASSWORD_RESET_MINUTES = 30
SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1


class AccountConflictError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class OAuthLinkRequiredError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=64
    )
    return "$".join((
        "scrypt",
        str(SCRYPT_N),
        str(SCRYPT_R),
        str(SCRYPT_P),
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(derived).decode("ascii"),
    ))


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, n, r, p, salt_value, expected_value = stored_hash.split("$")
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_value.encode("ascii"))
        expected = base64.urlsafe_b64decode(expected_value.encode("ascii"))
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


_DUMMY_PASSWORD_HASH = hash_password("TalibAI credential timing check")


def create_account(email: str, password: str) -> dict:
    user_id = secrets.token_urlsafe(24)
    now = _now().isoformat()
    conn = get_connection()
    try:
        conn.execute(
            'INSERT INTO users (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)',
            (user_id, email.strip().lower(), hash_password(password), now)
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        if "UNIQUE constraint failed: users.email" in str(exc):
            raise AccountConflictError from exc
        raise
    finally:
        conn.close()
    return {"id": user_id, "email": email.strip().lower()}


def authenticate(email: str, password: str) -> dict:
    conn = get_connection()
    row = conn.execute('SELECT id, email, password_hash FROM users WHERE email = ?', (email.strip().lower(),)).fetchone()
    conn.close()
    stored_hash = row["password_hash"] if row else _DUMMY_PASSWORD_HASH
    password_matches = verify_password(password, stored_hash)
    if not row or not password_matches:
        raise InvalidCredentialsError
    return {"id": row["id"], "email": row["email"]}


def resolve_oauth_account(
    provider: str,
    provider_subject: str,
    email: str,
    name: str,
    link_user_id: str | None = None,
) -> dict:
    normalized_email = email.strip().lower()
    now = _now().isoformat()
    conn = get_connection()
    conn.execute("BEGIN IMMEDIATE")
    identity = conn.execute('''
        SELECT users.id, users.email FROM oauth_identities
        JOIN users ON users.id = oauth_identities.user_id
        WHERE oauth_identities.provider = ? AND oauth_identities.provider_subject = ?
    ''', (provider, provider_subject)).fetchone()

    if identity:
        if link_user_id and identity["id"] != link_user_id:
            conn.rollback()
            conn.close()
            raise AccountConflictError
        conn.commit()
        conn.close()
        return dict(identity)

    created = False
    if link_user_id:
        user = conn.execute('SELECT id, email FROM users WHERE id = ?', (link_user_id,)).fetchone()
        if not user or user["email"].lower() != normalized_email:
            conn.rollback()
            conn.close()
            raise AccountConflictError
        user_id = user["id"]
    else:
        user = conn.execute('SELECT id, email FROM users WHERE email = ?', (normalized_email,)).fetchone()
        if user:
            conn.rollback()
            conn.close()
            raise OAuthLinkRequiredError
        user_id = secrets.token_urlsafe(24)
        password_hash = hash_password(secrets.token_urlsafe(32))
        try:
            conn.execute(
                'INSERT INTO users (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)',
                (user_id, normalized_email, password_hash, now)
            )
        except Exception as exc:
            conn.rollback()
            conn.close()
            if "UNIQUE constraint failed: users.email" in str(exc):
                raise OAuthLinkRequiredError from exc
            raise
        created = True

    conn.execute(
        'INSERT INTO oauth_identities (provider, provider_subject, user_id, created_at) VALUES (?, ?, ?, ?)',
        (provider, provider_subject, user_id, now)
    )
    conn.commit()
    conn.close()

    if created:
        from .db_service import get_or_create_student
        get_or_create_student(user_id, name=(name.strip() or normalized_email.split("@")[0])[:100])
    return {"id": user_id, "email": normalized_email}


def consume_auth_rate_limit(rate_key: str, max_attempts: int = 10, window_minutes: int = 15) -> bool:
    now = _now()
    conn = get_connection()
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute(
        'SELECT attempts, window_started_at FROM auth_rate_limits WHERE rate_key = ?', (rate_key,)
    ).fetchone()
    if row:
        window_start = datetime.fromisoformat(row["window_started_at"])
        if now - window_start >= timedelta(minutes=window_minutes):
            conn.execute(
                'UPDATE auth_rate_limits SET attempts = 1, window_started_at = ? WHERE rate_key = ?',
                (now.isoformat(), rate_key)
            )
        elif row["attempts"] >= max_attempts:
            conn.rollback()
            conn.close()
            return False
        else:
            conn.execute('UPDATE auth_rate_limits SET attempts = attempts + 1 WHERE rate_key = ?', (rate_key,))
    else:
        conn.execute(
            'INSERT INTO auth_rate_limits (rate_key, attempts, window_started_at) VALUES (?, 1, ?)',
            (rate_key, now.isoformat())
        )
    conn.commit()
    conn.close()
    return True


def clear_auth_rate_limit(rate_key: str):
    conn = get_connection()
    conn.execute('DELETE FROM auth_rate_limits WHERE rate_key = ?', (rate_key,))
    conn.commit()
    conn.close()


def create_session(user_id: str) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    now = _now()
    expires_at = now + timedelta(days=SESSION_DAYS)
    conn = get_connection()
    conn.execute(
        'INSERT INTO auth_sessions (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)',
        (_token_hash(token), user_id, expires_at.isoformat(), now.isoformat())
    )
    conn.execute('DELETE FROM auth_sessions WHERE expires_at <= ?', (now.isoformat(),))
    conn.commit()
    conn.close()
    return token, expires_at


def get_session_user(token: str | None) -> dict | None:
    if not token:
        return None
    conn = get_connection()
    row = conn.execute('''
        SELECT users.id, users.email
        FROM auth_sessions
        JOIN users ON users.id = auth_sessions.user_id
        WHERE auth_sessions.token_hash = ? AND auth_sessions.expires_at > ?
    ''', (_token_hash(token), _now().isoformat())).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_session(token: str | None):
    if not token:
        return
    conn = get_connection()
    conn.execute('DELETE FROM auth_sessions WHERE token_hash = ?', (_token_hash(token),))
    conn.commit()
    conn.close()


def email_is_configured() -> bool:
    return all(os.getenv(key) for key in ("SMTP_HOST", "SMTP_FROM"))


def _send_reset_email(email: str, token: str):
    host = os.getenv("SMTP_HOST")
    sender = os.getenv("SMTP_FROM")
    if not host or not sender:
        raise RuntimeError("Password reset email is not configured")

    port = int(os.getenv("SMTP_PORT", "587"))
    message = EmailMessage()
    message["Subject"] = "Reset your TalibAI password"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        "A password reset was requested for your TalibAI account. "
        "Open the app and submit this reset token within 30 minutes:\n\n" + token +
        "\n\nIf you did not request this, you can ignore this message."
    )
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    with smtplib.SMTP(host, port, timeout=15) as server:
        if use_tls:
            server.starttls()
        if username and password:
            server.login(username, password)
        server.send_message(message)


def request_password_reset(email: str):
    conn = get_connection()
    user = conn.execute('SELECT id FROM users WHERE email = ?', (email.strip().lower(),)).fetchone()
    if not user:
        conn.close()
        return

    token = secrets.token_urlsafe(32)
    now = _now()
    conn.execute('DELETE FROM password_resets WHERE user_id = ?', (user["id"],))
    conn.execute(
        'INSERT INTO password_resets (token_hash, user_id, expires_at) VALUES (?, ?, ?)',
        (_token_hash(token), user["id"], (now + timedelta(minutes=PASSWORD_RESET_MINUTES)).isoformat())
    )
    conn.commit()
    conn.close()
    try:
        _send_reset_email(email.strip().lower(), token)
    except Exception:
        conn = get_connection()
        conn.execute('DELETE FROM password_resets WHERE token_hash = ?', (_token_hash(token),))
        conn.commit()
        conn.close()
        raise


def reset_password(token: str, new_password: str) -> bool:
    now = _now()
    conn = get_connection()
    row = conn.execute('''
        SELECT user_id FROM password_resets
        WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?
    ''', (_token_hash(token), now.isoformat())).fetchone()
    if not row:
        conn.close()
        return False

    conn.execute('UPDATE users SET password_hash = ? WHERE id = ?', (hash_password(new_password), row["user_id"]))
    conn.execute('DELETE FROM auth_sessions WHERE user_id = ?', (row["user_id"],))
    conn.execute('DELETE FROM password_resets WHERE user_id = ?', (row["user_id"],))
    conn.commit()
    conn.close()
    return True
