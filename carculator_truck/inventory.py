"""
inventory.py contains Inventory which provides all methods to solve inventories.
"""

import warnings

import numpy as np
from carculator_utils.inventory import Inventory

from . import DATA_DIR

warnings.filterwarnings("ignore", category=np.VisibleDeprecationWarning)

IAM_FILES_DIR = DATA_DIR / "IAM"


class InventoryTruck(Inventory):
    """
    Build and solve the inventory for results
    characterization and inventory export

    """

    def fill_in_A_matrix(self):
        """
        Fill-in the A matrix. Does not return anything. Modifies in place.
        Shape of the A matrix (values, products, activities).

        :attr:`array` from :class:`CarModel` class
        """

        # Assembly
        self.A[
            :,
            self.find_input_indices(("assembly operation, for lorry",)),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = (
            self.array.sel(parameter="curb mass") * -1
        )

        # Glider/Frame
        self.A[
            :,
            self.find_input_indices(("frame, blanks and saddle, for lorry",)),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = (
            self.array.sel(parameter="glider base mass") * -1
        )

        # Suspension + Brakes
        self.A[
            :,
            self.find_input_indices(("suspension, for lorry",)),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = (
            self.array.sel(
                parameter=[
                    "suspension mass",
                    "braking system mass",
                ]
            ).sum(dim="parameter")
            * -1
        )

        # Wheels and tires
        self.A[
            :,
            self.find_input_indices(("tires and wheels, for lorry",)),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = (
            self.array.sel(parameter="wheels and tires mass") * -1
        )

        # Exhaust
        self.A[
            :,
            self.find_input_indices(("exhaust system, for lorry",)),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = (
            self.array.sel(parameter="exhaust system mass") * -1
        )

        # Electrical system
        self.A[
            :,
            self.find_input_indices(("power electronics, for lorry",)),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = (
            self.array.sel(parameter="electrical system mass") * -1
        )

        # Transmission (52% transmission shaft, 36% gearbox + 12% retarder)
        self.A[
            :,
            self.find_input_indices(("transmission, for lorry",)),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = (
            self.array.sel(parameter="transmission mass") * 0.52 * -1
        )

        self.A[
            :,
            self.find_input_indices(("gearbox, for lorry",)),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = (
            self.array.sel(parameter="transmission mass") * 0.36 * -1
        )

        self.A[
            :,
            self.find_input_indices(("retarder, for lorry",)),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = (
            self.array.sel(parameter="transmission mass") * 0.12 * -1
        )

        # Other components, for non-electric and hybrid trucks

        self.A[
            :,
            self.find_input_indices(("other components, for hybrid electric lorry",)),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = (
            self.array.sel(parameter="other components mass")
            * (self.array.sel(parameter="combustion power") > 0)
            * -1
        )

        # Other components, for electric trucks
        self.A[
            :,
            self.find_input_indices(("other components, for electric lorry",)),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = (
            self.array.sel(parameter="other components mass")
            * (self.array.sel(parameter="combustion power") == 0)
            * -1
        )

        self.A[
            :,
            self.find_input_indices(("glider lightweighting",)),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = (
            self.array.sel(parameter="lightweighting")
            * self.array.sel(parameter="glider base mass")
            * -1
        )

        self.A[
            :,
            self.find_input_indices(
                contains=("maintenance, lorry 16 metric ton",),
                excludes=("CH",),
                excludes_in=1,
            ),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = -1 * (
            self.array.sel(parameter="gross mass")
            * (self.array.sel(parameter="gross mass") < 26000)
            / 1000
            / 16
        )

        self.A[
            :,
            self.find_input_indices(contains=("maintenance, lorry 28 metric ton",)),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = -1 * (
            self.array.sel(parameter="gross mass")
            * np.where(self.array.sel(parameter="gross mass") < 26000, 0, 1)
            * np.where(self.array.sel(parameter="gross mass") >= 40000, 0, 1)
            / 1000
            / 28
        )

        self.A[
            :,
            self.find_input_indices(contains=("maintenance, lorry 40 metric ton",)),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = -1 * (
            self.array.sel(parameter="gross mass")
            * (self.array.sel(parameter="gross mass") >= 40000)
            / 1000
            / 40
        )

        # Electric powertrain components
        self.A[
            :,
            self.find_input_indices(
                ("market for converter, for electric passenger car",)
            ),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = (
            self.array.sel(parameter="converter mass") * -1
        )

        self.A[
            :,
            self.find_input_indices(
                ("market for electric motor, electric passenger car",)
            ),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = (
            self.array.sel(parameter="electric engine mass") * -1
        )

        self.A[
            :,
            self.find_input_indices(
                ("market for inverter, for electric passenger car",)
            ),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = (
            self.array.sel(parameter="inverter mass") * -1
        )

        self.A[
            :,
            self.find_input_indices(
                ("market for power distribution unit, for electric passenger car",)
            ),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = (
            self.array.sel(parameter="power distribution unit mass") * -1
        )

        self.A[
            :,
            self.find_input_indices(("internal combustion engine, for lorry",)),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = (
            self.array.sel(parameter="combustion engine mass") * -1
        )

        # Energy storage
        self.add_fuel_cell_stack()
        self.add_hydrogen_tank()
        self.add_battery()

        # Use the inventory of Wolff et al. 2020 for
        # lead acid battery for non-electric
        # and non-hybrid trucks
        self.A[
            :,
            self.find_input_indices(("lead acid battery, for lorry",)),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = (
            16.0  # kg/battery
            * (
                self.array.sel(parameter="lifetime kilometers")
                / self.array.sel(parameter="kilometers per year")
                / 5  # years
            )
            * (self.array.sel(parameter="combustion power") > 0)
        ) * -1

        # Fuel tank for diesel trucks
        self.A[
            :,
            self.find_input_indices(("fuel tank, for diesel vehicle",)),
            [
                j
                for i, j in self.inputs.items()
                if i[0].startswith("truck, ")
                and "EV-d" in i[0]
                and "battery" not in i[0]
            ],
        ] = (
            self.array.sel(
                parameter="fuel tank mass",
                combined_dim=[
                    d
                    for d in self.array.coords["combined_dim"].values
                    if any(x in d for x in ["ICEV-d", "HEV-d"])
                ],
            )
            * -1
        )

        self.add_cng_tank()

        # End-of-life disposal and treatment

        self.A[
            :,
            self.find_input_indices(
                contains=("treatment of used lorry, 16 metric ton",)
            ),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = 1 * (
            self.array.sel(parameter="gross mass")
            * (self.array.sel(parameter="gross mass") < 26000)
            / 1000
            / 16
        )

        self.A[
            :,
            self.find_input_indices(
                contains=("treatment of used lorry, 28 metric ton",)
            ),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = -1 * (
            self.array.sel(parameter="gross mass")
            * np.where(self.array.sel(parameter="gross mass") < 26000, 0, 1)
            * np.where(self.array.sel(parameter="gross mass") >= 40000, 0, 1)
            / 1000
            / 28
        )

        self.A[
            :,
            self.find_input_indices(
                contains=("treatment of used lorry, 40 metric ton",)
            ),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = -1 * (
            self.array.sel(parameter="gross mass")
            * (self.array.sel(parameter="gross mass") >= 40000)
            / 1000
            / 40
        )

        # END of vehicle building

        # Add vehicle dataset to transport dataset
        self.add_vehicle_to_transport_dataset()

        self.display_renewable_rate_in_mix()

        self.add_electricity_to_electric_vehicles()

        self.add_hydrogen_to_fuel_cell_vehicles()

        self.add_fuel_to_vehicles("methane", ["ICEV-g"], "EV-g")

        # CNG pump-to-tank leakage
        self.A[
            :,
            self.find_input_indices(("fuel supply for methane vehicles",)),
            self.find_input_indices((f"transport, {self.vm.vehicle_type}, ",)),
        ] *= 1 + self.array.sel(parameter="CNG pump-to-tank leakage")

        # Gas leakage to air
        self.A[
            :,
            self.inputs[("Methane, fossil", ("air",), "kilogram")],
            self.find_input_indices((f"transport, {self.vm.vehicle_type}",)),
        ] *= 1 + self.array.sel(parameter="CNG pump-to-tank leakage")

        self.add_fuel_to_vehicles("diesel", ["ICEV-d", "PHEV-d", "HEV-d"], "EV-d")

        self.add_abrasion_emissions()

        self.add_road_construction()

        self.add_road_maintenance()

        self.add_exhaust_emissions()

        self.add_noise_emissions()

        self.add_refrigerant_emissions()

        # Charging infrastructure
        # Plugin BEV trucks
        # The charging station has a lifetime of 24 years
        # Hence, we calculate the lifetime of the truck
        # We assume two trucks per charging station

        self.A[
            np.ix_(
                np.arange(self.iterations),
                self.find_input_indices(
                    ("EV charger, level 3, plugin, 200 kW",),
                ),
                [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
            )
        ] = (
            -1
            / (
                self.array.sel(
                    parameter=["kilometers per year"],
                )
                * 2
                * 24
            )
        ) * (
            self.array.sel(parameter="combustion power") == 0
        )

        print("*********************************************************************")
