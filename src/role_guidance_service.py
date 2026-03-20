from __future__ import annotations

from openai import OpenAI


class RoleGuidanceEngine:
    def __init__(self, api_key: str, model: str = "openai/gpt-oss-120b") -> None:
        self._client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        self._model = model

    def generate_guidance(
        self,
        chat_id: str,
        member_name: str,
        role: str,
        assigned_tasks: list[str],
        team_roles: list[str],
        open_tasks: list[str],
    ) -> str:
        tasks_block = "\n".join(assigned_tasks) if assigned_tasks else "No open assigned tasks"
        roles_block = "\n".join(team_roles) if team_roles else "No team roles set yet"
        open_tasks_block = "\n".join(open_tasks) if open_tasks else "No open team tasks"

        prompt = (
            "You are an expert student project coach. Provide concise, practical guidance for one student.\n\n"
            f"Team: {chat_id}\n"
            f"Student: {member_name}\n"
            f"Role: {role}\n\n"
            "Assigned tasks:\n"
            f"{tasks_block}\n\n"
            "Team roles:\n"
            f"{roles_block}\n\n"
            "Open team tasks:\n"
            f"{open_tasks_block}\n\n"
            "Output format:\n"
            "1) Today priorities (max 3 bullets)\n"
            "2) What to deliver next (specific artifacts)\n"
            "3) What to ask teammates for\n"
            "4) Risks/blockers to raise\n"
            "Keep output short and actionable."
        )

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful AI group project manager for university teams.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=1,
            max_completion_tokens=8192,
            top_p=1,
            stream=False,
            reasoning_effort="medium",
        )

        choices = getattr(response, "choices", [])
        if not choices:
            return "No guidance generated yet."
        msg = choices[0].message
        content = getattr(msg, "content", "") or "No guidance generated yet."
        return content.strip()
