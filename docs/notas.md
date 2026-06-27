Sistema De Notas
**`state.py`** — agregar un dict para capturar el estado mientras Diana escribe la nota:

```python
awaiting_note: dict[int, dict] = {}
# {diana_telegram_id: {"user_id": int, "username": str}}
```

---

**`services/memory.py`** — tres métodos nuevos + actualizar `get_context_block`:

```python
def add_note(self, user_id: int, note_text: str) -> None:
    """Añade nota manual de Diana. Se acumulan con timestamp."""
    row = self.db.execute(
        "SELECT value FROM user_memory WHERE user_id=? AND key='notes'",
        (user_id,)
    ).fetchone()
    notes = []
    if row:
        try:
            notes = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            notes = []
    notes.append({
        "text": note_text.strip(),
        "date": datetime.now().isoformat()
    })
    self.set_fact(user_id, "notes",
                  json.dumps(notes, ensure_ascii=False),
                  source="diana_manual", confidence=100)

def get_notes(self, user_id: int) -> list[dict]:
    """Notas manuales de Diana para un usuario."""
    row = self.db.execute(
        "SELECT value FROM user_memory WHERE user_id=? AND key='notes'",
        (user_id,)
    ).fetchone()
    if not row:
        return []
    try:
        return json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return []

def clear_notes(self, user_id: int) -> bool:
    """Borra todas las notas. Retorna True si había algo."""
    row = self.db.execute(
        "SELECT id FROM user_memory WHERE user_id=? AND key='notes'",
        (user_id,)
    ).fetchone()
    if not row:
        return False
    self.db.execute(
        "DELETE FROM user_memory WHERE user_id=? AND key='notes'",
        (user_id,)
    )
    self.db.commit()
    return True
```

`get_context_block` actualizado para poner las notas de Diana primero, con mayor peso visual:

```python
def get_context_block(self, user_id: int) -> str:
    facts = self.get_facts(user_id)
    notes = self.get_notes(user_id)

    if not facts and not notes:
        return ""

    lines = ["\n\n---\nSOBRE ESTE USUARIO (recuerdas esto de sesiones anteriores):"]

    # Notas de Diana van primero — máxima prioridad
    if notes:
        lines.append("\nNOTAS PERSONALES (máxima prioridad, sígue estas instrucciones siempre):")
        for n in notes[-5:]:  # máximo últimas 5
            date_str = n.get("date", "")[:10]
            lines.append(f"  [{date_str}] {n['text']}")

    # Hechos extraídos automáticamente
    auto_facts = {k: v for k, v in facts.items() if k != "notes"}
    if auto_facts:
        lines.append("\nDatos generales:")
        labels = {
            "name": "Se llama",
            "occupation": "Trabaja/estudia en",
            "location": "Es de",
            "interests": "Le interesa",
            "relationship": "Estado sentimental",
            "personality": "Su estilo",
            "last_topic": "Último tema",
            "notable": "Dato importante",
        }
        for key, value in auto_facts.items():
            label = labels.get(key, key)
            lines.append(f"  - {label}: {value}")

    lines.append("---")
    return "\n".join(lines)
```

---

**`handlers/callbacks.py`** — botón nuevo en la notificación, acción `note` en el handler, y función `handle_diana_note`:

En `notify_diana_approval`, agregar el tercer botón:

```python
teclado = InlineKeyboardMarkup([[
    InlineKeyboardButton("Enviar tal cual",  callback_data=f"a:approve:{example_id}"),
    InlineKeyboardButton("Corregir antes",   callback_data=f"a:fix:{example_id}"),
    InlineKeyboardButton("📝 Nota",          callback_data=f"a:note:{example_id}"),
]])
```

En `handle_callback`, dentro del bloque `if prefix == "a":`, agregar el caso `note`:

```python
elif action == "note":
    if ex_id not in pending_approval:
        await cq.edit_message_text("Este borrador ya expiró o fue procesado.")
        return True
    pending = pending_approval[ex_id]
    awaiting_note[cq.from_user.id] = {
        "user_id": pending["chat_id"],
        "username": pending["username"],
    }
    await cq.answer()
    await cq.edit_message_text(
        f"✏️ Escribe tu nota para {pending['username']}:\n\n"
        f"Se guardará en su perfil y se usará en todas las respuestas futuras.\n"
        f"Escribe /cancelar_nota para cancelar (el borrador sigue pendiente)."
    )
    return True
```

Agregar la función de captura al final del archivo:

