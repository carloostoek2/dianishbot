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
pending_dispatch: dict[str, dict] = {}
pending_dispatch_by_chat: dict[int, str] = {}
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


def _should_notify(review: dict) -> bool:
    if _cfg.get("review_all", True):
        return True
    return review.get("judge_score", 5) < 4 or review.get("judge_generic", False)


async def _create_review(
    chat_id: int,
    vip_user_id: int,
    username: str,
    user_message: str,
    bot_response: str,
    last_assistant: str | None,
    *,
    awaiting_send: bool = False,
) -> dict:
    review_id = _next_review_id()
    flags = run_heuristics(user_message, bot_response, last_assistant)
    if awaiting_send:
        judge = {"score": 3, "generic": False, "reason": "revisión manual pre-envío"}
    else:
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
        "status": "awaiting_send" if awaiting_send else "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    pending_reviews[review_id] = review
    _save_pending()
    return review


def cancel_dispatch_for_chat(chat_id: int) -> str | None:
    review_id = pending_dispatch_by_chat.pop(chat_id, None)
    if not review_id:
        return None
    pending_dispatch.pop(review_id, None)
    review = pending_reviews.get(review_id)
    if review and review["status"] == "awaiting_send":
        review["status"] = "superseded"
        _save_pending()
    return review_id


