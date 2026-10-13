"""PHEV battery use is weighted before subtracting the initial pack."""

import numpy as np
import pytest
import xarray as xr

from carculator_truck import (
    InventoryTruck,
    TruckInputParameters,
    TruckModel,
    fill_xarray_from_input_parameters,
)


def inputs():
    parameters = TruckInputParameters()
    parameters.static()
    return fill_xarray_from_input_parameters(
        parameters, scope={"size": ["40t"], "powertrain": ["PHEV-d"], "year": [2020]}
    )[1]


@pytest.mark.parametrize(
    "share, expected", [(0, 0), (0.15, 0), (0.5, 26 / 45), (1, 97 / 45)]
)
def test_actual_electric_distance_consumes_one_initial_pack(share, expected):
    model = TruckModel(inputs(), cycle="Regional delivery", drop_hybrids=False)
    model.set_all(electric_utility_factor=share)
    # 710000 lifetime km, a 60-km electric leg at 80% DoD and 3000 EFC/pack:
    # one pack serves 225000 electric km. The first pack is supplied once.
    for powertrain in ("PHEV-d", "PHEV-e", "PHEV-c-d"):
        count = model["battery lifetime replacements"].sel(powertrain=powertrain)
        np.testing.assert_allclose(count, expected, atol=2e-6)
    np.testing.assert_allclose(
        model["component replacement cost"].sel(powertrain="PHEV-d"),
        model["energy battery cost"].sel(powertrain="PHEV-d") * expected,
        rtol=2e-6,
        atol=0.01,
    )
    assert np.isfinite(model["total cost per km"]).all()


def test_fractional_overrides_are_physical_counts_at_zero_electric_share():
    array = inputs().isel(value=[0, 0]).assign_coords(value=["automatic", "explicit"])
    array.loc[
        dict(
            parameter="battery lifetime replacements",
            powertrain="PHEV-e",
            value="explicit",
        )
    ] = 1.25
    original = array.copy(deep=True)
    model = TruckModel(array, cycle="Regional delivery", drop_hybrids=False)
    model.set_all(electric_utility_factor=0)
    expected = model["battery lifetime replacements"].copy(deep=True)
    np.testing.assert_allclose(expected.sel(value="automatic"), 0)
    np.testing.assert_allclose(expected.sel(value="explicit"), 1.25)
    model.set_all(electric_utility_factor=0)
    xr.testing.assert_identical(model["battery lifetime replacements"], expected)
    xr.testing.assert_identical(array, original)


def test_conflicting_counts_for_the_same_physical_pack_are_rejected():
    array = inputs()
    array.loc[dict(parameter="battery lifetime replacements", powertrain="PHEV-e")] = 1
    array.loc[
        dict(parameter="battery lifetime replacements", powertrain="PHEV-c-d")
    ] = 2
    with pytest.raises(ValueError, match="Conflicting PHEV battery replacement"):
        TruckModel(array, cycle="Regional delivery").set_all()


def test_replacement_cap_is_applied_after_electric_usage():
    array = inputs()
    for parameter in array.parameter.values:
        if parameter.startswith("battery cycle life,"):
            array.loc[dict(parameter=parameter)] = 300
    model = TruckModel(array, cycle="Regional delivery")
    model.set_all(electric_utility_factor=0.15)
    assert model["battery lifetime replacements"].item() == 3


def test_positive_replacement_demand_reaches_supply_and_disposal_once():
    model = TruckModel(inputs(), cycle="Regional delivery")
    model.set_all(electric_utility_factor=0.5)
    inventory = InventoryTruck(model, scenario="static", functional_unit="vkm")
    column = inventory.inputs[("truck, PHEV-d, 40t", "CH", "unit", "truck")]
    packs = [
        i
        for label, i in inventory.inputs.items()
        if label[0].startswith("market for battery, Li-ion,")
    ]
    # A 710000-km life with 355000 electric km uses 355000/225000 packs.
    expected = model["energy battery mass"].item() * 355000 / 225000
    assert -inventory.A[0, packs, column, 0].sum() == pytest.approx(expected, rel=2e-6)
    disposal = inventory.inputs[
        ("market for used Li-ion battery", "GLO", "kilogram", "used Li-ion battery")
    ]
    assert inventory.A[0, disposal, column, 0] == pytest.approx(expected, rel=2e-6)
    impacts = inventory.calculate_impacts()
    assert np.isfinite(impacts).all()
    assert (impacts.sel(impact_category="climate change").sum("impact") > 0).all()
