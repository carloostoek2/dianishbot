import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from config import DIANA_ADMIN_CHAT_ID
from state import awaiting_correction, awaiting_note, pending_approval
from services.delivery import deliver_vip_response
from services.training import update_rating
from services.memory import schedule_memory_extract
from services import llm as llm_mod
from services.llm import failure_label
from state import history
log = logging.getLogger("diana")


async def notify_diana_approval(
    bot, example_id: int, username: str, context: list,
    response: str, confidence: int, topic: str,
):
    """Envía el borrador a Diana ANTES de mandarlo al usuario."""
    if not DIANA_ADMIN_CHAT_ID:
        return
    preview = "\n".join([
        f"{'[Usuario]' if m['role'] == 'user' else '[Bot]'} {m['content'][:80]}"
        for m in context[-4:]
    ])
    texto = (
        f"Borrador listo para {username} (conf {confidence}% | tema: {topic})\n\n"
        f"Contexto:\n{preview}\n\n"
        f"Respuesta propuesta:\n{response}"
    )
    teclado = InlineKeyboardMarkup([[
        InlineKeyboardButton("Enviar tal cual",  callback_data=f"a:approve:{example_id}"),
        InlineKeyboardButton("Corregir antes",   callback_data=f"a:fix:{example_id}"),
        InlineKeyboardButton("📝 Nota",          callback_data=f"a:note:{example_id}"),
    ]])
    try:
        await bot.send_message(
            chat_id=DIANA_ADMIN_CHAT_ID,
            text=texto,
            reply_markup=teclado,
        )
        log.info(f"Borrador enviado a Diana: ejemplo {example_id} ({username})")
    except Exception as e:
        log.error(f"notify_diana_approval error: {e}")


async def notify_diana_escalation(
    bot,
    *,
    user_id: int,
    username: str,
    chat_id: int,
    reason: str,
    trigger_text: str,
    context: list[dict],
):
    """Alerta a Diana cuando un VIP necesita atención personal."""
    if not DIANA_ADMIN_CHAT_ID:
        return
    preview = "\n".join([
        f"{'[Usuario]' if m['role'] == 'user' else '[Bot]'} {m['content'][:120]}"
        for m in context[-6:]
    ])
    texto = (
        "⚠️ ESCALACIÓN — atención personal requerida\n\n"
        f"Usuario: {username}\n"
        f"ID: {user_id} | Chat: {chat_id}\n"
        f"Motivo: {reason}\n\n"
        f"Mensaje que disparó la alerta:\n{trigger_text[:300]}\n\n"
        f"Contexto reciente:\n{preview}\n\n"
        "El bot no respondió. Responde tú desde Business."
    )
    try:
        await bot.send_message(
            chat_id=DIANA_ADMIN_CHAT_ID,
            text=texto,
        )
        log.info(f"Escalación notificada a Diana: {username} ({user_id}) — {reason}")
    except Exception as e:
        log.error(f"notify_diana_escalation error: {e}")


async def notify_diana_llm_failure(
    bot, *, username: str, chat_id: int, context: list, failure,
):
    """Avisa a Diana cuando el LLM no pudo generar respuesta."""
    if not DIANA_ADMIN_CHAT_ID:
        return
    preview = "\n".join([
        f"{'[Usuario]' if m['role'] == 'user' else '[Bot]'} {m['content'][:80]}"
        for m in context[-4:]
    ])
    texto = (
        f"⚠️ El bot NO pudo responder a {username}\n"
        f"Causa: {failure_label(failure.reason)}\n"
        f"Intentos: {failure.attempts}\n"
    )
    if failure.detail:
        texto += f"Detalle: {failure.detail[:200]}\n"
    texto += f"\nContexto:\n{preview}\n\n"
    texto += "Puedes responder manualmente en el chat del usuario."
    try:
        await bot.send_message(chat_id=DIANA_ADMIN_CHAT_ID, text=texto)
        log.info(
            f"Diana notificada de fallo LLM: {username} ({chat_id}) — "
            f"{failure_label(failure.reason)}"
        )
    except Exception as e:
        log.error(f"notify_diana_llm_failure error: {e}")