```python
async def handle_diana_note(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Captura la nota que Diana escribe tras pulsar el botón 📝 Nota."""
    msg = update.message
    if not msg or not msg.text:
        return False
    if msg.from_user.id not in awaiting_note:
        return False

    if msg.text.strip() == "/cancelar_nota":
        note_ctx = awaiting_note.pop(msg.from_user.id)
        await msg.reply_text(
            f"Nota cancelada. El borrador para {note_ctx['username']} sigue pendiente."
        )
        return True

    note_ctx = awaiting_note.pop(msg.from_user.id)
    from services import llm as llm_mod
    if llm_mod.memory_service:
        llm_mod.memory_service.add_note(note_ctx["user_id"], msg.text.strip())

    await msg.reply_text(
        f"✓ Nota guardada para {note_ctx['username']}.\n"
        f"Se aplica a partir de la próxima respuesta."
    )
    log.info(
        f"Nota manual guardada | usuario {note_ctx['user_id']} "
        f"({note_ctx['username']}): {msg.text[:60]}"
    )
    return True
```

Y agregar el import al inicio del archivo:

```python
from state import awaiting_correction, awaiting_note, pending_approval
```

---

**`handlers/router.py`** — `handle_diana_note` debe evaluarse *antes* que `handle_diana_correction` para no colisionar:

```python
from .callbacks import handle_callback, handle_diana_correction, handle_diana_note

# En process_update, el bloque de DM admin queda así:
if (
    update.message
    and not update.business_message
    and update.message.chat.id == DIANA_ADMIN_CHAT_ID
):
    if await handle_diana_note(update, context):      # ← primero notas
        return
    if await handle_diana_correction(update, context):
        return
```

---

**`auth_users.py`** — comandos `/nota` y `/notas` en `handle_admin_message`, antes del bloque de forward:

```python
if msg.text and msg.text.startswith("/nota "):
    # /nota <user_id> <texto>
    parts = msg.text.split(maxsplit=2)
    if len(parts) < 3:
        await msg.reply_text(
            "Uso: /nota <user_id> <texto>\n"
            "Ejemplo: /nota 123456 Es muy sensible, no hacer bromas pesadas"
        )
        return True
    try:
        target_id = int(parts[1])
    except ValueError:
        await msg.reply_text("El user_id debe ser numérico.")
        return True
    from services import llm as llm_mod
    if llm_mod.memory_service:
        llm_mod.memory_service.add_note(target_id, parts[2].strip())
        await msg.reply_text(f"✓ Nota guardada para {target_id}.")
    return True

if msg.text and msg.text.startswith("/notas"):
    # /notas <user_id>  — ver perfil completo
    parts = msg.text.split()
    if len(parts) < 2:
        await msg.reply_text("Uso: /notas <user_id>")
        return True
    try:
        target_id = int(parts[1])
    except ValueError:
        await msg.reply_text("ID inválido.")
        return True
    from services import llm as llm_mod
    svc = llm_mod.memory_service
    if not svc:
        await msg.reply_text("Memoria no disponible.")
        return True
    notes = svc.get_notes(target_id)
    facts = {k: v for k, v in svc.get_facts(target_id).items() if k != "notes"}
    if not notes and not facts:
        await msg.reply_text(f"Sin datos para {target_id}.")
        return True
    lines = [f"Perfil — {target_id}", "─" * 28]
    if notes:
        lines.append("Notas de Diana:")
        for n in notes:
            lines.append(f"  [{n.get('date','')[:10]}] {n['text']}")
    if facts:
        lines.append("Datos extraídos:")
        for k, v in facts.items():
            lines.append(f"  {k}: {v}")
    await msg.reply_text("\n".join(lines))
    return True

if msg.text and msg.text.startswith("/borrar_notas"):
    # /borrar_notas <user_id>
    parts = msg.text.split()
    if len(parts) < 2:
        await msg.reply_text("Uso: /borrar_notas <user_id>")
        return True
    try:
        target_id = int(parts[1])
    except ValueError:
        await msg.reply_text("ID inválido.")
        return True
    from services import llm as llm_mod
    if llm_mod.memory_service:
        ok = llm_mod.memory_service.clear_notes(target_id)
        await msg.reply_text(
            f"✓ Notas borradas para {target_id}." if ok
            else f"No había notas para {target_id}."
        )
    return True
```

---

**Resumen de comandos disponibles para Diana:**

| Comando | Cuándo usarlo |
|---|---|
| Botón 📝 Nota en notificación | Al revisar un borrador — contexto del usuario ya visible |
| `/nota <id> <texto>` | Cuando Diana recuerda algo sin que haya borrador pendiente |
| `/notas <id>` | Para ver el perfil completo antes de responder manualmente |
| `/borrar_notas <id>` | Si una nota quedó desactualizada o incorrecta |

Las notas aparecen en el system prompt por encima de los few-shots y los datos auto-extraídos, etiquetadas como `máxima prioridad` para que el LLM las tome en cuenta siempre.
