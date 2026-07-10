# CLAUDE.md — Project Guide for AI Agents

This file describes the architecture, conventions, and deployment process for this project so an AI agent can work on it without guessing.

---

## What this project is

A Telegram bot template built for students. It runs on PythonAnywhere's free tier, uses Cerebras (or any OpenAI-compatible API) for AI responses, and a local SQLite file on PA's persistent disk for per-user conversation memory.

**Stack:** Python 3.13 · Flask · pyTelegramBotAPI · OpenAI SDK · SQLite · PythonAnywhere

---

## Project structure

```
telegram-pythonanywhere-bot/
├── api/
│   └── index.py          # Flask entrypoint — webhook route, /api/health, secret verification
├── bot/
│   ├── __init__.py
│   ├── config.py         # All env vars and constants (edit this to configure the bot)
│   ├── clients.py        # Instantiates bot, ai, store (do not edit unless adding a client)
│   ├── store.py          # SqliteStore — KV with lazy TTL expiry, backed by sqlite3
│   ├── ai.py             # ask_ai() — history + dispatch to providers
│   ├── providers.py      # Provider dispatch: OpenAI-compatible (with retry) or HF Gradio space
│   ├── preferences.py    # Per-user provider preference stored via store
│   ├── history.py        # get/save/clear conversation history via store (graceful degradation)
│   ├── rate_limit.py     # Per-user daily message rate limiting via store (graceful degradation)
│   ├── users.py          # Known-user roster for the admin panel (graceful degradation)
│   ├── dedupe.py         # Drops repeated update_ids when Telegram retries (graceful degradation)
│   ├── helpers.py        # send_reply(), keep_typing() context manager, should_respond() utilities
│   └── handlers.py       # All Telegram command and message handlers — add new commands here
├── tests/
│   ├── conftest.py       # Mocks env vars and external packages (telebot, openai, flask)
│   ├── test_ai.py        # ask_ai() orchestration
│   ├── test_providers.py # _call_main() retry, _call_hf() prompt handling, generate() dispatch
│   ├── test_preferences.py
│   ├── test_handlers.py
│   ├── test_helpers.py
│   ├── test_history.py
│   ├── test_rate_limit.py
│   ├── test_dedupe.py
│   ├── test_users.py     # User roster (record/list/count + stateless degradation)
│   ├── test_admin.py     # Admin gate (is_admin/is_allowed) + /admin panel commands
│   ├── test_store.py     # Direct SqliteStore tests (get/set/delete/incr/expire + TTL)
│   ├── test_deploy.py    # /api/deploy auto-deploy webhook (secret verification + git pull)
│   └── test_webhook.py
├── .github/
│   └── workflows/
│       ├── ci.yml        # Runs pytest on every push and pull request
│       └── deploy.yml    # Triggers PA auto-deploy via /api/deploy on push to main
├── .env.example          # Template for required environment variables
├── run_local.py          # Run the bot locally via polling — for learning + dev
├── pythonanywhere_wsgi.py # WSGI entry exposing Flask `app` as `application` for PA
├── Makefile              # install / run / test shortcuts
├── requirements.txt
├── CLAUDE.md             # Agent-readable project guide (this file)
└── README.md             # Student-facing setup guide
```

---

## How the bot works

1. Telegram sends a POST to `https://<your-pa-username>.pythonanywhere.com/api/webhook` on every message
2. PA's WSGI loader imports `pythonanywhere_wsgi.py` at the project root, which loads `.env` then re-exports the Flask `app` as `application`
3. `api/index.py` validates the `X-Telegram-Bot-Api-Secret-Token` header (if `WEBHOOK_SECRET` is set), then deserializes the update and passes it to pyTelegramBotAPI
4. pyTelegramBotAPI routes to the correct handler in `bot/handlers.py`
5. For text messages: checks `should_respond()` → checks rate limit → enters `keep_typing()` context manager (a background thread re-sends the Telegram "typing" action every 4s so the indicator stays alive during slow generations) → calls `ask_ai()` → exits context (stops thread) → sends reply
6. `ask_ai()` loads history via the store, prepends the system prompt, dispatches to `generate()` in `bot/providers.py` which calls `_call_main()` (with retry logic) or `_call_hf()` depending on the user's provider preference, then saves updated history

**Critical:** `telebot.TeleBot` must be created with `threaded=False`. Without this, handlers run in threads that can be killed unexpectedly. `threaded=False` is also fine for local polling (`run_local.py`) — updates just process sequentially in the main thread.

