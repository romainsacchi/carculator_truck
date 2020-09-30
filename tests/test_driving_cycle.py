from carculator_truck.driving_cycles import get_standard_driving_cycle
from carculator_truck.gradients import get_gradients
import numpy as np
import pytest

def test_incorrect_cycle_name():
    # Ensure that passing a wrong driving cycle name stops the process
    with pytest.raises(SystemExit) as pytest_wrapped_e:
            get_standard_driving_cycle("jungle")
    assert pytest_wrapped_e.type == SystemExit

def test_finding_road_gradients():
    # Road gradients should be found for a given valid driving cycle name
    assert isinstance(get_gradients("Long haul"), np.ndarray)

    # Ensure that passing a wrong driving cycle name stops the process
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        get_gradients("jungle")
    assert pytest_wrapped_e.type == SystemExit

def test_shape_of_gradient_array():
    # Driving cycle and road gradient should be of same length
    cycle = get_standard_driving_cycle("Long haul")
    gradients = get_gradients("Long haul")

    assert cycle.shape == gradients.shape

def test_shape_dc_array():
    # Driving cycle array should be of shape (number of seconds, number of size classes)
    cycle = get_standard_driving_cycle("Long haul")

    assert cycle.shape == (5825, 6)
