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
    # The legacy energy rule is a floor; discharge power can require more.
    assert bool(
        (model["electric energy stored"] >= 20 + 2 * model["fuel mass"] - 1e-4).all()
    )
    np.testing.assert_allclose(
        model["energy battery mass"],
        model["electric energy stored"] * 238 / 25,
        rtol=2e-6,
    )


def test_reference_pack_power_and_mass_are_paired_not_lead_acid_values():
    from carculator_truck.fuel_cell_battery import FuelCellBatteryProfile

    profile = FuelCellBatteryProfile()
    # 100 kW continuous needs two 25-kWh packs. A 450-kW short design pulse
    # instead requires three packs; neither limit uses starter-battery density.
    assert profile.required_capacity(100, 200) == pytest.approx(50)
    assert profile.required_capacity(100, 450) == pytest.approx(75)
    assert profile.cell_energy_density * 238 * 0.7 == pytest.approx(25)


def test_all_regional_fcev_buffers_supply_cycle_continuously_and_limit_charging():
    inputs = TruckInputParameters()
    inputs.static()
    _, array = fill_xarray_from_input_parameters(
        inputs,
        scope={
            "size": ["3.5t", "7.5t", "18t", "26t", "32t", "40t", "60t"],
            "powertrain": ["FCEV"],
            "year": [2020],
        },
    )
    model = TruckModel(array, country="CH", cycle="Regional delivery")
    model.set_all()
    trace = model.energy.sel(parameter="motive energy", drop=True)
    aux = xr.DataArray(
        model.ecm.auxiliary_dc_demand_kw, dims=trace.dims, coords=trace.coords
    )
    demand = trace * model["fuel cell system efficiency"] + aux
    net_fc = model["fuel cell power"] / model["fuel cell own consumption"]
    capacity = model["electric energy stored"]
    assert bool(((demand - net_fc).max("second") <= capacity * 2 * (1 + 3e-6)).all())
    assert bool((model["battery power"] <= capacity * 6 * (1 + 3e-6)).all())
    assert np.all(
        model.ecm.regenerative_charge_dc_kw <= capacity.values.T * 36 / 25 + 1e-4
    )
    assert model.ecm.regenerative_curtailed_dc_kw.max() > 0
    np.testing.assert_allclose(
        model.ecm.regenerative_generator_dc_kw,
        model.ecm.regenerative_auxiliary_dc_kw
        + model.ecm.regenerative_charge_dc_kw
        + model.ecm.regenerative_curtailed_dc_kw,
        atol=1e-5,
    )
    assert model.ecm.power_deficit_kw.max() == 0
    np.testing.assert_allclose(
        capacity * 238 / 25, model["energy battery mass"], rtol=2e-6
    )
    assert bool((model["cargo mass"] <= model["available payload"]).all())


def test_explicit_fcev_capacity_is_preserved_and_inadequate_capacity_rejected():
    source = small_fcev_array().sel(size=["7.5t"], year=[2020])
    override = {"capacity": {("FCEV", "7.5t", 2020): 80}}
    model = TruckModel(source, cycle="Regional delivery", energy_storage=override)
    model.set_all()
    assert model["electric energy stored"].item() == pytest.approx(80)
    assert model["energy battery mass"].item() == pytest.approx(761.6, rel=2e-6)
    first = model.array.copy(deep=True)
    model.set_all()
    xr.testing.assert_identical(first, model.array)
    assert override == {"capacity": {("FCEV", "7.5t", 2020): 80}}
    too_small = TruckModel(
        source,
        cycle="Regional delivery",
        energy_storage={"capacity": {("FCEV", "7.5t", 2020): 1}},
    )
    with pytest.raises(ValueError, match="FCEV battery cannot supply"):
        too_small.set_all()


@pytest.mark.parametrize("invalid", [0, -1, np.nan, np.inf])
def test_invalid_fcev_pack_profile_is_rejected(invalid):
    with pytest.raises(ValueError, match="FCEV battery"):
        TruckModel(small_fcev_array(), fuel_cell_battery={"charge_kw": invalid})
