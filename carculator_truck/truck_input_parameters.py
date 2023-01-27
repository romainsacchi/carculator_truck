import json
from pathlib import Path
from typing import Union

from carculator_utils.vehicle_input_parameters import VehicleInputParameters

DEFAULT = Path(__file__, "..").resolve() / "data" / "default_parameters.json"
EXTRA = Path(__file__, "..").resolve() / "data" / "extra_parameters.json"


def load_parameters(obj):
    if isinstance(obj, (str, Path)):
        assert Path(obj).exists(), "Can't find this filepath"
        return json.load(open(obj))
    else:
        # Already in correct form, just return
        return obj


class TruckInputParameters(VehicleInputParameters):
    """ """

    DEFAULT = Path(__file__, "..").resolve() / "data" / "default_parameters.json"
    EXTRA = Path(__file__, "..").resolve() / "data" / "extra_parameters.json"

    def __init__(
        self,
        parameters: Union[str, Path, list] = None,
        extra: Union[str, Path, list] = None,
    ) -> None:
        """Create a `klausen <https://github.com/cmutel/klausen>`__ model with the car input parameters."""
        super().__init__(None)
