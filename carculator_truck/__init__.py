"""

Submodules
==========

.. autosummary::
    :toctree: _autosummary


"""

__all__ = (
    "TruckInputParameters",
    "fill_xarray_from_input_parameters",
    "TruckModel",
    "InventoryTruck",
    "get_driving_cycle",
)

# library version
__version__ = (0, 5, 0, "dev0")

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

from carculator_utils.array import fill_xarray_from_input_parameters

from .driving_cycles import get_driving_cycle
from .inventory import InventoryTruck
from .model import TruckModel
from .truck_input_parameters import TruckInputParameters
