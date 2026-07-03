from unittest.mock import patch, MagicMock


def make_message(text="hello", user_id=123, chat_id=456, chat_type="private"):
    msg = MagicMock()
    msg.text = text
    msg.from_user.id = user_id
    msg.chat.id = chat_id
    msg.chat.type = chat_type
    msg.reply_to_message = None
    return msg


HANDLER_PATCHES = {
    "bot.handlers.should_respond": True,
    "bot.handlers.is_rate_limited": False,
    "bot.handlers.BOT_INFO": MagicMock(id=42, username="testbot"),
}


def test_handle_message_calls_ask_ai():
    with (
        patch("bot.handlers.should_respond", return_value=True),
        patch("bot.handlers.is_rate_limited", return_value=False),
        patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")),
        patch("bot.handlers.ask_ai", return_value="AI reply") as mock_ask,
        patch("bot.handlers.send_reply") as mock_send,
        patch("bot.handlers.bot"),
    ):
        from bot.handlers import handle_message

        msg = make_message(text="hello")
        handle_message(msg)
        mock_ask.assert_called_once_with(123, "hello")
        mock_send.assert_called_once_with(msg, "AI reply")


def test_handle_message_skips_when_not_responding():
    with (
        patch("bot.handlers.should_respond", return_value=False),
        patch("bot.handlers.ask_ai") as mock_ask,
    ):
        from bot.handlers import handle_message

        handle_message(make_message())
        mock_ask.assert_not_called()


