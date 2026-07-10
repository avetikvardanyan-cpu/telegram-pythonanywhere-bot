import base64
import colorsys
import hashlib
import html
import io
import json
import os
import random
import re
import secrets
import string
import time
import uuid
from datetime import date, datetime, timezone
from urllib.parse import quote, unquote
from bot.clients import bot, BOT_INFO, store
from bot.config import (
    ALT_CEREBRAS_MODELS,
    CF_ACCOUNT_ID,
    CF_API_TOKEN,
    CF_EDIT_MODEL,
    CF_IMAGE_MODEL,
    COMMIT_SHA,
    HF_EDIT_GUIDANCE,
    HF_EDIT_SPACE,
    HF_EDIT_STEPS,
    HF_EDIT_TIMEOUT,
    HF_SPACE_ID,
    HF_TOKEN,
    HOSTING_LABEL,
    ARMENIAN_MODEL,
    IMAGE_TRANSLATE_MODEL,
    MODEL,
    MODEL_INFO,
    RATE_LIMIT,
    TOGETHER_API_KEY,
    TOGETHER_EDIT_MODEL,
    TOGETHER_IMAGE_MODEL,
)
from bot.ai import ask_ai
from bot.helpers import is_admin, is_allowed, keep_typing, send_reply, should_respond
from bot.history import clear_history
from bot.preferences import get_provider, set_provider
from bot.rate_limit import is_rate_limited
from bot.users import all_users, user_count


