import numpy as np
import pytest
from carculator_utils.array import fill_xarray_from_input_parameters

from carculator_truck import InventoryTruck, TruckInputParameters, TruckModel

tip = TruckInputParameters()
tip.static()
_, array = fill_xarray_from_input_parameters(
    tip, scope={"size": ["40t", "60t"], "powertrain": ["ICEV-d", "BEV"]}
)
tm = TruckModel(array, cycle="Long haul", country="CH")
tm.set_all()


def test_check_country():
    # Ensure that country specified in TruckModel equals country in InventoryTruck
    ic = InventoryTruck(tm)
    assert tm.country == ic.vm.country


def test_electricity_mix():
    # Electricity mix must be equal to 1
    ic = InventoryTruck(tm)
    assert np.allclose(np.sum(ic.mix, axis=1), [1.0, 1.0, 1.0, 1.0, 1.0, 1.0])

    # If we pass a custom electricity mix, check that it is used
    custom_mix = [
        [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    ]

    bc = {"custom electricity mix": custom_mix}
    ic = InventoryTruck(tm, background_configuration=bc)

    assert np.allclose(ic.mix, custom_mix)


def test_scope():
    """Test if scope works as expected"""
    ic = InventoryTruck(
        tm,
        method="recipe",
        indicator="midpoint",
    )
    results = ic.calculate_impacts()

    assert "32t" not in results.coords["size"].values
    assert "ICEV-g" not in results.coords["powertrain"].values


def test_fuel_blend():
    """Test if fuel blends defined by the user are considered"""

    fb = {
        "diesel": {
            "primary": {
                "type": "diesel",
                "share": [0.93, 0.93, 0.93, 0.93, 0.93, 0.93],
            },
            "secondary": {
                "type": "biodiesel - cooking oil",
                "share": [0.07, 0.07, 0.07, 0.07, 0.07, 0.07],
            },
        },
        "cng": {
            "primary": {
                "type": "biogas - sewage sludge",
                "share": [1, 1, 1, 1, 1, 1],
            }
        },
    }

    tm = TruckModel(array, cycle="Long haul", country="CH", fuel_blend=fb)
    tm.set_all()

    ic = InventoryTruck(tm, method="recipe", indicator="midpoint")

    assert np.allclose(
        tm.fuel_blend["diesel"]["primary"]["share"],
        [0.93, 0.93, 0.93, 0.93, 0.93, 0.93],
    )
    assert np.allclose(
        tm.fuel_blend["diesel"]["secondary"]["share"],
        [0.07, 0.07, 0.07, 0.07, 0.07, 0.07],
    )
    assert np.allclose(tm.fuel_blend["cng"]["primary"]["share"], [1, 1, 1, 1, 1, 1])
    # assert np.sum(ic.fuel_blends["cng"]["secondary"]["share"]) == 0

    ic.calculate_impacts()

    for fuels in [
        ("diesel", "electrolysis", "cng"),
        (
            "biodiesel - palm oil",
            "smr - natural gas",
            "biogas - sewage sludge",
        ),
        (
            "biodiesel - rapeseed oil",
            "smr - natural gas with CCS",
            "biogas - biowaste",
        ),
        (
            "biodiesel - cooking oil",
            "wood gasification with EF with CCS",
            "biogas - biowaste",
        ),
        (
            "biodiesel - algae",
            "atr - biogas",
            "biogas - biowaste",
        ),
        (
            "synthetic diesel - energy allocation",
            "wood gasification with EF with CCS",
            "syngas",
        ),
    ]:
        fb = {
            "diesel": {
                "primary": {"type": fuels[0], "share": [1, 1, 1, 1, 1, 1]},
            },
            "hydrogen": {"primary": {"type": fuels[1], "share": [1, 1, 1, 1, 1, 1]}},
            "cng": {"primary": {"type": fuels[2], "share": [1, 1, 1, 1, 1, 1]}},
        }

        tm = TruckModel(array, cycle="Long haul", country="CH", fuel_blend=fb)
        tm.set_all()
        ic = InventoryTruck(tm, method="recipe", indicator="midpoint")
        ic.calculate_impacts()


def test_countries():
    """Test that calculation works with all countries"""
    for c in ["AO", "AT", "AU"]:
        tm.country = c
        ic = InventoryTruck(
            tm,
            method="recipe",
            indicator="midpoint",
        )
        ic.calculate_impacts()


def test_endpoint():
    """Test if the correct impact categories are considered"""
    ic = InventoryTruck(tm, method="recipe", indicator="endpoint")
    results = ic.calculate_impacts()
    assert "human health" in [i.lower() for i in results.impact_category.values]
    assert len(results.impact_category.values) == 4

    """Test if it errors properly if an incorrect method type is give"""
    with pytest.raises(ValueError) as wrapped_error:
        ic = InventoryTruck(tm, method="recipe", indicator="endpint")
        ic.calculate_impacts()
    assert wrapped_error.type == ValueError


def test_sulfur_concentration():
    ic = InventoryTruck(tm, method="recipe", indicator="endpoint")
    ic.get_sulfur_content("RER", "diesel", 2000)
    ic.get_sulfur_content("foo", "diesel", 2000)

    with pytest.raises(ValueError) as wrapped_error:
        ic.get_sulfur_content("FR", "diesel", "jku")
    assert wrapped_error.type == ValueError


def test_custom_electricity_mix():
    """Test if a wrong number of electricity mixes throws an error"""

    # Passing four mixes instead of 6
    mix_1 = np.zeros((4, 21))
    mix_1[:, 0] = 1
    # Passing a mix inferior to 1
    mix_2 = np.zeros((6, 21))
    mix_2[:, 0] = 0.9

    # Passing a mix superior to 1
    mix_3 = np.zeros((6, 21))
    mix_3[:, 0] = 1
    mix_3[:, 1] = 0.1

    mixes = [mix_1, mix_2, mix_3]

    for i, mix in enumerate(mixes):
        if i == 0:
            with pytest.raises(ValueError) as wrapped_error:
                ic = InventoryTruck(
                    tm,
                    method="recipe",
                    indicator="endpoint",
                    background_configuration={"custom electricity mix": mix},
                )
            assert wrapped_error.type == ValueError

        else:
            InventoryTruck(
                tm,
                method="recipe",
                indicator="endpoint",
                background_configuration={"custom electricity mix": mix},
            )


def test_export_lci():
    """Test that inventories export successfully"""
    ic = InventoryTruck(tm, method="recipe", indicator="midpoint")
    for b in ("3.5", "3.6", "3.7", "3.8"):
        for s in ("brightway2", "simapro"):
            for f in ("file", "string", "bw2io"):
                ic.export_lci(
                    ecoinvent_version=b,
                    software=s,
                    format=f,
                )


# # GHG of 40t diesel truck must be between 80 and 110 g/ton-km in 2020
#
# # Only three impact categories are available for recipe 2008 endpoint
#
# # GHG emissions of 7.5t trucks must be superior to that of 40t trucks
#
# # GHG intensity of EU electricity in 2020 must be between 300 and 400 g/kWh
#
# # GHG intensity of 1 kWh of solar PV must be between 50 and 100 g
#
# # GHG intensity of 1 ton-km from FCEV truck mus tbe between X and Y
