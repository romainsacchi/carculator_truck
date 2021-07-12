"""

Submodules
==========

.. autosummary::
    :toctree: _autosummary


"""

_all_ = (
    "TruckInputParameters",
    "fill_xarray_from_input_parameters",
    "modify_xarray_from_custom_parameters",
    "TruckModel",
    "get_standard_driving_cycle",
    "EnergyConsumptionModel",
    "get_gradients",
    "HotEmissionsModel",
)

# library version
__version__ = (0, 2, 3)

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

from .array import (
    fill_xarray_from_input_parameters,
    modify_xarray_from_custom_parameters,
)
from .driving_cycles import get_standard_driving_cycle
from .energy_consumption import EnergyConsumptionModel
from .gradients import get_gradients
from .hot_emissions import HotEmissionsModel
from .inventory import InventoryCalculation
from .model import TruckModel
from .truck_input_parameters import TruckInputParameters
