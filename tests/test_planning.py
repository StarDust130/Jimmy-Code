import pytest

from jimmy.planning.models import PlanItem, PlanItemStatus, TaskPlan
from jimmy.planning.state import PlanState


def test_plan_state_starts_with_pending_items() -> None:
    plan = TaskPlan(
        goal="some task",
        items=[
            PlanItem(
                id="1",
                title="Inspect code",
            ),
            PlanItem(
                id="2",
                title="Run tests",
            ),
        ],
    )

    state = PlanState(plan)

    assert state.next_pending() == "1"


def test_plan_item_can_start_and_complete() -> None:
    plan = TaskPlan(
        goal="Fix authentication",
        items=[
            PlanItem(
                id="1",
                title="Inspect auth",
            ),
        ],
    )

    state = PlanState(plan)

    state.start("1")

    assert state.plan.items[0].status == PlanItemStatus.IN_PROGRESS

    state.complete("1", "Found the bug.")

    assert state.plan.items[0].status == PlanItemStatus.DONE
    assert state.plan.items[0].notes == "Found the bug."


def test_unknown_plan_item_raises() -> None:
    plan = TaskPlan(
        goal="Fix authentication",
    )

    state = PlanState(plan)

    with pytest.raises(KeyError, match="Unknown plan item"):
        state.start("999")
