from __future__ import annotations

import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import MessageEntityType, ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from config import Settings
from hindsight_service import HindsightProjectMemory
from role_guidance_service import RoleGuidanceEngine
from storage import Storage
from transcription import VoiceTranscriber


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

settings = Settings.from_env()
storage = Storage(db_path=os.path.join(os.path.dirname(__file__), "..", "data", "project_manager.db"))
memory = HindsightProjectMemory(
    base_url=settings.hindsight_base_url,
    api_key=settings.hindsight_api_key,
    bank_prefix=settings.hindsight_bank_prefix,
)

if settings.openai_api_key:
    transcriber = VoiceTranscriber(
        api_key=settings.openai_api_key,
        model=settings.openai_transcribe_model,
    )
elif settings.groq_api_key:
    # Groq uses OpenAI-compatible API with different whisper model names.
    groq_model = settings.openai_transcribe_model
    if groq_model == "whisper-1":
        groq_model = "whisper-large-v3-turbo"
    transcriber = VoiceTranscriber(
        api_key=settings.groq_api_key,
        model=groq_model,
        base_url="https://api.groq.com/openai/v1",
    )
else:
    transcriber = None
guidance_engine = (
    RoleGuidanceEngine(api_key=settings.groq_api_key, model=settings.groq_model)
    if settings.groq_api_key
    else None
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def chat_bank_id(update: Update) -> str:
    return memory.bank_id(str(update.effective_chat.id))


def build_welcome_text() -> str:
    voice_status = "enabled" if transcriber is not None else "disabled (set OPENAI_API_KEY or GROQ_API_KEY)"
    return "\n".join(
        [
            "<b>AI Group Project Manager</b>",
            "Team memory and delivery support for student projects.",
            "",
            "<b>Core Commands</b>",
            "<code>/setrole &lt;role&gt;</code> - reply to teammate to assign a role",
            "<code>/roles</code> - list current team roles",
            "<code>/task &lt;due YYYY-MM-DD optional&gt; | &lt;title&gt;</code> - create a task (reply to assign)",
            "<code>/tasks</code> - list open tasks",
            "<code>/done &lt;task_id&gt;</code> - mark a task completed",
            "<code>/decision &lt;text&gt;</code> - store a project decision",
            "<code>/guide</code> - personalized next steps by role",
            "",
            "<b>Meeting Commands</b>",
            "<code>/meeting_start</code> - begin transcript capture",
            "<code>/summary</code> - generate in-progress summary",
            "<code>/meeting_end</code> - generate final summary and close session",
            "<code>/recommend</code> - suggest task ownership from memory",
            "",
            "<b>Status</b>",
            f"Voice transcription: <b>{voice_status}</b>",
            f"Role guidance LLM: <b>{'enabled' if guidance_engine is not None else 'disabled (set GROQ_API_KEY)'}</b>",
            "Type <code>/help</code> any time to show this panel again.",
        ]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await memory.ensure_group_bank(chat_bank_id(update))
    await update.message.reply_text(
        text=build_welcome_text(),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def set_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    requester = update.effective_user

    if not context.args:
        await update.message.reply_text(
            "Usage: /setrole <role> (self), reply with /setrole <role>, or /setrole @username <role>"
        )
        return

    target = None
    role = ""

    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        role = " ".join(context.args).strip()
    else:
        entities = update.message.entities or []
        for entity in entities:
            if entity.type == MessageEntityType.TEXT_MENTION and getattr(entity, "user", None) is not None:
                target = entity.user
                mention_text = update.message.parse_entity(entity).strip()
                full_text = update.message.text or ""
                cmd_and_rest = full_text.split(maxsplit=1)
                rest = cmd_and_rest[1] if len(cmd_and_rest) > 1 else ""
                role = rest.replace(mention_text, "", 1).strip()
                break

        if target is None and context.args and context.args[0].startswith("@"):
            mention_username = context.args[0][1:].strip().lower()
            role = " ".join(context.args[1:]).strip()
            chat_id_lookup = str(update.effective_chat.id)
            known_roles = list(storage.list_roles(chat_id_lookup))
            for row in known_roles:
                row_username = (row["username"] or "").strip().lower()
                if row_username == mention_username:
                    class ResolvedUser:
                        def __init__(self, uid: str, uname: str) -> None:
                            self.id = int(uid)
                            self.username = uname
                            self.full_name = uname or uid

                    target = ResolvedUser(uid=str(row["user_id"]), uname=row["username"] or mention_username)
                    break

        # /setrole <role> => self assignment
        if target is None and not (context.args and context.args[0].startswith("@")):
            target = requester
            role = " ".join(context.args).strip()

    if target is None:
        await update.message.reply_text(
            "Could not resolve the teammate. Use reply mode, mention from member picker, "
            "or run /setrole <role> to set your own role."
        )
        return

    if not role:
        await update.message.reply_text(
            "Usage: /setrole <role> (self/reply) or /setrole @username <role>"
        )
        return

    chat_id = str(update.effective_chat.id)
    bank_id = chat_bank_id(update)
    await memory.ensure_group_bank(bank_id)

    storage.upsert_role(
        chat_id=chat_id,
        user_id=str(target.id),
        username=target.username,
        role=role,
        updated_at=utc_now_iso(),
    )

    display_name = target.username or target.full_name
    await memory.retain_event(
        bank_id=bank_id,
        content=f"{display_name} has role: {role}",
        context="Team role update",
        tags=[f"team:{chat_id}", f"user:{target.id}", "topic:roles"],
        metadata={"source": "telegram"},
    )

    await update.message.reply_text(f"Role saved: {display_name} -> {role}")


async def roles(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    rows = list(storage.list_roles(chat_id))
    if not rows:
        await update.message.reply_text("No roles stored yet.")
        return

    lines = ["Team roles:"]
    for row in rows:
        name = row["username"] or row["user_id"]
        lines.append(f"- {name}: {row['role']}")
    await update.message.reply_text("\n".join(lines))


async def decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Usage: /decision <decision text>")
        return

    chat_id = str(update.effective_chat.id)
    bank_id = chat_bank_id(update)
    await memory.ensure_group_bank(bank_id)

    await memory.retain_event(
        bank_id=bank_id,
        content=f"Project decision: {text}",
        context="Project decision",
        tags=[f"team:{chat_id}", "topic:decisions"],
        metadata={"source": "telegram"},
    )
    await update.message.reply_text("Decision stored.")


def _parse_task_payload(args: list[str]) -> tuple[str | None, str | None]:
    if not args:
        return None, None

    raw = " ".join(args)
    if "|" in raw:
        left, title = raw.split("|", 1)
        due_raw = left.strip()
        due = due_raw if due_raw else None
        return due, title.strip()

    return None, raw.strip()


async def task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    due, title = _parse_task_payload(context.args)
    if not title:
        await update.message.reply_text("Usage: /task <due YYYY-MM-DD optional> | <title>")
        return

    assignee_user_id = None
    assignee_username = None
    assignee_label = "unassigned"
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        assignee_user_id = str(target.id)
        assignee_username = target.username
        assignee_label = assignee_username or target.full_name

    chat_id = str(update.effective_chat.id)
    bank_id = chat_bank_id(update)
    await memory.ensure_group_bank(bank_id)

    task_id = storage.create_task(
        chat_id=chat_id,
        title=title,
        assignee_user_id=assignee_user_id,
        assignee_username=assignee_username,
        due_date=due,
        created_at=utc_now_iso(),
    )

    due_segment = f", due {due}" if due else ""
    await memory.retain_event(
        bank_id=bank_id,
        content=f"Task #{task_id} created: {title}. Owner: {assignee_label}{due_segment}",
        context="Task creation",
        tags=[f"team:{chat_id}", "topic:tasks", "status:open"],
        metadata={"source": "telegram", "task_id": str(task_id)},
    )

    await update.message.reply_text(f"Task #{task_id} created for {assignee_label}.")


async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    rows = list(storage.list_open_tasks(chat_id))
    if not rows:
        await update.message.reply_text("No open tasks.")
        return

    lines = ["Open tasks:"]
    for row in rows:
        owner = row["assignee_username"] or row["assignee_user_id"] or "unassigned"
        due = row["due_date"] or "no due date"
        lines.append(f"- #{row['id']} {row['title']} | owner: {owner} | due: {due}")
    await update.message.reply_text("\n".join(lines))


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /done <task_id>")
        return

    task_id = int(context.args[0])
    chat_id = str(update.effective_chat.id)
    bank_id = chat_bank_id(update)

    ok = storage.complete_task(chat_id=chat_id, task_id=task_id, completed_at=utc_now_iso())
    if not ok:
        await update.message.reply_text("Task not found or already completed.")
        return

    await memory.retain_event(
        bank_id=bank_id,
        content=f"Task #{task_id} completed.",
        context="Task completion",
        tags=[f"team:{chat_id}", "topic:tasks", "status:done"],
        metadata={"source": "telegram", "task_id": str(task_id)},
    )
    await update.message.reply_text(f"Task #{task_id} marked as done.")


async def meeting_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    session_id = uuid4().hex[:12]
    started_at = utc_now_iso()
    storage.set_active_session(chat_id=chat_id, session_id=session_id, started_at=started_at)

    bank_id = chat_bank_id(update)
    await memory.ensure_group_bank(bank_id)
    await memory.retain_event(
        bank_id=bank_id,
        content=f"Meeting started for team {chat_id}. session_id={session_id}",
        context="Meeting lifecycle",
        tags=[f"team:{chat_id}", f"session:{session_id}", "topic:meeting"],
        metadata={"source": "telegram"},
    )
    await update.message.reply_text(f"Meeting capture started. Session: {session_id}")


async def meeting_end(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    active = storage.get_active_session(chat_id)
    if not active:
        await update.message.reply_text("No active meeting session. Use /meeting_start first.")
        return

    session_id = active["session_id"]
    bank_id = chat_bank_id(update)

    transcript_row = storage.get_transcript(chat_id, session_id)
    if not transcript_row or not str(transcript_row["content"] or "").strip():
        await update.message.reply_text(
            "Meeting ended, but no discussion messages were captured. "
            "This usually means bot privacy mode is ON in Telegram. "
            "Use BotFather -> /setprivacy -> Disable, then start a new meeting."
        )
        storage.clear_active_session(chat_id)
        storage.clear_transcript(chat_id, session_id)
        return

    try:
        summary = await memory.meeting_summary(bank_id=bank_id, chat_id=chat_id, session_id=session_id)
    except Exception as exc:
        logger.exception("meeting summary failed", exc_info=exc)
        await update.message.reply_text("Meeting ended, but summary generation failed.")
    else:
        await update.message.reply_text(f"Meeting summary:\n{summary}")

    try:
        extracted_tasks = await memory.extract_action_items(
            bank_id=bank_id,
            chat_id=chat_id,
            session_id=session_id,
        )
    except Exception as exc:
        logger.exception("task extraction failed", exc_info=exc)
        extracted_tasks = []

    created_lines: list[str] = []
    if extracted_tasks:
        roles_map = {((row["username"] or "").lower()): row for row in storage.list_roles(chat_id)}

        for task_item in extracted_tasks[:10]:
            title = str(task_item.get("title", "")).strip()
            if not title:
                continue

            owner_raw = str(task_item.get("owner", "")).strip()
            owner_key = owner_raw.lstrip("@").lower()
            role_row = roles_map.get(owner_key)
            assignee_user_id = str(role_row["user_id"]) if role_row else None
            assignee_username = role_row["username"] if role_row else None
            assignee_label = assignee_username or owner_raw or "unassigned"

            due_candidate = str(task_item.get("due_date", "")).strip()
            due_date = due_candidate if re.fullmatch(r"\d{4}-\d{2}-\d{2}", due_candidate) else None

            task_id = storage.create_task(
                chat_id=chat_id,
                title=title,
                assignee_user_id=assignee_user_id,
                assignee_username=assignee_username,
                due_date=due_date,
                created_at=utc_now_iso(),
            )

            await memory.retain_event(
                bank_id=bank_id,
                content=f"Task #{task_id} created from meeting analysis: {title}. Owner: {assignee_label}",
                context="Task extraction",
                tags=[f"team:{chat_id}", f"session:{session_id}", "topic:tasks", "status:open"],
                metadata={"source": "telegram", "task_id": str(task_id)},
            )

            created_lines.append(
                f"- #{task_id} {title} | owner: {assignee_label} | due: {due_date or 'no due date'}"
            )

    if created_lines:
        await update.message.reply_text("LLM-created tasks:\n" + "\n".join(created_lines))

    storage.clear_active_session(chat_id)
    storage.clear_transcript(chat_id, session_id)


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    active = storage.get_active_session(chat_id)
    if not active:
        await update.message.reply_text("No active meeting. Use /meeting_start first, then /summary during the meeting.")
        return

    bank_id = chat_bank_id(update)
    transcript_row = storage.get_transcript(chat_id, active["session_id"])
    if not transcript_row or not str(transcript_row["content"] or "").strip():
        await update.message.reply_text(
            "No meeting transcript captured yet. "
            "If your team is chatting but bot sees only commands, disable privacy mode via BotFather (/setprivacy)."
        )
        return

    try:
        text = await memory.meeting_summary(
            bank_id=bank_id,
            chat_id=chat_id,
            session_id=active["session_id"],
        )
    except Exception as exc:
        logger.exception("summary failed", exc_info=exc)
        await update.message.reply_text("Summary generation failed.")
        return

    await update.message.reply_text(text)


async def recommend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    bank_id = chat_bank_id(update)
    try:
        text = await memory.assignment_recommendations(bank_id=bank_id, chat_id=chat_id)
    except Exception as exc:
        logger.exception("recommendation failed", exc_info=exc)
        await update.message.reply_text("Recommendation generation failed.")
        return

    await update.message.reply_text(text)


async def guide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    if guidance_engine is None:
        await update.message.reply_text("Role guidance is disabled. Set GROQ_API_KEY to enable /guide.")
        return

    requester = update.effective_user
    target = requester
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target = update.message.reply_to_message.from_user

    chat_id = str(update.effective_chat.id)
    user_id = str(target.id)
    bank_id = chat_bank_id(update)
    await memory.ensure_group_bank(bank_id)

    role_row = storage.get_role(chat_id=chat_id, user_id=user_id)
    if role_row is None:
        await update.message.reply_text(
            "No role found for this user yet. Use /setrole <role> by replying to their message first."
        )
        return

    role = role_row["role"]
    display_name = target.username or target.full_name
    open_tasks = list(storage.list_open_tasks(chat_id))
    assigned_tasks: list[str] = []
    for row in open_tasks:
        if row["assignee_user_id"] == user_id:
            due = row["due_date"] or "no due date"
            assigned_tasks.append(f"#{row['id']} {row['title']} (due: {due})")

    team_roles_rows = list(storage.list_roles(chat_id))
    team_roles = [
        f"{(row['username'] or row['user_id'])}: {row['role']}"
        for row in team_roles_rows
    ]
    open_tasks_all = [
        f"#{row['id']} {row['title']} | owner: {row['assignee_username'] or row['assignee_user_id'] or 'unassigned'} | due: {row['due_date'] or 'no due date'}"
        for row in open_tasks
    ]

    try:
        text = guidance_engine.generate_guidance(
            chat_id=chat_id,
            member_name=display_name,
            role=role,
            assigned_tasks=assigned_tasks,
            team_roles=team_roles,
            open_tasks=open_tasks_all,
        )
    except Exception as exc:
        logger.exception("role guidance failed", exc_info=exc)
        await update.message.reply_text("Guidance generation failed.")
        return

    await update.message.reply_text(f"Guidance for {display_name} ({role}):\n\n{text}")


async def _extract_message_text(update: Update) -> str | None:
    message = update.message
    if not message:
        return None

    if message.text:
        if message.text.startswith("/"):
            return None
        return message.text.strip()

    if message.document:
        file_name = message.document.file_name or "document"
        caption = (message.caption or "").strip()
        if caption:
            return f"[Document shared: {file_name}] {caption}"
        return f"[Document shared: {file_name}]"

    media = message.voice or message.audio
    if not media:
        return None

    if transcriber is None:
        return "[Voice note received but transcription is disabled: set OPENAI_API_KEY]"

    try:
        media_file = await media.get_file()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_audio:
            temp_path = temp_audio.name
        await media_file.download_to_drive(custom_path=temp_path)
        transcript = transcriber.transcribe(temp_path)
    except Exception as exc:
        logger.exception("voice transcription failed", exc_info=exc)
        return "[Voice note transcription failed]"
    finally:
        try:
            if "temp_path" in locals() and os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass

    if not transcript:
        return "[Voice note had no transcribable speech]"
    return transcript


async def capture_meeting_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    extracted_text = await _extract_message_text(update)
    if not extracted_text:
        return

    chat_id = str(update.effective_chat.id)
    active = storage.get_active_session(chat_id)
    if not active:
        return

    speaker = update.effective_user
    when = utc_now_iso()
    line = f"{speaker.full_name} ({when}): {extracted_text}"

    transcript = storage.append_transcript_line(
        chat_id=chat_id,
        session_id=active["session_id"],
        line=line,
        updated_at=when,
    )

    bank_id = chat_bank_id(update)
    await memory.retain_meeting_transcript(
        bank_id=bank_id,
        transcript=transcript,
        chat_id=chat_id,
        session_id=active["session_id"],
        started_at=active["started_at"],
    )


async def send_deadline_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    due_rows = list(storage.list_due_tasks(today))
    if not due_rows:
        return

    grouped: dict[str, list[str]] = {}
    for row in due_rows:
        msg = f"- #{row['id']} {row['title']} (owner: {row['assignee_username'] or row['assignee_user_id'] or 'unassigned'}, due: {row['due_date']})"
        grouped.setdefault(str(row["chat_id"]), []).append(msg)

    for chat_id, lines in grouped.items():
        await context.bot.send_message(
            chat_id=int(chat_id),
            text="Deadline reminder:\n" + "\n".join(lines),
        )


def main() -> None:
    app = Application.builder().token(settings.telegram_bot_token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("setrole", set_role))
    app.add_handler(CommandHandler("roles", roles))
    app.add_handler(CommandHandler("task", task))
    app.add_handler(CommandHandler("tasks", tasks))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CommandHandler("decision", decision))
    app.add_handler(CommandHandler("meeting_start", meeting_start))
    app.add_handler(CommandHandler("meeting_end", meeting_end))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("recommend", recommend))
    app.add_handler(CommandHandler("guide", guide))
    app.add_handler(
        MessageHandler(
            (filters.TEXT & (~filters.COMMAND)) | filters.VOICE | filters.AUDIO | filters.Document.ALL,
            capture_meeting_message,
        )
    )

    if app.job_queue:
        app.job_queue.run_daily(
            send_deadline_reminders,
            time=datetime.min.time().replace(hour=settings.reminder_hour_utc, minute=0, second=0),
            name="deadline-reminders",
        )

    if settings.webhook_mode:
        if not settings.webhook_public_url:
            raise ValueError("WEBHOOK_PUBLIC_URL is required when WEBHOOK_MODE=true")

        path = settings.webhook_path if settings.webhook_path.startswith("/") else f"/{settings.webhook_path}"
        webhook_url = f"{settings.webhook_public_url.rstrip('/')}{path}"
        app.run_webhook(
            listen=settings.webhook_listen,
            port=settings.webhook_port,
            url_path=path.lstrip("/"),
            webhook_url=webhook_url,
            close_loop=False,
            drop_pending_updates=False,
        )
    else:
        app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
