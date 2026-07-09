from bot.config import SYSTEM_PROMPT
from bot.history import get_history, save_history
from bot.providers import generate


def ask_ai(user_id: int, user_message: str, provider: str = None) -> str:
    history = get_history(user_id)
    history.append({"role": "user", "content": user_message})

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += history

    # Never let a provider error propagate: many command handlers call ask_ai
    # without their own try/except, and an uncaught exception here would turn
    # the whole webhook request into an HTTP 500 (Telegram then retries the
    # same update forever and the bot appears dead). Return a friendly message
    # instead, and don't pollute history with a failed turn.
    try:
        reply = generate(user_id, messages, provider=provider)
    except Exception as e:
        print(f"AI generation failed: {e}")
        return "Sorry, I couldn't reach the AI just now. Please try again in a moment."

    history.append({"role": "assistant", "content": reply})
    save_history(user_id, history)
    return reply
