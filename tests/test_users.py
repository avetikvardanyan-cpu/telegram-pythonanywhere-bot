from types import SimpleNamespace
from unittest.mock import patch


class FakeStore:
    """Minimal in-memory KV standing in for SqliteStore in tests."""

    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None):
        self.data[key] = value

    def delete(self, key):
        self.data.pop(key, None)


def _user(uid, username="", first_name=""):
    return SimpleNamespace(id=uid, username=username, first_name=first_name)


def test_record_and_list_user():
    with patch("bot.users.store", FakeStore()):
        from bot.users import all_users, record_user, user_count

        record_user(_user(111, "alice", "Alice"))
        assert user_count() == 1
        users = all_users()
        assert len(users) == 1
        assert users[0]["id"] == "111"
        assert users[0]["username"] == "alice"


def test_record_user_dedupes_index():
    with patch("bot.users.store", FakeStore()):
        from bot.users import record_user, user_count

        record_user(_user(111, "alice"))
        record_user(_user(111, "alice"))  # same user again
        record_user(_user(222, "bob"))
        assert user_count() == 2


def test_stateless_mode_returns_safe_defaults():
    with patch("bot.users.store", None):
        from bot.users import all_users, record_user, user_count

        record_user(_user(111, "alice"))  # no-op, must not raise
        assert all_users() == []
        assert user_count() == 0


def test_record_user_ignores_none():
    with patch("bot.users.store", FakeStore()):
        from bot.users import record_user, user_count

        record_user(None)
        assert user_count() == 0


def test_all_users_sorted_by_last_seen():
    store = FakeStore()
    with patch("bot.users.store", store):
        import bot.users as users_mod

        with patch.object(users_mod.time, "time", side_effect=[100, 200]):
            users_mod.record_user(_user(1, "old"))
            users_mod.record_user(_user(2, "new"))
        result = users_mod.all_users()
        assert [u["username"] for u in result] == ["new", "old"]


def test_record_from_update_extracts_sender():
    with patch("bot.users.store", FakeStore()):
        from bot.users import record_from_update, user_count

        update = SimpleNamespace(
            message=SimpleNamespace(from_user=_user(555, "carol")),
            edited_message=None,
        )
        record_from_update(update)
        assert user_count() == 1


def test_record_from_update_ignores_no_message():
    with patch("bot.users.store", FakeStore()):
        from bot.users import record_from_update, user_count

        update = SimpleNamespace(message=None, edited_message=None)
        record_from_update(update)
        assert user_count() == 0