def test_handle_message_rate_limited():
    with (
        patch("bot.handlers.should_respond", return_value=True),
        patch("bot.handlers.is_rate_limited", return_value=True),
        patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")),
        patch("bot.handlers.ask_ai") as mock_ask,
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import handle_message

        handle_message(make_message())
        mock_ask.assert_not_called()
        mock_bot.send_message.assert_called_once()
        assert "daily limit" in mock_bot.send_message.call_args[0][1]


def test_handle_message_sends_generic_error():
    with (
        patch("bot.handlers.should_respond", return_value=True),
        patch("bot.handlers.is_rate_limited", return_value=False),
        patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")),
        patch("bot.handlers.ask_ai", side_effect=Exception("API key invalid")),
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import handle_message

        handle_message(make_message())
        error_msg = mock_bot.send_message.call_args[0][1]
        assert "Something went wrong" in error_msg
        assert "API key" not in error_msg


def test_handle_message_none_text_skipped():
    """Stickers/photos/edits arriving with text=None must NOT call ask_ai
    (would burn rate limit and AI quota for no reason)."""
    with (
        patch("bot.handlers.should_respond", return_value=True),
        patch("bot.handlers.is_rate_limited", return_value=False),
        patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")),
        patch("bot.handlers.ask_ai") as mock_ask,
        patch("bot.handlers.send_reply") as mock_send,
        patch("bot.handlers.bot"),
    ):
        from bot.handlers import handle_message

        msg = make_message()
        msg.text = None
        handle_message(msg)
        mock_ask.assert_not_called()
        mock_send.assert_not_called()


def test_handle_message_mention_only_skipped():
    """In a group, '@testbot' alone strips to empty — don't call ask_ai."""
    with (
        patch("bot.handlers.should_respond", return_value=True),
        patch("bot.handlers.is_rate_limited", return_value=False),
        patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")),
        patch("bot.handlers.ask_ai") as mock_ask,
        patch("bot.handlers.send_reply"),
        patch("bot.handlers.bot"),
    ):
        from bot.handlers import handle_message

        msg = make_message(text="@testbot")
        handle_message(msg)
        mock_ask.assert_not_called()


# ── /debug, /review, /quiz ──────────────────────────────────────────────────────


def test_cmd_debug_calls_ask_ai_with_code():
    with (
        patch("bot.handlers.ask_ai", return_value="Fixed") as mock_ask,
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import cmd_debug

        cmd_debug(make_message(text="/debug print(x"))
        prompt = mock_ask.call_args[0][1]
        assert "print(x" in prompt
        mock_bot.send_message.assert_called_once_with(456, "Fixed")


def test_cmd_debug_no_code_shows_usage():
    with (
        patch("bot.handlers.ask_ai") as mock_ask,
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import cmd_debug

        cmd_debug(make_message(text="/debug"))
        mock_ask.assert_not_called()
        assert "Usage" in mock_bot.send_message.call_args[0][1]


def test_cmd_review_calls_ask_ai_with_code():
    with (
        patch("bot.handlers.ask_ai", return_value="Looks good") as mock_ask,
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import cmd_review

        cmd_review(make_message(text="/review def f(): pass"))
        prompt = mock_ask.call_args[0][1]
        assert "def f(): pass" in prompt
        mock_bot.send_message.assert_called_once_with(456, "Looks good")


def test_cmd_review_no_code_shows_usage():
    with (
        patch("bot.handlers.ask_ai") as mock_ask,
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import cmd_review

        cmd_review(make_message(text="/review"))
        mock_ask.assert_not_called()
        assert "Usage" in mock_bot.send_message.call_args[0][1]


def test_cmd_quiz_asks_question_and_registers_next_step():
    with (
        patch("bot.handlers.ask_ai", return_value="What is a list?") as mock_ask,
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import cmd_quiz

        sent = MagicMock()
        mock_bot.send_message.return_value = sent
        cmd_quiz(make_message(text="/quiz python"))
        assert "python" in mock_ask.call_args[0][1]
        # the generated question is passed through to the grader as an extra arg
        args = mock_bot.register_next_step_handler.call_args[0]
        assert args[0] is sent
        assert args[2] == "What is a list?"


def test_cmd_quiz_no_topic_shows_usage():
    with (
        patch("bot.handlers.ask_ai") as mock_ask,
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import cmd_quiz

        cmd_quiz(make_message(text="/quiz"))
        mock_ask.assert_not_called()
        assert "Usage" in mock_bot.send_message.call_args[0][1]


def test_grade_quiz_scores_answer_with_question_context():
    with (
        patch("bot.handlers.ask_ai", return_value="Correct!") as mock_ask,
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import _grade_quiz

        _grade_quiz(make_message(text="a list is ordered"), "What is a list?")
        prompt = mock_ask.call_args[0][1]
        assert "What is a list?" in prompt
        assert "a list is ordered" in prompt
        mock_bot.send_message.assert_called_once_with(456, "Correct!")


def test_grade_quiz_empty_answer_cancels():
    with (
        patch("bot.handlers.ask_ai") as mock_ask,
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import _grade_quiz

        msg = make_message()
        msg.text = ""
        _grade_quiz(msg, "What is a list?")
        mock_ask.assert_not_called()
        assert "cancelled" in mock_bot.send_message.call_args[0][1]


# ── /summarize ──────────────────────────────────────────────────────────────────


def test_cmd_summarize_calls_ask_ai_with_text():
    with (
        patch("bot.handlers.ask_ai", return_value="Short summary") as mock_ask,
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import cmd_summarize

        cmd_summarize(make_message(text="/summarize a long article about bees"))
        prompt = mock_ask.call_args[0][1]
        assert "a long article about bees" in prompt
        mock_bot.send_message.assert_called_once_with(456, "Short summary")


def test_cmd_summarize_no_text_shows_usage():
    with (
        patch("bot.handlers.ask_ai") as mock_ask,
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import cmd_summarize

        cmd_summarize(make_message(text="/summarize"))
        mock_ask.assert_not_called()
        assert "Usage" in mock_bot.send_message.call_args[0][1]


# ── /about ────────────────────────────────────────────────────────────────────


def test_cmd_about_with_sqlite():
    """When SQLite is configured, /about should reference SQLite."""
    with (
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.store", MagicMock()),
        patch("bot.handlers.HF_SPACE_ID", ""),
    ):
        from bot.handlers import cmd_about

        cmd_about(make_message())
        sent = mock_bot.send_message.call_args[0][1]
        assert "SQLite" in sent
        assert "stateless" not in sent


def test_cmd_about_includes_commit_sha_when_set():
    """When COMMIT_SHA is populated (worker booted inside a git repo),
    /about exposes a Version line so users can validate which commit is
    live."""
    with (
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.store", MagicMock()),
        patch("bot.handlers.HF_SPACE_ID", ""),
        patch("bot.handlers.COMMIT_SHA", "abc1234"),
    ):
        from bot.handlers import cmd_about

        cmd_about(make_message())
        sent = mock_bot.send_message.call_args[0][1]
        assert "Version: abc1234" in sent


def test_cmd_about_omits_version_line_when_sha_unknown():
    """If git rev-parse failed at boot, the Version line is dropped
    entirely rather than showing 'unknown' — clearer for the user."""
    with (
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.store", MagicMock()),
        patch("bot.handlers.HF_SPACE_ID", ""),
        patch("bot.handlers.COMMIT_SHA", ""),
    ):
        from bot.handlers import cmd_about

        cmd_about(make_message())
        sent = mock_bot.send_message.call_args[0][1]
        assert "Version" not in sent


def test_cmd_about_without_store():
    """When no backend is configured, /about must say stateless. Regression
    guard for the NameError that occurred when `store` was missing from
    bot.handlers' imports."""
    with (
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.store", None),
        patch("bot.handlers.HF_SPACE_ID", ""),
    ):
        from bot.handlers import cmd_about

        cmd_about(make_message())
        sent = mock_bot.send_message.call_args[0][1]
        assert "stateless" in sent


# ── /sha ─────────────────────────────────────────────────────────────────────


def test_cmd_sha_reports_live_commit_sha():
    with (
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.COMMIT_SHA", "abc1234"),
    ):
        from bot.handlers import cmd_sha

        cmd_sha(make_message())
        mock_bot.send_message.assert_called_once_with(456, "Live SHA: abc1234")


def test_cmd_sha_reports_unknown_when_git_sha_unavailable():
    with (
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.COMMIT_SHA", ""),
    ):
        from bot.handlers import cmd_sha

        cmd_sha(make_message())
        mock_bot.send_message.assert_called_once_with(456, "Live SHA: unknown")


# ── model registry (available_models / active_model / _resolve_model) ───────────

# available_models() reads bot.handlers.MODEL and bot.handlers.HF_SPACE_ID, so
# tests patch those to shape the registry. active_model() also reads
# get_provider(). All are patchable at the handler level — no module reload.


def test_available_models_main_only_without_hf():
    import bot.handlers

    with (
        patch("bot.handlers.HF_SPACE_ID", ""),
        patch("bot.handlers.MODEL", "gpt-oss-120b"),
    ):
        models = bot.handlers.available_models()
        assert [m["key"] for m in models] == ["main", "qwen-3-235b-a22b-instruct-2507"]
        assert models[0]["name"] == "gpt-oss-120b"
        assert models[0]["description"]


def test_available_models_includes_hf_when_configured():
    import bot.handlers

    with (
        patch("bot.handlers.HF_SPACE_ID", "fake/space"),
        patch("bot.handlers.MODEL", "gpt-oss-120b"),
    ):
        keys = [m["key"] for m in bot.handlers.available_models()]
        assert keys == ["main", "qwen-3-235b-a22b-instruct-2507", "hf"]


def test_active_model_reflects_provider():
    import bot.handlers

    with (
        patch("bot.handlers.HF_SPACE_ID", "fake/space"),
        patch("bot.handlers.get_provider", return_value="hf"),
    ):
        assert bot.handlers.active_model(123)["key"] == "hf"


def test_active_model_falls_back_when_provider_unavailable():
    """A stale 'hf' preference with HF now unset falls back to main."""
    import bot.handlers

    with (
        patch("bot.handlers.HF_SPACE_ID", ""),
        patch("bot.handlers.get_provider", return_value="hf"),
    ):
        assert bot.handlers.active_model(123)["key"] == "main"


def test_resolve_model_matches_key_and_name():
    import bot.handlers

    with (
        patch("bot.handlers.HF_SPACE_ID", "fake/space"),
        patch("bot.handlers.MODEL", "gpt-oss-120b"),
    ):
        assert bot.handlers._resolve_model("hf")["key"] == "hf"
        assert bot.handlers._resolve_model("ArmGPT")["key"] == "hf"
        assert bot.handlers._resolve_model("MAIN")["key"] == "main"
        assert bot.handlers._resolve_model("gpt-oss-120b")["key"] == "main"
        assert bot.handlers._resolve_model("qwen-3-235b-a22b-instruct-2507")["key"] == "qwen-3-235b-a22b-instruct-2507"
        assert bot.handlers._resolve_model("nope") is None


# ── /model command ──────────────────────────────────────────────────────────────


def test_cmd_model_no_args_shows_current_and_hint_without_hf():
    """Even without HF, main + the alternate Cerebras model give >1 option,
    so the no-arg /model reports the current model and hints how to switch."""
    from bot.handlers import cmd_model

    with (
        patch("bot.handlers.HF_SPACE_ID", ""),
        patch("bot.handlers.MODEL", "gpt-oss-120b"),
        patch("bot.handlers.get_provider", return_value="main"),
        patch("bot.handlers.bot") as mock_bot,
    ):
        cmd_model(make_message(text="/model"))
        sent = mock_bot.send_message.call_args[0][1]
        assert "Current model: gpt-oss-120b" in sent
        assert "/models" in sent


def test_cmd_model_no_args_hints_switch_when_multiple():
    from bot.handlers import cmd_model

    with (
        patch("bot.handlers.HF_SPACE_ID", "fake/space"),
        patch("bot.handlers.MODEL", "gpt-oss-120b"),
        patch("bot.handlers.get_provider", return_value="main"),
        patch("bot.handlers.bot") as mock_bot,
    ):
        cmd_model(make_message(text="/model"))
        sent = mock_bot.send_message.call_args[0][1]
        assert "Current model: gpt-oss-120b" in sent
        assert "/models" in sent


def test_cmd_model_switch_to_hf():
    from bot.handlers import cmd_model

    with (
        patch("bot.handlers.HF_SPACE_ID", "fake/space"),
        patch("bot.handlers.set_provider", return_value=True) as mock_set,
        patch("bot.handlers.bot") as mock_bot,
    ):
        cmd_model(make_message(text="/model hf"))
        mock_set.assert_called_once_with(123, "hf")
        sent = mock_bot.send_message.call_args[0][1]
        assert "hf" in sent
        assert "Armenian" in sent


def test_cmd_model_switch_by_display_name():
    """Switching accepts the display name, not just the provider key."""
    from bot.handlers import cmd_model

    with (
        patch("bot.handlers.HF_SPACE_ID", "fake/space"),
        patch("bot.handlers.set_provider", return_value=True) as mock_set,
        patch("bot.handlers.bot"),
    ):
        cmd_model(make_message(text="/model ArmGPT"))
        mock_set.assert_called_once_with(123, "hf")


def test_cmd_model_switch_to_main():
    from bot.handlers import cmd_model

    with (
        patch("bot.handlers.HF_SPACE_ID", "fake/space"),
        patch("bot.handlers.MODEL", "gpt-oss-120b"),
        patch("bot.handlers.set_provider", return_value=True) as mock_set,
        patch("bot.handlers.bot") as mock_bot,
    ):
        cmd_model(make_message(text="/model main"))
        mock_set.assert_called_once_with(123, "main")
        sent = mock_bot.send_message.call_args[0][1]
        assert "Main" in sent
        assert "gpt-oss-120b" in sent


def test_cmd_model_unknown_choice():
    from bot.handlers import cmd_model

    with (
        patch("bot.handlers.HF_SPACE_ID", "fake/space"),
        patch("bot.handlers.set_provider") as mock_set,
        patch("bot.handlers.bot") as mock_bot,
    ):
        cmd_model(make_message(text="/model bogus"))
        mock_set.assert_not_called()
        assert "Unknown model" in mock_bot.send_message.call_args[0][1]


def test_cmd_model_save_failure_reports_error():
    from bot.handlers import cmd_model

    with (
        patch("bot.handlers.HF_SPACE_ID", "fake/space"),
        patch("bot.handlers.set_provider", return_value=False),
        patch("bot.handlers.bot") as mock_bot,
    ):
        cmd_model(make_message(text="/model hf"))
        assert "Could not save" in mock_bot.send_message.call_args[0][1]


# ── /models command ─────────────────────────────────────────────────────────────


def test_cmd_models_lists_all_with_active_marker():
    from bot.handlers import cmd_models

    with (
        patch("bot.handlers.HF_SPACE_ID", "fake/space"),
        patch("bot.handlers.MODEL", "gpt-oss-120b"),
        patch("bot.handlers.get_provider", return_value="hf"),
        patch("bot.handlers.bot") as mock_bot,
    ):
        cmd_models(make_message(text="/models"))
        sent = mock_bot.send_message.call_args[0][1]
        # both models are listed, each with its description
        assert "gpt-oss-120b" in sent
        assert "ArmGPT" in sent
        assert "Armenian" in sent
        # only the active model (hf/ArmGPT) is marked active
        arm_line = next(line for line in sent.splitlines() if "ArmGPT" in line)
        main_line = next(line for line in sent.splitlines() if "gpt-oss-120b" in line)
        assert "active" in arm_line
        assert "active" not in main_line


def test_cmd_models_lists_cerebras_models_and_switch_hint_without_hf():
    """Without HF there are still two Cerebras models, so /models lists both,
    marks the active one, and shows the switch hint."""
    from bot.handlers import cmd_models

    with (
        patch("bot.handlers.HF_SPACE_ID", ""),
        patch("bot.handlers.MODEL", "gpt-oss-120b"),
        patch("bot.handlers.get_provider", return_value="main"),
        patch("bot.handlers.bot") as mock_bot,
    ):
        cmd_models(make_message(text="/models"))
        sent = mock_bot.send_message.call_args[0][1]
        main_line = next(line for line in sent.splitlines() if "gpt-oss-120b" in line)
        qwen_line = next(line for line in sent.splitlines() if "qwen-3-235b-a22b-instruct-2507" in line)
        assert "active" in main_line
        assert "active" not in qwen_line
        assert "Switch with" in sent


def test_handle_message_uses_keep_typing():
    """handle_message should wrap ask_ai in the keep_typing context."""
    with (
        patch("bot.handlers.should_respond", return_value=True),
        patch("bot.handlers.is_rate_limited", return_value=False),
        patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")),
        patch("bot.handlers.ask_ai", return_value="reply"),
        patch("bot.handlers.send_reply"),
        patch("bot.handlers.keep_typing") as mock_keep,
        patch("bot.handlers.bot"),
    ):
        mock_keep.return_value.__enter__ = MagicMock(return_value=None)
        mock_keep.return_value.__exit__ = MagicMock(return_value=None)
        from bot.handlers import handle_message

        msg = make_message()
        handle_message(msg)
        mock_keep.assert_called_once_with(456)
