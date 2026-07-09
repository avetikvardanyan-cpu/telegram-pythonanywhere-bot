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
        # English text -> no model override, use the user's saved model
        mock_ask.assert_called_once_with(123, "hello", provider=None)
        mock_send.assert_called_once_with(msg, "AI reply")


def test_handle_message_armenian_switches_to_armenian_model():
    """An Armenian message is answered with ARMENIAN_MODEL for that turn without
    changing the user's saved model."""
    with (
        patch("bot.handlers.should_respond", return_value=True),
        patch("bot.handlers.is_rate_limited", return_value=False),
        patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")),
        patch("bot.handlers.ARMENIAN_MODEL", "gemma-4-31b"),
        patch("bot.handlers.get_provider", return_value="main"),
        patch("bot.handlers.ask_ai", return_value="բարև") as mock_ask,
        patch("bot.handlers.send_reply"),
        patch("bot.handlers.bot"),
    ):
        from bot.handlers import handle_message

        handle_message(make_message(text="Բարև, ինչպե՞ս ես"))
        assert mock_ask.call_args.kwargs["provider"] == "gemma-4-31b"


def test_handle_message_armenian_keeps_model_when_already_armenian():
    """If the user already chose ARMENIAN_MODEL, don't override (keep the same)."""
    with (
        patch("bot.handlers.should_respond", return_value=True),
        patch("bot.handlers.is_rate_limited", return_value=False),
        patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")),
        patch("bot.handlers.ARMENIAN_MODEL", "gemma-4-31b"),
        patch("bot.handlers.get_provider", return_value="gemma-4-31b"),
        patch("bot.handlers.ask_ai", return_value="բարև") as mock_ask,
        patch("bot.handlers.send_reply"),
        patch("bot.handlers.bot"),
    ):
        from bot.handlers import handle_message

        handle_message(make_message(text="Բարև"))
        assert mock_ask.call_args.kwargs["provider"] is None


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
        patch("bot.handlers.send_reply") as mock_send,
        patch("bot.handlers.bot"),
    ):
        from bot.handlers import cmd_debug

        cmd_debug(make_message(text="/debug print(x"))
        prompt = mock_ask.call_args[0][1]
        assert "print(x" in prompt
        # replies go through send_reply (splits long code, renders Markdown)
        assert mock_send.call_args[0][1] == "Fixed"


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
        patch("bot.handlers.send_reply") as mock_send,
        patch("bot.handlers.bot"),
    ):
        from bot.handlers import cmd_review

        cmd_review(make_message(text="/review def f(): pass"))
        prompt = mock_ask.call_args[0][1]
        assert "def f(): pass" in prompt
        assert mock_send.call_args[0][1] == "Looks good"


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
        patch("bot.handlers.send_reply") as mock_send,
        patch("bot.handlers.bot"),
    ):
        from bot.handlers import _grade_quiz

        _grade_quiz(make_message(text="a list is ordered"), "What is a list?")
        prompt = mock_ask.call_args[0][1]
        assert "What is a list?" in prompt
        assert "a list is ordered" in prompt
        assert mock_send.call_args[0][1] == "Correct!"


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
        patch("bot.handlers.send_reply") as mock_send,
        patch("bot.handlers.bot"),
    ):
        from bot.handlers import cmd_summarize

        cmd_summarize(make_message(text="/summarize a long article about bees"))
        prompt = mock_ask.call_args[0][1]
        assert "a long article about bees" in prompt
        assert mock_send.call_args[0][1] == "Short summary"


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


def test_available_models_main_only_by_default():
    """No alternate Cerebras models and no HF -> just 'main'. Alternate ids are
    opt-in via ALT_CEREBRAS_MODELS so we never advertise a model the account
    can't access."""
    import bot.handlers

    with (
        patch("bot.handlers.HF_SPACE_ID", ""),
        patch("bot.handlers.ALT_CEREBRAS_MODELS", []),
        patch("bot.handlers.MODEL", "gpt-oss-120b"),
    ):
        models = bot.handlers.available_models()
        assert [m["key"] for m in models] == ["main"]
        assert models[0]["name"] == "gpt-oss-120b"
        assert models[0]["description"]


