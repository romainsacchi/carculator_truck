import numpy as np
from carculator_utils import get_standard_driving_cycle_and_gradient


def get_driving_cycle(size: list, name: str) -> np.ndarray:
    return get_standard_driving_cycle_and_gradient(
        vehicle_type="truck",
        vehicle_sizes=size,
        name=name,
    )[0]


def get_road_gradient(size: list, name: str) -> np.ndarray:
    return get_standard_driving_cycle_and_gradient(
        vehicle_type="truck",
        vehicle_sizes=size,
        name=name,
    )[1]
