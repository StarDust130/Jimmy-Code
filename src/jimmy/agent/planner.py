from dataclasses import dataclass


@dataclass
class PlanDecision:
    """The planner's decision for the next step."""

    instruction: str


class Planner:
    """Decides what the agent should do next."""

    def create_initial_plan(self, task: str) -> PlanDecision:
        return PlanDecision(
            instruction=task,
        )
