"""Power, mass and lifetime energy accounting for a finite HEV buffer."""

from copy import deepcopy

import numpy as np
import pytest
import xarray as xr

from carculator_truck import (
    InventoryTruck,
    TruckInputParameters,
    TruckModel,
    fill_xarray_from_input_parameters,
)
from carculator_truck.hybrid_battery import (
    HybridBatteryProfile,
    avoided_propulsion_fuel,
    run_buffer,
    size_hybrid_buffer,
)


def test_power_sizing_and_losses_have_independent_energy_balance():
    # A 1-kWh cell supplies 4 kW, accepts 2 kW; a 4-kW motor needs one cell.
    # 1800 s at 4 kW braking offers 2 kWh; the power limit accepts 1 kWh DC.
    # At 80% charge and 50% discharge efficiency this gives 0.4 kWh DC output.
    profile = HybridBatteryProfile(
        cell_energy_kwh=1, cell_charge_kw=2, cell_discharge_kw=4, usable_share=1
    )
    charge = np.r_[np.full(1800, 4), np.zeros(3600)]
    demand = np.r_[np.zeros(1800), np.full(3600, 4)]
    result = size_hybrid_buffer(
        charge, demand, 4, 0.8, 0.5, profile=profile, capacity_kwh=1
    )
    assert result["nominal_kwh"] == pytest.approx(1)
    assert result["charged_kwh"] == pytest.approx(0.8)
    assert result["discharged_kwh"] == pytest.approx(0.8)
    assert result["discharged_dc_kwh"] == pytest.approx(0.4)
    assert result["curtailed_kwh"] == pytest.approx(0.8)
    assert result["final_kwh"] == pytest.approx(result["initial_kwh"])


def test_automatic_sizing_can_be_governed_by_energy_instead_of_motor_power():
    profile = HybridBatteryProfile(
        cell_energy_kwh=1, cell_charge_kw=10, cell_discharge_kw=10, usable_share=0.5
    )
    charge = np.r_[np.full(3600, 2), np.zeros(3600)]
    demand = np.r_[np.zeros(3600), np.full(3600, 4)]
    result = size_hybrid_buffer(charge, demand, 4, 1, 1, profile=profile)
    assert result["power_minimum_kwh"] == pytest.approx(0.4)
    assert result["nominal_kwh"] == pytest.approx(4)
    assert result["discharged_dc_kwh"] == pytest.approx(2)


def test_periodic_buffer_neither_creates_energy_nor_depends_on_cycle_start():
    for charge, demand in (([2, 0], [0, 3]), ([0, 2], [3, 0])):
        result = run_buffer(charge, demand, 1)
        assert result["charged_kwh"] == pytest.approx(1)
        assert result["discharged_kwh"] == pytest.approx(1)
        assert result["curtailed_kwh"] == pytest.approx(1)
        assert result["initial_kwh"] == pytest.approx(result["final_kwh"])


def test_surplus_braking_is_spilled_in_a_repeating_downhill_cycle():
    result = size_hybrid_buffer([10, 0], [0, 1], 1, 1, 1)
    assert result["charged_kwh"] == pytest.approx(result["discharged_kwh"])
    assert result["curtailed_kwh"] > 0


def test_downhill_fuel_credit_caps_actual_reuse_not_the_unrestricted_potential():
    # 10 kJ DC reaches wheels through an 80%-efficient motor and 50%-efficient
    # transmission: 4 kJ at wheels. The engine would use 20 kJ fuel for that.
    # Even if unrestricted regeneration offered 100 kJ, accepting only 10 kJ
    # must still avoid all 20 kJ fuel (not 10% of the already capped 20 kJ).
    wheels, transmission, fuel = np.array([4.0]), np.array([0.5]), np.array([20.0])
    assert avoided_propulsion_fuel(
        10 / 3600, 0.8, wheels, transmission, fuel
    ) == pytest.approx(20)
    assert avoided_propulsion_fuel(
        5 / 3600, 0.8, wheels, transmission, fuel
    ) == pytest.approx(10)
    assert avoided_propulsion_fuel(
        30 / 3600, 0.8, wheels, transmission, fuel
    ) == pytest.approx(20)


