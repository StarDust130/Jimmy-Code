import pytest

from jimmy.planning.complexity import classify_task
from jimmy.planning.models import (
    PlanItem,
    PlanItemStatus,
    TaskComplexity,
    TaskPlan,
)
from jimmy.planning.state import PlanState


def test_simple_task_is_classified_simple() -> None:
    result = classify_task("Explain what this function does.")

    assert result == TaskComplexity.SIMPLE


def test_complex_task_is_classified_complex() -> None:
    result = classify_task("Refactor the authentication system across the project.")

    assert result == TaskComplexity.COMPLEX


def test_plan_state_starts_with_pending_items() -> None:
    plan = TaskPlan(
        goal="Complete the requested task",
        items=[
            PlanItem(
                id="1",
                title="Inspect the relevant code",
            ),
            PlanItem(
                id="2",
                title="Run the tests",
            ),
        ],
    )

    state = PlanState(plan)

    assert state.next_pending() == "1"


def test_plan_item_can_start_and_complete() -> None:
    plan = TaskPlan(
        goal="Complete the requested task",
        items=[
            PlanItem(
                id="1",
                title="Inspect the relevant code",
            ),
        ],
    )

    state = PlanState(plan)

    state.start("1")

    assert state.plan.items[0].status == PlanItemStatus.IN_PROGRESS

    state.complete(
        "1",
        "Inspection completed.",
    )

    assert state.plan.items[0].status == PlanItemStatus.DONE

    assert state.plan.items[0].notes == "Inspection completed."


def test_unknown_plan_item_raises() -> None:
    plan = TaskPlan(
        goal="Complete the requested task",
    )

    state = PlanState(plan)

    with pytest.raises(
        KeyError,
        match="Unknown plan item",
    ):
        state.start("999")
