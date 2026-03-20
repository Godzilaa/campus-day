from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from hindsight_client import Hindsight


logger = logging.getLogger(__name__)


class HindsightProjectMemory:
    def __init__(self, base_url: str, bank_prefix: str, api_key: str = "") -> None:
        if api_key:
            try:
                self._client = Hindsight(base_url=base_url, api_key=api_key)
            except TypeError:
                # Backward compatibility for older hindsight-client versions.
                self._client = Hindsight(base_url=base_url)
        else:
            self._client = Hindsight(base_url=base_url)
        self._bank_prefix = bank_prefix

    def bank_id(self, chat_id: str) -> str:
        return f"{self._bank_prefix}-{chat_id.replace('-', 'neg')}"

    async def ensure_group_bank(self, bank_id: str) -> None:
        try:
            await self._client.acreate_bank(bank_id=bank_id)
        except Exception as exc:
            msg = str(exc).lower()
            if "already" in msg and "exist" in msg:
                # Bank already exists, safe to continue.
                pass
            else:
                logger.exception("Failed to create Hindsight bank %s", bank_id, exc_info=exc)
                raise

        try:
            kwargs = {
                "retain_mission": (
                    "Extract team roles, project decisions, task commitments, deadlines, blockers, "
                    "ownership changes, and completion updates. Ignore greetings and small talk."
                ),
                "observations_mission": (
                    "Synthesize durable patterns about team collaboration, delivery risk, and recurring blockers."
                ),
                "reflect_mission": (
                    "You are an AI group project manager. Provide practical, concise guidance based on team history."
                ),
                "disposition_skepticism": 4,
                "disposition_literalism": 4,
                "disposition_empathy": 3,
            }

            if hasattr(self._client, "aupdate_bank_config"):
                await self._client.aupdate_bank_config(bank_id, **kwargs)
            else:
                logger.warning(
                    "Hindsight client does not support async bank config updates; skipping mission/disposition setup"
                )
        except Exception as exc:
            # Config method may differ between versions; continue with defaults.
            logger.warning("Failed to update bank config for %s: %s", bank_id, exc)

    async def retain_meeting_transcript(
        self,
        bank_id: str,
        transcript: str,
        chat_id: str,
        session_id: str,
        started_at: str,
    ) -> None:
        await self._client.aretain(
            bank_id=bank_id,
            content=transcript,
            context="Project meeting transcript from Telegram group",
            timestamp=started_at,
            document_id=f"meeting-{session_id}",
            tags=[f"team:{chat_id}", f"session:{session_id}"],
            metadata={"source": "telegram", "content_type": "meeting_transcript"},
        )

    async def retain_event(
        self,
        bank_id: str,
        content: str,
        context: str,
        tags: list[str],
        metadata: dict[str, str] | None = None,
        timestamp: str | None = None,
    ) -> None:
        event_timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        await self._client.aretain(
            bank_id=bank_id,
            content=content,
            context=context,
            timestamp=event_timestamp,
            tags=tags,
            metadata=metadata or {},
        )

    async def meeting_summary(self, bank_id: str, chat_id: str, session_id: str) -> str:
        response = await self._client.areflect(
            bank_id=bank_id,
            query=(
                "Create a meeting summary for this project team. Return: 1) key decisions, "
                "2) assigned tasks with owners, 3) deadlines, 4) blockers, 5) next actions. "
                "If missing data, explicitly say unknown."
            ),
            tags=[f"team:{chat_id}", f"session:{session_id}"],
            tags_match="all",
            budget="mid",
        )
        return getattr(response, "text", "") or "No summary generated."

    async def assignment_recommendations(self, bank_id: str, chat_id: str) -> str:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "recommendations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "task": {"type": "string"},
                            "owner": {"type": "string"},
                            "reason": {"type": "string"},
                            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                        },
                        "required": ["task", "owner", "reason", "confidence"],
                    },
                }
            },
            "required": ["recommendations"],
        }

        response = await self._client.areflect(
            bank_id=bank_id,
            query=(
                "Recommend best task ownership for the current project based on remembered roles, "
                "past decisions, and progress. Keep recommendations actionable."
            ),
            tags=[f"team:{chat_id}"],
            tags_match="any",
            budget="mid",
            response_schema=schema,
        )

        structured = getattr(response, "structured_output", None)
        if not structured:
            return "No structured recommendations available yet."

        recommendations = structured.get("recommendations", [])
        if not recommendations:
            return "No recommendations available yet."

        lines = ["Recommended task assignments:"]
        for rec in recommendations:
            lines.append(
                f"- {rec.get('task', 'Task')}: {rec.get('owner', 'Unassigned')} "
                f"({rec.get('confidence', 'medium')}) - {rec.get('reason', 'No reason')}")
        return "\n".join(lines)

    async def role_guidance(
        self,
        bank_id: str,
        chat_id: str,
        user_id: str,
        display_name: str,
        role: str,
        assigned_tasks: list[str],
    ) -> str:
        tasks_block = "\n".join([f"- {task}" for task in assigned_tasks]) if assigned_tasks else "- No open assigned tasks"
        response = await self._client.areflect(
            bank_id=bank_id,
            query=(
                "You are a student project manager assistant. Give role-specific guidance for this team member.\n"
                f"Member: {display_name}\n"
                f"Role: {role}\n"
                "Open assigned tasks:\n"
                f"{tasks_block}\n\n"
                "Return concise markdown with these sections:\n"
                "1) Priority for today (max 3 bullets)\n"
                "2) What to deliver next\n"
                "3) Risks and blockers to raise in the next meeting\n"
                "Keep it practical and specific."
            ),
            tags=[f"team:{chat_id}", f"user:{user_id}"],
            tags_match="any",
            budget="mid",
        )
        return getattr(response, "text", "") or "No guidance generated yet."

    async def extract_action_items(self, bank_id: str, chat_id: str, session_id: str) -> list[dict[str, Any]]:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "owner": {"type": "string"},
                            "due_date": {"type": "string"},
                            "notes": {"type": "string"},
                        },
                        "required": ["title"],
                    },
                }
            },
            "required": ["tasks"],
        }

        response = await self._client.areflect(
            bank_id=bank_id,
            query=(
                "Extract concrete action items from this meeting. Return only tasks that were clearly implied or "
                "explicitly discussed. For each task include title, suggested owner (if known), due_date in YYYY-MM-DD "
                "if present, and short notes."
            ),
            tags=[f"team:{chat_id}", f"session:{session_id}"],
            tags_match="all",
            budget="mid",
            response_schema=schema,
        )

        structured = getattr(response, "structured_output", None)
        if not structured:
            return []

        tasks = structured.get("tasks", [])
        if not isinstance(tasks, list):
            return []
        return tasks