def test_available_models_includes_alt_and_hf_when_configured():
    import bot.handlers

    with (
        patch("bot.handlers.HF_SPACE_ID", "fake/space"),
        patch("bot.handlers.ALT_CEREBRAS_MODELS", ["llama3.1-8b"]),
        patch("bot.handlers.MODEL", "gpt-oss-120b"),
    ):
        keys = [m["key"] for m in bot.handlers.available_models()]
        assert keys == ["main", "llama3.1-8b", "hf"]


def test_available_models_default_offers_gemma_and_glm_with_descriptions():
    """The default registry offers the extra Cerebras models with their
    strengths, so /model and /help can present them."""
    import bot.handlers

    with patch("bot.handlers.HF_SPACE_ID", ""):
        models = bot.handlers.available_models()
        keys = [m["key"] for m in models]
        assert "gemma-4-31b" in keys
        assert "zai-glm-4.7" in keys
        gemma = next(m for m in models if m["key"] == "gemma-4-31b")
        assert "Armenian" in gemma["description"]


def test_armenian_override_none_for_english_and_hf():
    """No override for English text, and never override an 'hf' user (ArmGPT is
    Armenian-native already)."""
    import bot.handlers

    with patch("bot.handlers.ARMENIAN_MODEL", "gemma-4-31b"):
        # English -> None (get_provider not even consulted)
        assert bot.handlers._armenian_provider_override(1, "hello there") is None
        with patch("bot.handlers.get_provider", return_value="hf"):
            assert bot.handlers._armenian_provider_override(1, "Բարև") is None
        with patch("bot.handlers.get_provider", return_value="main"):
            assert bot.handlers._armenian_provider_override(1, "Բարև") == "gemma-4-31b"


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
        patch("bot.handlers.ALT_CEREBRAS_MODELS", ["llama3.1-8b"]),
        patch("bot.handlers.MODEL", "gpt-oss-120b"),
    ):
        assert bot.handlers._resolve_model("hf")["key"] == "hf"
        assert bot.handlers._resolve_model("ArmGPT")["key"] == "hf"
        assert bot.handlers._resolve_model("MAIN")["key"] == "main"
        assert bot.handlers._resolve_model("gpt-oss-120b")["key"] == "main"
        assert bot.handlers._resolve_model("llama3.1-8b")["key"] == "llama3.1-8b"
        assert bot.handlers._resolve_model("nope") is None


# ── /model command ──────────────────────────────────────────────────────────────


def test_cmd_model_no_args_shows_current_single_model():
    from bot.handlers import cmd_model

    with (
        patch("bot.handlers.HF_SPACE_ID", ""),
        patch("bot.handlers.ALT_CEREBRAS_MODELS", []),
        patch("bot.handlers.MODEL", "gpt-oss-120b"),
        patch("bot.handlers.get_provider", return_value="main"),
        patch("bot.handlers.bot") as mock_bot,
    ):
        cmd_model(make_message(text="/model"))
        sent = mock_bot.send_message.call_args[0][1]
        assert sent == "Current model: gpt-oss-120b"


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
        assert "Switched to" in sent
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


def test_cmd_models_single_model_no_switch_hint():
    from bot.handlers import cmd_models

    with (
        patch("bot.handlers.HF_SPACE_ID", ""),
        patch("bot.handlers.ALT_CEREBRAS_MODELS", []),
        patch("bot.handlers.MODEL", "qwen-3-235b-a22b-instruct-2507"),
        patch("bot.handlers.get_provider", return_value="main"),
        patch("bot.handlers.bot") as mock_bot,
    ):
        cmd_models(make_message(text="/models"))
        sent = mock_bot.send_message.call_args[0][1]
        main_line = next(line for line in sent.splitlines() if "qwen-3-235b-a22b-instruct-2507" in line)
        assert "active" in main_line
        assert "Switch with" not in sent


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


# ── /edit (image editing) ────────────────────────────────────────────────────


def _photo_message(text="", file_id="photo_fid", chat_id=456):
    """A message carrying a Telegram photo (photo[-1].file_id == file_id)."""
    msg = MagicMock()
    msg.text = text
    msg.from_user.id = 123
    msg.chat.id = chat_id
    msg.reply_to_message = None
    photo = MagicMock()
    photo.file_id = file_id
    msg.photo = [photo]
    msg.document = None
    return msg


