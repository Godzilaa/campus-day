# AI Group Project Manager (Telegram + Hindsight)

This is an MVP Telegram bot that acts like a project manager for student teams.

It remembers:
- Team roles
- Project decisions
- Task progress (open/done + due dates)
- Meeting transcripts and summaries
- Voice notes transcribed during meetings

It provides:
- Automatic meeting summaries
- AI task assignment recommendations
- Deadline reminders
- Voice-to-text capture for meeting discussions

## Why Hindsight fits this idea

The bot uses Hindsight as long-term memory:
- `retain` stores meeting transcripts, role updates, task events, and decisions
- Stable `document_id` per meeting session keeps transcript memory up to date via upsert
- `tags` scope memory per team/session/user (`team:<chat_id>`, `session:<id>`, `user:<id>`)
- `reflect` produces summaries and role-aware assignment recommendations

This aligns with Hindsight best practices for mission tuning, tags, and document evolution.

## Project Structure

- `src/bot.py`: Telegram bot handlers and scheduler
- `src/hindsight_service.py`: Hindsight integration layer
- `src/storage.py`: SQLite state for tasks/roles/sessions
- `src/config.py`: environment settings

## Setup

1. Create and activate a Python environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy env file:

```bash
cp .env.example .env
```

4. Set environment variables in `.env`:
- `TELEGRAM_BOT_TOKEN`
- `HINDSIGHT_BASE_URL` (local default: `http://localhost:8888`)
- `HINDSIGHT_API_KEY` (required for Hindsight Cloud)
- `HINDSIGHT_BANK_PREFIX`
- `REMINDER_HOUR_UTC`
- `OPENAI_API_KEY` (optional for voice note transcription)
- `OPENAI_TRANSCRIBE_MODEL` (default: `whisper-1`; for Groq use `whisper-large-v3-turbo`)
- `GROQ_API_KEY` (required for `/guide` role-based LLM guidance)
- `GROQ_MODEL` (default: `openai/gpt-oss-120b`)
- `WEBHOOK_MODE` (`true` for webhook mode, `false` for polling)
- `WEBHOOK_LISTEN` (default: `0.0.0.0`)
- `WEBHOOK_PORT` (default: `8000`)
- `WEBHOOK_PATH` (default: `/telegram`)
- `WEBHOOK_PUBLIC_URL` (required when `WEBHOOK_MODE=true`, e.g. `https://your-tunnel.example.com`)

Hindsight Cloud option:
- Open https://ui.hindsight.vectorize.io/connect and sign in.
- Copy the API URL into `HINDSIGHT_BASE_URL` and API key into `HINDSIGHT_API_KEY`.
- Run the bot normally; no local Hindsight server is needed in cloud mode.

Voice transcription with Groq:
- If `OPENAI_API_KEY` is empty and `GROQ_API_KEY` is set, the bot will use Groq's OpenAI-compatible endpoint for transcription.
- Recommended model: `OPENAI_TRANSCRIBE_MODEL=whisper-large-v3-turbo`.

5. Start the bot:

```bash
python src/bot.py
```

### Webhook mode (for tunnel/proxy)

Set these values in `.env`:

```bash
WEBHOOK_MODE=true
WEBHOOK_LISTEN=0.0.0.0
WEBHOOK_PORT=8000
WEBHOOK_PATH=/telegram
WEBHOOK_PUBLIC_URL=https://your-public-domain-or-tunnel
```

Then start the bot with the same command:

```bash
python src/bot.py
```

Telegram updates will be delivered to:

```text
https://your-public-domain-or-tunnel/telegram
```

## Commands

- `/start` show help
- `/setrole <role>` assign role (must reply to teammate message)
- `/roles` list team roles
- `/decision <text>` store decision
- `/task <due YYYY-MM-DD optional> | <title>` create task (reply to assign)
- `/tasks` list open tasks
- `/done <task_id>` mark task complete
- `/meeting_start` start transcript capture
- `/summary` generate in-progress summary for active meeting
- `/meeting_end` generate final summary and close session
- `/recommend` suggest task assignments from memory
- `/guide` personalized guidance for your role (or reply to teammate and run `/guide`)

## Flow in a real group project

1. Add bot to Telegram group.
2. During a meeting: run `/meeting_start`.
3. Team discusses project; bot captures transcript and updates memory.
4. Team can send voice notes; bot transcribes and stores them in the same session context.
5. Assign roles and tasks in chat using `/setrole` and `/task`.
6. Record final decisions with `/decision`.
7. Run `/meeting_end` to get summary + next actions.
8. Use `/recommend` to ask who should take which task next.

## Notes

- SQLite is used for deterministic task state.
- Hindsight is used for semantic memory + reasoning over team history.
- For production, move polling to webhooks, add auth/permissions, and add retries/observability.
