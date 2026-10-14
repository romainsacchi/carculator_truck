"""Run the native sizing loop to guard FCEV power and pack accounting."""

import numpy as np

from carculator_truck import (
    TruckInputParameters,
    TruckModel,
    fill_xarray_from_input_parameters,
)


def test_completed_fcev_retains_complementary_power_and_complete_pack():
    inputs = TruckInputParameters()
    inputs.static()
    _, array = fill_xarray_from_input_parameters(
        inputs, scope={"size": ["40t"], "powertrain": ["FCEV"], "year": [2020, 2050]}
    )
    model = TruckModel(array, country="CH", cycle="Regional delivery")
    # Truck defaults do not supply an FCEV buffer price. A caller-provided
    # price must nevertheless see the retained, nonzero traction power.
    model["power battery cost per kW"] = 10
    model.set_all()
    net_stack = model["fuel cell power"] / model["fuel cell own consumption"]
    np.testing.assert_allclose(
        net_stack + model["battery power"], model["power"], rtol=2e-6
    )
    assert np.all(model["battery power"] > 0)
    assert np.all(model["power battery cost"] > 0)
    np.testing.assert_allclose(
        model["battery cell mass"] + model["battery BoP mass"],
        model["energy battery mass"],
        rtol=2e-6,
    )
    np.testing.assert_allclose(
        model["battery cell mass"] / model["energy battery mass"],
        model["battery cell mass share"],
        rtol=2e-6,
    )
    np.testing.assert_allclose(
        model["electric energy stored"],
        model["battery cell mass"] * model["battery cell energy density"],
        rtol=2e-6,
    )
    # Heavy vehicles retain their existing energy-sized buffer assumption.
    np.testing.assert_allclose(
        model["electric energy stored"],
        20 + 2 * model["fuel mass"],
        rtol=2e-6,
    )