async def notify_diana(
    bot, example_id: int, username: str, context: list,
    response: str, confidence: int, topic: str,
):
    """Envía a Diana la notificación con los botones de calificación."""
    if not DIANA_ADMIN_CHAT_ID:
        return
    preview = "\n".join([
        f"{'[Usuario]' if m['role'] == 'user' else '[Bot]'} {m['content'][:80]}"
        for m in context[-4:]
    ])
    texto = (
        f"Respuesta con confianza baja ({confidence}%)\n"
        f"Usuario: {username} | Tema: {topic}\n\n"
        f"Contexto:\n{preview}\n\n"
        f"Lo que respondio el bot:\n{response[:250]}"
    )
    teclado = InlineKeyboardMarkup([[
        InlineKeyboardButton("Perfecta", callback_data=f"t:good:{example_id}"),
        InlineKeyboardButton("Corregir", callback_data=f"t:fix:{example_id}"),
        InlineKeyboardButton("Mala", callback_data=f"t:bad:{example_id}"),
    ]])
    try:
        await bot.send_message(
            chat_id=DIANA_ADMIN_CHAT_ID,
            text=texto,
            reply_markup=teclado,
        )
        log.info(f"Diana notificada: ejemplo {example_id} (conf={confidence}%)")
    except Exception as e:
        log.error(f"notify_diana error: {e}")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Maneja callbacks de aprobación (a:) y retroalimentación post-envío (t:)."""
    cq = update.callback_query
    if not cq or not cq.data:
        return False

    parts = cq.data.split(":")
    if len(parts) != 3:
        return False

    prefix, action = parts[0], parts[1]
    try:
        ex_id = int(parts[2])
    except ValueError:
        return False
    if prefix not in ("a", "t"):
        return False

    if prefix == "a" and action == "approve":
        await cq.answer("Enviando...")
    else:
        await cq.answer()

    # ══ MODO APROBACIÓN (a:) ═══════════════════════════════════════
    if prefix == "a":
        if action == "approve":
            awaiting_note.pop(cq.from_user.id, None)
            if ex_id not in pending_approval:
                await cq.edit_message_text("Este borrador ya expiró o fue procesado.")
                return True
            pending = pending_approval[ex_id]
            await cq.edit_message_text(
                f"Enviando a {pending['username']}...",
                reply_markup=None,
            )
            pending = pending_approval.pop(ex_id)
            ok = await deliver_vip_response(
                context.bot,
                chat_id=pending["chat_id"],
                bc_id=pending["bc_id"],
                username=pending["username"],
                gen=pending["gen"],
                text=pending["response"],
            )
            if ok:
                update_rating(ex_id, "good")
                schedule_memory_extract(
                    llm_mod.memory_service,
                    pending["chat_id"],
                    history.get(pending["chat_id"], []),
                    llm_mod.raw_call,
                )
                await cq.edit_message_text(f"Enviado a {pending['username']}.")
                log.info(f"Aprobado y enviado: ejemplo {ex_id} → {pending['username']}")
            else:
                await cq.edit_message_text(
                    f"No enviado a {pending['username']}: el chat tiene un mensaje más reciente."
                )
                log.warning(f"Aprobación {ex_id} obsoleta — gen desactualizado")

        elif action == "note":
            if ex_id not in pending_approval:
                await cq.edit_message_text("Este borrador ya expiró o fue procesado.")
                return True
            pending = pending_approval[ex_id]
            awaiting_correction.pop(cq.from_user.id, None)
            awaiting_note[cq.from_user.id] = {
                "user_id": pending["chat_id"],
                "username": pending["username"],
            }
            await cq.edit_message_text(
                f"✏️ Escribe tu nota para {pending['username']}:\n\n"
                f"Se guardará en su perfil y se usará en todas las respuestas futuras.\n"
                f"Escribe /cancelar_nota para cancelar (el borrador sigue pendiente)."
            )

        elif action == "fix":
            if ex_id not in pending_approval:
                await cq.edit_message_text("Este borrador ya expiró o fue procesado.")
                return True
            pending = pending_approval[ex_id]
            awaiting_note.pop(cq.from_user.id, None)
            awaiting_correction[cq.from_user.id] = ex_id
            await cq.edit_message_text(
                f"Escribe la respuesta corregida para {pending['username']}:\n\n"
                f"Borrador actual:\n{pending['response'][:200]}"
            )

    # ══ MODO AUTÓNOMO — retroalimentación post-envío (t:) ══════════
    elif prefix == "t":
        if action == "good":
            awaiting_note.pop(cq.from_user.id, None)
            update_rating(ex_id, "good")
            await cq.edit_message_text(f"Guardado como ejemplo positivo (ID {ex_id}).")
            log.info(f"Ejemplo {ex_id} → good")
        elif action == "bad":
            awaiting_note.pop(cq.from_user.id, None)
            update_rating(ex_id, "bad")
            await cq.edit_message_text(f"Marcado como mala respuesta (ID {ex_id}).")
            log.info(f"Ejemplo {ex_id} → bad")
        elif action == "fix":
            awaiting_note.pop(cq.from_user.id, None)
            awaiting_correction[cq.from_user.id] = ex_id
            await cq.edit_message_text(
                f"Esperando tu corrección para el ejemplo {ex_id}.\n\n"
                "Escribe la respuesta ideal:"
            )

    return True


async def handle_diana_correction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Captura correcciones de Diana — envía al usuario (aprobación) o solo guarda (autónomo)."""
    msg = update.message
    if not msg or not msg.text:
        return False
    if msg.from_user.id not in awaiting_correction:
        return False

    stripped = msg.text.strip()
    if stripped.startswith("/"):
        return False

    ex_id = awaiting_correction.pop(msg.from_user.id)
    correction = stripped
    update_rating(ex_id, "corrected", correction)

    if ex_id in pending_approval:
        pending = pending_approval.pop(ex_id)
        ok = await deliver_vip_response(
            context.bot,
            chat_id=pending["chat_id"],
            bc_id=pending["bc_id"],
            username=pending["username"],
            gen=pending["gen"],
            text=correction,
        )
        if ok:
            schedule_memory_extract(
                llm_mod.memory_service,
                pending["chat_id"],
                history.get(pending["chat_id"], []),
                llm_mod.raw_call,
            )
            await msg.reply_text(
                f"Correccion enviada a {pending['username']} y guardada como ejemplo de entrenamiento."
            )
            log.info(f"Corrección enviada (aprobación): ejemplo {ex_id} → {pending['username']}")
        else:
            await msg.reply_text(
                f"Corrección guardada pero no enviada a {pending['username']}: "
                "el chat tiene un mensaje más reciente."
            )
            log.warning(f"Corrección {ex_id} obsoleta — gen desactualizado")
    else:
        await msg.reply_text(
            f"Corrección guardada (ejemplo {ex_id}). Se usará en respuestas futuras."
        )
        log.info(f"Corrección guardada (autónomo): ejemplo {ex_id} → '{correction[:60]}'")

    return True


