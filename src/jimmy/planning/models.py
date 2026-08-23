from enum import StrEnum

from pydantic import BaseModel, Field


class PlanItemStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"


class TaskComplexity(StrEnum):
    SIMPLE = "simple"
    COMPLEX = "complex"


class PlanItem(BaseModel):
    id: str
    title: str
    status: PlanItemStatus = PlanItemStatus.PENDING
    notes: str | None = None


class TaskPlan(BaseModel):
    goal: str
    items: list[PlanItem] = Field(default_factory=list)
