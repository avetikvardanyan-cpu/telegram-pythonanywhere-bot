import os
import secrets as _secrets_mod
import subprocess as _subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_WEBHOOK_SECRET_FILE = _PROJECT_ROOT / ".webhook_secret"


def _get_commit_sha() -> str:
    """Return the short SHA of the deployed commit, or an empty string.

    Computed once at module import — so the value reflects the worker's
    actual code, not whatever `git pull` did since boot. The auto-deploy
    flow touches the WSGI file on pull, which spawns a fresh worker on
    the next request with the new SHA. This makes /about a reliable
    "what version is live right now" probe.
    """
    try:
        result = _subprocess.run(
            ["git", "-C", str(_PROJECT_ROOT), "rev-parse", "--short=7", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (_subprocess.SubprocessError, OSError):
        pass
    return ""


COMMIT_SHA = _get_commit_sha()


def _bootstrap_webhook_secret(file_path: Path = _WEBHOOK_SECRET_FILE) -> str:
    """Return WEBHOOK_SECRET from env if set; otherwise read/generate a
    persistent random secret in `file_path`.

    This makes the webhook signed-by-default: a fresh PA deploy with no
    manual `openssl rand` step still rejects forged updates because the
    bot auto-generates and persists a 64-hex-char secret on first run,
    then registers it with Telegram via the boot-time `register_webhook()`.

    Precedence: env var > on-disk file > newly generated. Filesystem
    errors fall back to the empty string so a read-only mount can't
    crash worker boot — the webhook just stays unsigned in that case.
    """
    env_value = os.environ.get("WEBHOOK_SECRET", "").strip()
    if env_value:
        return env_value
    try:
        if file_path.exists():
            existing = file_path.read_text().strip()
            # Empty or whitespace-only file: treat as missing and regenerate,
            # otherwise we'd silently disable webhook auth.
            if existing:
                return existing
        new_secret = _secrets_mod.token_hex(32)
        file_path.write_text(new_secret)
        try:
            os.chmod(file_path, 0o600)
        except OSError:
            pass  # best-effort tightening; Windows / odd mounts can skip
        print(f"Generated webhook secret at {file_path} (auto-bootstrap)")
        return new_secret
    except OSError as e:
        print(f"Could not persist webhook secret ({e}); webhook will be unsigned")
        return ""


# Telegram
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"].strip()
WEBHOOK_SECRET = _bootstrap_webhook_secret()

# When set, the bot auto-registers this URL as the Telegram webhook on
# worker boot and after every /api/deploy. Leave unset for local
# polling (run_local.py). Example value on PA:
#   WEBHOOK_URL=https://<your-pa-username>.pythonanywhere.com/api/webhook
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()

# AI provider
AI_API_KEY = os.environ["AI_API_KEY"].strip()
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.cerebras.ai/v1").strip()
MODEL = os.environ.get("AI_MODEL", "gpt-oss-120b").strip()

# The Cerebras model that handles Armenian well. gpt-oss-120b (the chat MODEL)
# translates Armenian poorly — it dropped "elephant" and hallucinated
# "crater"/"pumpkin" in testing — whereas gemma-4-31b is accurate. Used to
# (1) translate Armenian /image + /edit prompts to English and (2) auto-answer
# Armenian chat messages (see bot/handlers.py::_armenian_provider_override).
ARMENIAN_MODEL = os.environ.get("ARMENIAN_MODEL", "gemma-4-31b").strip()

# Model used to translate non-English (currently Armenian) /image and /edit
# prompts into English before they hit the image backend. Defaults to
# ARMENIAN_MODEL. If the account can't access this id,
# _translate_prompt_for_image() falls back to MODEL, then to the original
# prompt, so /image never breaks. Set IMAGE_TRANSLATE_MODEL="" to just use MODEL.
IMAGE_TRANSLATE_MODEL = os.environ.get("IMAGE_TRANSLATE_MODEL", ARMENIAN_MODEL).strip()

# Human-readable strengths for the Cerebras models this bot offers, shown by
# /models and /help. Keyed by model id. A model not listed here still works —
# it just gets a generic description.
MODEL_INFO = {
    "gpt-oss-120b": "strong all-round reasoning + coding at Cerebras speed — best for English and code (default)",
    "gemma-4-31b": "best at Armenian & other non-English languages — accurate, natural replies (auto-used when you write in Armenian)",
    "zai-glm-4.7": "strong multilingual reasoning — good for longer, detailed answers",
}

# Extra Cerebras model ids the account can access, offered as switchable
# options by /model and /models (comma-separated). Defaults to the extra models
# this key has (gemma-4-31b, zai-glm-4.7) alongside the default gpt-oss-120b.
# Only list ids your AI_API_KEY actually has access to, or /model <id> will 404
# and fall back to MODEL. Override via the ALT_CEREBRAS_MODELS env var.
ALT_CEREBRAS_MODELS = [
    m.strip()
    for m in os.environ.get("ALT_CEREBRAS_MODELS", "gemma-4-31b,zai-glm-4.7").split(",")
    if m.strip()
]

# Hugging Face provider (optional) — when set, users can switch via /model
HF_SPACE_ID = os.environ.get("HF_SPACE_ID", "").strip()
HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()  # optional, for private spaces
DEFAULT_PROVIDER = "main"

# Image generation for /image. When TOGETHER_API_KEY is set, /image uses
# Together AI (api.together.xyz — on PythonAnywhere's outbound allowlist).
# When unset, /image falls back to the keyless pollinations.ai service (which
# works locally but needs an allowlist request to reach it from PA free tier).
TOGETHER_API_KEY = os.environ.get("TOGETHER_API_KEY", "").strip()
TOGETHER_IMAGE_MODEL = os.environ.get(
    "TOGETHER_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell-Free"
).strip()

# Cloudflare Workers AI — another free image backend (api.cloudflare.com is on
# PA's allowlist). Free tier runs FLUX.1-schnell. Needs a free account id + an
# API token scoped to "Workers AI". Used by /image when both are set.
CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "").strip()
CF_API_TOKEN = os.environ.get("CF_API_TOKEN", "").strip()
CF_IMAGE_MODEL = os.environ.get(
    "CF_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell"
).strip()

# Image editing (image-to-image) for /edit. Editing an existing image needs an
# img2img-capable backend, so /edit reuses the TOGETHER / CF keys above but a
# different model: Together AI uses a FLUX.1 Kontext model (takes a source
# image + instruction), Cloudflare uses a Stable Diffusion img2img model. The
# keyless pollinations fallback is text-to-image only and can't edit, so /edit
# is unavailable when neither TOGETHER_API_KEY nor CF_ACCOUNT_ID+CF_API_TOKEN
# is set. Override these only if your key can access a different model.
TOGETHER_EDIT_MODEL = os.environ.get(
    "TOGETHER_EDIT_MODEL", "black-forest-labs/FLUX.1-kontext-dev"
).strip()
CF_EDIT_MODEL = os.environ.get(
    "CF_EDIT_MODEL", "@cf/runwayml/stable-diffusion-v1-5-img2img"
).strip()

# FREE image editing via a Hugging Face Space running FLUX.1 Kontext — a true
# instruction-based editor ("make the sky a sunset" changes only the sky).
# Preferred /edit backend when HF_EDIT_SPACE is set (it defaults on, so /edit
# does real Kontext editing out of the box). Called via gradio_client, which
# uploads the source image straight to the Space (no public URL, no bot-token
# leak). Both hf.space and huggingface.co are on PA's outbound allowlist, and
# the Space runs on a free shared GPU (ZeroGPU) — so an edit can queue for
# ~30-60s or be briefly unavailable. HF_TOKEN (optional, free) raises the
# ZeroGPU quota for more reliable use; it is reused from the HF provider above.
HF_EDIT_SPACE = os.environ.get(
    "HF_EDIT_SPACE", "black-forest-labs/FLUX.1-Kontext-Dev"
).strip()
# Generous timeout: gradio_client waits through the queue. Telegram may retry
# the webhook past ~60s, but dedupe drops the retry and the finished image is
# still delivered out-of-band via send_photo, so a slow edit isn't lost.
HF_EDIT_TIMEOUT = int(os.environ.get("HF_EDIT_TIMEOUT", "120"))
# Diffusion steps. Generation time scales ~linearly with this. Benchmarked on
# the Kontext-Dev Space: 8 steps ~12s, 16 ~19s, 28 ~31s — with little visible
# quality difference for typical edits. Default 12 is the speed/quality sweet
# spot; raise it (e.g. 20-28) for more detail, lower (8) for max speed. The
# shared free GPU's queue wait is separate and not controllable from here.
HF_EDIT_STEPS = int(os.environ.get("HF_EDIT_STEPS", "12"))
HF_EDIT_GUIDANCE = float(os.environ.get("HF_EDIT_GUIDANCE", "2.5"))

# Storage — optional. When SQLITE_PATH is unset the bot runs in
# stateless mode: history / rate limiting / preferences / dedupe all
# degrade gracefully (the consumer modules in bot/ check `store is
# None` at the top of every function and return safe defaults).
SQLITE_PATH = os.environ.get("SQLITE_PATH", "").strip()

# Label shown by the /about command. Defaults to "PythonAnywhere" since
# that is the documented deployment target. Override to suit your host.
HOSTING_LABEL = os.environ.get("HOSTING_LABEL", "PythonAnywhere").strip()

# Auto-deploy webhook secret. When set, /api/deploy accepts requests
# that present this value in the X-Deploy-Secret header and runs
# `git pull` + WSGI reload. When unset, /api/deploy returns 403 — the
# endpoint is fail-closed.
DEPLOY_SECRET = os.environ.get("DEPLOY_SECRET", "").strip()

# App
SYSTEM_PROMPT = """You are a friendly, knowledgeable coding assistant and tutor chatting with a student on Telegram. You specialize in programming, software, and computer science — writing code, debugging, explaining concepts, algorithms, and tools.

Your goals, in order: be accurate, be helpful, and help the student actually learn.

Coding and tech are your specialty, but if someone asks about something else, go ahead and answer it helpfully too. You can gently mention you're happiest with programming questions, but never refuse to help.

How to respond:
- Keep it concise and chat-friendly. Telegram messages are short — no rigid section headers or long essays unless the student asks for depth.
- Match the question: a quick question gets a quick answer; a hard one gets a clear, step-by-step explanation.
- When you show code, keep it minimal and correct, and put it in a code block. Add a short note on what it does and why.
- Teach the "why," not just the "what." Nudge the student toward understanding instead of just handing over answers.
- Adapt to the student's level. Explain jargon the first time you use it.

Language:
- Reply in the language of the student's own words — the topic, question, or content THEY wrote — not the language of any instructions wrapped around it. If the student's input is in Armenian, reply in fluent, natural Armenian, even when the surrounding request is phrased in English. If they write in English (or switch languages), follow them.
- Keep code, API names, commands, and technical terms in their standard form (usually English) even inside an Armenian reply.

Accuracy:
- Never invent APIs, syntax, library names, or facts. If you're not sure, say so plainly rather than guessing.
- If a question is ambiguous and the answer depends on it, ask one short clarifying question.

Tone: warm, encouraging, and a little fun. You're here to make coding feel approachable."""

MAX_HISTORY = 20  # messages kept per user (10 conversation turns)
HISTORY_TTL = 2592000  # conversation history expires after 30 days (seconds)
RATE_LIMIT = int(os.environ.get("RATE_LIMIT", "250"))  # max messages per user per day

# Comma-separated whitelist of Telegram users. Each entry is either a
# username (with or without leading @) or a numeric user_id. Empty
# (default) means everyone can talk to the bot. When non-empty, the
# bot stays silent for anyone not in the list — silence instead of a
# rejection message so scanners don't get confirmation the bot exists.
#
# Example: ALLOWED_USERS=@alice,bob,123456789
ALLOWED_USERS = [
    u.strip().lstrip("@")
    for u in os.environ.get("ALLOWED_USERS", "").split(",")
    if u.strip()
]
MAX_MSG_LEN = 4096  # Telegram's character limit per message
# Provider call budget. Total worst case =
# AI_RETRIES * AI_REQUEST_TIMEOUT + sum of backoff sleeps. With
# retries=2 and timeout=25s plus 1s backoff: 25 + 1 + 25 = 51s.
AI_REQUEST_TIMEOUT = 25  # seconds, applied per-attempt to OpenAI-compatible calls
AI_RETRIES = 2  # total attempts (not extra retries) — 2 means one retry on failure
# HF Gradio request timeout. Without this a hung `predict()` would occupy the
# PA worker indefinitely; combined with the dedupe pre-claim, Telegram's
# retries get silently dropped for ~10 min. Tuned to give ArmGPT enough
# headroom for cold-start jitter while still freeing the worker before
# Telegram's webhook timeout (~60s).
HF_REQUEST_TIMEOUT = 50
