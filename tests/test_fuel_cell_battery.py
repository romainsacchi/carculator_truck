"""Run the native sizing loop to guard FCEV power and pack accounting."""

import numpy as np
import pytest
import xarray as xr

from carculator_truck import (
    TruckInputParameters,
    TruckModel,
    fill_xarray_from_input_parameters,
)


def small_fcev_array():
    inputs = TruckInputParameters()
    inputs.static()
    return fill_xarray_from_input_parameters(
        inputs,
        scope={"size": ["3.5t", "7.5t"], "powertrain": ["FCEV"], "year": [2020, 2050]},
    )[1]


def test_small_fcev_motor_proxies_complete_regional_cycle():
    source = small_fcev_array()
    before = source.copy(deep=True)
    model = TruckModel(source, country="CH", cycle="Regional delivery")
    model.set_all()
    xr.testing.assert_identical(source, before)
    for size, rating in (("3.5t", 57), ("7.5t", 129)):
        np.testing.assert_allclose(model["electric power"].sel(size=size), rating)
    assert np.max(model.ecm.power_deficit_kw) == 0
    # Check the actual cycle output, independently of the diagnostic attribute.
    required = model.energy.sel(parameter="motive energy at wheels") / model.energy.sel(
        parameter="transmission efficiency"
    )
    assert bool((required.max("second") <= model["electric power"]).all())
    dc = model["electric power"] / model["electric motor efficiency"]
    dc += model["auxiliary power demand"] / 1000
    np.testing.assert_allclose(
        model["fuel cell power"] / model["fuel cell own consumption"]
        + model["battery power"],
        dc,
        rtol=2e-6,
    )
    np.testing.assert_allclose(
        model["fuel mass"] * model["LHV fuel MJ per kg"] * 1000 / model["TtW energy"],
        model["target range"],
        rtol=3e-6,
    )


def test_rated_power_respects_samples_and_explicit_power_override():
    array = small_fcev_array().isel(value=[0, 0]).assign_coords(value=["a", "b"])
    array.loc[dict(size="3.5t", year=2020, parameter="rated power")] = xr.DataArray(
        [57, 60], dims="value", coords={"value": ["a", "b"]}
    )
    overrides = {("FCEV", "7.5t", 2020): 140}
    model = TruckModel(array, power=overrides)
    model["curb mass"] = 1000
    model.set_power_parameters()
    np.testing.assert_allclose(
        model["power"].sel(size="3.5t", year=2020).values.ravel(), [57, 60]
    )
    np.testing.assert_allclose(model["power"].sel(size="7.5t", year=2020), 140)
    assert overrides == {("FCEV", "7.5t", 2020): 140}
    # Explicit zero restores the original mass-based assumption for a cell.
    model["rated power"] = 0
    model.set_power_parameters()
    np.testing.assert_allclose(model["power"].sel(size="3.5t", year=2020), 25)
    legacy = TruckModel(array.drop_sel(parameter="rated power"))
    legacy["curb mass"] = 1000
    legacy.set_power_parameters()
    np.testing.assert_allclose(legacy["power"].sel(size="3.5t", year=2020), 25)


@pytest.mark.parametrize("invalid", [-1, np.nan, np.inf])
def test_invalid_rated_power_is_rejected(invalid):
    model = TruckModel(small_fcev_array())
    model["rated power"] = invalid
    with pytest.raises(ValueError, match="Rated power"):
        model.set_power_parameters()


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
    auxiliary_fields = ["auxiliary energy"]
    # Recover delivered auxiliary DC demand from the independently calculated
    # hydrogen-input trace; it bypasses motor conversion losses.
    auxiliary = (
        model.energy.sel(parameter=auxiliary_fields).sum("parameter").max("second")
        * model["fuel cell system efficiency"]
    ).transpose(*model["power"].dims)
    required_dc = model["power"] / model["electric motor efficiency"] + auxiliary
    np.testing.assert_allclose(
        net_stack + model["battery power"], required_dc, rtol=2e-6
    )
    np.testing.assert_allclose(
        net_stack / required_dc, model["fuel cell power share"], rtol=2e-6
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