VERBOSE_LOG = os.environ.get("BOT_VERBOSE_LOG", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def _log(message, direction: str, text: str) -> None:
    """Print a one-line trace of a message in verbose mode.

    direction is "in" (user → bot) or "out" (bot → user). Text is
    truncated to 500 characters so long AI replies don't flood the
    terminal. Newlines are collapsed for single-line readability.
    """
    if not VERBOSE_LOG:
        return
    user = message.from_user
    user_name = (
        f"@{user.username}" if user.username else (user.first_name or f"user:{user.id}")
    )
    bot_name = f"@{BOT_INFO.username}"
    snippet = (text or "").replace("\n", " ").replace("\r", " ")
    if len(snippet) > 500:
        snippet = snippet[:500] + "..."
    if direction == "in":
        sender, receiver = user_name, bot_name
    else:
        sender, receiver = bot_name, user_name
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {sender} → {receiver}: {snippet}", flush=True)


# Single source of truth for the bot's command list. Drives both /help
# and the Telegram "/" autocomplete menu (registered via set_my_commands
# in bot.clients.register_commands). Add a new command here when you add
# its handler, or it won't show up in the menu.
# Single source of truth for the bot's commands, grouped into categories.
# COMMAND_CATEGORIES drives three things: the per-category /help messages,
# the flat COMMANDS list below, and (via command_menu -> register_commands
# in bot.clients) the Telegram "/" autocomplete menu. Add a new command to
# the right category here when you add its handler, or it won't show up.
COMMAND_CATEGORIES = [
    ("🤖 Bot & session", [
        ("start", "welcome message"),
        ("help", "show this message"),
        ("reset", "clear conversation history"),
        ("about", "about this bot"),
        ("model", "show or switch the AI model"),
        ("models", "list the available AI models"),
        ("sha", "show the running version (commit SHA)"),
    ]),
    ("🎉 Fun & random", [
        ("joke", "tell a programming joke"),
        ("quote", "tell a coding quote"),
        ("fact", "tell a coding fact"),
        ("compliment", "give a compliment"),
        ("motivate", "get a motivational boost"),
        ("roast", "get roasted"),
        ("roll", "roll the dice"),
        ("coin", "flip a coin"),
        ("random", "random number in a range"),
        ("pick", "pick a random option"),
    ]),
    ("📚 Learn & explain", [
        ("explain", "explain a coding topic"),
        ("eli5", "explain a topic super simply"),
        ("analogy", "explain a concept by analogy"),
        ("cheatsheet", "quick reference for a topic"),
        ("roadmap", "learning roadmap for a skill"),
        ("challenge", "get a coding challenge"),
        ("quiz", "take a quick quiz on a topic"),
        ("interview", "get an interview question"),
        ("compare", "compare two languages, tools, or ideas"),
        ("http", "explain an HTTP status code"),
    ]),
    ("✍️ Write code", [
        ("snippet", "generate a code snippet"),
        ("pseudocode", "write pseudocode for a task"),
        ("algo", "suggest an algorithm for a problem"),
        ("scaffold", "starter project scaffold"),
        ("cli", "build a command-line parser"),
        ("decorator", "write a decorator/wrapper"),
        ("middleware", "write middleware"),
        ("webhook", "write a webhook handler"),
        ("orm", "write ORM model code"),
        ("auth", "outline authentication for a stack"),
        ("jwt", "generate JWT auth code"),
        ("validate", "write input-validation code"),
        ("logging", "add logging to code"),
        ("retry", "add retry logic to code"),
        ("cache", "add caching to code"),
        ("pagination", "implement pagination"),
        ("migration", "write a database migration"),
        ("async", "convert code to async"),
        ("memoize", "add memoization to a function"),
        ("mock", "generate test mocks/stubs"),
        ("fixture", "generate test fixtures"),
    ]),
    ("🔧 Understand & improve code", [
        ("explaincode", "explain what a piece of code does"),
        ("translate", "translate code to another language"),
        ("debug", "find the bug in your code"),
        ("error", "explain and fix an error message"),
        ("review", "get a short code review"),
        ("lint", "check code for style/lint issues"),
        ("optimize", "optimize code for speed and clarity"),
        ("refactor", "restructure code for readability"),
        ("oneliner", "condense code into a one-liner"),
        ("types", "add type hints to code"),
        ("document", "add docstrings and comments to code"),
        ("test", "generate unit tests for your code"),
        ("edgecases", "list edge cases to handle"),
        ("complexity", "analyze time & space complexity"),
        ("security", "check code for security issues"),
        ("name", "suggest names for variables/functions"),
        ("benchmark", "write a micro-benchmark for code"),
        ("solid", "refactor toward SOLID"),
        ("dry", "remove duplicate code (DRY)"),
    ]),
    ("🗄️ APIs, data & queries", [
        ("api", "design a REST API"),
        ("schema", "design a database schema"),
        ("sql", "write a SQL query from a description"),
        ("sqlformat", "format a SQL query"),
        ("graphql", "design a GraphQL schema"),
        ("openapi", "generate an OpenAPI (Swagger) spec"),
        ("mockdata", "generate mock JSON data"),
        ("regex", "build or explain a regular expression"),
        ("regexplain", "explain a regular expression"),
    ]),
    ("⚙️ DevOps, git & config", [
        ("bash", "write a bash command or script"),
        ("curl", "build a curl command for an API"),
        ("cron", "build and explain a cron expression"),
        ("dockerfile", "generate a Dockerfile for a stack"),
        ("gitignore", "generate a .gitignore for a stack"),
        ("ci", "generate a GitHub Actions workflow"),
        ("makefile", "generate a Makefile"),
        ("compose", "generate a docker-compose.yml"),
        ("dotenv", "generate a sample .env"),
        ("k8s", "generate a Kubernetes manifest"),
        ("terraform", "generate Terraform config"),
        ("nginx", "generate an nginx config"),
        ("git", "get git commands for a task"),
        ("commit", "write a git commit message"),
        ("pr", "write a pull request description"),
        ("semver", "suggest the next semantic version"),
        ("changelog", "write a changelog entry"),
        ("readme", "generate a README"),
    ]),
    ("🏗️ Design & architecture", [
        ("design", "high-level system design"),
        ("pattern", "suggest a design pattern"),
        ("stack", "recommend a tech stack"),
        ("userstory", "write a user story"),
        ("mermaid", "generate a Mermaid diagram"),
        ("uml", "describe a UML class diagram"),
        ("flowchart", "turn a process into a flowchart"),
    ]),
    ("🔤 Text & converters", [
        ("summarize", "summarize a block of text"),
        ("case", "convert text between naming cases"),
        ("slug", "make a URL slug from text"),
        ("reverse", "reverse text"),
        ("count", "count characters, words, and lines"),
        ("lorem", "generate lorem ipsum placeholder text"),
        ("json", "pretty-print and validate JSON"),
        ("base64", "encode or decode base64"),
        ("urlencode", "URL-encode or decode text"),
        ("hash", "hash text (md5, sha1, sha256)"),
        ("color", "convert colors (hex, rgb, hsl)"),
        ("uuid", "generate a random UUID"),
        ("password", "generate a strong password"),
        ("timestamp", "unix timestamp tools"),
        ("base", "convert number bases (bin/hex/dec)"),
        ("sort", "sort lines alphabetically"),
        ("dedupe", "remove duplicate lines"),
        ("trim", "collapse and trim whitespace"),
        ("rot13", "ROT13 encode/decode text"),
        ("morse", "text to/from Morse code"),
        ("charcode", "char to/from code point"),
    ]),
    ("🖼️ Media & files", [
        ("image", "generate an image from a prompt"),
        ("edit", "edit an image with an instruction"),
        ("qr", "generate a QR code image"),
        ("shorten", "shorten a URL"),
        ("define", "define a word"),
        ("convert", "convert image formats (jpg, png, webp...)"),
        ("topdf", "turn text into a PDF file"),
        ("pdf", "save this conversation as a PDF"),
    ]),
    ("📝 Notes", [
        ("remember", "save a note"),
        ("recall", "list your notes"),
        ("forget", "clear your notes"),
    ]),
]

# Flat (command, description) list derived from the categories — the single
# source used by the Telegram "/" autocomplete menu and command_menu().
COMMANDS = [cmd for _title, cmds in COMMAND_CATEGORIES for cmd in cmds]


def command_menu():
    """Full flat (command, description) list, derived from COMMAND_CATEGORIES.
    Used by register_commands() (bot.clients) for the "/" autocomplete menu and
    by /help. /model, /models, and /sha live in the "Bot & session" category
    because they are always available (they introspect / switch the active
    model and report the running version, regardless of HF config). Telegram's
    set_my_commands accepts at most 100 commands, so register_commands() caps it
    there — /help still lists everything, grouped per category."""
    return list(COMMANDS)


# Small helper so new handlers can safely read the text after the command
# without the trailing-space IndexError that "text.split()[1]" can hit.
def _arg(message):
    parts = (message.text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


@bot.message_handler(commands=["start"], func=is_allowed)
def cmd_start(message):
    bot.send_message(
        message.chat.id,
        "Hello! I'm your AI coding assistant. If you don't know what to ask, try /help for a list of commands.",
    )


@bot.message_handler(commands=["joke"], func=is_allowed)
def cmd_joke(message):
    reply = ask_ai(
        message.from_user.id,
        "Tell me one original, clean programming or tech joke. "
        "Keep it short (1-2 lines) and make sure it actually lands with a clever punchline. "
        "Reply with only the joke — no preamble, no explanation.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["quote"], func=is_allowed)
def cmd_quote(message):
    reply = ask_ai(
        message.from_user.id,
        "Share one memorable quote about programming, software, or technology. "
        "Attribute it to the real author if known. "
        "Format it as:\n\"<quote>\"\n— <author>\n"
        "Reply with only the quote — no preamble, no explanation.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["fact"], func=is_allowed)
def cmd_fact(message):
    reply = ask_ai(
        message.from_user.id,
        "Share one genuinely surprising, true fact about computing, programming, or tech history. "
        "Keep it to 1-3 sentences and make it something most people wouldn't already know. "
        "Reply with only the fact — no preamble, no explanation.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["compliment"], func=is_allowed)
def cmd_compliment(message):
    reply = ask_ai(
        message.from_user.id,
        "Give me one warm, genuine, and original compliment. "
        "Make it uplifting and specific rather than generic flattery, and keep it to 1-2 sentences. "
        "Reply with only the compliment — no preamble, no explanation.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["explain"], func=is_allowed)
def cmd_explain(message):
    topic = message.text.split(maxsplit=1)[1].strip() if " " in message.text else ""
    if not topic:
        bot.send_message(message.chat.id, "Usage: /explain <topic>  (e.g. /explain recursion)")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Explain this coding topic clearly and simply for a beginner: {topic}. "
        "Use plain language, keep it concise, and include one short example if it helps. "
        "Reply with only the explanation — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["challenge"], func=is_allowed)
def cmd_challenge(message):
    reply = ask_ai(
        message.from_user.id,
        "Give me one small, self-contained programming challenge suitable for a student. "
        "State the task clearly with an example input and expected output. "
        "Keep it beginner-friendly and solvable in a few lines of code. "
        "Do NOT include the solution. Reply with only the challenge — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["analogy"], func=is_allowed)
def cmd_analogy(message):
    concept = message.text.split(maxsplit=1)[1].strip() if " " in message.text else ""
    if not concept:
        bot.send_message(message.chat.id, "Usage: /analogy <concept>  (e.g. /analogy pointers)")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Explain this coding concept using one clear, relatable real-world analogy: {concept}. "
        "Keep it short and make the analogy do the work. Reply with only the analogy — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["motivate"], func=is_allowed)
def cmd_motivate(message):
    reply = ask_ai(
        message.from_user.id,
        "Give me one short, genuine, and uplifting motivational message for a student "
        "who is learning to code and might feel stuck or frustrated. "
        "Keep it warm and encouraging, 1-2 sentences. Reply with only the message — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["translate"], func=is_allowed)
def cmd_translate(message):
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[2].strip():
        bot.send_message(
            message.chat.id,
            "Usage: /translate <language> <code>\n"
            "Example: /translate javascript print('hi')",
        )
        return
    lang = parts[1].strip()
    code = parts[2].strip()
    reply = ask_ai(
        message.from_user.id,
        f"Translate the following code into {lang}. "
        "Keep the same behavior and logic. Reply with only the translated code in a code block, "
        f"followed by one short sentence noting anything that changed.\n\nCode:\n{code}",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["debug"], func=is_allowed)
def cmd_debug(message):
    code = message.text.split(maxsplit=1)[1].strip() if " " in message.text else ""
    if not code:
        bot.send_message(message.chat.id, "Usage: /debug <code>\nPaste the code that isn't working.")
        return
    reply = ask_ai(
        message.from_user.id,
        "Find the bug in the following code. Explain what's wrong in 1-2 sentences, "
        "then show the corrected code in a code block. If there is no bug, say so. "
        f"Keep it concise. Reply with only the answer — no preamble.\n\nCode:\n{code}",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["review"], func=is_allowed)
def cmd_review(message):
    code = message.text.split(maxsplit=1)[1].strip() if " " in message.text else ""
    if not code:
        bot.send_message(message.chat.id, "Usage: /review <code>\nPaste the code you'd like reviewed.")
        return
    reply = ask_ai(
        message.from_user.id,
        "Give a short, constructive code review of the following code. "
        "Point out any bugs, style issues, and one concrete improvement. "
        "Be encouraging and keep it concise. "
        f"Reply with only the review — no preamble.\n\nCode:\n{code}",
    )
    send_reply(message, reply)


# --- Coding tools (AI) ------------------------------------------------------

@bot.message_handler(commands=["snippet"], func=is_allowed)
def cmd_snippet(message):
    task = _arg(message)
    if not task:
        bot.send_message(message.chat.id, "Usage: /snippet <task>  (e.g. /snippet read a JSON file in Python)")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Write a short, correct code snippet for this task: {task}. "
        "Pick a sensible language if none is specified. Reply with only the code in a code "
        "block, plus one short sentence on how to use it. No preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["error"], func=is_allowed)
def cmd_error(message):
    err = _arg(message)
    if not err:
        bot.send_message(message.chat.id, "Usage: /error <error message or traceback>\nPaste the error you're seeing.")
        return
    reply = ask_ai(
        message.from_user.id,
        "Explain the following error in plain language, state the most likely cause, and give "
        "a concrete fix. Keep it concise. Reply with only the answer — no preamble.\n\n"
        f"Error:\n{err}",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["optimize"], func=is_allowed)
def cmd_optimize(message):
    code = _arg(message)
    if not code:
        bot.send_message(message.chat.id, "Usage: /optimize <code>\nPaste the code you'd like optimized.")
        return
    reply = ask_ai(
        message.from_user.id,
        "Optimize the following code for performance and readability. Note what you improved "
        "in 1-2 sentences, then show the optimized version in a code block. Keep the same "
        f"behavior. Reply with only the answer — no preamble.\n\nCode:\n{code}",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["refactor"], func=is_allowed)
def cmd_refactor(message):
    code = _arg(message)
    if not code:
        bot.send_message(message.chat.id, "Usage: /refactor <code>\nPaste the code you'd like restructured.")
        return
    reply = ask_ai(
        message.from_user.id,
        "Refactor the following code for readability and clean structure without changing its "
        "behavior. Note the key changes in 1-2 sentences, then show the refactored code in a "
        f"code block. Reply with only the answer — no preamble.\n\nCode:\n{code}",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["test"], func=is_allowed)
def cmd_test(message):
    code = _arg(message)
    if not code:
        bot.send_message(message.chat.id, "Usage: /test <code>\nPaste the function or code you'd like tests for.")
        return
    reply = ask_ai(
        message.from_user.id,
        "Write clear unit tests for the following code. Cover the main cases plus one or two "
        "edge cases, using the language's standard testing style. Reply with only the tests "
        f"in a code block — no preamble.\n\nCode:\n{code}",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["document"], func=is_allowed)
def cmd_document(message):
    code = _arg(message)
    if not code:
        bot.send_message(message.chat.id, "Usage: /document <code>\nPaste the code you'd like documented.")
        return
    reply = ask_ai(
        message.from_user.id,
        "Add clear docstrings and brief inline comments to the following code. Do not change "
        "what the code does. Keep comments concise and useful. Reply with only the documented "
        f"code in a code block — no preamble.\n\nCode:\n{code}",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["complexity"], func=is_allowed)
def cmd_complexity(message):
    code = _arg(message)
    if not code:
        bot.send_message(message.chat.id, "Usage: /complexity <code>\nPaste the code you'd like analyzed.")
        return
    reply = ask_ai(
        message.from_user.id,
        "Analyze the time and space complexity (Big-O) of the following code. State both "
        "clearly, then explain why in 1-2 sentences. If it can be improved, mention the better "
        f"complexity briefly. Reply with only the analysis — no preamble.\n\nCode:\n{code}",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["security"], func=is_allowed)
def cmd_security(message):
    code = _arg(message)
    if not code:
        bot.send_message(message.chat.id, "Usage: /security <code>\nPaste the code you'd like checked.")
        return
    reply = ask_ai(
        message.from_user.id,
        "Review the following code for security issues. List any vulnerabilities you find and "
        "how to fix each one. If it looks safe, say so. Be concise. Reply with only the review "
        f"— no preamble.\n\nCode:\n{code}",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["regex"], func=is_allowed)
def cmd_regex(message):
    desc = _arg(message)
    if not desc:
        bot.send_message(
            message.chat.id,
            "Usage: /regex <what to match>\nExample: /regex a valid email address",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        f"Create a regular expression for: {desc}. Show the regex in a code block, then "
        "explain each part in a few short bullet points and give one matching example. "
        "Keep it concise. Reply with only the answer — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["sql"], func=is_allowed)
def cmd_sql(message):
    req = _arg(message)
    if not req:
        bot.send_message(message.chat.id, "Usage: /sql <what you want>\nExample: /sql top 5 customers by total spend")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Write a SQL query for this request: {req}. Use standard SQL. Show the query in a "
        "code block, then explain it in one or two short sentences. If you assume table or "
        "column names, note them briefly. Reply with only the answer — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["schema"], func=is_allowed)
def cmd_schema(message):
    desc = _arg(message)
    if not desc:
        bot.send_message(
            message.chat.id,
            "Usage: /schema <what to model>\nExample: /schema a blog with users, posts, comments",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        f"Design a database schema for: {desc}. List the tables with their columns, types, and "
        "keys, and note the relationships between them. Keep it concise. Reply with only the "
        "schema — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["api"], func=is_allowed)
def cmd_api(message):
    desc = _arg(message)
    if not desc:
        bot.send_message(message.chat.id, "Usage: /api <what it does>\nExample: /api a todo list service")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Design a simple REST API for: {desc}. List the endpoints (method + path), what each "
        "does, and the key request/response fields. Keep it concise. Reply with only the "
        "design — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["pseudocode"], func=is_allowed)
def cmd_pseudocode(message):
    task = _arg(message)
    if not task:
        bot.send_message(message.chat.id, "Usage: /pseudocode <task>  (e.g. /pseudocode binary search)")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Write clear, language-agnostic pseudocode for this task: {task}. Use simple numbered "
        "steps or indented structure. Reply with only the pseudocode in a code block — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["dockerfile"], func=is_allowed)
def cmd_dockerfile(message):
    stack = _arg(message)
    if not stack:
        bot.send_message(message.chat.id, "Usage: /dockerfile <stack>\nExample: /dockerfile python flask app")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Write a clean, production-reasonable Dockerfile for this stack: {stack}. Use a "
        "sensible base image and good practices (small layers, no secrets). Reply with only the "
        "Dockerfile in a code block, plus one short note if needed. No preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["gitignore"], func=is_allowed)
def cmd_gitignore(message):
    stack = _arg(message)
    if not stack:
        bot.send_message(message.chat.id, "Usage: /gitignore <stack>\nExample: /gitignore node react")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Generate a sensible .gitignore for this stack/tooling: {stack}. Reply with only the "
        ".gitignore contents in a code block — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["git"], func=is_allowed)
def cmd_git(message):
    q = _arg(message)
    if not q:
        bot.send_message(
            message.chat.id,
            "Usage: /git <what you want to do>\nExample: /git undo my last commit but keep the changes",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        f"Answer this git question with the exact commands to run and a one-line explanation of "
        f"each: {q}. Keep it concise. Reply with only the answer — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["commit"], func=is_allowed)
def cmd_commit(message):
    desc = _arg(message)
    if not desc:
        bot.send_message(
            message.chat.id,
            "Usage: /commit <what you changed>\nExample: /commit added login rate limiting",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        f"Write a clear git commit message for this change: {desc}. Use the Conventional "
        "Commits style (e.g. 'feat:', 'fix:', 'docs:'). Give a concise subject line, and 1-3 "
        "short body bullets only if useful. Reply with only the commit message in a code block "
        "— no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["name"], func=is_allowed)
def cmd_name(message):
    desc = _arg(message)
    if not desc:
        bot.send_message(
            message.chat.id,
            "Usage: /name <what it is>\nExample: /name a function that trims whitespace from a string",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        f"Suggest 5 clear, idiomatic names for this, each with a short note: {desc}. Prefer "
        "descriptive, conventional names. Reply with only the list — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["compare"], func=is_allowed)
def cmd_compare(message):
    topic = _arg(message)
    if not topic:
        bot.send_message(message.chat.id, "Usage: /compare <A vs B>\nExample: /compare REST vs GraphQL")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Compare these clearly and fairly: {topic}. Cover the key differences and note when to "
        "use each. Keep it concise and balanced. Reply with only the comparison — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["eli5"], func=is_allowed)
def cmd_eli5(message):
    topic = _arg(message)
    if not topic:
        bot.send_message(message.chat.id, "Usage: /eli5 <topic>  (e.g. /eli5 how does the internet work)")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Explain this like I'm five years old, in simple words with a friendly tone: {topic}. "
        "Keep it to a few short sentences. Reply with only the explanation — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["cheatsheet"], func=is_allowed)
def cmd_cheatsheet(message):
    topic = _arg(message)
    if not topic:
        bot.send_message(message.chat.id, "Usage: /cheatsheet <topic>  (e.g. /cheatsheet git)")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Create a short, practical cheatsheet for: {topic}. List the most useful commands or "
        "concepts with a one-line description each, grouped if it helps. Keep it compact and "
        "skimmable. Reply with only the cheatsheet — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["roadmap"], func=is_allowed)
def cmd_roadmap(message):
    topic = _arg(message)
    if not topic:
        bot.send_message(message.chat.id, "Usage: /roadmap <skill>  (e.g. /roadmap backend web development)")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Create a concise learning roadmap for: {topic}. Give ordered steps or stages from "
        "beginner to advanced, each with a short note. Reply with only the roadmap — no preamble.",
    )
    send_reply(message, reply)


# --- More coding tools (AI) -------------------------------------------------

@bot.message_handler(commands=["explaincode"], func=is_allowed)
def cmd_explaincode(message):
    code = _arg(message)
    if not code:
        bot.send_message(message.chat.id, "Usage: /explaincode <code>\nPaste the code you'd like explained.")
        return
    reply = ask_ai(
        message.from_user.id,
        "Explain what the following code does, step by step and in plain language. Keep it "
        "clear and concise. Reply with only the explanation — no preamble.\n\nCode:\n" + code,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["lint"], func=is_allowed)
def cmd_lint(message):
    code = _arg(message)
    if not code:
        bot.send_message(message.chat.id, "Usage: /lint <code>\nPaste the code you'd like checked.")
        return
    reply = ask_ai(
        message.from_user.id,
        "Point out style and lint issues in the following code (naming, formatting, "
        "conventions, small code smells) and how to fix each. If it's clean, say so. Be "
        "concise. Reply with only the feedback — no preamble.\n\nCode:\n" + code,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["types"], func=is_allowed)
def cmd_types(message):
    code = _arg(message)
    if not code:
        bot.send_message(message.chat.id, "Usage: /types <code>\nPaste the code you'd like type-annotated.")
        return
    reply = ask_ai(
        message.from_user.id,
        "Add type hints/annotations to the following code, using the language's idiomatic "
        "typing. Do not change behavior. Reply with only the annotated code in a code block — "
        "no preamble.\n\nCode:\n" + code,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["oneliner"], func=is_allowed)
def cmd_oneliner(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /oneliner <code or task>\nExample: /oneliner sum the even numbers in a list",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Give a clean, readable one-liner (or the shortest reasonable form) for the following, "
        "keeping it correct. Show it in a code block and add one short note if it hurts "
        "readability. Reply with only the answer — no preamble.\n\nCode/Task:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["edgecases"], func=is_allowed)
def cmd_edgecases(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /edgecases <function or feature>\nExample: /edgecases a function that parses a date string",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "List the important edge cases to handle and test for the following code or feature. "
        "Give a short bulleted list, each with a one-line reason. Reply with only the list — "
        "no preamble.\n\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["algo"], func=is_allowed)
def cmd_algo(message):
    problem = _arg(message)
    if not problem:
        bot.send_message(
            message.chat.id,
            "Usage: /algo <problem>\nExample: /algo find the shortest path in a weighted graph",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        f"Suggest a good algorithm or approach for this problem: {problem}. Name the technique, "
        "give its time/space complexity, and outline the idea in a few sentences. Do NOT write "
        "full code. Reply with only the answer — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["bash"], func=is_allowed)
def cmd_bash(message):
    task = _arg(message)
    if not task:
        bot.send_message(
            message.chat.id,
            "Usage: /bash <task>\nExample: /bash find and delete files older than 30 days",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        f"Write a bash command or short script for this task: {task}. Prefer a safe, portable "
        "one-liner if possible. Show it in a code block, then explain it in one short sentence. "
        "Reply with only the answer — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["curl"], func=is_allowed)
def cmd_curl(message):
    desc = _arg(message)
    if not desc:
        bot.send_message(
            message.chat.id,
            "Usage: /curl <request>\nExample: /curl POST JSON to api.example.com/login with email and password",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        f"Write a curl command for this API request: {desc}. Include sensible headers and "
        "flags. Show it in a code block, then one short line explaining it. Reply with only the "
        "answer — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["cron"], func=is_allowed)
def cmd_cron(message):
    desc = _arg(message)
    if not desc:
        bot.send_message(message.chat.id, "Usage: /cron <schedule in words>\nExample: /cron every weekday at 9:30am")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Create a cron expression for this schedule: {desc}. Show the cron expression in a "
        "code block, then explain each field in one short line. Reply with only the answer — "
        "no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["ci"], func=is_allowed)
def cmd_ci(message):
    desc = _arg(message)
    if not desc:
        bot.send_message(message.chat.id, "Usage: /ci <project/need>\nExample: /ci run pytest on a Python package")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Write a GitHub Actions CI workflow for this: {desc}. Use sensible steps (checkout, "
        "setup, install, test). Reply with only the YAML in a code block, plus one short note "
        "if needed. No preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["scaffold"], func=is_allowed)
def cmd_scaffold(message):
    desc = _arg(message)
    if not desc:
        bot.send_message(message.chat.id, "Usage: /scaffold <project>\nExample: /scaffold a Flask REST API")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Give a starter project scaffold for: {desc}. Show a sensible file/folder structure and "
        "the key starter files with minimal boilerplate. Keep it concise. Reply with only the "
        "scaffold — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["design"], func=is_allowed)
def cmd_design(message):
    desc = _arg(message)
    if not desc:
        bot.send_message(message.chat.id, "Usage: /design <system>\nExample: /design a URL shortener")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Give a high-level system design for: {desc}. Cover the main components, how they "
        "interact, the data flow, and 1-2 key trade-offs. Keep it concise. Reply with only the "
        "design — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["pattern"], func=is_allowed)
def cmd_pattern(message):
    desc = _arg(message)
    if not desc:
        bot.send_message(
            message.chat.id,
            "Usage: /pattern <scenario>\nExample: /pattern many objects need to react to one event",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        f"Suggest a suitable software design pattern for this scenario: {desc}. Name the "
        "pattern, explain why it fits in a few sentences, and sketch how it'd be applied. Reply "
        "with only the answer — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["stack"], func=is_allowed)
def cmd_stack(message):
    desc = _arg(message)
    if not desc:
        bot.send_message(message.chat.id, "Usage: /stack <project>\nExample: /stack a real-time chat app")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Recommend a practical tech stack for this project: {desc}. Suggest choices for the "
        "main layers (frontend, backend, database, hosting as relevant) with a one-line reason "
        "each. Reply with only the recommendation — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["readme"], func=is_allowed)
def cmd_readme(message):
    desc = _arg(message)
    if not desc:
        bot.send_message(message.chat.id, "Usage: /readme <project>\nExample: /readme a CLI tool that renames files")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Write a clear README for this project: {desc}. Include sensible sections (title, "
        "description, features, install, usage). Keep it concise. Reply with only the README in "
        "Markdown — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["makefile"], func=is_allowed)
def cmd_makefile(message):
    stack = _arg(message)
    if not stack:
        bot.send_message(message.chat.id, "Usage: /makefile <stack>\nExample: /makefile a Python project with tests")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Write a useful Makefile for this stack/project: {stack}. Include common targets (e.g. "
        "install, run, test, lint, clean) as relevant. Reply with only the Makefile in a code "
        "block — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["compose"], func=is_allowed)
def cmd_compose(message):
    desc = _arg(message)
    if not desc:
        bot.send_message(
            message.chat.id,
            "Usage: /compose <setup>\nExample: /compose a web app with postgres and redis",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        f"Write a docker-compose.yml for this setup: {desc}. Use sensible services, ports, "
        "volumes, and env. Reply with only the YAML in a code block, plus one short note if "
        "needed. No preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["dotenv"], func=is_allowed)
def cmd_dotenv(message):
    desc = _arg(message)
    if not desc:
        bot.send_message(
            message.chat.id,
            "Usage: /dotenv <stack/app>\nExample: /dotenv a Django app with a database and email",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        f"Generate a sample .env file for this stack/app: {desc}. List the likely environment "
        "variables with placeholder values and a short comment each. Reply with only the .env in "
        "a code block — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["mockdata"], func=is_allowed)
def cmd_mockdata(message):
    desc = _arg(message)
    if not desc:
        bot.send_message(message.chat.id, "Usage: /mockdata <what>\nExample: /mockdata 5 users with name, email, age")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Generate realistic sample/mock data as JSON for: {desc}. Produce a small array (about "
        "3-5 items) with sensible field values. Reply with only the JSON in a code block — no "
        "preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["sqlformat"], func=is_allowed)
def cmd_sqlformat(message):
    sql = _arg(message)
    if not sql:
        bot.send_message(message.chat.id, "Usage: /sqlformat <sql>\nPaste the SQL you'd like formatted.")
        return
    reply = ask_ai(
        message.from_user.id,
        "Reformat the following SQL to be clean and readable (consistent keywords, indentation, "
        "and line breaks) without changing what it does. Reply with only the formatted SQL in a "
        "code block — no preamble.\n\nSQL:\n" + sql,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["regexplain"], func=is_allowed)
def cmd_regexplain(message):
    rx = _arg(message)
    if not rx:
        bot.send_message(message.chat.id, "Usage: /regexplain <regex>\nPaste a regex to have it explained.")
        return
    reply = ask_ai(
        message.from_user.id,
        "Explain the following regular expression piece by piece in plain language, and give one "
        "example of what it matches. Keep it concise. Reply with only the explanation — no "
        "preamble.\n\nRegex:\n" + rx,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["changelog"], func=is_allowed)
def cmd_changelog(message):
    desc = _arg(message)
    if not desc:
        bot.send_message(
            message.chat.id,
            "Usage: /changelog <changes>\nExample: /changelog added dark mode, fixed login bug",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        f"Write a changelog entry for these changes: {desc}. Group items under "
        "Added/Changed/Fixed/Removed as relevant (Keep a Changelog style). Reply with only the "
        "entry in Markdown — no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["userstory"], func=is_allowed)
def cmd_userstory(message):
    desc = _arg(message)
    if not desc:
        bot.send_message(message.chat.id, "Usage: /userstory <feature>\nExample: /userstory password reset via email")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Write a user story for this feature: {desc}. Use the 'As a <role>, I want <goal>, so "
        "that <benefit>' format, followed by 3-5 acceptance criteria. Reply with only the story "
        "— no preamble.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["interview"], func=is_allowed)
def cmd_interview(message):
    topic = _arg(message)
    if not topic:
        bot.send_message(message.chat.id, "Usage: /interview <topic>  (e.g. /interview python, recursion)")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Ask one realistic coding interview question about: {topic}. State the question "
        "clearly, then on a new line briefly note what skill it tests. Do NOT give the "
        "solution. Reply with only that — no preamble.",
    )
    send_reply(message, reply)


# --- 30 more coding tools (AI) ----------------------------------------------

@bot.message_handler(commands=["mermaid"], func=is_allowed)
def cmd_mermaid(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /mermaid <description>\nExample: /mermaid login flow for a web app",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Create a Mermaid diagram for the following. Choose the best diagram type (flowchart, "
        "sequence, class, etc.). Reply with only the Mermaid code in a code block, plus one "
        "short note. "
        "\n\nDescribe:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["uml"], func=is_allowed)
def cmd_uml(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /uml <system>\nExample: /uml an online store with orders and products",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Describe a UML class diagram for the following system. List the classes with their "
        "key attributes and methods, and the relationships between them. Keep it concise. "
        "Reply with only the design — no preamble. "
        "\n\nSystem:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["flowchart"], func=is_allowed)
def cmd_flowchart(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /flowchart <process>\nExample: /flowchart how a password reset works",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Turn the following process into a clear text flowchart using arrows and simple steps. "
        "Number the steps and show any branches. Reply with only the flowchart — no preamble. "
        "\n\nProcess:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["benchmark"], func=is_allowed)
def cmd_benchmark(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /benchmark <code>\nPaste the code you want benchmarked.",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Write a small, correct micro-benchmark that measures the performance of the following "
        "code, using the language's standard timing tools. Reply with only the benchmark in a "
        "code block, plus one short note on how to read the result. "
        "\n\nCode:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["graphql"], func=is_allowed)
def cmd_graphql(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /graphql <what it models>\nExample: /graphql a blog with posts and authors",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Design a GraphQL schema (SDL) for the following. Include the main types, queries, and "
        "mutations. Reply with only the schema in a code block — no preamble. "
        "\n\nRequirement:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["openapi"], func=is_allowed)
def cmd_openapi(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /openapi <API>\nExample: /openapi a todo list REST API",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Write a concise OpenAPI 3 (Swagger) spec in YAML for the following API. Include a "
        "couple of representative paths with their methods, parameters, and responses. Reply "
        "with only the YAML in a code block — no preamble. "
        "\n\nAPI:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["k8s"], func=is_allowed)
def cmd_k8s(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /k8s <what to deploy>\nExample: /k8s a stateless web app with 3 replicas",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Write a sensible Kubernetes manifest (YAML) for the following. Use good defaults "
        "(resource limits, labels, a Service if it fits). Reply with only the YAML in a code "
        "block, plus one short note. "
        "\n\nDeploy:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["terraform"], func=is_allowed)
def cmd_terraform(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /terraform <resource>\nExample: /terraform an AWS S3 bucket with versioning",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Write clean Terraform (HCL) for the following. Use sensible defaults and note any "
        "required variables. Reply with only the Terraform in a code block, plus one short "
        "note. "
        "\n\nResource:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["nginx"], func=is_allowed)
def cmd_nginx(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /nginx <need>\nExample: /nginx reverse proxy to a local app on port 8000",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Write a clean nginx configuration for the following. Include only the relevant "
        "server/location blocks with good defaults. Reply with only the config in a code "
        "block, plus one short note. "
        "\n\nNeed:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["orm"], func=is_allowed)
def cmd_orm(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /orm <model>\nExample: /orm a User with email and posts (SQLAlchemy)",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Write ORM model code for the following. If no ORM is named, pick a common one and say "
        "which. Include fields, types, and relationships. Reply with only the code in a code "
        "block, plus one short note. "
        "\n\nModel:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["auth"], func=is_allowed)
def cmd_auth(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /auth <stack/need>\nExample: /auth email and password login for a Flask app",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Explain how to implement secure authentication for the following, with the key steps "
        "and a minimal code sketch. Mention password hashing and session or token handling. "
        "Keep it concise. Reply with only the answer — no preamble. "
        "\n\nNeed:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["jwt"], func=is_allowed)
def cmd_jwt(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /jwt <stack>\nExample: /jwt issue and verify a JWT in Node.js",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Write minimal, correct code to issue and verify a JSON Web Token for the following "
        "stack. Note the secret and expiry handling. Reply with only the code in a code block, "
        "plus one short note. "
        "\n\nStack:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["validate"], func=is_allowed)
def cmd_validate(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /validate <what to validate>\nExample: /validate a signup form (email, password)",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Write clear input-validation code for the following. Check the important constraints "
        "and return helpful errors. Pick a sensible language or library if none is given. "
        "Reply with only the code in a code block — no preamble. "
        "\n\nValidate:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["logging"], func=is_allowed)
def cmd_logging(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /logging <code>\nPaste the code you want logging added to.",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Add sensible, idiomatic logging to the following code (useful levels and messages, no "
        "noisy spam) without changing its behavior. Reply with only the updated code in a code "
        "block, plus one short note. "
        "\n\nCode:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["retry"], func=is_allowed)
def cmd_retry(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /retry <code>\nPaste the code you want retry logic for.",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Add robust retry logic with exponential backoff to the following code, retrying only "
        "on transient errors. Keep behavior otherwise identical. Reply with only the updated "
        "code in a code block, plus one short note. "
        "\n\nCode:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["cache"], func=is_allowed)
def cmd_cache(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /cache <code or task>\nExample: /cache memoize an expensive function",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Add appropriate caching to the following, choosing a sensible strategy (in-memory, "
        "memoization, or TTL). Keep correctness. Reply with only the code in a code block, "
        "plus one short note on the trade-offs. "
        "\n\nCode/Task:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["pagination"], func=is_allowed)
def cmd_pagination(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /pagination <what to paginate>\nExample: /pagination a product list in a REST API",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Show how to implement pagination for the following. Cover the approach (offset or "
        "cursor) and give a concise code example. Reply with only the answer — no preamble. "
        "\n\nRequirement:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["migration"], func=is_allowed)
def cmd_migration(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /migration <change>\nExample: /migration add a nullable phone column to users",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Write a database migration for the following change. Include both the up and down "
        "steps. Pick a common migration style if none is given and say which. Reply with only "
        "the migration in a code block — no preamble. "
        "\n\nChange:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["mock"], func=is_allowed)
def cmd_mock(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /mock <what to mock>\nExample: /mock an HTTP client used by a service",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Write test mocks or stubs for the following, using the language's standard mocking "
        "approach. Show a short example test that uses them. Reply with only the code in a "
        "code block — no preamble. "
        "\n\nMock:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["fixture"], func=is_allowed)
def cmd_fixture(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /fixture <what to set up>\nExample: /fixture a temp database with a seeded user",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Write reusable test fixtures for the following setup, using the language's standard "
        "testing style. Reply with only the code in a code block, plus one short note on "
        "usage. "
        "\n\nSetup:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["decorator"], func=is_allowed)
def cmd_decorator(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /decorator <what it should do>\nExample: /decorator time how long a function takes",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Write a clean, reusable decorator or wrapper that does the following. Preserve the "
        "wrapped function's metadata. Show a short usage example. Reply with only the code in "
        "a code block — no preamble. "
        "\n\nBehavior:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["async"], func=is_allowed)
def cmd_async(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /async <code>\nPaste the synchronous code to convert.",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Convert the following synchronous code to an idiomatic asynchronous version, keeping "
        "the same behavior. Note anything callers must change. Reply with only the async code "
        "in a code block, plus one short note. "
        "\n\nCode:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["memoize"], func=is_allowed)
def cmd_memoize(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /memoize <code>\nPaste the function to memoize.",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Add memoization to the following function using an idiomatic approach, keeping "
        "results correct for the same inputs. Reply with only the updated code in a code "
        "block, plus one short note on cache invalidation. "
        "\n\nCode:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["solid"], func=is_allowed)
def cmd_solid(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /solid <code>\nPaste the code you'd like improved.",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Refactor the following code toward the SOLID principles. Name which principles you "
        "applied and why in 1-2 sentences, then show the improved code. Reply with only the "
        "answer — no preamble. "
        "\n\nCode:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["dry"], func=is_allowed)
def cmd_dry(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /dry <code>\nPaste the code with repetition.",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Remove duplication from the following code (DRY) by extracting shared logic, without "
        "changing behavior. Note what you factored out in one sentence, then show the result. "
        "Reply with only the answer — no preamble. "
        "\n\nCode:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["pr"], func=is_allowed)
def cmd_pr(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /pr <what the change does>\nExample: /pr add rate limiting to the login endpoint",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Write a clear pull request description for the following change. Include a short "
        "summary, what changed, and how to test it. Reply with only the description in "
        "Markdown — no preamble. "
        "\n\nChange:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["cli"], func=is_allowed)
def cmd_cli(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /cli <tool>\nExample: /cli a tool that resizes images with --width",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Write a clean command-line argument parser for the following tool, using the "
        "language's standard library. Include the flags, help text, and a main entry point. "
        "Reply with only the code in a code block — no preamble. "
        "\n\nTool:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["middleware"], func=is_allowed)
def cmd_middleware(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /middleware <what it does>\nExample: /middleware log request time in Express",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Write middleware that does the following, for the framework named (pick a common one "
        "if none is given and say which). Reply with only the code in a code block, plus one "
        "short note on where to register it. "
        "\n\nBehavior:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["webhook"], func=is_allowed)
def cmd_webhook(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /webhook <event>\nExample: /webhook handle a Stripe payment success event",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Write a concise, secure webhook handler for the following. Verify the signature if "
        "relevant, parse the payload, and respond correctly. Reply with only the code in a "
        "code block, plus one short note. "
        "\n\nEvent:\n" + arg,
    )
    send_reply(message, reply)


@bot.message_handler(commands=["semver"], func=is_allowed)
def cmd_semver(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /semver <version + changes>\nExample: /semver 1.4.2 with a new compatible feature",
        )
        return
    reply = ask_ai(
        message.from_user.id,
        "Given the current version and the described changes, state the correct next semantic "
        "version (MAJOR.MINOR.PATCH) and explain which part bumped and why in one or two "
        "sentences. Reply with only the answer — no preamble. "
        "\n\nDetails:\n" + arg,
    )
    send_reply(message, reply)


# --- Text & developer utilities (no AI call needed) -------------------------

def _case_words(text):
    """Split arbitrary text into lowercase words, handling spaces, dashes,
    underscores, and camelCase boundaries."""
    text = re.sub(r"[_\-\s]+", " ", text.strip())
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return [w.lower() for w in text.split() if w]


@bot.message_handler(commands=["case"], func=is_allowed)
def cmd_case(message):
    words = _case_words(_arg(message))
    if not words:
        bot.send_message(message.chat.id, "Usage: /case <text>  (e.g. /case get user by id)")
        return
    variants = {
        "snake_case": "_".join(words),
        "kebab-case": "-".join(words),
        "camelCase": words[0] + "".join(w.capitalize() for w in words[1:]),
        "PascalCase": "".join(w.capitalize() for w in words),
        "CONSTANT_CASE": "_".join(w.upper() for w in words),
        "Title Case": " ".join(w.capitalize() for w in words),
    }
    bot.send_message(message.chat.id, "\n".join(f"{k}: {v}" for k, v in variants.items()))


@bot.message_handler(commands=["slug"], func=is_allowed)
def cmd_slug(message):
    text = _arg(message)
    if not text:
        bot.send_message(message.chat.id, "Usage: /slug <text>  (e.g. /slug My First Blog Post!)")
        return
    slug = text.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)      # drop punctuation
    slug = re.sub(r"[\s_]+", "-", slug)        # spaces/underscores -> hyphen
    slug = re.sub(r"-+", "-", slug).strip("-")
    bot.send_message(message.chat.id, slug or "(nothing to slugify)")


@bot.message_handler(commands=["reverse"], func=is_allowed)
def cmd_reverse(message):
    text = _arg(message)
    if not text:
        bot.send_message(message.chat.id, "Usage: /reverse <text>")
        return
    bot.send_message(message.chat.id, text[::-1])


@bot.message_handler(commands=["count"], func=is_allowed)
def cmd_count(message):
    text = message.text.split(maxsplit=1)[1] if len(message.text.split(maxsplit=1)) > 1 else ""
    if not text.strip():
        bot.send_message(message.chat.id, "Usage: /count <text>\nCounts characters, words, and lines.")
        return
    chars = len(text)
    chars_no_space = len(re.sub(r"\s", "", text))
    words = len(text.split())
    lines = text.count("\n") + 1
    bot.send_message(
        message.chat.id,
        f"Characters: {chars}\nCharacters (no spaces): {chars_no_space}\nWords: {words}\nLines: {lines}",
    )


_LOREM = (
    "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt "
    "ut labore et dolore magna aliqua ut enim ad minim veniam quis nostrud exercitation ullamco "
    "laboris nisi ut aliquip ex ea commodo consequat duis aute irure dolor in reprehenderit"
).split()


@bot.message_handler(commands=["lorem"], func=is_allowed)
def cmd_lorem(message):
    parts = (message.text or "").split(maxsplit=1)
    n = 40
    if len(parts) > 1 and parts[1].strip().isdigit():
        n = max(1, min(300, int(parts[1].strip())))
    words = [random.choice(_LOREM) for _ in range(n)]
    words[0] = words[0].capitalize()
    bot.send_message(message.chat.id, " ".join(words) + ".")


@bot.message_handler(commands=["json"], func=is_allowed)
def cmd_json(message):
    raw = _arg(message)
    if not raw:
        bot.send_message(message.chat.id, "Usage: /json <json>\nPretty-prints and validates JSON.")
        return
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        bot.send_message(message.chat.id, f"Invalid JSON: {e}")
        return
    pretty = json.dumps(obj, indent=2, ensure_ascii=False)
    if len(pretty) > 3500:  # stay under Telegram's message size limit
        pretty = pretty[:3500] + "\n... (truncated)"
    bot.send_message(message.chat.id, pretty)


@bot.message_handler(commands=["base64"], func=is_allowed)
def cmd_base64(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage:\n/base64 <text>          — encode\n/base64 decode <text>   — decode",
        )
        return
    sub = arg.split(maxsplit=1)
    mode = sub[0].lower()
    if mode in ("encode", "decode") and len(sub) == 2:
        payload = sub[1]
    else:
        mode, payload = "encode", arg
    try:
        if mode == "encode":
            result = base64.b64encode(payload.encode()).decode()
        else:
            result = base64.b64decode(payload.encode()).decode("utf-8", "replace")
    except Exception:
        bot.send_message(message.chat.id, "That doesn't look like valid base64.")
        return
    bot.send_message(message.chat.id, result or "(empty result)")


@bot.message_handler(commands=["urlencode"], func=is_allowed)
def cmd_urlencode(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage:\n/urlencode <text>          — encode\n/urlencode decode <text>   — decode",
        )
        return
    sub = arg.split(maxsplit=1)
    if sub[0].lower() == "decode" and len(sub) == 2:
        bot.send_message(message.chat.id, unquote(sub[1]))
    else:
        bot.send_message(message.chat.id, quote(arg, safe=""))


@bot.message_handler(commands=["hash"], func=is_allowed)
def cmd_hash(message):
    text = _arg(message)
    if not text:
        bot.send_message(message.chat.id, "Usage: /hash <text>\nReturns md5, sha1, and sha256.")
        return
    data = text.encode()
    lines = [f"{algo}: {hashlib.new(algo, data).hexdigest()}" for algo in ("md5", "sha1", "sha256")]
    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(commands=["color"], func=is_allowed)
def cmd_color(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /color <hex or r,g,b>\nExamples: /color #3498db   |   /color 52,152,219",
        )
        return
    val = arg.strip().lstrip("#")
    rgb = None
    if re.fullmatch(r"[0-9a-fA-F]{6}", val):
        rgb = tuple(int(val[i: i + 2], 16) for i in (0, 2, 4))
    elif re.fullmatch(r"[0-9a-fA-F]{3}", val):
        rgb = tuple(int(c * 2, 16) for c in val)
    else:
        nums = re.findall(r"\d+", arg)
        if len(nums) == 3 and all(0 <= int(x) <= 255 for x in nums):
            rgb = tuple(int(x) for x in nums)
    if not rgb:
        bot.send_message(message.chat.id, "Couldn't parse that color. Try #3498db or 52,152,219.")
        return
    r, g, b = rgb
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    bot.send_message(
        message.chat.id,
        f"HEX: #{r:02x}{g:02x}{b:02x}\n"
        f"RGB: {r}, {g}, {b}\n"
        f"HSL: {round(h * 360)}°, {round(s * 100)}%, {round(l * 100)}%",
    )


@bot.message_handler(commands=["uuid"], func=is_allowed)
def cmd_uuid(message):
    parts = (message.text or "").split(maxsplit=1)
    count = 1
    if len(parts) > 1 and parts[1].strip().isdigit():
        count = max(1, min(10, int(parts[1].strip())))
    bot.send_message(message.chat.id, "\n".join(str(uuid.uuid4()) for _ in range(count)))


@bot.message_handler(commands=["password"], func=is_allowed)
def cmd_password(message):
    parts = (message.text or "").split(maxsplit=1)
    length = 16
    if len(parts) > 1 and parts[1].strip().isdigit():
        length = max(8, min(128, int(parts[1].strip())))
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    pw = "".join(secrets.choice(alphabet) for _ in range(length))
    bot.send_message(message.chat.id, pw)


@bot.message_handler(commands=["timestamp"], func=is_allowed)
def cmd_timestamp(message):
    arg = _arg(message)
    if not arg:
        now = datetime.now()
        utc = datetime.now(timezone.utc)
        bot.send_message(
            message.chat.id,
            f"Unix:  {int(now.timestamp())}\n"
            f"Local: {now:%Y-%m-%d %H:%M:%S}\n"
            f"UTC:   {utc:%Y-%m-%d %H:%M:%S}",
        )
        return
    if re.fullmatch(r"\d{1,13}", arg):
        ts = int(arg)
        if len(arg) > 10:
            ts = ts / 1000  # milliseconds -> seconds
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            bot.send_message(message.chat.id, "That timestamp is out of range.")
            return
        bot.send_message(message.chat.id, f"{int(ts)} (unix) →\nUTC: {dt:%Y-%m-%d %H:%M:%S}")
        return
    bot.send_message(
        message.chat.id,
        "Usage:\n/timestamp              — current time\n/timestamp 1700000000  — unix → date",
    )


# Number-base conversion (bin/oct/dec/hex), used by /base.
_BASES = {
    "bin": 2, "binary": 2, "oct": 8, "octal": 8,
    "dec": 10, "decimal": 10, "hex": 16, "hexadecimal": 16,
}


def _try_base_convert(arg):
    """Exact number-base conversion, e.g. '255 to hex' or '0xff to dec'.
    Returns a result string, or None if the input isn't a base conversion."""
    tokens = arg.lower().split()
    if "to" not in tokens:
        return None
    i = tokens.index("to")
    left, right = tokens[:i], tokens[i + 1:]
    if not left or not right or right[0] not in _BASES:
        return None
    target_base = _BASES[right[0]]
    raw = left[0]
    src_base = _BASES[left[1]] if len(left) >= 2 and left[1] in _BASES else None
    if src_base is None:
        if raw.startswith("0x"):
            src_base, raw = 16, raw[2:]
        elif raw.startswith("0o"):
            src_base, raw = 8, raw[2:]
        elif raw.startswith("0b"):
            src_base, raw = 2, raw[2:]
        else:
            src_base = 10
    if not raw:
        return None
    try:
        value = int(raw, src_base)
    except ValueError:
        return None
    sign = "-" if value < 0 else ""
    mag = abs(value)
    fmt = {2: "b", 8: "o", 16: "x"}
    if target_base in fmt:
        body = format(mag, fmt[target_base])
        prefix = {2: "0b", 8: "0o", 16: "0x"}[target_base]
    else:
        body, prefix = str(mag), ""
    return f"{arg} = {sign}{prefix}{body}"


@bot.message_handler(commands=["base"], func=is_allowed)
def cmd_base(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage: /base <value> to <base>\n"
            "Examples:\n/base 255 to hex\n/base 0xff to dec\n/base 1010 bin to hex\n"
            "Bases: bin, oct, dec, hex",
        )
        return
    result = _try_base_convert(arg)
    if result is None:
        bot.send_message(message.chat.id, "Couldn't parse that. Try: /base 255 to hex")
        return
    bot.send_message(message.chat.id, result)


@bot.message_handler(commands=["sort"], func=is_allowed)
def cmd_sort(message):
    text = _arg(message)
    if not text:
        bot.send_message(message.chat.id, "Usage: /sort <lines>\nSorts the lines alphabetically (one item per line).")
        return
    lines = sorted((ln for ln in text.splitlines() if ln.strip()), key=str.lower)
    bot.send_message(message.chat.id, "\n".join(lines) or "(nothing to sort)")


@bot.message_handler(commands=["dedupe"], func=is_allowed)
def cmd_dedupe(message):
    text = _arg(message)
    if not text:
        bot.send_message(message.chat.id, "Usage: /dedupe <lines>\nRemoves duplicate lines, keeping order.")
        return
    seen, out = set(), []
    for ln in text.splitlines():
        key = ln.strip()
        if key and key not in seen:
            seen.add(key)
            out.append(ln)
    bot.send_message(message.chat.id, "\n".join(out) or "(nothing to dedupe)")


@bot.message_handler(commands=["trim"], func=is_allowed)
def cmd_trim(message):
    text = _arg(message)
    if not text:
        bot.send_message(message.chat.id, "Usage: /trim <text>\nCollapses repeated spaces and trims each line.")
        return
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    bot.send_message(message.chat.id, "\n".join(lines).strip() or "(nothing to trim)")


_ROT13 = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    "NOPQRSTUVWXYZABCDEFGHIJKLMnopqrstuvwxyzabcdefghijklm",
)


@bot.message_handler(commands=["rot13"], func=is_allowed)
def cmd_rot13(message):
    text = _arg(message)
    if not text:
        bot.send_message(message.chat.id, "Usage: /rot13 <text>\nROT13 is its own inverse.")
        return
    bot.send_message(message.chat.id, text.translate(_ROT13))


_MORSE = {
    "a": ".-", "b": "-...", "c": "-.-.", "d": "-..", "e": ".", "f": "..-.", "g": "--.",
    "h": "....", "i": "..", "j": ".---", "k": "-.-", "l": ".-..", "m": "--", "n": "-.",
    "o": "---", "p": ".--.", "q": "--.-", "r": ".-.", "s": "...", "t": "-", "u": "..-",
    "v": "...-", "w": ".--", "x": "-..-", "y": "-.--", "z": "--..", "0": "-----",
    "1": ".----", "2": "..---", "3": "...--", "4": "....-", "5": ".....", "6": "-....",
    "7": "--...", "8": "---..", "9": "----.", ".": ".-.-.-", ",": "--..--", "?": "..--..",
    "!": "-.-.--", "/": "-..-.", "-": "-....-", "(": "-.--.", ")": "-.--.-", "'": ".----.",
    "@": ".--.-.", ":": "---...", "=": "-...-", "+": ".-.-.",
}
_MORSE_INV = {v: k for k, v in _MORSE.items()}


@bot.message_handler(commands=["morse"], func=is_allowed)
def cmd_morse(message):
    text = _arg(message)
    if not text:
        bot.send_message(message.chat.id, "Usage:\n/morse <text>        — to Morse\n/morse .... .   — Morse to text")
        return
    if re.fullmatch(r"[.\-/ ]+", text):  # looks like Morse -> decode
        words = [w for w in text.strip().split("/")]
        decoded = ["".join(_MORSE_INV.get(sym, "?") for sym in w.split()) for w in words]
        bot.send_message(message.chat.id, " ".join(d for d in decoded if d) or "(nothing)")
    else:  # encode
        parts = []
        for ch in text.lower():
            if ch == " ":
                parts.append("/")
            elif ch in _MORSE:
                parts.append(_MORSE[ch])
        bot.send_message(message.chat.id, " ".join(parts) or "(nothing to encode)")


@bot.message_handler(commands=["charcode"], func=is_allowed)
def cmd_charcode(message):
    arg = _arg(message)
    if not arg:
        bot.send_message(
            message.chat.id,
            "Usage:\n/charcode A     — char → code point\n/charcode 65    — code point → char",
        )
        return
    tokens = arg.split()
    if all(re.fullmatch(r"0x[0-9a-fA-F]+|\d+", t) for t in tokens):  # code points -> chars
        chars = []
        for t in tokens:
            cp = int(t, 16) if t.lower().startswith("0x") else int(t)
            try:
                chars.append(chr(cp))
            except (ValueError, OverflowError):
                chars.append("?")
        bot.send_message(message.chat.id, "".join(chars))
    else:  # chars -> code points
        lines = [f"{ch}  U+{ord(ch):04X}  (dec {ord(ch)})" for ch in arg if ch != " "]
        bot.send_message(message.chat.id, "\n".join(lines) or "(nothing)")


_HTTP_STATUS = {
    100: "Continue", 101: "Switching Protocols", 200: "OK", 201: "Created", 202: "Accepted",
    204: "No Content", 206: "Partial Content", 301: "Moved Permanently", 302: "Found",
    303: "See Other", 304: "Not Modified", 307: "Temporary Redirect", 308: "Permanent Redirect",
    400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
    405: "Method Not Allowed", 408: "Request Timeout", 409: "Conflict", 410: "Gone",
    418: "I'm a teapot", 422: "Unprocessable Entity", 429: "Too Many Requests",
    500: "Internal Server Error", 501: "Not Implemented", 502: "Bad Gateway",
    503: "Service Unavailable", 504: "Gateway Timeout",
}


@bot.message_handler(commands=["http"], func=is_allowed)
def cmd_http(message):
    arg = _arg(message)
    if not re.fullmatch(r"\d{3}", arg or ""):
        bot.send_message(message.chat.id, "Usage: /http <code>  (e.g. /http 404)")
        return
    code = int(arg)
    cls = {1: "Informational", 2: "Success", 3: "Redirection",
           4: "Client Error", 5: "Server Error"}.get(code // 100, "Unknown")
    name = _HTTP_STATUS.get(code)
    if name:
        bot.send_message(message.chat.id, f"{code} {name}\nClass: {cls}")
    else:
        bot.send_message(message.chat.id, f"{code} — {cls} (no standard name on file)")


@bot.message_handler(commands=["random"], func=is_allowed)
def cmd_random(message):
    nums = [int(p) for p in (message.text or "").split()[1:] if re.fullmatch(r"-?\d+", p)]
    if len(nums) >= 2:
        lo, hi = nums[0], nums[1]
    elif len(nums) == 1:
        lo, hi = 1, nums[0]
    else:
        lo, hi = 1, 100
    if lo > hi:
        lo, hi = hi, lo
    bot.send_message(message.chat.id, str(random.randint(lo, hi)))


@bot.message_handler(commands=["pick"], func=is_allowed)
def cmd_pick(message):
    arg = _arg(message)
    options = [o.strip() for o in re.split(r"[,\n]", arg) if o.strip()] if arg else []
    if not options:
        bot.send_message(message.chat.id, "Usage: /pick a, b, c\nPicks one option at random.")
        return
    bot.send_message(message.chat.id, "🎯 " + random.choice(options))


@bot.message_handler(commands=["coin"], func=is_allowed)
def cmd_coin(message):
    bot.send_message(message.chat.id, "🪙 " + random.choice(["Heads", "Tails"]))


# --- Image generation for /image --------------------------------------------
# When TOGETHER_API_KEY is set, /image uses Together AI (api.together.xyz — on
# PythonAnywhere's outbound allowlist, FLUX.1-schnell-Free free tier). Without
# a key it falls back to the keyless pollinations.ai service, which works
# locally but needs a PA allowlist request to reach image.pollinations.ai.

def _http_get_bytes(url, timeout=120, retries=0):
    """GET a URL and return the raw bytes. Uses requests if available (it
    ships with pyTelegramBotAPI) and falls back to the standard library.

    ``retries`` extra attempts are made on HTTP 429 (Too Many Requests) with
    exponential backoff (1s, 2s, 4s, …). This matters on PythonAnywhere, where
    the outbound IP is shared, so per-IP-rate-limited free APIs (e.g.
    open-meteo) can 429 on bursts even when this bot is quiet."""
    headers = {"User-Agent": "coding-assistant-bot/1.0"}
    for attempt in range(retries + 1):
        try:
            try:
                import requests
                resp = requests.get(url, timeout=timeout, headers=headers)
                if resp.status_code == 429 and attempt < retries:
                    raise _RateLimited()
                resp.raise_for_status()
                return resp.content
            except ImportError:
                import urllib.error
                import urllib.request
                req = urllib.request.Request(url, headers=headers)
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as r:
                        return r.read()
                except urllib.error.HTTPError as e:
                    if e.code == 429 and attempt < retries:
                        raise _RateLimited()
                    raise
        except _RateLimited:
            time.sleep(2 ** attempt)
    # Unreachable: the loop either returns or raises on the final attempt.
    raise RuntimeError("request failed after retries")


class _RateLimited(Exception):
    """Internal sentinel: a 429 that we intend to retry."""


# Armenian block (U+0530–U+058F) plus the Armenian ligatures (U+FB13–U+FB17).
_ARMENIAN_RE = re.compile(r"[԰-֏ﬓ-ﬗ]")


def _has_armenian(text: str) -> bool:
    return bool(_ARMENIAN_RE.search(text or ""))


_TRANSLATE_SYSTEM = (
    "You are a translation engine for image-generation prompts. Translate the "
    "user's text into natural, descriptive English suitable for an image model. "
    "Rules, always: output ONLY the English translation as a plain phrase — no "
    "quotes, no markdown, no preamble, no notes, no explanations. NEVER ask for "
    "clarification and NEVER refuse; if the text is short, misspelled, or "
    "ambiguous, translate it as literally as you can anyway. Preserve every "
    "visual detail and do not add, drop, or reinterpret anything. Words already "
    "in English stay unchanged. Proper names stay as-is."
)


def _clean_translation(text: str) -> str:
    """Strip wrapping quotes/backticks/whitespace a model sometimes adds."""
    return (text or "").strip().strip("\"'`").strip()


def _translate_prompt_for_image(prompt: str) -> str:
    """Translate a non-English (currently: Armenian) image prompt to English.

    The image backends (FLUX / Cloudflare / pollinations) follow English
    prompts well but largely ignore Armenian, so an Armenian prompt would
    produce an unrelated picture. We route the prompt through the main
    Cerebras chat model for a quick literal translation first.

    A one-shot example is included so the reasoning model reliably behaves as a
    pure translator (just the English phrase) instead of answering
    conversationally — the failure mode that produced unrelated images.

    Best-effort only: if there's no Armenian text, if the call fails, or if the
    model gives back something unusable (empty, or still containing Armenian —
    i.e. it didn't actually translate), we return the original prompt unchanged
    so /image never breaks or gets *worse* because translation misbehaved.
    """
    if not _has_armenian(prompt):
        return prompt
    from bot.providers import _call_main

    messages = [
        {"role": "system", "content": _TRANSLATE_SYSTEM},
        {"role": "user", "content": "կատու ձյան մեջ մայրամուտին"},
        {"role": "assistant", "content": "a cat in the snow at sunset"},
        {"role": "user", "content": prompt},
    ]
    # Prefer the dedicated translation model (gemma-4-31b is accurate on
    # Armenian; the chat MODEL / gpt-oss-120b is not), then fall back to MODEL
    # if that id isn't available on this key. Dedupe so we don't call twice.
    candidates = []
    for m in (IMAGE_TRANSLATE_MODEL, MODEL):
        if m and m not in candidates:
            candidates.append(m)
    for model in candidates:
        try:
            translated = _call_main(messages, retries=1, model=model)
        except Exception as e:
            print(f"prompt translation via '{model}' failed: {e}")
            continue
        translated = _clean_translation(translated)
        if translated and not _has_armenian(translated):
            return translated
        # Empty or not actually translated — try the next model.
        print(f"prompt translation via '{model}' gave no usable English")
    return prompt


def _generate_image_together(prompt, width=1024, height=1024):
    """Generate an image via Together AI's OpenAI-compatible images endpoint.
    Requests b64_json so we get the bytes directly (no second fetch to a CDN
    host that might not be allowlisted)."""
    import requests

    resp = requests.post(
        "https://api.together.xyz/v1/images/generations",
        headers={"Authorization": f"Bearer {TOGETHER_API_KEY}"},
        json={
            "model": TOGETHER_IMAGE_MODEL,
            "prompt": prompt,
            "width": width,
            "height": height,
            "steps": 4,  # FLUX.1-schnell is tuned for ~4 steps
            "n": 1,
            "response_format": "b64_json",
        },
        timeout=120,
    )
    resp.raise_for_status()
    items = resp.json().get("data") or []
    if not items:
        raise RuntimeError("the image service returned no image")
    item = items[0]
    if item.get("b64_json"):
        data = base64.b64decode(item["b64_json"])
    elif item.get("url"):
        data = _http_get_bytes(item["url"], timeout=120)
    else:
        raise RuntimeError("the image service returned no image data")
    if not data or len(data) < 1000:  # too small to be a real image
        raise RuntimeError("the image service returned no image")
    return data


def _generate_image_cloudflare(prompt, width=1024, height=1024):
    """Generate an image via Cloudflare Workers AI (free tier, FLUX.1-schnell).
    FLUX returns JSON with a base64 image; some models (e.g. SDXL) return raw
    image bytes — handle both by checking the response content type."""
    import requests

    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{CF_IMAGE_MODEL}"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {CF_API_TOKEN}"},
        json={"prompt": prompt},
        timeout=120,
    )
    resp.raise_for_status()
    if "application/json" in resp.headers.get("content-type", ""):
        result = resp.json().get("result") or {}
        b64 = result.get("image")
        data = base64.b64decode(b64) if b64 else b""
    else:
        data = resp.content
    if not data or len(data) < 1000:  # too small to be a real image
        raise RuntimeError("the image service returned no image")
    return data


def _generate_image_pollinations(prompt, width=1024, height=1024):
    seed = random.randint(1, 1_000_000)
    url = (
        "https://image.pollinations.ai/prompt/"
        + quote(prompt, safe="")
        + f"?width={width}&height={height}&seed={seed}&nologo=true&model=flux"
    )
    data = _http_get_bytes(url, timeout=120)
    if not data or len(data) < 1000:  # too small to be a real image
        raise RuntimeError("the image service returned no image")
    return data


def _generate_image(prompt, width=1024, height=1024):
    """Pick the first configured image backend. All are free; whichever key(s)
    are set win, else fall back to keyless pollinations."""
    prompt = _translate_prompt_for_image(prompt)
    if TOGETHER_API_KEY:
        return _generate_image_together(prompt, width, height)
    if CF_ACCOUNT_ID and CF_API_TOKEN:
        return _generate_image_cloudflare(prompt, width, height)
    return _generate_image_pollinations(prompt, width, height)


@bot.message_handler(commands=["image"], func=is_allowed)
def cmd_image(message):
    prompt = _arg(message)
    if not prompt:
        bot.send_message(
            message.chat.id,
            "Usage: /image <prompt>\n"
            "Example: /image a cozy cabin in a snowy forest at night\n"
            "\n"
            "📊 What to expect (free tier):\n"
            "• Speed: usually ready in a few seconds\n"
            f"• Daily limit: up to {RATE_LIMIT} requests/day (shared with your other messages)",
        )
        return
    try:
        bot.send_chat_action(message.chat.id, "upload_photo")
    except Exception:
        pass
    try:
        data = _generate_image(prompt)
    except Exception as e:
        bot.send_message(message.chat.id, f"Couldn't generate that image: {e}")
        return
    buf = io.BytesIO(data)
    buf.name = "image.jpg"
    try:
        bot.send_photo(message.chat.id, buf, caption=prompt[:1000])
    except Exception:
        buf.seek(0)  # fall back to sending it as a file
        bot.send_document(message.chat.id, buf, visible_file_name="image.jpg")


# --- Image editing for /edit ------------------------------------------------
# Where /image is text -> image, /edit is (image + instruction) -> image. That
# needs an img2img backend: Together AI (a FLUX.1 Kontext model) or Cloudflare
# Workers AI (a Stable Diffusion img2img model). The keyless pollinations
# service only does text-to-image, so /edit has no keyless fallback — it tells
# the user to configure a backend when neither key is set.

def _edit_image_together(prompt, image_bytes):
    """Edit an image via Together AI's FLUX.1 Kontext model. The source image is
    passed inline as a base64 data URI so we never need a public URL for the
    upload (important on PA, where the bot has no public file host)."""
    import requests

    data_uri = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    resp = requests.post(
        "https://api.together.xyz/v1/images/generations",
        headers={"Authorization": f"Bearer {TOGETHER_API_KEY}"},
        json={
            "model": TOGETHER_EDIT_MODEL,
            "prompt": prompt,
            "image_url": data_uri,
            "n": 1,
            "response_format": "b64_json",
        },
        timeout=120,
    )
    resp.raise_for_status()
    items = resp.json().get("data") or []
    if not items:
        raise RuntimeError("the image service returned no image")
    item = items[0]
    if item.get("b64_json"):
        data = base64.b64decode(item["b64_json"])
    elif item.get("url"):
        data = _http_get_bytes(item["url"], timeout=120)
    else:
        raise RuntimeError("the image service returned no image data")
    if not data or len(data) < 1000:  # too small to be a real image
        raise RuntimeError("the image service returned no image")
    return data


def _edit_image_cloudflare(prompt, image_bytes):
    """Edit an image via Cloudflare Workers AI's img2img model. Workers AI wants
    the source image as an array of byte values (0-255); the response is JSON
    with a base64 image or raw bytes, same as the generate path."""
    import requests

    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{CF_EDIT_MODEL}"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {CF_API_TOKEN}"},
        json={"prompt": prompt, "image": list(image_bytes)},
        timeout=120,
    )
    resp.raise_for_status()
    if "application/json" in resp.headers.get("content-type", ""):
        result = resp.json().get("result") or {}
        b64 = result.get("image")
        data = base64.b64decode(b64) if b64 else b""
    else:
        data = resp.content
    if not data or len(data) < 1000:  # too small to be a real image
        raise RuntimeError("the image service returned no image")
    return data


def _to_telegram_image(data):
    """Normalize edited image bytes to PNG. FLUX Kontext Spaces return WebP,
    which Telegram's send_photo can reject; re-encode via Pillow when it's
    available, otherwise fall back to the original bytes."""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()
    except Exception:
        return data


def _edit_image_hf(prompt, image_bytes):
    """FREE, high-quality editing via a Hugging Face Space running FLUX.1
    Kontext (a true instruction editor). gradio_client uploads the source image
    to the Space directly, so no public URL or bot-token leak is needed.
    hf.space + huggingface.co are on PA's allowlist. The Space is a shared free
    GPU, so this can queue for ~30-60s or be briefly unavailable."""
    import tempfile
    from gradio_client import Client, handle_file

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    try:
        tmp.write(image_bytes)
        tmp.close()
        client = Client(
            HF_EDIT_SPACE,
            token=(HF_TOKEN or None),
            httpx_kwargs={"timeout": HF_EDIT_TIMEOUT},
        )
        result = client.predict(
            input_image=handle_file(tmp.name),
            prompt=prompt,
            seed=0,
            randomize_seed=True,
            guidance_scale=HF_EDIT_GUIDANCE,
            steps=HF_EDIT_STEPS,
            api_name="/infer",
        )
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    # /infer returns (edited_image, seed); the image is a local path (str) or a
    # {path|url} dict depending on the gradio version.
    out = result[0] if isinstance(result, (list, tuple)) else result
    if isinstance(out, dict):
        out = out.get("path") or out.get("url")
    if not out:
        raise RuntimeError("the edit service returned no image")
    if isinstance(out, str) and out.startswith("http"):
        data = _http_get_bytes(out, timeout=HF_EDIT_TIMEOUT)
    else:
        with open(out, "rb") as f:
            data = f.read()
    if not data or len(data) < 1000:  # too small to be a real image
        raise RuntimeError("the edit service returned no image")
    return _to_telegram_image(data)


def _edit_image(prompt, image_bytes):
    """Pick the first configured edit-capable backend. Prefers free FLUX.1
    Kontext (a Hugging Face Space) for true instruction-based editing, then the
    OpenAI-compatible img2img backends. Unlike _generate_image there is no
    keyless *text-to-image* fallback — editing needs a real edit backend — so
    raise a clear message when none is configured."""
    prompt = _translate_prompt_for_image(prompt)
    if HF_EDIT_SPACE:
        return _edit_image_hf(prompt, image_bytes)
    if TOGETHER_API_KEY:
        return _edit_image_together(prompt, image_bytes)
    if CF_ACCOUNT_ID and CF_API_TOKEN:
        return _edit_image_cloudflare(prompt, image_bytes)
    raise RuntimeError(
        "image editing isn't configured on this bot. It needs an edit backend "
        "— set HF_EDIT_SPACE (free FLUX.1 Kontext), TOGETHER_API_KEY, or "
        "CF_ACCOUNT_ID + CF_API_TOKEN. (The keyless image service can only "
        "create new images, not edit them.)"
    )


def _image_file_id(message):
    """Return a downloadable file_id for an image attached to `message`, or
    None. Accepts both Telegram photos and image documents (files sent to keep
    original quality)."""
    if message is None:
        return None
    if getattr(message, "photo", None):
        return message.photo[-1].file_id
    doc = getattr(message, "document", None)
    if doc is not None and (getattr(doc, "mime_type", "") or "").startswith("image/"):
        return doc.file_id
    return None


@bot.message_handler(commands=["edit"], func=is_allowed)
def cmd_edit(message):
    prompt = _arg(message)
    if not prompt:
        bot.send_message(
            message.chat.id,
            "Usage — three ways to edit an image:\n"
            "1. Send a photo with the caption /edit <what to change>\n"
            "2. Reply to a photo with /edit <what to change>\n"
            "3. Send /edit <what to change>, then send the photo\n"
            "Example: /edit make the sky a sunset",
        )
        return
    # One-step flow: reply to a photo/image with "/edit <prompt>".
    replied_file_id = _image_file_id(getattr(message, "reply_to_message", None))
    if replied_file_id:
        _do_edit(message, prompt, replied_file_id)
        return
    # Two-step flow (mirrors /convert): ask for the image, edit on arrival.
    sent = bot.send_message(
        message.chat.id,
        "Now send me the image to edit.\n"
        "Tip: send it as a file (not a photo) to keep the original quality.",
    )
    bot.register_next_step_handler(sent, _do_edit, prompt)


def _command_in_caption(message, name):
    """True when a photo/document arrives captioned with the /<name> command
    (optionally /<name>@botname). Lets users attach an image and type the
    instruction in the caption — the most natural gesture — which telebot's
    command handler otherwise misses because it only matches text, not
    captions."""
    cap = (getattr(message, "caption", "") or "").strip()
    if not cap.startswith("/"):
        return False
    cmd = cap.split(maxsplit=1)[0].lstrip("/").split("@")[0].lower()
    return cmd == name and is_allowed(message)


def _edit_command_in_caption(message):
    return _command_in_caption(message, "edit")


@bot.message_handler(content_types=["photo", "document"], func=_edit_command_in_caption)
def cmd_edit_caption(message):
    parts = (message.caption or "").strip().split(maxsplit=1)
    prompt = parts[1].strip() if len(parts) > 1 else ""
    file_id = _image_file_id(message)
    if not file_id:
        bot.send_message(
            message.chat.id,
            "Send a photo or image file with the caption /edit <what to change>.",
        )
        return
    if not prompt:
        bot.send_message(
            message.chat.id,
            "Add the change after /edit — e.g. caption the image "
            "'/edit make the sky a sunset'.",
        )
        return
    _do_edit(message, prompt, file_id)


def _do_edit(message, prompt, file_id=None):
    if file_id is None:
        file_id = _image_file_id(message)
    if not file_id:
        bot.send_message(message.chat.id, "That wasn't an image — edit cancelled.")
        return
    try:
        bot.send_chat_action(message.chat.id, "upload_photo")
    except Exception:
        pass
    try:
        info = bot.get_file(file_id)
        source = bot.download_file(info.file_path)
        # Kontext on a free GPU can take ~30-60s; keep the indicator alive.
        with keep_typing(message.chat.id):
            data = _edit_image(prompt, source)
    except Exception as e:
        print(f"Error in _do_edit: {e}")  # surface backend failures in the PA log
        bot.send_message(message.chat.id, f"Couldn't edit that image: {e}")
        return
    buf = io.BytesIO(data)
    buf.name = "edited.jpg"
    try:
        bot.send_photo(message.chat.id, buf, caption=prompt[:1000])
    except Exception:
        buf.seek(0)  # fall back to sending it as a file
        bot.send_document(message.chat.id, buf, visible_file_name="edited.jpg")


# --- More free/keyless helpers (QR, URL shortener, dictionary) ------

def _http_get_text(url, timeout=30, retries=0):
    return _http_get_bytes(url, timeout=timeout, retries=retries).decode("utf-8", "replace")


def _make_qr_png(text):
    """Render a QR code PNG. Prefer the local `qrcode` library (no network, so
    it works even behind PythonAnywhere's outbound firewall); fall back to the
    remote qrserver API if the library isn't installed. Returns bytes or None."""
    try:
        import qrcode

        buf = io.BytesIO()
        qrcode.make(text).save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        try:
            url = (
                "https://api.qrserver.com/v1/create-qr-code/?size=400x400&data="
                + quote(text, safe="")
            )
            return _http_get_bytes(url, timeout=30)
        except Exception:
            return None
    except Exception:
        return None


@bot.message_handler(commands=["qr"], func=is_allowed)
def cmd_qr(message):
    text = _arg(message)
    if not text:
        bot.send_message(message.chat.id, "Usage: /qr <text or url>\nGenerates a QR code image.")
        return
    try:
        bot.send_chat_action(message.chat.id, "upload_photo")
    except Exception:
        pass
    data = _make_qr_png(text)
    if not data:
        bot.send_message(message.chat.id, "Couldn't make a QR code right now.")
        return
    buf = io.BytesIO(data)
    buf.name = "qr.png"
    try:
        bot.send_photo(message.chat.id, buf, caption=text[:1000])
    except Exception:
        buf.seek(0)
        bot.send_document(message.chat.id, buf, visible_file_name="qr.png")


@bot.message_handler(commands=["shorten"], func=is_allowed)
def cmd_shorten(message):
    url = _arg(message)
    if not url:
        bot.send_message(message.chat.id, "Usage: /shorten <url>")
        return
    if not re.match(r"https?://", url):
        url = "http://" + url
    api = "https://is.gd/create.php?format=simple&url=" + quote(url, safe="")
    try:
        short = _http_get_text(api, timeout=20).strip()
    except Exception as e:
        bot.send_message(message.chat.id, f"Couldn't shorten that: {e}")
        return
    if not short.startswith("http"):
        bot.send_message(message.chat.id, f"Couldn't shorten that URL. ({short[:100]})")
        return
    bot.send_message(message.chat.id, short)


@bot.message_handler(commands=["define"], func=is_allowed)
def cmd_define(message):
    word = _arg(message)
    if not word:
        bot.send_message(message.chat.id, "Usage: /define <word>")
        return
    api = "https://api.dictionaryapi.dev/api/v2/entries/en/" + quote(word.split()[0], safe="")
    try:
        entries = json.loads(_http_get_text(api, timeout=20))
    except Exception:
        bot.send_message(message.chat.id, f"Couldn't find a definition for '{word}'.")
        return
    if not isinstance(entries, list) or not entries:
        bot.send_message(message.chat.id, f"No definition found for '{word}'.")
        return
    entry = entries[0]
    lines = [entry.get("word", word)]
    if entry.get("phonetic"):
        lines.append(entry["phonetic"])
    for meaning in entry.get("meanings", [])[:3]:
        defs = meaning.get("definitions", [])
        if defs:
            lines.append(f"\n({meaning.get('partOfSpeech', '')}) {defs[0].get('definition', '')}")
    bot.send_message(message.chat.id, "\n".join(lines))


# --- Image format converter -------------------------------------------------
# /convert asks for a target format, then converts the next image you send.
# Send the image as a *file* to preserve the original format/quality; photos
# are re-encoded to JPEG by Telegram before they ever reach the bot.

SUPPORTED_IMAGE_FORMATS = ("jpg", "jpeg", "png", "webp", "gif", "bmp", "tiff", "ico")


def _pil_format(fmt):
    """Map a user-typed extension to a Pillow format name."""
    return {"jpg": "JPEG", "jpeg": "JPEG", "tif": "TIFF", "tiff": "TIFF", "ico": "ICO"}.get(
        fmt, fmt.upper()
    )


@bot.message_handler(commands=["convert"], func=is_allowed)
def cmd_convert(message):
    parts = (message.text or "").split(maxsplit=1)
    fmt = parts[1].strip().lower().lstrip(".") if len(parts) > 1 else ""
    if not fmt:
        bot.send_message(
            message.chat.id,
            "Usage: /convert <format>, then send the image.\n"
            f"Supported: {', '.join(SUPPORTED_IMAGE_FORMATS)}\n"
            "Example: /convert webp",
        )
        return
    if fmt not in SUPPORTED_IMAGE_FORMATS:
        bot.send_message(
            message.chat.id,
            f"Can't convert to '{fmt}'. Supported: {', '.join(SUPPORTED_IMAGE_FORMATS)}",
        )
        return
    sent = bot.send_message(
        message.chat.id,
        f"Now send me the image to convert to {fmt}.\n"
        "Tip: send it as a file (not a photo) to keep the original quality.",
    )
    bot.register_next_step_handler(sent, _do_convert, fmt)


def _do_convert(message, fmt):
    try:
        from PIL import Image
    except ImportError:
        bot.send_message(message.chat.id, "Image conversion needs the Pillow library (pip install pillow).")
        return

    file_id = None
    source_name = "image"
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        file_id = message.document.file_id
        source_name = message.document.file_name or "image"
    if not file_id:
        bot.send_message(message.chat.id, "That wasn't an image — conversion cancelled.")
        return

    try:
        info = bot.get_file(file_id)
        data = bot.download_file(info.file_path)
        img = Image.open(io.BytesIO(data))
        pil_fmt = _pil_format(fmt)
        if pil_fmt in ("JPEG", "BMP") and img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")  # these formats can't store an alpha channel
        elif pil_fmt == "ICO":
            img = img.convert("RGBA")
        out = io.BytesIO()
        img.save(out, format=pil_fmt)
        out.seek(0)
        base = source_name.rsplit(".", 1)[0] or "image"
        out.name = f"{base}.{fmt}"
        bot.send_document(message.chat.id, out, visible_file_name=out.name)
    except Exception as e:
        bot.send_message(message.chat.id, f"Couldn't convert that image: {e}")


@bot.message_handler(commands=["quiz"], func=is_allowed)
def cmd_quiz(message):
    topic = message.text.split(maxsplit=1)[1].strip() if " " in message.text else ""
    if not topic:
        bot.send_message(message.chat.id, "Usage: /quiz <topic>  (e.g. /quiz python lists)")
        return
    question = ask_ai(
        message.from_user.id,
        f"Create one short quiz question about: {topic}. "
        "Ask a single clear question that has a definite correct answer. "
        "Do NOT reveal or hint at the answer. Reply with only the question — no preamble.",
    )
    sent = bot.send_message(message.chat.id, f"❓ {question}\n\nReply with your answer.")
    bot.register_next_step_handler(sent, _grade_quiz, question)


def _grade_quiz(message, question):
    answer = (message.text or "").strip()
    if not answer:
        bot.send_message(message.chat.id, "No answer given — quiz cancelled.")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Quiz question: {question}\n"
        f"Student's answer: {answer}\n\n"
        "Say whether the answer is correct, then give the correct answer with a one-sentence "
        "explanation. Be encouraging and concise.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["summarize"], func=is_allowed)
def cmd_summarize(message):
    text = message.text.split(maxsplit=1)[1].strip() if " " in message.text else ""
    if not text:
        bot.send_message(message.chat.id, "Usage: /summarize <text>\nPaste the text you'd like summarized.")
        return
    reply = ask_ai(
        message.from_user.id,
        "Summarize the following text concisely, capturing the key points as a short "
        "paragraph or a few bullet points. Do not add opinions or information that isn't "
        f"in the text. Reply with only the summary — no preamble.\n\nText:\n{text}",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["roll"], func=is_allowed)
def cmd_roll(message):
    result = random.randint(1, 6)
    bot.send_message(message.chat.id, f"🎲 You rolled a {result}!")


@bot.message_handler(commands=["roast"], func=is_allowed)
def cmd_roast(message):
    sent = bot.send_message(message.chat.id, "Who should I roast? Send me a name.")
    bot.register_next_step_handler(sent, _do_roast)


def _do_roast(message):
    name = (message.text or "").strip()
    if not name:
        bot.send_message(message.chat.id, "No name given — roast cancelled.")
        return
    reply = ask_ai(
        message.from_user.id,
        f"Write a short, brutal, savage roast of {name}. "
        "Go hard — be sharp, witty, and merciless. Don't hold back or soften it, "
        "but keep it clever comedy (no slurs, no protected-class attacks, nothing genuinely hateful). "
        "Keep it to 1-3 punchy lines. Reply with only the roast — no preamble, no disclaimers.",
    )
    send_reply(message, reply)


@bot.message_handler(commands=["remember"], func=is_allowed)
def cmd_remember(message):
    if store is None:
        bot.send_message(message.chat.id, "Notes need storage, which isn't set up right now.")
        return
    note = message.text.split(maxsplit=1)[1].strip() if " " in message.text else ""
    if not note:
        bot.send_message(message.chat.id, "Usage: /remember <something to note>")
        return
    key = f"notes:{message.from_user.id}"
    raw = store.get(key)
    notes = json.loads(raw) if raw else []  # strings only — decode the list on the way out
    notes.append(note)  # append, don't replace
    store.set(key, json.dumps(notes))  # encode the list on the way in
    bot.send_message(message.chat.id, f"Saved! You now have {len(notes)} note(s).")


@bot.message_handler(commands=["recall"], func=is_allowed)
def cmd_recall(message):
    if store is None:
        bot.send_message(message.chat.id, "Notes need storage, which isn't set up right now.")
        return
    raw = store.get(f"notes:{message.from_user.id}")
    notes = json.loads(raw) if raw else []
    if not notes:
        bot.send_message(message.chat.id, "You have no saved notes. Add one with /remember <text>")
        return
    lines = [f"{i}. {note}" for i, note in enumerate(notes, start=1)]
    bot.send_message(message.chat.id, "Your notes:\n" + "\n".join(lines))


@bot.message_handler(commands=["forget"], func=is_allowed)
def cmd_forget(message):
    if store is None:
        bot.send_message(message.chat.id, "Notes need storage, which isn't set up right now.")
        return
    store.delete(f"notes:{message.from_user.id}")
    bot.send_message(message.chat.id, "All your notes have been cleared.")


@bot.message_handler(commands=["help"], func=is_allowed)
def cmd_help(message):
    # One message per category so each fits well under Telegram's 4096-char
    # limit and the list is easy to scan. send_reply handles any splitting.
    for title, cmds in COMMAND_CATEGORIES:
        body = "\n".join(f"/{name} — {desc}" for name, desc in cmds)
        send_reply(message, f"*{title}*\n{body}")

    # A dedicated "AI models" message: what each model is good for and how to
    # switch, since picking the right model per task is the main lever a user
    # has over answer quality.
    models = available_models()
    if len(models) > 1:
        active = active_model(message.from_user.id)
        lines = ["*🧠 AI models* — switch with `/model <name>`"]
        for m in models:
            marker = "  ✅ (current)" if m["key"] == active["key"] else ""
            lines.append(f"• *{m['name']}* — {m['description']}{marker}")
        if ARMENIAN_MODEL:
            lines.append(
                f"\n💡 Write in Armenian and I'll automatically answer with "
                f"*{ARMENIAN_MODEL}* (the best model for Armenian) for that "
                f"message, then return to your chosen model."
            )
        send_reply(message, "\n".join(lines))


@bot.message_handler(commands=["reset"], func=is_allowed)
def cmd_reset(message):
    clear_history(message.from_user.id)
    if store is not None:
        try:
            store.delete(f"transcript:{message.from_user.id}")  # also drop the /pdf transcript
        except Exception:
            pass
    bot.send_message(message.chat.id, "Conversation cleared. Starting fresh!")


@bot.message_handler(commands=["about"], func=is_allowed)
def cmd_about(message):
    if HF_SPACE_ID:
        provider = get_provider(message.from_user.id)
        model_line = f"{MODEL} (main)" if provider == "main" else f"{HF_SPACE_ID} (hf)"
    else:
        model_line = MODEL
    storage_line = "SQLite" if store is not None else "stateless (no memory)"
    lines = [
        f"Model  : {model_line}",
        f"Storage: {storage_line}",
        f"Hosting: {HOSTING_LABEL}",
    ]
    if COMMIT_SHA:
        lines.append(f"Version: {COMMIT_SHA}")
    bot.send_message(message.chat.id, "\n".join(lines))


# --- PDF helpers: shared font + builders for /pdf and /topdf ----------------

def _pdf_fonts():
    """Register a Unicode TrueType font so non-Latin text and symbols render.
    Falls back to Helvetica (Latin-1 only) if DejaVu isn't installed."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    regular = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(regular):
            if "Deja" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("Deja", regular))
                if os.path.exists(bold):
                    pdfmetrics.registerFont(TTFont("Deja-Bold", bold))
            return "Deja", ("Deja-Bold" if os.path.exists(bold) else "Deja")
    except Exception:
        pass
    return "Helvetica", "Helvetica-Bold"


def _pdf_escaper(latin_only):
    """Return a function that makes text safe for a reportlab Paragraph."""
    def esc(s):
        s = s or ""
        if latin_only:  # standard fonts can't encode non-Latin-1 text
            s = s.encode("latin-1", "replace").decode("latin-1")
        return html.escape(s).replace("\n", "<br/>")
    return esc


def _build_text_pdf(text, title="Document"):
    """Render arbitrary text into a PDF (used by /topdf). Blank lines start
    new paragraphs so long text flows and paginates cleanly."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

    font, _ = _pdf_fonts()
    esc = _pdf_escaper(font == "Helvetica")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, title=title,
        topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=18 * mm, rightMargin=18 * mm,
    )
    body = ParagraphStyle("body", fontName=font, fontSize=11, leading=15)
    story = []
    for block in re.split(r"\n\s*\n", text.strip()) or [text]:
        story.append(Paragraph(esc(block), body))
        story.append(Spacer(1, 8))
    if not story:
        story.append(Paragraph(esc(text), body))
    doc.build(story)
    return buf.getvalue()


@bot.message_handler(commands=["topdf"], func=is_allowed)
def cmd_topdf(message):
    text = _arg(message)
    if not text:
        bot.send_message(message.chat.id, "Usage: /topdf <text>\nTurns your text into a downloadable PDF file.")
        return
    try:
        import reportlab  # noqa: F401  (just checking it's installed)
    except ImportError:
        bot.send_message(message.chat.id, "Making PDFs needs the reportlab library (pip install reportlab).")
        return
    try:
        pdf_bytes = _build_text_pdf(text)
    except Exception as e:
        bot.send_message(message.chat.id, f"Couldn't create the PDF: {e}")
        return
    buf = io.BytesIO(pdf_bytes)
    buf.name = f"document_{datetime.now():%Y%m%d_%H%M%S}.pdf"
    bot.send_document(message.chat.id, buf, visible_file_name=buf.name)


# --- Conversation transcript + /pdf export ----------------------------------
# handle_message records each user/bot turn to storage so /pdf can render the
# whole conversation. Recording is best-effort and never blocks a reply.

_TRANSCRIPT_MAX = 400  # keep only the most recent N turns per user


def _record_turn(user_id, who, text):
    if store is None:
        return
    try:
        key = f"transcript:{user_id}"
        raw = store.get(key)
        turns = json.loads(raw) if raw else []
        turns.append(
            {"t": datetime.now().strftime("%Y-%m-%d %H:%M"), "who": who, "text": text or ""}
        )
        if len(turns) > _TRANSCRIPT_MAX:
            turns = turns[-_TRANSCRIPT_MAX:]
        store.set(key, json.dumps(turns))
    except Exception:
        pass  # logging must never break the conversation


def _build_transcript_pdf(turns):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph

    font, font_bold = _pdf_fonts()
    esc = _pdf_escaper(font == "Helvetica")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, title="Conversation",
        topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=18 * mm, rightMargin=18 * mm,
    )
    title_style = ParagraphStyle("title", fontName=font_bold, fontSize=16, spaceAfter=2)
    meta_style = ParagraphStyle("meta", fontName=font, fontSize=8, textColor=colors.grey, spaceAfter=12)
    you_style = ParagraphStyle("you", fontName=font_bold, fontSize=9,
                               textColor=colors.HexColor("#1a5fb4"), spaceBefore=8, spaceAfter=1)
    bot_style = ParagraphStyle("bot", fontName=font_bold, fontSize=9,
                               textColor=colors.HexColor("#26a269"), spaceBefore=8, spaceAfter=1)
    body_style = ParagraphStyle("body", fontName=font, fontSize=10, leading=14)

    story = [
        Paragraph("Conversation transcript", title_style),
        Paragraph("Exported " + datetime.now().strftime("%Y-%m-%d %H:%M"), meta_style),
    ]
    for turn in turns:
        who = turn.get("who", "")
        header = f"{who}  ·  {turn['t']}" if turn.get("t") else who
        style = you_style if who.lower().startswith("you") else bot_style
        story.append(Paragraph(esc(header), style))
        story.append(Paragraph(esc(turn.get("text", "")), body_style))
    doc.build(story)
    return buf.getvalue()


@bot.message_handler(commands=["pdf"], func=is_allowed)
def cmd_pdf(message):
    if store is None:
        bot.send_message(message.chat.id, "Saving conversations needs storage, which isn't set up right now.")
        return
    try:
        import reportlab  # noqa: F401
    except ImportError:
        bot.send_message(message.chat.id, "Making PDFs needs the reportlab library (pip install reportlab).")
        return
    raw = store.get(f"transcript:{message.from_user.id}")
    turns = json.loads(raw) if raw else []
    if not turns:
        bot.send_message(message.chat.id, "No conversation saved yet. Chat with me a little, then try /pdf.")
        return
    try:
        pdf_bytes = _build_transcript_pdf(turns)
    except Exception as e:
        bot.send_message(message.chat.id, f"Couldn't create the PDF: {e}")
        return
    buf = io.BytesIO(pdf_bytes)
    buf.name = f"conversation_{datetime.now():%Y%m%d_%H%M%S}.pdf"
    bot.send_document(
        message.chat.id, buf, visible_file_name=buf.name,
        caption=f"Here's your conversation — {len(turns)} messages.",
    )


# --- AI model registry + /model, /models, /sha -----------------------------
# "main" is the configured MODEL. Extra Cerebras model ids the account can
# access are added via the ALT_CEREBRAS_MODELS env var (empty by default — we
# don't advertise models the key can't use, which would 404). When HF_SPACE_ID
# is set, the ArmGPT Hugging Face space ("hf") is offered too. Each model is a
# dict with key / name / description. get_provider stores the user's choice by
# key; providers.generate() routes "main"/<cerebras-id> to Cerebras, "hf" to HF.

def available_models():
    """Return the selectable models as {key, name, description} dicts.

    Reads MODEL, ALT_CEREBRAS_MODELS and HF_SPACE_ID at call time so tests can
    patch them."""
    models = [
        {"key": "main", "name": MODEL,
         "description": MODEL_INFO.get(
             MODEL, "fast and multilingual, with conversation memory")},
    ]
    for model_id in ALT_CEREBRAS_MODELS:
        if model_id == MODEL:
            continue  # already listed as 'main'
        models.append(
            {"key": model_id, "name": model_id,
             "description": MODEL_INFO.get(model_id, "alternate Cerebras model")}
        )
    if HF_SPACE_ID:
        models.append(
            {"key": "hf", "name": "ArmGPT",
             "description": "Armenian only, slow, no memory"}
        )
    return models


def _resolve_model(text):
    """Match user input to a model by key or display name (case-insensitive).
    Returns the model dict, or None if nothing matches."""
    query = (text or "").strip().lower()
    if not query:
        return None
    for model in available_models():
        if query == model["key"].lower() or query == model["name"].lower():
            return model
    return None


def active_model(user_id):
    """The model dict the user is currently on. Falls back to the first model
    (main) if their saved preference is no longer available (e.g. a stale 'hf'
    after HF was unconfigured)."""
    provider = get_provider(user_id)
    models = available_models()
    for model in models:
        if model["key"] == provider:
            return model
    return models[0]


@bot.message_handler(commands=["sha"], func=is_allowed)
def cmd_sha(message):
    bot.send_message(message.chat.id, f"Live SHA: {COMMIT_SHA or 'unknown'}")


@bot.message_handler(commands=["model"], func=is_allowed)
def cmd_model(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 1:
        current = active_model(message.from_user.id)
        msg = f"Current model: {current['name']}"
        if len(available_models()) > 1:
            msg += "\n\nSee /models to list the options and switch."
        bot.send_message(message.chat.id, msg)
        return
    model = _resolve_model(parts[1])
    if model is None:
        bot.send_message(
            message.chat.id,
            f"Unknown model: {parts[1].strip()}. See /models for the options.",
        )
        return
    if not set_provider(message.from_user.id, model["key"]):
        bot.send_message(message.chat.id, "Could not save your preference. Try again later.")
        return
    if model["key"] == "hf":
        bot.send_message(
            message.chat.id,
            "Switched to hf (ArmGPT).\n\n"
            "Note: this is a tiny base completion model trained only on Armenian text. "
            "It continues whatever you write rather than answering questions, and it "
            "does not understand English. Replies take ~30-60s and there is no memory.",
        )
    else:
        bot.send_message(
            message.chat.id,
            f"Switched to {model['name']} — {model['description']}.",
        )


@bot.message_handler(commands=["models"], func=is_allowed)
def cmd_models(message):
    active = active_model(message.from_user.id)
    lines = []
    for model in available_models():
        marker = "  (active)" if model["key"] == active["key"] else ""
        lines.append(f"{model['name']} — {model['description']}{marker}")
    text = "\n".join(lines)
    if len(available_models()) > 1:
        text += "\n\nSwitch with /model <name>."
    bot.send_message(message.chat.id, text)


def _armenian_provider_override(user_id, text):
    """When the user writes Armenian, answer this one message with ARMENIAN_MODEL
    (accurate on Armenian) without touching their saved model. Returns a
    provider key to use for this call, or None to use their saved preference.

    None is returned — i.e. keep their model — when there's no Armenian, when
    ARMENIAN_MODEL is disabled, when they're already on it, or when they're on
    'hf' (ArmGPT is itself Armenian-native).
    """
    if not ARMENIAN_MODEL or not _has_armenian(text):
        return None
    current = get_provider(user_id)
    if current in ("hf", ARMENIAN_MODEL):
        return None
    return ARMENIAN_MODEL


@bot.message_handler(commands=["whoami"], func=is_allowed)
def cmd_whoami(message):
    """Report the sender's own Telegram identity + whether they're an admin.

    Available to everyone (it only reveals your own id/username). This is
    the setup helper for the admin panel: matching by numeric user id is
    the most reliable way to configure ADMIN_USERS, since a Telegram
    username can be unset or changed."""
    user = message.from_user
    username = f"@{user.username}" if getattr(user, "username", "") else "(none set)"
    admin = is_admin(message)
    lines = [
        "👤 *Your Telegram identity*",
        f"• User ID: `{user.id}`",
        f"• Username: {username}",
        f"• Name: {getattr(user, 'first_name', '') or '—'}",
        f"• Admin: {'yes ✅' if admin else 'no'}",
    ]
    if not admin:
        lines.append(
            "\nTo get admin access, set `ADMIN_USERS` in the server's `.env` "
            "to your *User ID* above (most reliable) or your username, then "
            "reload the web app."
        )
    send_reply(message, "\n".join(lines))


# --- Admin panel ------------------------------------------------------------
# Owner-only management commands, gated by func=is_admin (ADMIN_USERS in
# bot/config.py, default @Avetik_11). Deliberately NOT listed in
# COMMAND_CATEGORIES / the "/" autocomplete menu so they stay hidden from
# ordinary users; /admin is the discoverable entry point for the admin.
# /whoami (above) is available to everyone and reports your id/username so
# you can configure ADMIN_USERS reliably. User tracking that powers /stats,
# /users, and /broadcast lives in bot/users.py, recorded from the webhook.

# Admin command list, rendered by /admin. (command, description).
_ADMIN_COMMANDS = [
    ("admin", "show this admin panel"),
    ("stats", "usage statistics"),
    ("users", "list known users"),
    ("broadcast", "message every known user — /broadcast <text>"),
    ("say", "DM one user — /say <user_id> <text>"),
]


def _admin_name(message):
    """Best display name for the admin, for the panel header."""
    user = message.from_user
    if getattr(user, "username", ""):
        return f"@{user.username}"
    return getattr(user, "first_name", None) or f"user {user.id}"


def _messages_today():
    """Sum today's per-user message counters across the roster.

    The rate limiter stores a `rate:<id>:<date>` counter per user; there's
    no key scan in the store, so we read one counter per known user. Returns
    (total, active_user_count)."""
    if store is None:
        return 0, 0
    today = date.today()
    total = 0
    active = 0
    for user in all_users():
        try:
            raw = store.get(f"rate:{user['id']}:{today}")
        except Exception:
            raw = None
        if raw:
            n = int(raw)
            total += n
            active += 1
    return total, active


@bot.message_handler(commands=["admin"], func=is_admin)
def cmd_admin(message):
    if store is None:
        storage_line = "stateless (no user tracking, stats, or broadcast)"
    else:
        storage_line = "SQLite"
    total_today, active_today = _messages_today()
    lines = [
        f"🔧 *Admin panel* — {_admin_name(message)}",
        "",
        "*Status*",
        f"• Known users: {user_count()}",
        f"• Messages today: {total_today} (from {active_today} user(s))",
        f"• Model: {MODEL}",
        f"• Storage: {storage_line}",
        f"• Rate limit: {RATE_LIMIT}/user/day",
    ]
    if COMMIT_SHA:
        lines.append(f"• Version: {COMMIT_SHA}")
    lines.append("")
    lines.append("*Commands*")
    for name, desc in _ADMIN_COMMANDS:
        lines.append(f"/{name} — {desc}")
    send_reply(message, "\n".join(lines))


@bot.message_handler(commands=["stats"], func=is_admin)
def cmd_stats(message):
    if store is None:
        bot.send_message(
            message.chat.id,
            "Stats need storage (SQLITE_PATH), which isn't set up right now.",
        )
        return
    users = all_users()
    total_today, active_today = _messages_today()
    with_username = sum(1 for u in users if u.get("username"))
    lines = [
        "📊 *Bot statistics*",
        f"• Known users: {len(users)}",
        f"• With a @username: {with_username}",
        f"• Active today: {active_today}",
        f"• Messages today: {total_today}",
        f"• Model: {MODEL}",
        f"• Hosting: {HOSTING_LABEL}",
    ]
    if COMMIT_SHA:
        lines.append(f"• Version: {COMMIT_SHA}")
    send_reply(message, "\n".join(lines))


def _format_last_seen(ts):
    if not ts:
        return "?"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OverflowError, OSError):
        return "?"


@bot.message_handler(commands=["users"], func=is_admin)
def cmd_users(message):
    if store is None:
        bot.send_message(
            message.chat.id,
            "The user list needs storage (SQLITE_PATH), which isn't set up right now.",
        )
        return
    users = all_users()
    if not users:
        bot.send_message(message.chat.id, "No users recorded yet.")
        return
    limit = 100  # keep the reply bounded; most recent first
    shown = users[:limit]
    lines = [f"👥 *Known users* ({len(users)} total, showing {len(shown)})", ""]
    for i, user in enumerate(shown, start=1):
        handle = f"@{user['username']}" if user.get("username") else (user.get("first_name") or "—")
        lines.append(
            f"{i}. {handle}  `{user['id']}`  · last seen {_format_last_seen(user.get('last_seen'))}"
        )
    if len(users) > limit:
        lines.append(f"\n…and {len(users) - limit} more.")
    send_reply(message, "\n".join(lines))


@bot.message_handler(commands=["broadcast"], func=is_admin)
def cmd_broadcast(message):
    if store is None:
        bot.send_message(
            message.chat.id,
            "Broadcast needs storage (SQLITE_PATH), which isn't set up right now.",
        )
        return
    text = _arg(message)
    if not text:
        bot.send_message(
            message.chat.id,
            "Usage: /broadcast <message>\nSends your message to every known user.",
        )
        return
    users = all_users()
    if not users:
        bot.send_message(message.chat.id, "No users to broadcast to yet.")
        return
    sent = 0
    failed = 0
    for user in users:
        try:
            bot.send_message(int(user["id"]), text)
            sent += 1
        except Exception as e:
            failed += 1
            print(f"broadcast to {user.get('id')} failed: {e}")
        time.sleep(0.05)  # stay under Telegram's ~30 msg/s bulk limit
    bot.send_message(
        message.chat.id,
        f"📣 Broadcast done — delivered to {sent} user(s)"
        + (f", {failed} failed." if failed else "."),
    )


@bot.message_handler(commands=["say"], func=is_admin)
def cmd_say(message):
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[2].strip():
        bot.send_message(
            message.chat.id,
            "Usage: /say <user_id> <message>\nExample: /say 123456789 Hello there!",
        )
        return
    target, text = parts[1].strip(), parts[2].strip()
    if not target.lstrip("-").isdigit():
        bot.send_message(message.chat.id, f"Invalid user id: {target}. Use a numeric id (see /users).")
        return
    try:
        bot.send_message(int(target), text)
    except Exception as e:
        print(f"/say to {target} failed: {e}")
        bot.send_message(message.chat.id, f"Couldn't deliver to {target}: {e}")
        return
    bot.send_message(message.chat.id, f"✅ Sent to {target}.")


# --- Free-text chat handler -------------------------------------------------
# MUST stay the LAST-registered message handler. telebot dispatches the first
# handler that matches in registration order, and this one matches *any* text
# message (including commands, which are just text). Registering it after all
# command handlers is what lets /joke, /admin, /whoami, etc. win first; a
# command handler placed after this would be shadowed and never fire.

@bot.message_handler(content_types=["text"], func=is_allowed)
def handle_message(message):
    if not should_respond(message):
        return
    text = (message.text or "").replace(f"@{BOT_INFO.username}", "").strip()
    if not text:
        # Edited messages, forwards, or stickers-with-empty-caption can
        # arrive with no usable text. Don't burn rate-limit / AI calls on them.
        return
    _log(message, "in", text)
    if is_rate_limited(message.from_user.id):
        limit_msg = f"You've reached the daily limit of {RATE_LIMIT} messages. Try again tomorrow."
        bot.send_message(message.chat.id, limit_msg)
        _log(message, "out", f"[rate limited] {limit_msg}")
        return
    _record_turn(message.from_user.id, "You", text)  # save for /pdf export
    provider = _armenian_provider_override(message.from_user.id, text)
    try:
        with keep_typing(message.chat.id):
            reply = ask_ai(message.from_user.id, text, provider=provider)
        send_reply(message, reply)
        _record_turn(message.from_user.id, "Bot", reply)
        _log(message, "out", reply)
    except Exception as e:
        print(f"Error in handle_message: {e}")
        bot.send_message(message.chat.id, "Something went wrong. Please try again.")
        _log(message, "out", f"[error] {e}")
