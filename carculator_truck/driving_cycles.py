import numpy as np
from carculator_utils import get_standard_driving_cycle_and_gradient


def get_driving_cycle(size: list, name: str) -> np.ndarray:
    """
    Get driving cycle.

    :param size: List of vehicle sizes.
    :param name: The name of the driving cycle.
    :return: :meth:`ndarray` object
    """
    return get_standard_driving_cycle_and_gradient(
        vehicle_type="truck",
        vehicle_sizes=size,
        name=name,
    )[0]


def get_road_gradient(size: list, name: str) -> np.ndarray:
    """
    Get road gradient data.

    :param size: List of vehicle sizes.
    :param name: The name of the driving cycle.
    :return: :meth:`ndarray` object
    """
    return get_standard_driving_cycle_and_gradient(
        vehicle_type="truck",
        vehicle_sizes=size,
        name=name,
    )[1]