def test_cmd_edit_no_prompt_shows_usage():
    with patch("bot.handlers.bot") as mock_bot:
        from bot.handlers import cmd_edit

        cmd_edit(make_message(text="/edit"))
        mock_bot.register_next_step_handler.assert_not_called()
        assert "Usage" in mock_bot.send_message.call_args[0][1]


def test_cmd_edit_asks_for_image_and_registers_next_step():
    with patch("bot.handlers.bot") as mock_bot:
        from bot.handlers import cmd_edit, _do_edit

        sent = MagicMock()
        mock_bot.send_message.return_value = sent
        # make_message sets reply_to_message = None, so no one-step flow.
        cmd_edit(make_message(text="/edit make the sky a sunset"))
        args = mock_bot.register_next_step_handler.call_args[0]
        assert args[0] is sent
        assert args[1] is _do_edit
        assert args[2] == "make the sky a sunset"


def test_cmd_edit_reply_to_photo_edits_immediately():
    """Replying to a photo with '/edit <prompt>' skips the ask-for-image step
    and edits right away, passing the replied photo's file_id."""
    with (
        patch("bot.handlers._do_edit") as mock_do,
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import cmd_edit

        msg = make_message(text="/edit make it blue")
        msg.reply_to_message = _photo_message(file_id="src_fid")
        cmd_edit(msg)
        mock_bot.register_next_step_handler.assert_not_called()
        mock_do.assert_called_once_with(msg, "make it blue", "src_fid")


def test_do_edit_downloads_source_and_sends_result():
    with (
        patch("bot.handlers._edit_image", return_value=b"x" * 2000) as mock_edit,
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import _do_edit

        mock_bot.get_file.return_value = MagicMock(file_path="path/to/src.jpg")
        mock_bot.download_file.return_value = b"source-bytes"
        _do_edit(make_message(), "make it blue", file_id="fid")
        mock_bot.get_file.assert_called_once_with("fid")
        mock_bot.download_file.assert_called_once_with("path/to/src.jpg")
        # prompt + downloaded bytes are handed to the edit backend
        assert mock_edit.call_args[0][0] == "make it blue"
        assert mock_edit.call_args[0][1] == b"source-bytes"
        assert mock_bot.send_photo.called


def test_do_edit_non_image_cancels():
    with (
        patch("bot.handlers._edit_image") as mock_edit,
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import _do_edit

        msg = make_message()
        msg.photo = None
        msg.document = None
        _do_edit(msg, "make it blue")  # no file_id, nothing attached
        mock_edit.assert_not_called()
        assert "wasn't an image" in mock_bot.send_message.call_args[0][1]


def test_do_edit_reports_backend_error():
    with (
        patch("bot.handlers._edit_image", side_effect=RuntimeError("no backend")),
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import _do_edit

        mock_bot.get_file.return_value = MagicMock(file_path="p")
        mock_bot.download_file.return_value = b"bytes"
        _do_edit(make_message(), "make it blue", file_id="fid")
        assert "Couldn't edit" in mock_bot.send_message.call_args[0][1]
        assert "no backend" in mock_bot.send_message.call_args[0][1]


def test_edit_command_in_caption_detects_edit():
    import bot.handlers

    with patch("bot.handlers.is_allowed", return_value=True):
        yes = MagicMock(caption="/edit make it blue")
        no1 = MagicMock(caption="/image a cat")
        no2 = MagicMock(caption="just a photo")
        atbot = MagicMock(caption="/edit@testbot make it blue")
        assert bot.handlers._edit_command_in_caption(yes) is True
        assert bot.handlers._edit_command_in_caption(atbot) is True
        assert bot.handlers._edit_command_in_caption(no1) is False
        assert bot.handlers._edit_command_in_caption(no2) is False


def test_cmd_edit_caption_edits_photo_with_caption():
    """A photo captioned '/edit <prompt>' should edit immediately, passing the
    photo's file_id — the gesture telebot's command matcher misses."""
    with (
        patch("bot.handlers._do_edit") as mock_do,
        patch("bot.handlers.bot"),
    ):
        from bot.handlers import cmd_edit_caption

        msg = _photo_message(file_id="cap_fid")
        msg.caption = "/edit make it blue"
        cmd_edit_caption(msg)
        mock_do.assert_called_once_with(msg, "make it blue", "cap_fid")


def test_cmd_edit_caption_no_prompt_shows_hint():
    with (
        patch("bot.handlers._do_edit") as mock_do,
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import cmd_edit_caption

        msg = _photo_message(file_id="cap_fid")
        msg.caption = "/edit"
        cmd_edit_caption(msg)
        mock_do.assert_not_called()
        assert "/edit" in mock_bot.send_message.call_args[0][1]


def test_edit_image_prefers_hf_kontext():
    """Free FLUX.1 Kontext (an HF Space) is the preferred /edit backend."""
    import bot.handlers

    with (
        patch("bot.handlers.HF_EDIT_SPACE", "black-forest-labs/FLUX.1-Kontext-Dev"),
        patch("bot.handlers._edit_image_hf", return_value=b"kontext") as mock_hf,
        patch("bot.handlers._edit_image_together") as mock_t,
        patch("bot.handlers._edit_image_cloudflare") as mock_cf,
    ):
        assert bot.handlers._edit_image("p", b"img") == b"kontext"
        mock_hf.assert_called_once()
        mock_t.assert_not_called()
        mock_cf.assert_not_called()


def test_edit_image_prefers_together_when_no_hf():
    import bot.handlers

    with (
        patch("bot.handlers.HF_EDIT_SPACE", ""),
        patch("bot.handlers.TOGETHER_API_KEY", "tk"),
        patch("bot.handlers._edit_image_together", return_value=b"together") as mock_t,
        patch("bot.handlers._edit_image_cloudflare") as mock_cf,
    ):
        assert bot.handlers._edit_image("p", b"img") == b"together"
        mock_t.assert_called_once()
        mock_cf.assert_not_called()


def test_edit_image_uses_cloudflare_when_no_hf_or_together():
    import bot.handlers

    with (
        patch("bot.handlers.HF_EDIT_SPACE", ""),
        patch("bot.handlers.TOGETHER_API_KEY", ""),
        patch("bot.handlers.CF_ACCOUNT_ID", "acct"),
        patch("bot.handlers.CF_API_TOKEN", "tok"),
        patch("bot.handlers._edit_image_cloudflare", return_value=b"cf") as mock_cf,
    ):
        assert bot.handlers._edit_image("p", b"img") == b"cf"
        mock_cf.assert_called_once()


def test_edit_image_raises_when_no_backend_configured():
    import bot.handlers
    import pytest

    with (
        patch("bot.handlers.HF_EDIT_SPACE", ""),
        patch("bot.handlers.TOGETHER_API_KEY", ""),
        patch("bot.handlers.CF_ACCOUNT_ID", ""),
        patch("bot.handlers.CF_API_TOKEN", ""),
    ):
        with pytest.raises(RuntimeError):
            bot.handlers._edit_image("p", b"img")


# --- Armenian prompt translation for /image + /edit -------------------------

def test_has_armenian_detects_armenian_and_ignores_english():
    import bot.handlers

    assert bot.handlers._has_armenian("կատու ձյան մեջ") is True
    assert bot.handlers._has_armenian("a cat in the snow") is False
    assert bot.handlers._has_armenian("") is False


def test_translate_prompt_translates_armenian_via_ai():
    """An Armenian prompt is routed through the chat model and the English
    translation is what reaches the image backend."""
    import bot.handlers

    with patch(
        "bot.providers._call_main", return_value="a cat in the snow"
    ) as mock_ai:
        out = bot.handlers._translate_prompt_for_image("կատու ձյան մեջ")
        assert out == "a cat in the snow"
        mock_ai.assert_called_once()


def test_translate_prompt_skips_english_without_ai_call():
    """English prompts never incur a translation round-trip."""
    import bot.handlers

    with patch("bot.providers._call_main") as mock_ai:
        out = bot.handlers._translate_prompt_for_image("a cat in the snow")
        assert out == "a cat in the snow"
        mock_ai.assert_not_called()


def test_translate_prompt_falls_back_to_original_on_failure():
    """If translation errors, /image still runs on the original prompt."""
    import bot.handlers

    with patch("bot.providers._call_main", side_effect=RuntimeError("down")):
        out = bot.handlers._translate_prompt_for_image("կատու")
        assert out == "կատու"


def test_translate_prompt_falls_back_when_output_untranslated():
    """If the model hands back Armenian (didn't actually translate) or an empty
    string, use the original prompt rather than feeding the backend garbage."""
    import bot.handlers

    with patch("bot.providers._call_main", return_value="կատու"):
        assert bot.handlers._translate_prompt_for_image("կատու") == "կատու"
    with patch("bot.providers._call_main", return_value="  "):
        assert bot.handlers._translate_prompt_for_image("կատու") == "կատու"


def test_translate_prompt_strips_wrapping_quotes():
    """Quotes/backticks a model wraps around the translation are stripped."""
    import bot.handlers

    with patch("bot.providers._call_main", return_value='"a red car"'):
        assert bot.handlers._translate_prompt_for_image("կարմիր մեքենա") == "a red car"


def test_translate_prompt_prefers_dedicated_model():
    """Translation uses IMAGE_TRANSLATE_MODEL (accurate on Armenian), not the
    chat MODEL which mistranslates it."""
    import bot.handlers

    with (
        patch("bot.handlers.IMAGE_TRANSLATE_MODEL", "gemma-4-31b"),
        patch("bot.handlers.MODEL", "gpt-oss-120b"),
        patch("bot.providers._call_main", return_value="an elephant") as mock_ai,
    ):
        out = bot.handlers._translate_prompt_for_image("փիղ")
        assert out == "an elephant"
        assert mock_ai.call_args.kwargs["model"] == "gemma-4-31b"


def test_translate_prompt_falls_back_to_chat_model_when_dedicated_unavailable():
    """If the dedicated model 404s, fall back to MODEL rather than giving up."""
    import bot.handlers

    def fake(messages, retries=1, model=None):
        if model == "gemma-4-31b":
            raise RuntimeError("model_not_found")
        return "an elephant on mars"

    with (
        patch("bot.handlers.IMAGE_TRANSLATE_MODEL", "gemma-4-31b"),
        patch("bot.handlers.MODEL", "gpt-oss-120b"),
        patch("bot.providers._call_main", side_effect=fake),
    ):
        out = bot.handlers._translate_prompt_for_image("փիղ Մարսի վրա")
        assert out == "an elephant on mars"


def test_generate_image_translates_armenian_prompt():
    """_generate_image translates before handing off to the backend."""
    import bot.handlers

    with (
        patch("bot.handlers.TOGETHER_API_KEY", "tk"),
        patch(
            "bot.handlers._translate_prompt_for_image", return_value="translated"
        ) as mock_tr,
        patch(
            "bot.handlers._generate_image_together", return_value=b"img"
        ) as mock_gen,
    ):
        assert bot.handlers._generate_image("կատու") == b"img"
        mock_tr.assert_called_once_with("կատու")
        mock_gen.assert_called_once()
        assert mock_gen.call_args.args[0] == "translated"


# --- /help (one message per category) --------------------------------------


def test_cmd_help_sends_one_message_per_category():
    import bot.handlers

    with (
        patch("bot.handlers.HF_SPACE_ID", ""),
        patch("bot.handlers.ALT_CEREBRAS_MODELS", ["gemma-4-31b", "zai-glm-4.7"]),
        patch("bot.handlers.MODEL", "gpt-oss-120b"),
        patch("bot.handlers.ARMENIAN_MODEL", "gemma-4-31b"),
        patch("bot.handlers.get_provider", return_value="main"),
        patch("bot.handlers.send_reply") as mock_reply,
        patch("bot.handlers.bot"),
    ):
        from bot.handlers import cmd_help, COMMAND_CATEGORIES

        cmd_help(make_message(text="/help"))
        # one message per category, each led by its title...
        for call, (title, _cmds) in zip(mock_reply.call_args_list, COMMAND_CATEGORIES):
            text = call[0][1]
            assert title in text
        # ...plus a trailing "AI models" message when >1 model is available
        assert mock_reply.call_count == len(COMMAND_CATEGORIES) + 1
        models_msg = mock_reply.call_args_list[-1][0][1]
        assert "AI models" in models_msg
        assert "gemma-4-31b" in models_msg
        assert "Armenian" in models_msg


def test_command_categories_have_no_duplicate_commands():
    import bot.handlers

    names = [name for _title, cmds in bot.handlers.COMMAND_CATEGORIES for name, _ in cmds]
    assert len(names) == len(set(names)), "a command is listed in two categories"
    # the flat COMMANDS list is exactly the categories flattened
    assert [n for n, _ in bot.handlers.COMMANDS] == names
