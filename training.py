"""Sistema de entrenamiento — captura, revisión y persistencia."""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import aiohttp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

log = logging.getLogger("diana.training")

_cfg: dict[str, Any] = {}
pending_reviews: dict[str, dict] = {}
pending_correction: dict[int, str] = {}
last_auto: dict[int, dict] = {}
_notify_queue: list[dict] = []
_reviewer_id: int | None = None
_review_counter = 0

EVASION_PHRASES = (
    "historia larga",
    "otro momento",
    "no sé",
    "no se",
    "mejor con lucien",
    "el mayordomobot",
)

JUDGE_PROMPT = """Evalúa si esta respuesta automática de Diana fue adecuada.

Mensaje del usuario:
{user_message}

Respuesta generada:
{bot_response}

Responde SOLO con JSON válido:
{{"score": 1-5, "generic": true/false, "reason": "breve explicación"}}"""


def configure(**kwargs: Any) -> None:
    global _cfg
    _cfg = kwargs
    _load_pending()
    _init_counter()


def set_reviewer_id(user_id: int) -> None:
    global _reviewer_id
    _reviewer_id = user_id


def get_reviewer_id() -> int | None:
    if _cfg.get("reviewer_id"):
        return _cfg["reviewer_id"]
    return _reviewer_id


def _training_path() -> Path:
    return Path(_cfg.get("training_file", "diana_training.jsonl"))


def _pending_path() -> Path:
    return Path(_cfg.get("pending_file", "diana_training_pending.json"))


def _load_pending() -> None:
    global pending_reviews
    path = _pending_path()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pending_reviews = data.get("reviews", {})
    except Exception as e:
        log.error(f"Error cargando pending: {e}")


def _save_pending() -> None:
    path = _pending_path()
    path.write_text(
        json.dumps({"reviews": pending_reviews}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _init_counter() -> None:
    global _review_counter
    max_id = 0
    for rid in pending_reviews:
        if m := re.match(r"rev-(\d+)", rid):
            max_id = max(max_id, int(m.group(1)))
    if _training_path().exists():
        for line in _training_path().read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                if m := re.match(r"rev-(\d+)", entry.get("review_id", "")):
                    max_id = max(max_id, int(m.group(1)))
            except json.JSONDecodeError:
                continue
    _review_counter = max_id


def _next_review_id() -> str:
    global _review_counter
    _review_counter += 1
    return f"rev-{_review_counter:04d}"


def _append_training(entry: dict) -> None:
    path = _training_path()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _load_training_entries() -> list[dict]:
    path = _training_path()
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"\w{5,}", text.lower())
    return set(words)


def run_heuristics(
    user_message: str,
    bot_response: str,
    last_assistant: str | None = None,
) -> list[str]:
    flags: list[str] = []
    lower = bot_response.lower()

    if any(p in lower for p in EVASION_PHRASES):
        flags.append("evasión")

    if len(bot_response) < 30 and len(user_message) > 60:
        flags.append("respuesta_corta")

    user_words = _tokenize(user_message)
    if user_words and not user_words & _tokenize(bot_response):
        flags.append("desconectada")

    if last_assistant:
        a = bot_response.lower().strip()
        b = last_assistant.lower().strip()
        if a and b and (a == b or a in b or b in a):
            flags.append("repetición")

    return flags


async def judge_response(user_message: str, bot_response: str) -> dict:
    payload = {
        "model": _cfg["deepseek_model"],
        "messages": [
            {
                "role": "user",
                "content": JUDGE_PROMPT.format(
                    user_message=user_message,
                    bot_response=bot_response,
                ),
            }
        ],
        "max_tokens": 120,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {_cfg['deepseek_key']}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                _cfg["deepseek_url"],
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=12),
            ) as resp:
                if resp.status != 200:
                    log.warning(f"Judge API {resp.status}")
                    return {"score": 3, "generic": False, "reason": "juez no disponible"}
                data = await resp.json()
                raw = data["choices"][0]["message"]["content"].strip()
                result = json.loads(raw)
                result["score"] = max(1, min(5, int(result.get("score", 3))))
                result["generic"] = bool(result.get("generic", False))
                return result
    except Exception as e:
        log.warning(f"Judge error: {e}")
        return {"score": 3, "generic": False, "reason": "juez falló"}


def _should_notify(judge: dict) -> bool:
    if _cfg.get("review_all", True):
        return True
    return judge.get("score", 5) < 4 or judge.get("generic", False)


