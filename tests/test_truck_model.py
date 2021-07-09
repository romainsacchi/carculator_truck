import numpy as np

from carculator_truck import *

tip = TruckInputParameters()
tip.static()
_, array = fill_xarray_from_input_parameters(tip)
tm = TruckModel(array, cycle="Long haul", country="CH")
tm.set_all()

# def test_energy_target_compliance():
# ICEV-d and ICEV-g after 2020 should comply with given energy targets
# In this case, 30% reduction in 2030 compared to 2020
#    assert np.all((tm.array.sel(powertrain=["ICEV-d", "ICEV-g"], size="40t", year=2030, parameter="TtW energy")/
#     tm.array.sel(powertrain=["ICEV-d", "ICEV-g"], size="40t", year=2020, parameter="TtW energy")) <= .7)


def test_presence_PHEVe():
    # PHEV-e should be dropped
    assert "PHEV-e" not in tm.array.powertrain.values.tolist()


def test_ttw_energy_against_VECTO():
    # The TtW energy consumption of a 40-ton diesel must be
    # within an interval given by VECTO
    vecto_empty, vecto_full = (8300, 13700)

    assert (
        vecto_empty
        <= tm.array.sel(
            powertrain="ICEV-d", year=2020, size="40t", parameter="TtW energy", value=0
        )
        <= vecto_full
    )


# The fuel cell stack mass must be in a given interval


def test_auxiliary_power_demand():
    # The auxilliary power demand must be lower for combustion trucks
    assert np.all(
        tm.array.sel(
            powertrain="ICEV-d", year=2020, parameter="auxiliary power demand", value=0
        )
        < tm.array.sel(
            powertrain="BEV", year=2020, parameter="auxiliary power demand", value=0
        )
    )


def test_battery_replacement():
    # Battery replacements cannot be lower than 0
    assert np.all(tm["battery lifetime replacements"] >= 0)


def test_cargo_mass():
    # Cargo mass cannot be superior to available payload
    assert np.all(tm["total cargo mass"] <= tm["available payload"])

    # Cargo mass must equal the available payload * load factor
    # assert np.allclose((tm["available payload"] * tm["capacity utilization"]), tm["total cargo mass"])


def test_electric_utility_factor():
    # Electric utility factor must be between 0 and 1
    assert 0 <= np.all(tm["electric utility factor"]) <= 1


def test_fuel_blends():
    # Shares of a fuel blend must equal 1
    for fuel in tm.fuel_blend:
        np.testing.assert_array_equal(
            np.array(tm.fuel_blend[fuel]["primary"]["share"])
            + np.array(tm.fuel_blend[fuel]["secondary"]["share"]),
            [1, 1, 1, 1, 1, 1],
        )

    # A fuel cannot be specified both as primary and secondary fuel
    for fuel in tm.fuel_blend:
        assert (
            tm.fuel_blend[fuel]["primary"]["type"]
            != tm.fuel_blend[fuel]["secondary"]["type"]
        )


def test_battery_mass():
    # Battery mass must equal cell mass and BoP mass
    with tm("BEV") as cpm:
        assert np.allclose(
            cpm["energy battery mass"],
            cpm["battery cell mass"] + cpm["battery BoP mass"],
        )

    # Cell mass must equal capacity divided by energy density of cells
    with tm("BEV") as cpm:
        assert np.allclose(
            cpm["battery cell mass"],
            cpm["electric energy stored"] / cpm["battery cell energy density, NMC-111"],
        )


# Long haul efficiencies are superior to Urban delivery efficiencies for combustion vehicles

# Emissions of NOx in 2020 must be below EURO VI limits


def test_noise_emissions():
    # Noise emissions with Urban delivery must only affect urban area
    tm = TruckModel(array, cycle="Urban delivery", country="CH")
    tm.set_all()

    list_comp = ["rural", "suburban"]
    params = [
        p
        for p in tm.array.parameter.values
        if "noise" in p and any([x in p for x in list_comp])
    ]

    assert tm.array.sel(parameter=params).sum() == 0


# Hydrogen must have zero CO2 emissions, synthetic diesel, 3.16