async def notify_llm_failure(
    bot,
    *,
    chat_id: int,
    bc_id: str,
    username: str,
    gen: int,
    vip_user_id: int,
    user_message: str,
) -> None:
    """Avisa a Diana cuando el LLM no generó respuesta — puede escribir una manual."""
    reviewer_id = get_reviewer_id()
    if not reviewer_id:
        log.warning("LLM falló y reviewer ID no disponible")
        return

    review_id = _next_review_id()
    review = {
        "id": review_id,
        "chat_id": chat_id,
        "vip_user_id": vip_user_id,
        "vip_username": username,
        "user_message": user_message,
        "bot_response": "(sin respuesta del modelo)",
        "heuristic_flags": ["llm_failure"],
        "judge_score": 0,
        "judge_generic": True,
        "judge_reason": "El modelo no generó texto",
        "status": "awaiting_send",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    pending_reviews[review_id] = review
    _save_pending()

    pending_dispatch[review_id] = {
        "chat_id": chat_id,
        "bc_id": bc_id,
        "username": username,
        "gen": gen,
    }
    pending_dispatch_by_chat[chat_id] = review_id
    pending_correction[reviewer_id] = review_id
    review["status"] = "awaiting_correction"
    _save_pending()

    num = review_id.replace("rev-", "")
    text = (
        f"LLM sin respuesta — #{num} {username}\n"
        f"{'─' * 25}\n"
        f"Él: {user_message[:300]}\n"
        f"{'─' * 25}\n"
        f"Escribe la respuesta que quieres enviar:"
    )
    try:
        await bot.send_message(chat_id=reviewer_id, text=text)
        log.info(f"LLM failure notificado a Diana: {review_id}")
    except Exception as e:
        log.error(f"Error notificando LLM failure: {e}")


async def request_pre_approval(
    bot,
    *,
    chat_id: int,
    bc_id: str,
    username: str,
    gen: int,
    vip_user_id: int,
    user_message: str,
    bot_response: str,
    last_assistant: str | None = None,
) -> None:
    if not _cfg.get("enabled", True):
        deliver = _cfg.get("deliver_vip")
        if deliver:
            await deliver(
                bot, chat_id=chat_id, bc_id=bc_id, username=username,
                gen=gen, text=bot_response,
            )
        return

    cancel_dispatch_for_chat(chat_id)

    review = await _create_review(
        chat_id, vip_user_id, username, user_message, bot_response,
        last_assistant, awaiting_send=True,
    )
    review_id = review["id"]

    pending_dispatch[review_id] = {
        "chat_id": chat_id,
        "bc_id": bc_id,
        "username": username,
        "gen": gen,
    }
    pending_dispatch_by_chat[chat_id] = review_id

    await notify_reviewer(bot, review)


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

    review = await _create_review(
        chat_id, vip_user_id, username, user_message, bot_response, last_assistant,
    )

    last_auto[chat_id] = {
        "response": bot_response,
        "user_message": user_message,
        "review_id": review["id"],
        "timestamp": datetime.now(timezone.utc),
    }

    if _should_notify(review):
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


def _save_validated(review: dict) -> None:
    num = review["id"].replace("rev-", "")
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


async def _deliver_from_review(
    bot, review: dict, text: str, context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    dispatch = pending_dispatch.pop(review["id"], None)
    pending_dispatch_by_chat.pop(review["chat_id"], None)
    if not dispatch:
        return False
    deliver: Callable = _cfg["deliver_vip"]
    return await deliver(
        bot,
        chat_id=dispatch["chat_id"],
        bc_id=dispatch["bc_id"],
        username=dispatch["username"],
        gen=dispatch["gen"],
        text=text,
    )


async def _send_review_message(bot, chat_id: int, review: dict) -> None:
    num = review["id"].replace("rev-", "")
    flags = ", ".join(review["heuristic_flags"]) or "ninguna"
    generic = "sí" if review["judge_generic"] else "no"
    pre = _cfg.get("pre_approval", False)
    header = "Aprobación" if pre else "Revisión"

    text = (
        f"{header} #{num} — {review['vip_username']}\n"
        f"{'─' * 25}\n"
        f"Él: {review['user_message'][:300]}\n\n"
        f"{'Propuesta' if pre else 'Diana (auto)'}: {review['bot_response'][:300]}\n\n"
        f"Score: {review['judge_score']}/5 | genérica: {generic}\n"
        f"Flags: {flags}\n"
        f"{'─' * 25}"
    )
    if review.get("judge_reason"):
        text += f"\n{review['judge_reason'][:200]}"

    if pre:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Enviar", callback_data=f"tr:send:{num}"),
                InlineKeyboardButton("Modificar", callback_data=f"tr:fix:{num}"),
                InlineKeyboardButton("No enviar", callback_data=f"tr:esc:{num}"),
            ]
        ])
    else:
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

    pre = _cfg.get("pre_approval", False)

    if action in ("ok", "send"):
        review["status"] = "validated"
        _save_pending()
        _save_validated(review)
        if pre and action == "send":
            ok = await _deliver_from_review(
                context.bot, review, review["bot_response"], context,
            )
            await query.answer("Enviado" if ok else "No enviado — chat actualizado")
        else:
            await query.answer("Marcado como correcto")
        await query.edit_message_reply_markup(reply_markup=None)

    elif action == "fix":
        review["status"] = "awaiting_correction"
        _save_pending()
        pending_correction[reviewer_id] = review["id"]
        await query.answer()
        prompt = (
            f"Aprobación #{num} — escribe la versión que quieres enviar:"
            if pre else f"Revisión #{num} — ¿qué habrías dicho?"
        )
        await context.bot.send_message(chat_id=reviewer_id, text=prompt)

    elif action == "esc":
        review["status"] = "escalated"
        _save_pending()
        if pre:
            cancel_dispatch_for_chat(review["chat_id"])
        log_escalation: Callable = _cfg["log_escalation"]
        log_escalation(
            review.get("vip_user_id", review["chat_id"]),
            review["vip_username"],
            f"{'Pre-envío' if pre else 'Retroactivo'}: {review['judge_reason']}",
            [
                {"role": "user", "content": review["user_message"]},
                {"role": "assistant", "content": review["bot_response"]},
            ],
        )
        await query.answer("No enviado — escalado" if pre else "Escalado")
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

    corrected = msg.text.strip()
    _save_correction(review, corrected, "diana_feedback")
    review["status"] = "corrected"
    _save_pending()
    pending_correction.pop(reviewer_id, None)

    num = review_id.replace("rev-", "")
    if _cfg.get("pre_approval") and review_id in pending_dispatch:
        ok = await _deliver_from_review(context.bot, review, corrected, context)
        await msg.reply_text(
            f"Corrección #{num} enviada." if ok
            else f"Corrección #{num} guardada — no enviada (chat actualizado)."
        )
    else:
        await msg.reply_text(f"Corrección #{num} guardada.")
    log.info(f"Corrección guardada: {review_id}")
    return True


def on_diana_manual_reply(chat_id: int, manual_text: str) -> None:
    """Cancela aprobación pendiente o registra corrección implícita post-envío."""
    review_id = pending_dispatch_by_chat.get(chat_id)
    if review_id and _cfg.get("pre_approval"):
        review = pending_reviews.get(review_id)
        pending_dispatch.pop(review_id, None)
        pending_dispatch_by_chat.pop(chat_id, None)
        if review:
            manual = manual_text.strip()
            if manual.lower() != review["bot_response"].lower().strip():
                _save_correction(review, manual, "implicit_correction")
            review["status"] = "implicit_corrected"
            _save_pending()
            log.info(f"Aprobación cancelada — Diana respondió manual: {review_id}")
        return
    on_implicit_correction(chat_id, manual_text)


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
    awaiting = sum(1 for r in pending_reviews.values() if r.get("status") == "awaiting_send")
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
        f"Por aprobar: {awaiting}\n"
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