"""Gray-zone guidance consult callbacks (g: prefix)."""

from __future__ import annotations

import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import DIANA_ADMIN_CHAT_ID
from state import (
    awaiting_correction,
    awaiting_guidance_answer,
    awaiting_note,
    history,
    pending_guidance,
    reply_gen,
    _save_runtime_state,
)
from services import knowledge, sandbox
from services.delivery import deliver_vip_response
from services.training import save_example

from .shared import _clear_awaiting_note_with_prompt_restore
from .approval import notify_diana_approval

log = logging.getLogger("diana")

EXPIRED_GUIDANCE_TEXT = "Esta consulta ya expiró o fue procesada."


def _format_guidance_text(
    *,
    guidance_id: int,
    pending: dict,
    context: list[dict],
) -> str:
    preview = "\n".join([
        f"{'[Usuario]' if m['role'] == 'user' else '[Bot]'} {m['content'][:120]}"
        for m in context[-6:]
    ])
    draft = pending.get("draft_response") or ""
    if len(draft) > 800:
        draft = draft[:800] + "…"
    header = ""
    if sandbox.is_active(pending["chat_id"]):
        prof = sandbox.get_profile(pending["chat_id"]) or "?"
        header = f"🧪 SANDBOX — perfil: {prof}\n\n"
    return header + (
        f"🧭 Necesito tu criterio (zona gris) #{guidance_id}\n\n"
        f"VIP: @{pending.get('username', '?')} ({pending['chat_id']})\n"
        f"Tema: {pending.get('topic') or '—'}\n\n"
        f"Pregunta:\n{pending.get('gap_question') or '—'}\n\n"
        f"Contexto (últimos mensajes):\n{preview or '—'}\n\n"
        f"Borrador tentativo (no enviado):\n\"{draft}\""
    )


def _build_guidance_keyboard(guidance_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Responder", callback_data=f"g:answer:{guidance_id}"),
        InlineKeyboardButton("Usar borrador", callback_data=f"g:use_draft:{guidance_id}"),
        InlineKeyboardButton("Yo me encargo", callback_data=f"g:skip:{guidance_id}"),
    ]])


async def notify_diana_guidance(
    bot,
    *,
    guidance_id: int,
    pending: dict,
    context: list[dict] | None = None,
) -> None:
    """DM Diana with gray-zone consult UI (no VIP I/O)."""
    if not DIANA_ADMIN_CHAT_ID:
        return
    ctx = context if context is not None else history.get(pending["chat_id"], [])
    texto = _format_guidance_text(
        guidance_id=guidance_id, pending=pending, context=ctx,
    )
    teclado = _build_guidance_keyboard(guidance_id)
    try:
        msg = await bot.send_message(
            chat_id=DIANA_ADMIN_CHAT_ID,
            text=texto,
            reply_markup=teclado,
        )
        if msg is not None and getattr(msg, "message_id", None) is not None:
            pending["notify_message_id"] = msg.message_id
            _save_runtime_state()
        log.info(
            f"Guidance notificada a Diana: #{guidance_id} "
            f"{pending.get('username')} ({pending['chat_id']})"
        )
    except Exception as e:
        log.error(f"notify_diana_guidance error: {e}")


def clear_awaiting_guidance_answer(admin_id: int) -> None:
    awaiting_guidance_answer.pop(admin_id, None)


async def _close_pending(
    guidance_id: int,
    *,
    status: str,
    diana_answer_raw: str | None = None,
) -> dict | None:
    """Pop runtime pending and resolve DB row. Returns pending dict or None."""
    pending = pending_guidance.pop(guidance_id, None)
    for admin_id, gid in list(awaiting_guidance_answer.items()):
        if gid == guidance_id:
            awaiting_guidance_answer.pop(admin_id, None)
    if pending is not None:
        _save_runtime_state()
    chat_id = pending["chat_id"] if pending else 0
    if pending is None or sandbox.should_persist(chat_id):
        try:
            knowledge.resolve_guidance_request(
                guidance_id,
                status=status,
                diana_answer_raw=diana_answer_raw,
            )
        except Exception as e:
            log.debug(f"resolve_guidance_request({guidance_id}): {e}")
    return pending


async def enter_normal_draft_path(
    bot,
    *,
    chat_id: int,
    bc_id: str,
    username: str,
    gen: int,
    response: str,
    confidence: int,
    topic: str,
) -> int | None:
    """Shared save → approve | deliver path used by timer, use_draft, answer (WU2).

    Returns example_id or None on failure/stale.
    """
    from handlers.timer import enter_draft_pipeline

    return await enter_draft_pipeline(
        bot,
        chat_id=chat_id,
        bc_id=bc_id,
        username=username,
        gen=gen,
        response=response,
        confidence=confidence,
        topic=topic,
    )


