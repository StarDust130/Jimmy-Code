from jimmy.planning.models import PlanItem, TaskPlan
from jimmy.planning.state import PlanState


class Planner:
    """Creates and manages task plans."""

    def create_initial_plan(self, task: str) -> PlanState:
        plan = TaskPlan(
            goal=task,
            items=[
                PlanItem(
                    id="1",
                    title="Understand the task",
                ),
                PlanItem(
                    id="2",
                    title="Inspect the relevant code",
                ),
                PlanItem(
                    id="3",
                    title="Implement the required change",
                ),
                PlanItem(
                    id="4",
                    title="Run tests and verify the change",
                ),
            ],
        )

        return PlanState(plan)