@pytest.mark.parametrize("override", [0.001, -1, np.nan, np.inf])
def test_explicit_pack_must_supply_the_retained_motor_rating(override):
    with pytest.raises(ValueError, match="capacity"):
        size_hybrid_buffer([1, 0], [0, 100], 100, 1, 1, capacity_kwh=override)


@pytest.mark.parametrize(
    "field,value",
    [
        ("cell_charge_kw", 0),
        ("cell_discharge_kw", -1),
        ("cell_energy_kwh", np.nan),
        ("cell_mass_kg", np.inf),
        ("usable_share", 1.1),
    ],
)
def test_invalid_cell_profiles_are_visible(field, value):
    with pytest.raises(ValueError, match="Hybrid battery"):
        HybridBatteryProfile(**{field: value}).validate()


def inputs(years=(2020,), sizes=("40t",)):
    parameters = TruckInputParameters()
    parameters.static()
    return fill_xarray_from_input_parameters(
        parameters,
        scope={"size": list(sizes), "powertrain": ["HEV-d"], "year": list(years)},
    )[1]


@pytest.fixture(scope="module")
def completed():
    model = TruckModel(inputs((2020, 2050)), cycle="Regional delivery")
    model.set_all()
    return model


def test_completed_hev_pack_closes_mass_energy_power_and_lifetime(completed):
    model = completed
    np.testing.assert_allclose(
        model["battery cell mass"] * model["battery cell energy density"],
        model["electric energy stored"],
        rtol=2e-6,
    )
    np.testing.assert_allclose(
        model["battery cell mass"] + model["battery BoP mass"],
        model["energy battery mass"],
        rtol=2e-6,
    )
    assert (model["starter battery mass"] > 0).all()
    assert (model["electric energy stored"] > 0).all()
    assert (model["energy battery cost"] > 0).all()
    assert (model["charger mass"] == 0).all()
    assert np.isfinite(model["total cost per km"]).all()
    for (size, year, sample), balance in model.hybrid_buffer_results.items():
        cell = model.array.sel(size=size, year=year, value=sample, powertrain="HEV-d")
        value = lambda name: float(cell.sel(parameter=name))
        assert balance["charged_kwh"] == pytest.approx(balance["discharged_kwh"])
        assert balance["maximum_discharge_kw"] >= value("electric power")
        assert balance["discharged_dc_kwh"] < balance["unconstrained_reusable_dc_kwh"]
        trace = model.energy.sel(size=size, year=year, value=sample, powertrain="HEV-d")
        unconstrained_share = float(
            trace.sel(parameter="recuperated energy").sum()
            / trace.sel(parameter="negative motive energy").sum()
        )
        assert value("share recuperated energy") == pytest.approx(
            unconstrained_share
            * balance["discharged_dc_kwh"]
            / balance["unconstrained_reusable_dc_kwh"],
            rel=2e-6,
        )
        distance_per_pack = (
            value("electric energy stored")
            * value("battery cycle life")
            / balance["discharged_stored_kwh_per_km"]
        )
        count = np.clip(value("lifetime kilometers") / distance_per_pack - 1, 0, 3)
        assert value("battery lifetime replacements") == pytest.approx(count, abs=2e-6)
    # Traction cycling creates real replacement demand despite no grid charger.
    assert model["battery lifetime replacements"].sel(year=2020).item() > 0


