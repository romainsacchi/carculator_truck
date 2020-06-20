"""

Submodules
==========

.. autosummary::
    :toctree: _autosummary


"""

_all_ = (
    "TruckInputParameters"
)

__version__ = (0, 0, 1)

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

from .truck_input_parameters import TruckInputParameters
from .array import (
    fill_xarray_from_input_parameters,
    modify_xarray_from_custom_parameters,
)
print("Hello!")
