import asyncio
import random
import logging
from config import (
    APPROVAL_MODE, SILENCE_MINUTES, RESPONSE_DELAY_MIN, RESPONSE_DELAY_MAX,
    CONFIDENCE_THRESHOLD, is_llm_escalation_topic,
)
from state import (
    history, reply_gen, timers, pending_approval, chat_meta,
    _clear_timer_schedule, _save_runtime_state,
)
from services.llm import FAIL_ABORTED, get_diana_response, raw_call
from services.training import save_example, save_llm_failure
from services.delivery import deliver_vip_response
from services.memory import schedule_memory_extract
from .callbacks import notify_diana_approval, notify_diana, notify_diana_llm_failure
# wired at runtime from diana main (preserves memory extract task from item2)
memory_service = None
log = logging.getLogger("diana")


def compute_reply_delay() -> float:
    if APPROVAL_MODE:
        return SILENCE_MINUTES * 60
    return random.uniform(RESPONSE_DELAY_MIN * 60, RESPONSE_DELAY_MAX * 60)


def _finish_timer(chat_id: int) -> None:
    if timers.get(chat_id) is asyncio.current_task():
        timers.pop(chat_id, None)
    _clear_timer_schedule(chat_id)
    _save_runtime_state()


async def auto_reply(
    bot, chat_id: int, username: str, bc_id: str, gen: int,
    *, delay_sec: float | None = None,
):
    if delay_sec is None:
        delay_sec = compute_reply_delay()
    log.info(f"⏳ {username}: respuesta programada en {delay_sec / 60:.1f} min")

    try:
        await asyncio.sleep(delay_sec)
    except asyncio.CancelledError:
        return

    if reply_gen.get(chat_id) != gen:
        return

    log.info(f"Cobertura activada para {username} ({chat_id})")

    response, confidence, topic, failure = await get_diana_response(
        chat_id,
        should_abort=lambda: reply_gen.get(chat_id) != gen,
    )
    if not response:
        if failure and failure.reason != FAIL_ABORTED:
            from services import sandbox
            if sandbox.should_persist(chat_id):
                save_llm_failure(
                    chat_id, username, history.get(chat_id, []), failure, topic,
                )
            await notify_diana_llm_failure(
                bot, username=username, chat_id=chat_id,
                context=history.get(chat_id, []), failure=failure,
            )
        _finish_timer(chat_id)
        return

    if reply_gen.get(chat_id) != gen:
        _finish_timer(chat_id)
        return

    if is_llm_escalation_topic(topic):
        from .business import escalate_to_diana

        msgs = history.get(chat_id, [])
        trigger = next(
            (m["content"] for m in reversed(msgs) if m["role"] == "user"), "",
        )
        user_id = chat_meta.get(chat_id, {}).get("vip_id", chat_id)
        reason = f"Tema LLM: '{topic}'"
        await escalate_to_diana(
            bot,
            user_id=user_id,
            username=username,
            chat_id=chat_id,
            reason=reason,
            trigger_text=trigger,
            context=msgs,
        )
        _finish_timer(chat_id)
        return

    from services import sandbox
    if sandbox.is_active(chat_id):
        example_id = sandbox.allocate_draft_id()
    else:
        example_id = save_example(
            chat_id, username, history.get(chat_id, []),
            response, confidence, topic,
        )
    log.info(
        f"Ejemplo {example_id} | conf={confidence}% | topic={topic} | "
        f"modo={'supervisado' if APPROVAL_MODE else 'autónomo'}"
    )

    if APPROVAL_MODE:
        pending_approval[example_id] = {
            "chat_id": chat_id,
            "bc_id": bc_id,
            "username": username,
            "gen": gen,
            "variants": [
                {"response": response, "confidence": confidence, "topic": topic},
            ],
            "selected": 0,
            "regenerating": False,
        }
        _clear_timer_schedule(chat_id)
        _save_runtime_state()
        await notify_diana_approval(
            bot, example_id, username, history.get(chat_id, []),
            response, confidence, topic,
            chat_id=chat_id, gen=gen,
        )
    else:
        if confidence < CONFIDENCE_THRESHOLD:
            asyncio.create_task(
                notify_diana(
                    bot, example_id, username, history.get(chat_id, []),
                    response, confidence, topic,
                ),
            )
        try:
            ok = await deliver_vip_response(
                bot, chat_id=chat_id, bc_id=bc_id,
                username=username, gen=gen, text=response,
            )
            if ok and sandbox.should_persist(chat_id):
                schedule_memory_extract(
                    memory_service, chat_id, history.get(chat_id, []), raw_call,
                )
        except Exception as e:
            log.error(f"Error enviando a {chat_id}: {e}")
        _finish_timer(chat_id)
        return

    _finish_timer(chat_id)
