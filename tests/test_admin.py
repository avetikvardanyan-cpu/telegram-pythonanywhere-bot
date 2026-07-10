from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _message(user_id=1, username="", first_name="", text=""):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id, username=username, first_name=first_name),
        chat=SimpleNamespace(id=user_id),
        text=text,
    )


# --- is_admin / is_allowed gating ------------------------------------------

def test_is_admin_matches_configured_username():
    # ADMIN_USERS defaults to @Avetik_11 (bot/config.py); match is
    # case-insensitive on the username.
    from bot.helpers import is_admin

    assert is_admin(_message(user_id=1, username="Avetik_11")) is True
    assert is_admin(_message(user_id=1, username="avetik_11")) is True


def test_is_admin_rejects_non_admin():
    from bot.helpers import is_admin

    assert is_admin(_message(user_id=99, username="randomkid")) is False


def test_is_admin_matches_numeric_id():
    with patch("bot.helpers.ADMIN_USERS", ["12345"]), \
         patch("bot.helpers._ADMIN_USER_IDS", {"12345"}), \
         patch("bot.helpers._ADMIN_USERNAMES", set()):
        from bot.helpers import is_admin

        assert is_admin(_message(user_id=12345)) is True
        assert is_admin(_message(user_id=54321)) is False


def test_is_admin_disabled_when_no_admins():
    with patch("bot.helpers.ADMIN_USERS", []):
        from bot.helpers import is_admin

        assert is_admin(_message(username="Avetik_11")) is False


def test_admin_always_allowed_despite_whitelist():
    """An admin who isn't in a non-empty ALLOWED_USERS whitelist can still
    talk to the bot (otherwise the owner could lock themselves out)."""
    with patch("bot.helpers.ALLOWED_USERS", ["someoneelse"]), \
         patch("bot.helpers._ALLOWED_USERNAMES", {"someoneelse"}), \
         patch("bot.helpers._ALLOWED_USER_IDS", set()):
        from bot.helpers import is_allowed

        assert is_allowed(_message(username="Avetik_11")) is True
        assert is_allowed(_message(username="intruder")) is False


# --- admin command handlers ------------------------------------------------

def test_stats_requires_storage():
    mock_bot = MagicMock()
    with patch("bot.handlers.store", None), patch("bot.handlers.bot", mock_bot):
        from bot.handlers import cmd_stats

        cmd_stats(_message(text="/stats"))
        args = mock_bot.send_message.call_args[0]
        assert "storage" in args[1].lower()


def test_broadcast_sends_to_all_users():
    mock_bot = MagicMock()
    roster = [{"id": "111"}, {"id": "222"}, {"id": "333"}]
    with patch("bot.handlers.store", object()), \
         patch("bot.handlers.bot", mock_bot), \
         patch("bot.handlers.all_users", return_value=roster), \
         patch("bot.handlers.time.sleep"):
        from bot.handlers import cmd_broadcast

        cmd_broadcast(_message(user_id=1, username="Avetik_11", text="/broadcast hi all"))

    # 3 broadcast sends + 1 summary back to the admin
    assert mock_bot.send_message.call_count == 4
    delivered = [c.args[0] for c in mock_bot.send_message.call_args_list[:3]]
    assert delivered == [111, 222, 333]
    assert "hi all" == mock_bot.send_message.call_args_list[0].args[1]


def test_broadcast_requires_text():
    mock_bot = MagicMock()
    with patch("bot.handlers.store", object()), patch("bot.handlers.bot", mock_bot):
        from bot.handlers import cmd_broadcast

        cmd_broadcast(_message(text="/broadcast"))
        assert "Usage" in mock_bot.send_message.call_args[0][1]


def test_say_validates_numeric_id():
    mock_bot = MagicMock()
    with patch("bot.handlers.bot", mock_bot):
        from bot.handlers import cmd_say

        cmd_say(_message(text="/say notanid hello"))
        assert "Invalid user id" in mock_bot.send_message.call_args[0][1]


def test_say_delivers_to_target():
    mock_bot = MagicMock()
    with patch("bot.handlers.bot", mock_bot):
        from bot.handlers import cmd_say

        cmd_say(_message(user_id=1, text="/say 987654321 hello there"))

    # first send: the DM to the target; second: confirmation to the admin
    first = mock_bot.send_message.call_args_list[0].args
    assert first[0] == 987654321
    assert first[1] == "hello there"


def test_admin_panel_lists_commands():
    # cmd_admin renders via send_reply(), which sends through bot.helpers.bot.
    mock_bot = MagicMock()
    with patch("bot.handlers.store", None), \
         patch("bot.helpers.bot", mock_bot), \
         patch("bot.handlers.user_count", return_value=0):
        from bot.handlers import cmd_admin

        cmd_admin(_message(user_id=1, username="Avetik_11", text="/admin"))
        body = mock_bot.send_message.call_args[0][1]
        assert "/broadcast" in body
        assert "Admin panel" in body