async def handle_diana_note(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Captura la nota que Diana escribe tras pulsar el botón 📝 Nota."""
    msg = update.message
    if not msg or not msg.text:
        return False
    if msg.from_user.id not in awaiting_note:
        return False

    stripped = msg.text.strip()
    if stripped.startswith("/"):
        base_cmd = stripped.split()[0].split("@")[0]
        if base_cmd == "/cancelar_nota":
            note_ctx = awaiting_note.pop(msg.from_user.id)
            await msg.reply_text(
                f"Nota cancelada. El borrador para {note_ctx['username']} "
                "sigue pendiente."
            )
            return True
        return False

    note_ctx = awaiting_note[msg.from_user.id]
    if not llm_mod.memory_service:
        await msg.reply_text("Memoria no disponible.")
        return True

    try:
        saved = llm_mod.memory_service.add_note(
            note_ctx["user_id"], stripped,
        )
    except Exception as e:
        log.error(
            f"Error guardando nota manual | usuario {note_ctx['user_id']}: {e}"
        )
        await msg.reply_text(
            "Error al guardar la nota. Intenta de nuevo o /cancelar_nota."
        )
        return True

    if not saved:
        await msg.reply_text(
            "La nota está vacía o no es válida. Escribe de nuevo o /cancelar_nota."
        )
        return True

    awaiting_note.pop(msg.from_user.id)
    await msg.reply_text(
        f"✓ Nota guardada para {note_ctx['username']}.\n"
        f"Se aplica a partir de la próxima respuesta."
    )
    log.info(
        f"Nota manual guardada | usuario {note_ctx['user_id']} "
        f"({note_ctx['username']}): {stripped[:60]}"
    )
    return True