**Local development mode:** `run_local.py` at the repo root runs the same `bot/` modules via `bot.infinity_polling()` instead of the webhook. It auto-loads `.env` with a zero-dependency inline loader, calls `bot.remove_webhook()` to release any registered production webhook, then blocks on polling. Use this for teaching, prototyping, or iterating without redeploying. Any production webhook registered against the same bot token must be re-registered via `setWebhook` after you stop polling, otherwise production will stay silent.

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | — | From @BotFather on Telegram |
| `AI_API_KEY` | Yes | — | API key for the AI provider |
| `SQLITE_PATH` | No | — | Absolute path to a SQLite DB file. When set, enables history / rate limit / preferences / dedupe. When unset, bot runs in **stateless mode**. On PA use `/home/<your-pa-username>/bot.db` |
| `AI_BASE_URL` | No | `https://api.cerebras.ai/v1` | Any OpenAI-compatible base URL |
| `AI_MODEL` | No | `gpt-oss-120b` | Model name for the provider |
| `IMAGE_TRANSLATE_MODEL` | No | `gemma-4-31b` | Model used to translate Armenian `/image` + `/edit` prompts to English before generation. Kept separate from `AI_MODEL` because `gpt-oss-120b` mistranslates Armenian (turned "elephant on Mars" into "crater"/"pumpkin"); `gemma-4-31b` is accurate. Falls back to `AI_MODEL` then the raw prompt if unavailable. Set to `""` to disable and just use `AI_MODEL` |
| `ALT_CEREBRAS_MODELS` | No | `gemma-4-31b,zai-glm-4.7` | Comma-separated extra Cerebras model ids to offer as switchable options in `/model` / `/models`. Defaults to the extra models this key has. Only list ids your `AI_API_KEY` actually has access to, or `/model <id>` will 404 (and `generate()` falls back to `MODEL`). Note: not every account has access to every model (e.g. `qwen-3-235b-a22b-instruct-2507` 404s on some free-tier keys) |
| `ARMENIAN_MODEL` | No | `gemma-4-31b` | Cerebras model that handles Armenian well (accurate where `gpt-oss-120b` mistranslates). Used to translate Armenian `/image`/`/edit` prompts and to auto-answer Armenian chat messages. Blank to disable the chat auto-switch |
| `HF_SPACE_ID` | No | — | Hugging Face Gradio space ID (e.g. `edisimon/armgpt-demo`) — enables `/model` command when set |
| `HF_TOKEN` | No | — | HF auth token — needed if the Gradio space is private/gated; also optional for `/edit` (raises the free ZeroGPU quota for more reliable FLUX.1 Kontext edits) |
| `TOGETHER_API_KEY` | No | — | When set, `/image` generates via Together AI (`api.together.xyz` — on PA's outbound allowlist). When unset, `/image` falls back to keyless pollinations.ai (works locally; needs a PA allowlist request to reach `image.pollinations.ai` from PA free tier) |
| `TOGETHER_IMAGE_MODEL` | No | `black-forest-labs/FLUX.1-schnell-Free` | Together model id used by `/image` |
| `CF_ACCOUNT_ID` / `CF_API_TOKEN` | No | — | Cloudflare Workers AI — another free `/image` backend (`api.cloudflare.com` is allowlisted). When both are set (and `TOGETHER_API_KEY` isn't), `/image` uses Cloudflare. Token needs the "Workers AI" permission |
| `CF_IMAGE_MODEL` | No | `@cf/black-forest-labs/flux-1-schnell` | Cloudflare Workers AI model id used by `/image` |
| `HF_EDIT_SPACE` | No | `black-forest-labs/FLUX.1-Kontext-Dev` | Hugging Face Space (FLUX.1 Kontext) used by `/edit` — the **free, preferred, highest-quality** edit backend (true instruction editing). Called via `gradio_client`; uploads the source image to the Space (no public URL / token leak). Blank it to fall back to Together/Cloudflare. Free shared GPU, so ~30-60s per edit |
| `HF_EDIT_TIMEOUT` / `HF_EDIT_STEPS` / `HF_EDIT_GUIDANCE` | No | `120` / `12` / `2.5` | `/edit` Kontext knobs: gradio_client timeout (s), diffusion steps, guidance scale. Time scales ~linearly with steps (benchmarked: 8→~12s, 16→~19s, 28→~31s); default 12 favors speed with little quality loss. Raise for more detail |
| `TOGETHER_EDIT_MODEL` | No | `black-forest-labs/FLUX.1-kontext-dev` | Together AI model used by `/edit` when `HF_EDIT_SPACE` is blank and `TOGETHER_API_KEY` is set. Must be a Kontext / img2img-capable model — the default `/image` model can't edit |
| `CF_EDIT_MODEL` | No | `@cf/runwayml/stable-diffusion-v1-5-img2img` | Cloudflare Workers AI img2img model used by `/edit` when neither `HF_EDIT_SPACE` nor `TOGETHER_API_KEY` is set (and `CF_ACCOUNT_ID` + `CF_API_TOKEN` are). Lower quality (SD 1.5, not instruction-based) |
| `WEBHOOK_SECRET` | No | _auto-generated_ | Random string Telegram echoes back in `X-Telegram-Bot-Api-Secret-Token`. Auto-bootstrapped on first run: if the env var is unset, `bot/config.py::_bootstrap_webhook_secret()` generates a 64-hex secret, persists it to `.webhook_secret` (gitignored, mode 0600), and reuses it on subsequent boots. The boot-time `register_webhook()` then ships it to Telegram. Set the env var to override / share across envs |
| `WEBHOOK_URL` | No | — | When set, the bot auto-registers this URL as the Telegram webhook on every worker boot and after every `/api/deploy`. No manual `setWebhook` step needed. Idempotent. On PA, value is `https://<your-pa-username>.pythonanywhere.com/api/webhook`. Leave unset for local polling |
| `RATE_LIMIT` | No | `250` | Max messages per user per day |
| `ALLOWED_USERS` | No | _open_ | Comma-separated whitelist of usernames (with/without `@`) or numeric user IDs. Empty = everyone allowed. Non-empty = silent drop for non-whitelisted (no rejection reply, no leak of bot existence). Implemented as `func=is_allowed` on every `@bot.message_handler` so telebot never dispatches the handler |
| `ADMIN_USERS` | No | `Avetik_11` | Comma-separated admins (username with/without `@`, or numeric id — same format as `ALLOWED_USERS`). Admins get the `/admin` panel + management commands (`/stats`, `/users`, `/broadcast`, `/say`) and are always allowed to talk to the bot even when `ALLOWED_USERS` is a non-empty whitelist (so the owner can't lock themselves out). Gated via `func=is_admin` (`bot/helpers.py`). Set to `""` to disable the admin panel entirely. See "Admin panel" below |
| `HOSTING_LABEL` | No | `PythonAnywhere` | Label shown by the `/about` command |
| `DEPLOY_SECRET` | No | — | Enables `/api/deploy` auto-deploy webhook. Fail-closed: when unset, the endpoint returns 403. Generate with `openssl rand -hex 32` and set the same value as a GitHub repo secret named `DEPLOY_SECRET` so the workflow at `.github/workflows/deploy.yml` can call the endpoint |
| `PA_WSGI_PATH` | No | _auto-detected_ | Absolute path of the PA WSGI file `/api/deploy` touches to reload the worker. Only needed when auto-detection fails (non-default PA layout / custom domain) — the deploy response says so explicitly when that happens |

All env vars are read in `bot/config.py`. `.strip()` is called on every value to defend against trailing newlines / whitespace from copy-paste.

---

## AI provider

The bot uses the OpenAI Python SDK pointed at any OpenAI-compatible endpoint. Switching providers only requires changing `AI_BASE_URL` and `AI_MODEL` (via env vars — no code change needed).

**Known working providers (free tier):**

| Provider | Base URL | Notes |
|---|---|---|
| Cerebras | `https://api.cerebras.ai/v1` | Default. Confirmed working on free tier: `gpt-oss-120b`, `qwen-3-235b-a22b-instruct-2507` |
| Groq | `https://api.groq.com/openai/v1` | 14,400 req/day free. Model: `llama-3.1-8b-instant` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | Model: `gemini-2.5-flash` (250 req/day) |

**Cerebras model IDs** (exact strings — wrong format causes 404):
- `gpt-oss-120b` ✓ verified working on free tier. Current default (`bot/config.py`, `.env.example`) — strong reasoning at Cerebras speed
- `qwen-3-235b-a22b-instruct-2507` — availability is **account-dependent**: some free-tier keys have it, others 404 ("does not exist or you do not have access to it"). Not offered by default; add it to `ALT_CEREBRAS_MODELS` only after confirming your key can call it. Strong reasoning and multilingual, but slower per-token and more queue-pressured
- `llama3.1-8b` ✗ deprecated by Cerebras — do not use (was the previous default)

---

## Multi-provider support

The bot can dispatch requests to one of several models per user. Provider identifiers are **`main`**, any id listed in **`ALT_CEREBRAS_MODELS`**, and **`hf`**.

1. **`main`** (default) — the default Cerebras model from `AI_MODEL`.
2. **alternate Cerebras ids** — whatever is set in `ALT_CEREBRAS_MODELS` (comma-separated). **Defaults to `gemma-4-31b,zai-glm-4.7`** (the extra models the project's key has), so `main`, `gemma-4-31b`, `zai-glm-4.7` (and `hf`, if configured) are offered out of the box. Only list ids the account can access — advertising a model it can't makes `/model <id>` 404. (`generate()` falls back to `MODEL` on such a 404, so it degrades gracefully, but the honest fix is to only list ids the key has.) Each id gets a strengths blurb from `MODEL_INFO`.
3. **`hf`** (optional) — a Hugging Face Gradio space set via `HF_SPACE_ID` (with optional `HF_TOKEN` for private spaces). Called via `gradio_client.Client(...).predict(prompt, length, temperature, top_k, api_name="/generate")`. No retry (HF is slow).

`available_models()` in `bot/handlers.py` builds the list (`main` + `ALT_CEREBRAS_MODELS` + `hf`). `/model` shows/switches the current model (accepts a key or display name), `/models` lists them with an `(active)` marker. The switch hint only appears when more than one model is available.

Preferences are stored via `store` under `provider:{user_id}` (no TTL). If the store is not configured (stateless mode), the bot falls back to `DEFAULT_PROVIDER` (`"main"`). A saved preference that is no longer in `available_models()` (e.g. an id removed from `ALT_CEREBRAS_MODELS`) is treated as invalid on read and falls back to `main`.

**HF provider caveats** — the current target (`edisimon/armgpt-demo`, ArmGPT) has:
- Base completion model, not a chat model — `bot/providers.py::_last_user_message` extracts only the most recent user message and passes it as a bare prompt. Chat transcripts (`"User: ...\nAssistant: ..."`) would just confuse it since it was trained on raw Armenian text with no turn structure
- No system prompt support — the system prompt is dropped entirely for HF
- No conversation memory — only the latest user turn is sent
- Hardcoded knobs (`bot/providers.py`) — `HF_LENGTH=100`, `HF_TEMPERATURE=0.6`, `HF_TOP_K=30`. Tuned so generation finishes inside Telegram's ~60s webhook window
- Output is a `(html_output, status_text)` tuple — `_call_hf` takes index 0, strips HTML tags, and strips the echoed prompt prefix if present

To switch to a different HF space, change `HF_SPACE_ID` and confirm the target space exposes a `/generate` API with the same signature, or adapt `_call_hf` in `bot/providers.py`.

**PA outbound-whitelist caveat for HF Spaces.** `gradio_client` first fetches the space config from `huggingface.co` (whitelisted) and then routes `predict()` calls to `<space-subdomain>.hf.space` (NOT explicitly whitelisted as of last check). If `/model hf` hangs or 403s on PA but works locally, that's almost certainly the cause — verify with `curl -I https://<space>.hf.space/` from a PA Bash console, and if blocked, request `*.hf.space` on the PA forum whitelist thread. `bot/providers.py::_call_hf` passes `httpx_kwargs={"timeout": HF_REQUEST_TIMEOUT}` so a blocked subdomain fails fast instead of wedging the worker.

---

## Language handling (Armenian)

The bot works in Armenian end-to-end:

- **Chat + all AI-backed commands** — `SYSTEM_PROMPT` (`bot/config.py`) instructs the model to reply in the language of the *student's own words* (their topic/question/content), not the language of the English instruction template each command wraps around it. So `/explain ռեկուրսիա` answers in Armenian while `/explain recursion` answers in English. Every AI command routes through `ask_ai()`, so this one directive covers them all. Code/API names/technical terms stay in their standard (English) form even inside an Armenian reply.
- **Auto model-switch for Armenian chat** — `gpt-oss-120b` (the default chat model) understands Armenian but mistranslates specific words, while `gemma-4-31b` (`ARMENIAN_MODEL`) is accurate. So `handle_message()` calls `_armenian_provider_override()`: if a free-chat message contains Armenian, that single reply is generated with `ARMENIAN_MODEL` (threaded through `ask_ai(..., provider=...)` → `generate(..., provider=...)`) **without** changing the user's saved model. It's a no-op when there's no Armenian, when the user is already on `ARMENIAN_MODEL`, or when they're on `hf`/ArmGPT (Armenian-native). Only free chat auto-switches; slash commands keep the user's model and rely on the system-prompt directive above.
- **Model registry** — `available_models()` offers `main` (`AI_MODEL`, default `gpt-oss-120b`) plus `ALT_CEREBRAS_MODELS` (now defaults to `gemma-4-31b,zai-glm-4.7`) plus `hf` (if configured). Each carries a strengths blurb from `MODEL_INFO` (`bot/config.py`), shown by `/models`, `/model`, and a dedicated `/help` section. `/model <name>` switches; the switch is by key or display name.
- **`/image` + `/edit`** — image backends (FLUX / Cloudflare / pollinations) follow English prompts but largely ignore Armenian, so `_translate_prompt_for_image()` in `bot/handlers.py` detects Armenian text (`_has_armenian`, Unicode block U+0530–U+058F + ligatures U+FB13–U+FB17) and translates it to English before dispatch. Both `_generate_image()` and `_edit_image()` translate at the top.
  - **Translation model matters.** The translation uses `IMAGE_TRANSLATE_MODEL` (default `gemma-4-31b`), **not** the chat `MODEL`. This is deliberate: `gpt-oss-120b` translates Armenian badly (in testing it turned "elephant on Mars" into "a crater on Mars" / "a pumpkin on Mars"), while `gemma-4-31b` is accurate. If that id isn't on the key, it falls back to `MODEL`, then to the original prompt.
  - **Robustness.** A one-shot example in the messages keeps the model behaving as a pure translator (not answering conversationally — the failure mode that produced unrelated images). Output is rejected (→ next model / original) if it's empty or still contains Armenian, and wrapping quotes/backticks are stripped. English prompts skip translation entirely.

## Image commands

- **`/image <prompt>`** — text-to-image. `_generate_image()` in `bot/handlers.py` picks the first configured backend: Together AI → Cloudflare Workers AI → keyless pollinations.ai (the zero-config fallback). All three are free-tier friendly.
- **`/edit <instruction>`** — image-to-image (the AI edits an existing image). Three ways to use it: (1) send a photo with the caption `/edit <instruction>` — handled by `cmd_edit_caption` (a `content_types=["photo","document"]` handler gated on `_edit_command_in_caption`, because telebot's command matcher only sees `message.text`, never a photo caption); (2) reply to a photo/image with `/edit <instruction>`; (3) send `/edit <instruction>` then send the image (mirrors `/convert` via `register_next_step_handler`). Both a photo and an image *document* are accepted (`_image_file_id()`).
  - **Backend priority (`_edit_image()`):** free **FLUX.1 Kontext via a Hugging Face Space** (`HF_EDIT_SPACE`, default `black-forest-labs/FLUX.1-Kontext-Dev`) → Together AI (`TOGETHER_EDIT_MODEL`) → Cloudflare img2img (`CF_EDIT_MODEL`). HF Kontext is a *true instruction editor* ("make the sky a sunset" changes only the sky) and is preferred because it's free and highest quality. It's called via `gradio_client` (`_edit_image_hf`), which uploads the source image straight to the Space — **no public URL and no bot-token leak** (important on PA, which has no public file host). `hf.space` + `huggingface.co` are now on PA's allowlist. The Space runs on a free shared GPU (ZeroGPU), so an edit typically takes ~30-60s and can occasionally be busy/unavailable; `_do_edit` wraps the call in `keep_typing()`, and a slow edit still delivers because `send_photo` is out-of-band from the webhook reply. Anonymous access works; an optional free `HF_TOKEN` raises the ZeroGPU quota. Kontext Spaces return WebP, so `_to_telegram_image()` re-encodes to PNG (Telegram's `send_photo` can reject WebP).
  - **No keyless fallback:** pollinations only does text-to-image (its `kontext` model is now paywalled to `enter.pollinations.ai`), so if `HF_EDIT_SPACE` is blanked and no Together/CF keys are set, `/edit` returns a clear "not configured" message. `_do_edit` logs backend exceptions (`print("Error in _do_edit: …")`) so failures show up in the PA error log, not just the user-facing message.

> **No `/video` command (removed, don't re-add without a paid backend).** A text-to-video `/video` was built and removed. Root cause: free video is impractical on this stack. Free HF ZeroGPU caps GPU **per call** (~120s) and gives only a few minutes/day: the models that fit the cap (distilled LTX) follow prompts poorly, and the models that follow prompts (CogVideoX-5B reserves 300s) exceed the free per-call cap and need HF PRO. Together/Cloudflare have no free text-to-video; there is no keyless fallback; Kling has no free API and isn't PA-allowlisted. A viable `/video` needs **HF PRO** or a **paid API** (fal.ai/Replicate/Kling) behind a key + a PA allowlist request. See git history around this note for the full LTX/CogVideoX `gradio_client` signatures if reviving it.

## Webhook verification

To block spoofed requests, set a random secret and pass it when registering the webhook:

```bash
# Add WEBHOOK_SECRET to PA .env, reload the web app, then:
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  --data-urlencode "url=https://<your-pa-username>.pythonanywhere.com/api/webhook" \
  --data-urlencode "secret_token=<your secret>"
```

When `WEBHOOK_SECRET` is set, `api/index.py` checks the `X-Telegram-Bot-Api-Secret-Token` header on every request and returns 403 if it does not match. If the variable is not set, verification is skipped (backwards compatible).

---

## Storage

The bot's storage layer is a thin KV-with-TTL abstraction in `bot/store.py` exposing five operations: `get / set / delete / incr / expire`. Only one backend exists: **`SqliteStore`** — a file-backed sqlite3 with lazy TTL expiry.

- **`SQLITE_PATH` unset (stateless mode):** `bot/clients.py` sets `store = None` and prints a one-line startup notice. Each consumer (`history`, `rate_limit`, `preferences`, `dedupe`) checks for `None` at the top of every function and returns safe defaults: history is empty, rate limiting is skipped, `get_provider` returns `DEFAULT_PROVIDER`, `set_provider` returns `False`, dedupe is a no-op. This is the intended Day-1 teaching mode — kids can run the bot locally with only a Telegram token and an AI API key.
- **`SQLITE_PATH` set:** `SqliteStore` opens the DB in WAL mode with `check_same_thread=False`. The schema is a single `kv(key, value, expires_at)` table; expired rows are filtered on read and overwritten on write — no background sweeper, never affects correctness.
- **Graceful degradation under runtime failure:** every store call in the consumer modules is wrapped in try-except. On failure: same fallbacks as stateless mode, plus an error log line.
- **Performance vs. networked KV:** SQLite ops are in-process and take microseconds, vs. ~20–80ms per round-trip to a remote KV over HTTPS. The webhook reply latency for an average message is dominated by the AI call, not storage.

---

## Admin panel

Owner-only management commands, gated by `func=is_admin` (`bot/helpers.py`), configured via `ADMIN_USERS` (default `Avetik_11`). Non-admins fail the filter, so telebot never dispatches these handlers — an admin command typed by a non-admin just falls through to normal text handling (like any unknown command), so the panel's existence isn't confirmed to them. The commands are deliberately **not** in `COMMAND_CATEGORIES`, so they don't appear in `/help` or the `/` autocomplete menu; `/admin` is the discoverable entry point for admins.

Commands (`bot/handlers.py`, at the end of the file):

- **`/admin`** — the panel: live status (known users, messages today, model, storage, rate limit, version) + the admin command list.
- **`/stats`** — usage statistics (known users, how many have a `@username`, active-today count, messages today).
- **`/users`** — the known-user roster (most recent first, capped at 100 in the reply), each with `@handle`, numeric id, and last-seen time.
- **`/broadcast <text>`** — send `<text>` to every known user, with a `time.sleep(0.05)` between sends to stay under Telegram's ~30 msg/s bulk limit; reports delivered/failed counts.
- **`/say <user_id> <text>`** — DM a single user by numeric id (get ids from `/users`).

**User roster (`bot/users.py`).** The bot otherwise has no list of *who* has used it (history/rate limits are keyed per id but there's no index). `bot/users.py` keeps a lightweight roster in the same KV store: a `users:index` JSON list of id strings + one `user:<id>` record each (username, first name, last-seen). `record_from_update()` is called once per update from the webhook in `api/index.py` (after the dedupe claim, so never twice), best-effort and wrapped so roster bookkeeping can't break message handling. It follows the same graceful-degradation pattern as `history`/`preferences`/`rate_limit`: every function no-ops / returns safe defaults in stateless mode (`SQLITE_PATH` unset) or on a store error — so `/stats`, `/users`, and `/broadcast` report "needs storage" rather than crashing. `/stats`'s "messages today" is computed by reading each roster user's `rate:<id>:<today>` counter (the store has no key scan), so it's exact but O(users).

---

## Reliability

- **AI retry logic:** `_call_main()` in `bot/providers.py` retries up to 3 attempts (`AI_RETRIES=2` extra retries) with exponential backoff (1s, 2s) before raising. Handles transient network errors and rate-limit spikes. HF is not retried (it's too slow — a retry would blow the per-request budget).
- **Typing indicator during slow calls:** `keep_typing()` in `bot/helpers.py` spawns a daemon thread that re-sends `send_chat_action(chat_id, "typing")` every 4 seconds (Telegram's typing action expires after ~5s). On context exit the thread is signalled and joined with a 2s timeout so the request shuts down cleanly. Proxy 503s from PA's outbound proxy are caught and logged; the thread keeps looping.

---

## PythonAnywhere deployment

The deployment target is `https://<your-pa-username>.pythonanywhere.com`. The same Flask app at `api/index.py` runs via a long-lived WSGI worker — no serverless cold-start considerations, no function timeout caps.

**PA wiring** (manual one-time setup, no CLI equivalent):
- PA's WSGI file at `/var/www/<your-pa-username>_pythonanywhere_com_wsgi.py` adds the project to `sys.path` and does `from pythonanywhere_wsgi import application`
- `.env` is uploaded to the PA project directory (read by `pythonanywhere_wsgi.py` at worker startup using the same minimal loader as `run_local.py`)
- Webhook registration is a one-off `curl setWebhook` against `https://<your-pa-username>.pythonanywhere.com/api/webhook`

**Re-deploying after a `git pull`:** PA workers don't auto-reload. Either click "Reload" on the Web tab, or `touch /var/www/<your-pa-username>_pythonanywhere_com_wsgi.py` in a Bash console (changing the WSGI file's mtime triggers a worker reload).

**First-time deploy automation.** `scripts/pa_deploy.sh` (run via `make deploy-pa`) drives the full first-time setup from the local terminal: creates the web app via `POST /api/v0/user/<u>/webapps/`, finds or creates a bash console (the only step requiring a one-time browser visit — PA initializes new consoles only after they're loaded in the browser), then `send_input`s `git clone`, `python3.13 -m venv`, and `pip install -r requirements.txt`. It then uploads `.env` to `<PROJECT_DIR>/.env` and the WSGI shim to `/var/www/<u>_pythonanywhere_com_wsgi.py` via the Files API, `PATCH`es `source_directory` + `virtualenv_path` on the web app, and reloads. Required `.env` vars: `PA_USERNAME`, `PA_API_TOKEN` (in addition to the regular bot vars). Idempotent — re-running heals partial state. For ongoing updates the GitHub Actions workflow (`.github/workflows/deploy.yml` → `/api/deploy`) is still preferred; the script is for first-time setup + recovery.

**Console output polling.** `pa_deploy.sh::run_remote` wraps every command it sends as `{ cmd; } && echo <marker>_'OK' || echo <marker>_'FAIL'`, then polls `GET /consoles/<id>/get_latest_output/` every 3s until either marker appears (or it times out). The quoted `'OK'`/`'FAIL'` suffixes keep the echoed *input* line from matching the grep — only the executed echo produces the contiguous marker — so success isn't declared early or on a failed command. Cloning uses an HTTPS URL derived from the origin remote (PA consoles have no SSH key for GitHub).

**Auto-deploy on push to main.** When `DEPLOY_SECRET` is set in PA's `.env`, the `/api/deploy` endpoint accepts authenticated POSTs that converge the checkout to origin and reload the worker: `git fetch origin` + `git reset --hard origin/<branch>` (NOT `git pull --ff-only` — a pull wedges permanently once the server worktree diverges via a hand-edited file or a force-push, and every later deploy 500s while the bot keeps running old code; reproduced live 2026-07-02). Untracked files (`.env`, `.webhook_secret`, `.deploy.lock`, `bot.db`) survive the reset; there is deliberately no `git clean`. Consequence: edits to TRACKED files made directly on PA are discarded by the next deploy — the PA checkout is a deploy target, not a workspace. If the deploy changed `requirements.txt`, the endpoint runs `<venv>/bin/pip install -r requirements.txt` (venv found via `sys.prefix`) before reloading, and refuses to reload (500, old worker keeps serving) if pip fails. The WSGI-touch outcome is always reported in the response body — a missing WSGI file yields a loud "worker was NOT restarted" warning instead of the old silent skip; `_pa_wsgi_path()` resolves via `PA_WSGI_PATH` env → `$USER`/`$LOGNAME` → `pwd.getpwuid` → `/home/<user>/` prefix of the checkout → unambiguous `/var/www/*_pythonanywhere_com_wsgi.py` glob. `.github/workflows/deploy.yml` triggers on push to `main` using two repo secrets (`DEPLOY_SECRET`, `PA_DEPLOY_URL`), retries the curl through PA proxy blips (idempotent server side makes retries safe), then polls `/api/health` until the pushed commit's SHA is actually being served — a green run means the new code is LIVE, not merely that the server said OK. The endpoint fails-closed (403) when `DEPLOY_SECRET` is unset and uses `hmac.compare_digest` for secret comparison. The workflow skips with a warning when its secrets aren't set, so this is fully optional. `/api/health` returns `OK <short-sha>`, with the SHA captured at worker boot — it identifies the code the worker is *running*, which is what makes the verification step truthful.

**Auto webhook registration.** When `WEBHOOK_URL` is set, `pythonanywhere_wsgi.py` calls `bot.clients.register_webhook()` at worker boot, and `/api/deploy` calls it again after every deploy. Both call `bot.set_webhook(url=WEBHOOK_URL, secret_token=WEBHOOK_SECRET)` with up to 3 attempts (1s/2s backoff) because PA's outbound proxy 503-blips transiently (a boot-time registration was seen failing on such a blip on 2026-06-29). Failures are caught and logged — never crash the worker. This eliminates the manual `curl setWebhook` step from the deploy guide.

**Auto webhook-secret bootstrap.** If `WEBHOOK_SECRET` is unset, `bot/config.py::_bootstrap_webhook_secret()` generates a 64-hex-character random secret and persists it in `.webhook_secret` at the project root (gitignored, chmod 0600). Subsequent boots read it back. The auto-registration above then passes it to Telegram via `secret_token`, so the bot is signed-by-default with zero manual setup. A read-only mount or other FS error falls back to an empty secret (unsigned webhook) rather than crashing the worker. To rotate: delete `.webhook_secret` and reload — boot generates a new one and re-registers. Tests must set `WEBHOOK_SECRET` in env (conftest.py does this) so the bootstrap doesn't litter the working tree.

**Critical PA-specific constraints:**
- **Free-tier outbound HTTPS whitelist.** `api.telegram.org`, `api.cerebras.ai`, `huggingface.co` are all on it. Most other domains aren't — if you add a feature that calls a new service, check `https://www.pythonanywhere.com/whitelist/` first. To request a new domain be added, post on the PA forums.
- **Monthly renewal.** Free-tier web apps expire roughly every month. PA emails a week before. The user must click "Run until N days from today" in the Web tab to extend. There is no API endpoint for this on free tier — it must be done in the browser (or via paid plan upgrade).
- **No SSH, no scheduled tasks on free tier.** Automation against PA is limited to the HTTP API for files/webapps/consoles, and consoles require a one-time browser visit before the API can send_input. Don't promise full hands-off automation.
- **One webhook per bot token.** If you ever run `make run` locally, the production webhook is removed. Re-register it after by running `setWebhook` again — see README Step 12.

---

## Known gotchas

- **`threaded=False` is required** — see "How the bot works" above
- **Cerebras model names** — exact ID strings are required (e.g. `gpt-oss-120b`); a wrong format causes a 404. Check https://inference-docs.cerebras.ai/models for current IDs
- **Telegram 4096 char limit** — `send_reply()` in `bot/helpers.py` handles splitting automatically
- **Group chats** — `should_respond()` returns `True` for all messages, so the bot replies to every message in any chat it's in. If you need mention-gated or reply-gated behavior in groups, reintroduce it in `bot/helpers.py::should_respond`. The handler still strips `@<bot_username>` from text before sending to the AI
- **Webhook secret must match** — if `WEBHOOK_SECRET` is set, the same value must be passed as `secret_token` in `setWebhook`. Mismatch causes all updates to return 403 and the bot goes silent
- **Don't hand-edit tracked files on PA** — every `/api/deploy` runs `git reset --hard origin/<branch>`, so server-side edits to tracked files are silently discarded on the next push. Untracked files (`.env`, `.webhook_secret`, `bot.db`) are safe. Change code via git, always
- **`/api/health` body is `OK <short-sha>`** — the deploy workflow string-matches this prefix to verify a deploy went live. Scripts should check the HTTP status or the `OK ` prefix, never exact body equality
- **PA expects WSGI to expose `application`** — `pythonanywhere_wsgi.py` does `from api.index import app as application`. Renaming the Flask app variable would break this
- **Formatter strips unused imports between Edit calls** — if you do a two-step rewrite (add an import in one Edit, use it in the next), the formatter may remove the "unused" import between calls. Combine them into one Edit, or re-add the import after the second Edit
- **`fcntl` is POSIX-only** — `api/index.py` guards `import fcntl` with `try/except ImportError` and routes its `/api/deploy` flock through `_lock_deploy_nb`/`_unlock_deploy` (no-ops without fcntl). A bare `import fcntl` breaks every test that imports `api.index` on Windows. Don't reintroduce one
- **Windows `make.ps1 install` + the Microsoft Store Python stub** — typing `py`/`python` on Windows can hit a Store "app execution alias": a 0-byte stub under `%LOCALAPPDATA%\Microsoft\WindowsApps` that exits 0 and creates nothing. So `Get-Command py` succeeding (or `py -m venv` returning 0) proves nothing. `make.ps1`'s `New-RepoVenv` tries `py`→`python`→`python3` and keeps the first whose run actually produces `.venv\Scripts\python.exe`; don't "simplify" it back to a single `Get-Command` check. A student whose `python --version` works can still hit the old failure because the script tried `py` (the stub) first