def test_named_samples_explicit_counts_and_repeated_runs_preserve_inputs():
    source = inputs().isel(value=[0, 0]).assign_coords(value=["default", "explicit"])
    source.loc[dict(parameter="battery lifetime replacements", value="explicit")] = 1.25
    original = source.copy(deep=True)
    overrides = {"capacity": {("HEV-d", "40t", 2020): 12}}
    saved = deepcopy(overrides)
    model = TruckModel(source, cycle="Regional delivery", energy_storage=overrides)
    model.set_all()
    first = model.array.copy(deep=True)
    model.set_all()
    xr.testing.assert_identical(first, model.array)
    xr.testing.assert_identical(source, original)
    assert overrides == saved
    np.testing.assert_allclose(model["electric energy stored"], 12)
    assert model["battery lifetime replacements"].sel(value="explicit").item() == 1.25


def test_explicit_chemistry_is_preserved_and_electrical_proxy_disclosed():
    choice = {"electric": {("HEV-d", "40t", 2020): "NMC-811"}}
    model = TruckModel(inputs(), cycle="Regional delivery", energy_storage=choice)
    model.set_all()
    assert model.energy_storage["electric"] == choice["electric"]
    assert model.hybrid_battery_profile_transfers == [("HEV-d", "40t", 2020, "NMC-811")]
    np.testing.assert_allclose(
        model["battery cell energy density"],
        model["battery cell energy density, NMC-811"],
    )


def test_chemistry_price_proxy_and_explicit_zero_cost_are_distinct():
    array = inputs()
    array.loc[dict(parameter="markup factor")] = 1
    model = TruckModel(array, cycle="Regional delivery")
    model.set_all()
    assert model["energy battery cost per kWh"].item() == pytest.approx(90)
    assert model["energy battery cost"].item() == pytest.approx(
        90 * model["electric energy stored"].item(), rel=2e-6
    )
    free = TruckModel(
        inputs(),
        cycle="Regional delivery",
        battery_costs={"energy battery cost per kWh": {("HEV-d", "40t", 2020): 0}},
    )
    free.set_all()
    assert free["energy battery cost"].item() == 0


def test_native_inventory_supplies_and_disposes_each_physical_pack_once(completed):
    model = deepcopy(completed)
    inventory = InventoryTruck(model, scenario="static", functional_unit="vkm")
    column = inventory.inputs[("truck, HEV-d, 40t", "CH", "unit", "truck")]
    packs = [
        i
        for label, i in inventory.inputs.items()
        if label[0].startswith("market for battery, Li-ion,")
    ]
    expected = (
        model["energy battery mass"] * (1 + model["battery lifetime replacements"])
    ).values.ravel()
    np.testing.assert_allclose(
        -inventory.A[0, packs, column, :].sum(axis=0), expected, rtol=2e-6
    )
    disposal = inventory.inputs[
        ("market for used Li-ion battery", "GLO", "kilogram", "used Li-ion battery")
    ]
    np.testing.assert_allclose(inventory.A[0, disposal, column, :], expected, rtol=2e-6)
    starter = inventory.find_input_indices(("lead acid battery, for lorry",))
    starter_packs = (
        model["lifetime kilometers"] / model["kilometers per year"] / 5
    ).clip(min=1)
    expected_starter = (model["starter battery mass"] * starter_packs).values.ravel()
    np.testing.assert_allclose(
        -inventory.A[0, starter, column, :].sum(axis=0), expected_starter, rtol=2e-6
    )
    impacts = inventory.calculate_impacts()
    assert np.isfinite(impacts).all()
    assert (impacts.sel(impact_category="climate change").sum("impact") > 0).all()


def test_short_lived_hev_still_purchases_one_complete_starter():
    # The 18 t Regional-delivery default life is shorter than five years.
    model = TruckModel(inputs(sizes=("18t",)), cycle="Regional delivery")
    model.set_all()
    assert (model["lifetime kilometers"] / model["kilometers per year"]).item() < 5
    inventory = InventoryTruck(model, scenario="static", functional_unit="vkm")
    column = inventory.inputs[("truck, HEV-d, 18t", "CH", "unit", "truck")]
    starter = inventory.find_input_indices(("lead acid battery, for lorry",))
    assert -inventory.A[0, starter, column, 0].sum() == pytest.approx(
        model["starter battery mass"].item(), rel=2e-6
    )
