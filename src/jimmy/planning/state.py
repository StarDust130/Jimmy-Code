from jimmy.planning.models import PlanItemStatus, TaskPlan


class PlanState:
    """Owns and updates the current task plan."""

    def __init__(self, plan: TaskPlan) -> None:
        self.plan = plan

    def start(self, item_id: str) -> None:
        item = self._find(item_id)
        item.status = PlanItemStatus.IN_PROGRESS

    def complete(self, item_id: str, notes: str | None = None) -> None:
        item = self._find(item_id)
        item.status = PlanItemStatus.DONE

        if notes is not None:
            item.notes = notes

    def block(self, item_id: str, notes: str | None = None) -> None:
        item = self._find(item_id)
        item.status = PlanItemStatus.BLOCKED

        if notes is not None:
            item.notes = notes

    def next_pending(self) -> str | None:
        for item in self.plan.items:
            if item.status == PlanItemStatus.PENDING:
                return item.id

        return None

    def summary(self) -> str:
        lines = [f"Goal: {self.plan.goal}"]

        for item in self.plan.items:
            lines.append(f"{item.id}. [{item.status}] {item.title}")

        return "\n".join(lines)

    def _find(self, item_id: str):
        for item in self.plan.items:
            if item.id == item_id:
                return item

        raise KeyError(f"Unknown plan item: {item_id}")
