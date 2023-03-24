from pathlib import Path

import numpy as np
import pandas as pd
from carculator_utils.array import fill_xarray_from_input_parameters

from carculator_truck import TruckInputParameters, TruckModel

tip = TruckInputParameters()
tip.static()
_, array = fill_xarray_from_input_parameters(tip)
tm = TruckModel(array, cycle="Long haul", country="CH")
tm.set_all()


def test_presence_PHEVe():
    # PHEV-e should be dropped
    assert "PHEV-e" not in tm.array.powertrain.values.tolist()


def test_ttw_energy_against_VECTO():
    # The TtW energy consumption of a 40-ton diesel must be
    # within an interval given by VECTO
    vecto_empty, vecto_full = (8300, 16000)

    assert (
        vecto_empty
        <= tm.array.sel(
            powertrain="ICEV-d", year=2020, size="40t", parameter="TtW energy", value=0
        )
        <= vecto_full
    )


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
    # Cargo mass must equal the available payload * load factor

    assert np.allclose(
        (
            tm.array.sel(
                parameter="available payload",
                powertrain="ICEV-d",
                year=2020,
                size="40t",
            )
            * tm.array.sel(
                parameter="capacity utilization",
                powertrain="ICEV-d",
                year=2020,
                size="40t",
            )
        ),
        tm.array.sel(
            parameter="cargo mass", powertrain="ICEV-d", year=2020, size="40t"
        ),
        rtol=1e-3,
    )


def test_electric_utility_factor():
    # Electric utility factor must be between 0 and 1
    assert 0 <= np.all(tm["electric utility factor"]) <= 1
    assert (
        tm.array.sel(parameter="electric utility factor", powertrain="PHEV-d").all() > 0
    )


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

    assert np.allclose(
        tm.array.sel(
            parameter="energy battery mass", powertrain="BEV", year=2030, size="40t"
        ),
        tm.array.sel(
            parameter="battery cell mass", powertrain="BEV", year=2030, size="40t"
        )
        + tm.array.sel(
            parameter="battery BoP mass", powertrain="BEV", year=2030, size="40t"
        ),
    )

    # Cell mass must equal capacity divided by energy density of cells

    assert np.allclose(
        tm.array.sel(
            parameter="battery cell mass", powertrain="BEV", year=2030, size="40t"
        ),
        tm.array.sel(
            parameter="electric energy stored", powertrain="BEV", year=2030, size="40t"
        )
        / tm.array.sel(
            parameter="battery cell energy density",
            powertrain="BEV",
            year=2030,
            size="40t",
        ),
    )


DATA = Path(__file__, "..").resolve() / "fixtures" / "trucks_values.xlsx"
OUTPUT = Path(__file__, "..").resolve() / "fixtures" / "test_model_results.xlsx"
ref = pd.read_excel(DATA, index_col=0)

tip = TruckInputParameters()
tip.static()
dcts, arr = fill_xarray_from_input_parameters(tip)
tm = TruckModel(arr)
tm.set_all()


def test_model_results():
    list_powertrains = [
        "ICEV-d",
        "PHEV-d",
        "BEV",
        "ICEV-g",
        "HEV-d",
    ]
    list_sizes = [
        # "3.5t",
        # "7.5t",
        "18t",
        # "32t"
    ]
    list_years = [
        2020,
        # 2030,
        # 2040,
        # 2050
    ]

    l_res = []

    for pwt in list_powertrains:
        for size in list_sizes:
            for year in list_years:
                for param in tm.array.parameter.values:
                    val = float(
                        tm.array.sel(
                            powertrain=pwt,
                            size=size,
                            year=year,
                            parameter=param,
                            value=0,
                        ).values
                    )

                    try:
                        ref_val = (
                            ref.loc[
                                (ref["powertrain"] == pwt)
                                & (ref["size"] == size)
                                & (ref["parameter"] == param),
                                year,
                            ]
                            .values.astype(float)
                            .item(0)
                        )
                    except:
                        ref_val = 1

                    _ = lambda x: np.where(ref_val == 0, 1, ref_val)
                    diff = val / _(ref_val)
                    l_res.append([pwt, size, year, param, val, ref_val, diff])

    pd.DataFrame(
        l_res,
        columns=["powertrain", "size", "year", "parameter", "val", "ref_val", "diff"],
    ).to_excel(OUTPUT)
