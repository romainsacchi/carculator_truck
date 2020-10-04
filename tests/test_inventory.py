from carculator_truck import *
import numpy as np

tip = TruckInputParameters()
tip.static()
_, array = fill_xarray_from_input_parameters(tip)
tm = TruckModel(array, cycle="Long haul", country="CH")
tm.set_all()


def test_check_country():
    # Ensure that country specified in TruckModel equals country in InventoryCalculation
    ic = InventoryCalculation(tm)
    assert tm.country == ic.country

def test_electricity_mix():
    # Electricity mix must be equal to 1
    ic = InventoryCalculation(tm)
    assert np.allclose(np.sum(ic.mix, axis=1), [1., 1., 1., 1., 1., 1.])

    # If we pass a custom electricity mix, check that it is used
    custom_mix = [
        [1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
    ]

    bc = {"custom electricity mix": custom_mix}
    ic = InventoryCalculation(tm, background_configuration=bc)

    assert np.allclose(ic.mix, custom_mix)




# GHG of 40t diesel truck must be between 80 and 110 g/ton-km in 2020

# Only three impact categories are available for recipe 2008 endpoint

# GHG emissions of 7.5t trucks must be superior to that of 40t trucks

# GHG intensity of EU electricity in 2020 must be between 300 and 400 g/kWh

# GHG intensity of 1 kWh of solar PV must be between 50 and 100 g

# GHG intensity of 1 ton-km from FCEV truck mus tbe between X and Y
