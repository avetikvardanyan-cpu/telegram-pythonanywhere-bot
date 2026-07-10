"""Track known users so the admin panel can show stats / broadcast to them.

The bot is otherwise stateless about *who* has used it — history and rate
limits are keyed per user_id but there's no roster. This module keeps a
lightweight roster in the same KV store: an index list of user id strings
plus one record per user (username, first name, last-seen timestamp).

Follows the graceful-degradation pattern of history/preferences/rate_limit:
every function no-ops and returns a safe default when the store is
unconfigured (stateless mode) or a store op fails, so user tracking can
never break message handling. Recording happens once per update from the
webhook (bot never processes an update twice thanks to dedupe).
"""

import json
import time

from bot.clients import store

_INDEX_KEY = "users:index"  # JSON list of known user id strings
_REC_PREFIX = "user:"  # user:<id> -> JSON {id, username, first_name, last_seen}


def record_user(user) -> None:
    """Upsert one Telegram user into the roster. Best-effort; never raises."""
    if store is None or user is None:
        return
    uid = getattr(user, "id", None)
    if uid is None:
        return
    try:
        uid = str(uid)
        record = {
            "id": uid,
            "username": getattr(user, "username", "") or "",
            "first_name": getattr(user, "first_name", "") or "",
            "last_seen": int(time.time()),
        }
        store.set(f"{_REC_PREFIX}{uid}", json.dumps(record))
        raw = store.get(_INDEX_KEY)
        ids = json.loads(raw) if raw else []
        if uid not in ids:
            ids.append(uid)
            store.set(_INDEX_KEY, json.dumps(ids))
    except Exception as e:
        print(f"record_user error: {e}")


def record_from_update(update) -> None:
    """Extract the sender from a Telegram update and record them.

    Looks at message / edited_message so both fresh and edited messages
    count. Silently does nothing for updates without a from_user (e.g.
    channel posts). Wrapped so a malformed update can't break the webhook.
    """
    if update is None:
        return
    try:
        source = getattr(update, "message", None) or getattr(
            update, "edited_message", None
        )
        if source is not None:
            record_user(getattr(source, "from_user", None))
    except Exception as e:
        print(f"record_from_update error: {e}")


def all_users() -> list:
    """Return the roster as a list of user record dicts (most recent first).

    Empty list in stateless mode or on any store error."""
    if store is None:
        return []
    try:
        raw = store.get(_INDEX_KEY)
        ids = json.loads(raw) if raw else []
        users = []
        for uid in ids:
            rec = store.get(f"{_REC_PREFIX}{uid}")
            if rec:
                users.append(json.loads(rec))
            else:
                users.append({"id": uid, "username": "", "first_name": "", "last_seen": 0})
        users.sort(key=lambda u: u.get("last_seen", 0), reverse=True)
        return users
    except Exception as e:
        print(f"all_users error: {e}")
        return []


def user_count() -> int:
    """Number of known users, or 0 in stateless mode / on error."""
    if store is None:
        return 0
    try:
        raw = store.get(_INDEX_KEY)
        return len(json.loads(raw)) if raw else 0
    except Exception as e:
        print(f"user_count error: {e}")
        return 0
