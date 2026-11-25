"""Content-free Supabase Broadcast signals telling browsers to refetch through Flask."""

import hashlib
import hmac
import logging
import os

import httpx
from flask import Blueprint, jsonify, session

from identity import session_student_id

logger = logging.getLogger(__name__)


def settings():
    """Return the realtime configuration, or None unless every value is set."""
    values = {
        "url": os.getenv("SUPABASE_URL", "").rstrip("/"),
        "secret_key": os.getenv("SUPABASE_SECRET_KEY"),
        "public_key": os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY"),
        # Topics must match across workers, so a random per-process key will not do.
        "topic_secret": os.getenv("FLASK_SECRET_KEY"),
    }
    return values if all(values.values()) else None


def topic(user_id, secret):
    digest = hmac.new(secret.encode(), f"realtime:{user_id}".encode(), hashlib.sha256)
    return "user:" + digest.hexdigest()


def signal(db, *user_ids):
    """Queue a signal to send after this connection's transaction commits."""
    db.signals.update(user_ids)


def publish(user_ids):
    """Best effort: clients also poll, so a failed signal never fails a request."""
    config = settings()
    if not config or not user_ids:
        return
    messages = [{"topic": topic(user_id, config["topic_secret"]), "event": "changed", "payload": {}}
                for user_id in sorted(user_ids)]
    try:
        httpx.post(
            config["url"] + "/realtime/v1/api/broadcast",
            headers={"apikey": config["secret_key"]},
            json={"messages": messages},
            timeout=2,
        ).raise_for_status()
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        logger.warning("Realtime signal failed (%s).", type(exc).__name__)


def create_realtime_blueprint(get_db):
    api = Blueprint("realtime", __name__)

    @api.get("/api/realtime")
    def subscription():
        with get_db() as db:
            student_id = session_student_id(db, session)
        if student_id is None:
            return jsonify(error="Sign in to continue."), 401
        config = settings()
        if not config:
            return jsonify(enabled=False)
        # Only the browser-safe key leaves the server.
        return jsonify(enabled=True, url=config["url"], key=config["public_key"],
                       topic=topic(student_id, config["topic_secret"]))

    return api