async def on_auto_reply_sent(
    bot,
    chat_id: int,
    vip_user_id: int,
    username: str,
    user_message: str,
    bot_response: str,
    last_assistant: str | None = None,
) -> None:
    if not _cfg.get("enabled", True):
        return

    review_id = _next_review_id()
    flags = run_heuristics(user_message, bot_response, last_assistant)
    judge = await judge_response(user_message, bot_response)

    review = {
        "id": review_id,
        "chat_id": chat_id,
        "vip_user_id": vip_user_id,
        "vip_username": username,
        "user_message": user_message,
        "bot_response": bot_response,
        "heuristic_flags": flags,
        "judge_score": judge.get("score", 3),
        "judge_generic": judge.get("generic", False),
        "judge_reason": judge.get("reason", ""),
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    pending_reviews[review_id] = review
    _save_pending()

    last_auto[chat_id] = {
        "response": bot_response,
        "user_message": user_message,
        "review_id": review_id,
        "timestamp": datetime.now(timezone.utc),
    }

    if _should_notify(judge):
        await notify_reviewer(bot, review)


async def notify_reviewer(bot, review: dict) -> None:
    reviewer_id = get_reviewer_id()
    if not reviewer_id:
        _notify_queue.append(review)
        log.warning("Reviewer ID no disponible — revisión encolada")
        return

    await _send_review_message(bot, reviewer_id, review)


async def flush_notify_queue(bot) -> None:
    global _notify_queue
    if not _notify_queue or not get_reviewer_id():
        return
    queued = _notify_queue[:]
    _notify_queue = []
    for review in queued:
        await _send_review_message(bot, get_reviewer_id(), review)


async def _send_review_message(bot, chat_id: int, review: dict) -> None:
    num = review["id"].replace("rev-", "")
    flags = ", ".join(review["heuristic_flags"]) or "ninguna"
    generic = "sí" if review["judge_generic"] else "no"

    text = (
        f"Revisión #{num} — {review['vip_username']}\n"
        f"{'─' * 25}\n"
        f"Él: {review['user_message'][:300]}\n\n"
        f"Diana (auto): {review['bot_response'][:300]}\n\n"
        f"Score: {review['judge_score']}/5 | genérica: {generic}\n"
        f"Flags: {flags}\n"
        f"{'─' * 25}"
    )
    if review.get("judge_reason"):
        text += f"\n{review['judge_reason'][:200]}"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Estuvo bien", callback_data=f"tr:ok:{num}"),
            InlineKeyboardButton("Mejorar", callback_data=f"tr:fix:{num}"),
            InlineKeyboardButton("Debió escalar", callback_data=f"tr:esc:{num}"),
        ]
    ])

    try:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
        log.info(f"Revisión {review['id']} enviada a {chat_id}")
    except Exception as e:
        log.error(f"Error enviando revisión: {e}")
        _notify_queue.append(review)


def _review_by_num(num: str) -> dict | None:
    try:
        return pending_reviews.get(f"rev-{int(num):04d}")
    except ValueError:
        return None


