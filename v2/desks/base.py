"""DeskV2 Protocol.

A desk implementation is any object satisfying this Protocol. The base
class ConcreteDeskV2 is provided as a convenient superclass for desks
that want default __repr__ + identity checks; desks may implement the
Protocol directly without inheriting.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from v2.contracts.forecast_v2 import ForecastV2
from v2.feature_view.spec import FeatureSpec
from v2.feature_view.view import FeatureView


@runtime_checkable
class DeskV2(Protocol):
    """Every v2 desk exposes:

    - `family_id` + `desk_id` as class or instance attributes;
    - `feature_specs()` returning the desk's declared input set; and
    - `forecast(view, prereg_hash, code_commit)` consuming a FeatureView
      and emitting a ForecastV2 (possibly an abstaining one).

    The Protocol is runtime-checkable so tests can `isinstance(desk, DeskV2)`.
    """

    family_id: str
    desk_id: str

    def feature_specs(self) -> list[FeatureSpec]: ...

    def forecast(
        self,
        view: FeatureView,
        *,
        prereg_hash: str,
        code_commit: str,
    ) -> ForecastV2: ...


class ConcreteDeskV2:
    """Convenience base. Not required by the Protocol."""

    family_id: str = ""
    desk_id: str = ""

    def __repr__(self) -> str:
        return f"<{type(self).__name__} family={self.family_id} desk={self.desk_id}>"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ConcreteDeskV2):
            return NotImplemented
        return (
            self.family_id == other.family_id
            and self.desk_id == other.desk_id
            and type(self) is type(other)
        )

    def __hash__(self) -> int:
        return hash((type(self).__name__, self.family_id, self.desk_id))
