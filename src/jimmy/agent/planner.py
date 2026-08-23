import json
from typing import Any

from jimmy.llm.base import LLMProvider
from jimmy.planning.complexity import classify_task
from jimmy.planning.models import (
    TaskComplexity,
    TaskPlan,
)
from jimmy.planning.state import PlanState

PLANNER_SYSTEM_PROMPT = """You are Jimmy's planning component.

Create a concise execution plan for the user's coding task.

Return ONLY valid JSON.

Required format:

{
  "goal": "string",
  "items": [
    {
      "id": "1",
      "title": "string"
    }
  ]
}

Rules:
- Create only useful steps.
- Keep the number of steps small.
- Steps should be concrete and actionable.
- Do not include status fields.
- Do not include explanations outside the JSON.
"""


class Planner:
    """Creates and manages task plans."""

    def __init__(self, llm: LLMProvider | None = None) -> None:
        self.llm = llm

    def create_initial_plan(self, task: str) -> PlanState | None:
        complexity = classify_task(task)

        if complexity == TaskComplexity.SIMPLE:
            return None

        if self.llm is None:
            raise RuntimeError("A planning LLM is required for complex tasks.")

        response = self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": PLANNER_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": task,
                },
            ]
        )

        content = response.content or ""

        plan_data = self._parse_json(content)
        plan = TaskPlan.model_validate(plan_data)

        if not plan.items:
            raise ValueError("Planner returned a plan with no steps.")

        return PlanState(plan)

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        cleaned = content.strip()

        if cleaned.startswith("```"):
            lines = cleaned.splitlines()

            if lines and lines[0].startswith("```"):
                lines = lines[1:]

            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]

            cleaned = "\n".join(lines).strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError("Planner returned invalid JSON.") from exc

        if not isinstance(data, dict):
            raise TypeError("Planner response must be a JSON object.")

        return data
