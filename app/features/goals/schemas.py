from typing import Literal

from pydantic import BaseModel, ConfigDict

Objective = Literal["build_muscle", "lose_fat", "gain_weight", "maintain_weight"]


class ObjectivePut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: Objective


class ObjectiveResponse(BaseModel):
    objective: Objective | None