async def handle_guidance_action(
    cq, context: ContextTypes.DEFAULT_TYPE, action: str, guidance_id: int,
) -> None:
    """Handle g:answer / g:use_draft / g:skip."""
    if guidance_id not in pending_guidance:
        await cq.answer()
        await cq.edit_message_text(EXPIRED_GUIDANCE_TEXT)
        return

    pending = pending_guidance[guidance_id]

    if action == "answer":
        await _clear_awaiting_note_with_prompt_restore(context.bot, cq.from_user.id)
        awaiting_correction.pop(cq.from_user.id, None)
        awaiting_guidance_answer[cq.from_user.id] = guidance_id
        await cq.answer()
        await cq.edit_message_text(
            f"✏️ Escribe tu criterio para la zona gris "
            f"(VIP @{pending.get('username', '?')}):\n\n"
            f"Pregunta: {pending.get('gap_question') or '—'}\n\n"
            f"Tu respuesta se guardará como doctrina (política de tema) "
            f"en el siguiente paso. Por ahora se usará el borrador tentativo "
            f"para el VIP."
        )
        return

    if action == "skip":
        await _clear_awaiting_note_with_prompt_restore(context.bot, cq.from_user.id)
        clear_awaiting_guidance_answer(cq.from_user.id)
        await _close_pending(guidance_id, status="skipped")
        await cq.answer("Consulta cerrada — te encargas vos")
        await cq.edit_message_text(
            f"Consulta #{guidance_id} cerrada. "
            f"Diana se encarga del VIP @{pending.get('username', '?')} manualmente. "
            f"No se envió nada."
        )
        log.info(f"Guidance {guidance_id} → skipped (manual)")
        return

    if action == "use_draft":
        await _clear_awaiting_note_with_prompt_restore(context.bot, cq.from_user.id)
        clear_awaiting_guidance_answer(cq.from_user.id)
        chat_id = pending["chat_id"]
        if reply_gen.get(chat_id) != pending.get("gen"):
            await _close_pending(guidance_id, status="skipped")
            await cq.answer()
            await cq.edit_message_text(
                f"Consulta #{guidance_id} cerrada: el VIP escribió de nuevo "
                f"(borrador obsoleto). No se envió nada."
            )
            return
        draft = pending.get("draft_response") or ""
        conf = int(pending.get("confidence") or 0)
        topic = pending.get("topic") or "general"
        await _close_pending(guidance_id, status="skipped")
        await cq.answer("Abriendo borrador…")
        ex_id = await enter_normal_draft_path(
            context.bot,
            chat_id=chat_id,
            bc_id=pending.get("bc_id") or "",
            username=pending.get("username") or "",
            gen=pending["gen"],
            response=draft,
            confidence=conf,
            topic=topic,
        )
        if ex_id is None:
            await cq.edit_message_text(
                f"No se pudo abrir el borrador de la consulta #{guidance_id}."
            )
        else:
            await cq.edit_message_text(
                f"Consulta #{guidance_id}: se usó el borrador tentativo. "
                f"Revisá el flujo normal de aprobación/envío."
            )
        log.info(f"Guidance {guidance_id} → use_draft (example={ex_id})")
        return

    await cq.answer()


async def handle_diana_guidance_answer(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """Capture free-text answer after g:answer. WU2: store raw + use_draft path.

    Full distill+regen is WU3. Here we persist diana_answer_raw, mark answered,
    then re-enter the normal draft pipeline with the stored tentative draft so
    the VIP is not left frozen forever.
    """
    msg = update.message
    if not msg or not msg.text:
        return False
    admin_id = msg.from_user.id
    if admin_id not in awaiting_guidance_answer:
        return False

    stripped = msg.text.strip()
    if stripped.startswith("/"):
        return False

    guidance_id = awaiting_guidance_answer.pop(admin_id)
    pending = pending_guidance.get(guidance_id)
    if pending is None:
        await msg.reply_text(EXPIRED_GUIDANCE_TEXT)
        return True

    chat_id = pending["chat_id"]
    draft = pending.get("draft_response") or ""
    conf = int(pending.get("confidence") or 0)
    topic = pending.get("topic") or "general"
    gen = pending.get("gen", 0)

    if reply_gen.get(chat_id) != gen:
        await _close_pending(
            guidance_id, status="answered", diana_answer_raw=stripped,
        )
        await msg.reply_text(
            "Guardé tu criterio, pero el VIP ya escribió de nuevo — "
            "no se envía el borrador viejo. La política completa se aplicará "
            "en el siguiente turno (WU3 distill)."
        )
        return True

    await _close_pending(
        guidance_id, status="answered", diana_answer_raw=stripped,
    )
    ex_id = await enter_normal_draft_path(
        context.bot,
        chat_id=chat_id,
        bc_id=pending.get("bc_id") or "",
        username=pending.get("username") or "",
        gen=gen,
        response=draft,
        confidence=conf,
        topic=topic,
    )
    if ex_id is None:
        await msg.reply_text(
            "Criterio guardado, pero no se pudo abrir el borrador para el VIP."
        )
    else:
        await msg.reply_text(
            f"Criterio guardado (consulta #{guidance_id}). "
            f"Se abrió el borrador tentativo por el camino normal "
            f"(distill+regen llega en WU3)."
        )
    log.info(
        f"Guidance {guidance_id} answered (raw stored); draft path example={ex_id}"
    )
    return True


def open_guidance_consult(
    *,
    chat_id: int,
    bc_id: str,
    username: str,
    gen: int,
    topic: str,
    gap_question: str,
    draft_response: str,
    confidence: int,
    context: list | None = None,
) -> int:
    """Create DB request + runtime pending_guidance entry. Returns guidance id."""
    gid = knowledge.create_guidance_request(
        chat_id=chat_id,
        username=username,
        topic=topic,
        gap_question=gap_question,
        context=context,
        draft_response=draft_response,
    )
    pending_guidance[gid] = {
        "chat_id": chat_id,
        "bc_id": bc_id,
        "username": username,
        "gen": gen,
        "topic": topic,
        "gap_question": gap_question,
        "draft_response": draft_response,
        "confidence": confidence,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save_runtime_state()
    return gid


async def supersede_guidance_for_chat(chat_id: int) -> int:
    """Owner inbound: mark all open guidances for chat as superseded. Returns count."""
    closed = 0
    for gid, pending in list(pending_guidance.items()):
        if pending.get("chat_id") != chat_id:
            continue
        await _close_pending(gid, status="superseded")
        closed += 1
        log.info(f"Guidance {gid} superseded (owner inbound chat {chat_id})")
    return closed