def _save_correction(
    review: dict,
    good_response: str,
    source: str,
) -> None:
    num = review["id"].replace("rev-", "")
    entry = {
        "id": f"t-{num}",
        "review_id": review["id"],
        "chat_id": review["chat_id"],
        "vip_username": review["vip_username"],
        "user_message": review["user_message"],
        "bad_response": review["bot_response"],
        "good_response": good_response,
        "source": source,
        "judge_score": review["judge_score"],
        "heuristic_flags": review["heuristic_flags"],
        "tags": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _append_training(entry)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    query = update.callback_query
    if not query or not query.data or not query.data.startswith("tr:"):
        return False

    reviewer_id = get_reviewer_id()
    if not reviewer_id or query.from_user.id != reviewer_id:
        await query.answer("No autorizado", show_alert=True)
        return True

    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer()
        return True

    action, num = parts[1], parts[2]
    review = _review_by_num(num)
    if not review:
        await query.answer("Revisión no encontrada", show_alert=True)
        return True

    if action == "ok":
        review["status"] = "validated"
        _save_pending()
        _append_training({
            "id": f"t-{num}",
            "review_id": review["id"],
            "chat_id": review["chat_id"],
            "vip_username": review["vip_username"],
            "user_message": review["user_message"],
            "bad_response": review["bot_response"],
            "good_response": review["bot_response"],
            "source": "validated",
            "judge_score": review["judge_score"],
            "heuristic_flags": review["heuristic_flags"],
            "tags": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        await query.answer("Marcado como correcto")
        await query.edit_message_reply_markup(reply_markup=None)

    elif action == "fix":
        review["status"] = "awaiting_correction"
        _save_pending()
        pending_correction[reviewer_id] = review["id"]
        await query.answer()
        await context.bot.send_message(
            chat_id=reviewer_id,
            text=f"Revisión #{num} — ¿qué habrías dicho?",
        )

    elif action == "esc":
        review["status"] = "escalated"
        _save_pending()
        log_escalation: Callable = _cfg["log_escalation"]
        log_escalation(
            review.get("vip_user_id", review["chat_id"]),
            review["vip_username"],
            f"Retroactivo post-auto-reply: {review['judge_reason']}",
            [
                {"role": "user", "content": review["user_message"]},
                {"role": "assistant", "content": review["bot_response"]},
            ],
        )
        await query.answer("Escalado")
        await query.edit_message_reply_markup(reply_markup=None)

    return True


async def handle_reviewer_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    msg = update.message
    if not msg or not msg.text:
        return False

    reviewer_id = get_reviewer_id()
    if not reviewer_id or msg.from_user.id != reviewer_id:
        return False

    review_id = pending_correction.get(reviewer_id)
    if not review_id:
        return False

    review = pending_reviews.get(review_id)
    if not review or review["status"] != "awaiting_correction":
        pending_correction.pop(reviewer_id, None)
        return False

    _save_correction(review, msg.text.strip(), "diana_feedback")
    review["status"] = "corrected"
    _save_pending()
    pending_correction.pop(reviewer_id, None)

    num = review_id.replace("rev-", "")
    await msg.reply_text(f"Corrección #{num} guardada.")
    log.info(f"Corrección guardada: {review_id}")
    return True


def on_implicit_correction(chat_id: int, manual_text: str) -> bool:
    if not _cfg.get("enabled", True):
        return False

    auto = last_auto.get(chat_id)
    if not auto:
        return False

    window = _cfg.get("implicit_correction_secs", 600)
    elapsed = (datetime.now(timezone.utc) - auto["timestamp"]).total_seconds()
    if elapsed > window:
        return False

    manual = manual_text.strip()
    if not manual or manual.lower() == auto["response"].lower().strip():
        return False

    review = pending_reviews.get(auto["review_id"])
    if not review:
        return False

    _save_correction(review, manual, "implicit_correction")
    review["status"] = "implicit_corrected"
    _save_pending()
    last_auto.pop(chat_id, None)
    log.info(f"Corrección implícita guardada: {auto['review_id']}")
    return True


async def send_stats(bot, chat_id: int) -> None:
    entries = _load_training_entries()
    validated = sum(1 for e in entries if e.get("source") == "validated")
    corrected = sum(1 for e in entries if e.get("source") == "diana_feedback")
    implicit = sum(1 for e in entries if e.get("source") == "implicit_correction")
    escalated = sum(1 for r in pending_reviews.values() if r.get("status") == "escalated")
    pending = sum(1 for r in pending_reviews.values() if r.get("status") == "pending")
    total_reviews = len(pending_reviews)

    text = (
        f"Entrenamiento\n"
        f"{'─' * 20}\n"
        f"Auto-replies revisados: {total_reviews}\n"
        f"Correcciones manuales: {corrected}\n"
        f"Correcciones implícitas: {implicit}\n"
        f"Validados: {validated}\n"
        f"Escalados: {escalated}\n"
        f"Pendientes: {pending}\n"
        f"Ejemplos en jsonl: {len(entries)}"
    )
    await bot.send_message(chat_id=chat_id, text=text)


def build_examples_block(user_message: str, max_examples: int = 3) -> str:
    entries = _load_training_entries()
    corrections = [
        e for e in entries
        if e.get("source") in ("diana_feedback", "implicit_correction")
        and e.get("good_response")
    ]
    if not corrections:
        return ""

    user_words = _tokenize(user_message)

    def score(entry: dict) -> int:
        overlap = len(user_words & _tokenize(entry.get("user_message", "")))
        return overlap

    ranked = sorted(corrections, key=score, reverse=True)[:max_examples]
    if not ranked or score(ranked[0]) == 0:
        ranked = corrections[-max_examples:]

    lines = ["\n\n## EJEMPLOS APRENDIDOS (úsalos como referencia de tono y contenido)"]
    for ex in ranked:
        lines.append(f"\nUsuario: {ex['user_message']}")
        lines.append(f"Diana: {ex['good_response']}")

    return "\n".join(lines)