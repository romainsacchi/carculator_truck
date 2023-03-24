"""
inventory.py contains Inventory which provides all methods to solve inventories.
"""

import numpy as np
from carculator_utils.inventory import Inventory

from . import DATA_DIR

np.warnings.filterwarnings("ignore", category=np.VisibleDeprecationWarning)

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

        :param array: :attr:`array` from :class:`CarModel` class
        """

        # Glider/Frame
        self.A[
            :,
            self.find_input_indices(("frame, blanks and saddle, for lorry",)),
            self.find_input_indices(("Truck, ",)),
        ] = (
            self.array[self.array_inputs["glider base mass"]] * -1
        )

        # Suspension + Brakes
        self.A[
            :,
            self.find_input_indices(("suspension, for lorry",)),
            self.find_input_indices(("Truck, ",)),
        ] = (
            self.array[
                [
                    self.array_inputs["suspension mass"],
                    self.array_inputs["braking system mass"],
                ],
                :,
            ].sum(axis=0)
            * -1
        )

        # Wheels and tires
        self.A[
            :,
            self.find_input_indices(("tires and wheels, for lorry",)),
            self.find_input_indices(("Truck, ",)),
        ] = (
            self.array[self.array_inputs["wheels and tires mass"], :] * -1
        )

        # Exhaust
        self.A[
            :,
            self.find_input_indices(("exhaust system, for lorry",)),
            self.find_input_indices(("Truck, ",)),
        ] = (
            self.array[self.array_inputs["exhaust system mass"], :] * -1
        )

        # Electrical system
        self.A[
            :,
            self.find_input_indices(("power electronics, for lorry",)),
            self.find_input_indices(("Truck, ",)),
        ] = (
            self.array[self.array_inputs["electrical system mass"], :] * -1
        )

        # Transmission (52% transmission shaft, 36% gearbox + 12% retarder)
        self.A[
            :,
            self.find_input_indices(("transmission, for lorry",)),
            self.find_input_indices(("Truck, ",)),
        ] = (
            self.array[self.array_inputs["transmission mass"], :] * 0.52 * -1
        )

        self.A[
            :,
            self.find_input_indices(("gearbox, for lorry",)),
            self.find_input_indices(("Truck, ",)),
        ] = (
            self.array[self.array_inputs["transmission mass"], :] * 0.36 * -1
        )

        self.A[
            :,
            self.find_input_indices(("retarder, for lorry",)),
            self.find_input_indices(("Truck, ",)),
        ] = (
            self.array[self.array_inputs["transmission mass"], :] * 0.12 * -1
        )

        # Other components, for non-electric and hybrid trucks
        index = self.get_index_vehicle_from_array(["ICEV-d", "HEV-d", "ICEV-g"])

        self.A[
            :,
            self.find_input_indices(("other components, for hybrid electric lorry",)),
            self.find_input_indices(
                contains=("Truck, ",), excludes=("BEV", "FCEV", "PHEV")
            ),
        ] = (
            self.array[self.array_inputs["other components mass"], :, index] * -1
        )

        # Other components, for electric trucks
        index = self.get_index_vehicle_from_array(["BEV", "FCEV"])

        self.A[
            :,
            self.find_input_indices(("other components, for electric lorry",)),
            self.find_input_indices(contains=("Truck, ",), excludes=("ICEV", "HEV")),
        ] = (
            self.array[self.array_inputs["other components mass"], :, index] * -1
        )

        self.A[
            :,
            self.find_input_indices(("Glider lightweighting",)),
            self.find_input_indices(contains=("Truck, ",)),
        ] = (
            self.array[self.array_inputs["lightweighting"], :]
            * self.array[self.array_inputs["glider base mass"], :]
            * -1
        )

        index_arr_16t = self.get_index_vehicle_from_array(["3.5t", "7.5t", "18t"])

        index_arr_28t = self.get_index_vehicle_from_array(["26t", "32t"])

        index_arr_40t = self.get_index_vehicle_from_array(["40t", "60t"])

        self.A[
            :,
            self.find_input_indices(contains=("maintenance, lorry 16 metric ton",)),
            self.find_input_indices(
                contains=("Truck, ",), excludes=("26t", "32t", "40t", "60t")
            ),
        ] = -1 * (
            self.array[self.array_inputs["gross mass"], :, index_arr_16t] / 1000 / 16
        )

        self.A[
            :,
            self.find_input_indices(contains=("maintenance, lorry 28 metric ton",)),
            self.find_input_indices(
                contains=("Truck, ",), excludes=("3.5t", "7.5t", "18t", "40t", "60t")
            ),
        ] = -1 * (
            self.array[self.array_inputs["gross mass"], :, index_arr_28t] / 1000 / 28
        )

        self.A[
            :,
            self.find_input_indices(contains=("maintenance, lorry 40 metric ton",)),
            self.find_input_indices(
                contains=("Truck, ",), excludes=("3.5t", "7.5t", "18t", "26t", "32t")
            ),
        ] = -1 * (
            self.array[self.array_inputs["gross mass"], :, index_arr_40t] / 1000 / 40
        )

        # Electric powertrain components
        self.A[
            :,
            self.find_input_indices(
                ("market for converter, for electric passenger car",)
            ),
            self.find_input_indices(contains=("Truck, ",)),
        ] = (
            self.array[self.array_inputs["converter mass"], :] * -1
        )

        self.A[
            :,
            self.find_input_indices(
                ("market for electric motor, electric passenger car",)
            ),
            self.find_input_indices(contains=("Truck, ",)),
        ] = (
            self.array[self.array_inputs["electric engine mass"], :] * -1
        )

        self.A[
            :,
            self.find_input_indices(
                ("market for inverter, for electric passenger car",)
            ),
            self.find_input_indices(contains=("Truck, ",)),
        ] = (
            self.array[self.array_inputs["inverter mass"], :] * -1
        )

        self.A[
            :,
            self.find_input_indices(
                ("market for power distribution unit, for electric passenger car",)
            ),
            self.find_input_indices(contains=("Truck, ",)),
        ] = (
            self.array[self.array_inputs["power distribution unit mass"], :] * -1
        )

        self.A[
            :,
            self.find_input_indices(("internal combustion engine, for lorry",)),
            self.find_input_indices(contains=("Truck, ",)),
        ] = (
            self.array[
                self.array_inputs["combustion engine mass"],
                :,
            ].sum(axis=0)
            * -1
        )

        # Energy storage
        self.add_fuel_cell_stack()
        self.add_hydrogen_tank()
        self.add_battery()

        # Use the inventory of Wolff et al. 2020 for
        # lead acid battery for non-electric
        # and non-hybrid trucks

        index = self.get_index_vehicle_from_array(["ICEV-d", "ICEV-g"])

        self.A[
            :,
            self.find_input_indices(("lead acid battery, for lorry",)),
            self.find_input_indices(contains=("Truck, ", "ICEV")),
        ] = (
            self.array[
                [
                    self.array_inputs[x]
                    for x in ["battery BoP mass", "battery cell mass"]
                ],
                :,
                index,
            ].sum(dim="parameter")
            * (
                1
                + self.array[
                    self.array_inputs["battery lifetime replacements"], :, index
                ]
            )
        ) * -1

        # Fuel tank for diesel trucks
        index = self.get_index_vehicle_from_array(["ICEV-d", "HEV-d", "PHEV-d"])

        self.A[
            :,
            self.find_input_indices(("fuel tank, for diesel vehicle",)),
            self.find_input_indices(
                contains=("Truck, ", "EV-d"), excludes=("battery",)
            ),
        ] = (
            self.array[self.array_inputs["fuel tank mass"], :, index] * -1
        )

        self.add_cng_tank()

        # End-of-life disposal and treatment

        self.A[
            :,
            self.find_input_indices(
                contains=("treatment of used lorry, 16 metric ton",)
            ),
            self.find_input_indices(
                contains=("Truck, ",), excludes=("26t", "32t", "40t", "60t")
            ),
        ] = 1 * (
            self.array[self.array_inputs["gross mass"], :, index_arr_16t] / 1000 / 16
        )

        self.A[
            :,
            self.find_input_indices(
                contains=("treatment of used lorry, 28 metric ton",)
            ),
            self.find_input_indices(
                contains=("Truck, ",), excludes=("3.5t", "7.5t", "18t", "40t", "60t")
            ),
        ] = 1 * (
            self.array[self.array_inputs["gross mass"], :, index_arr_28t] / 1000 / 28
        )

        self.A[
            :,
            self.find_input_indices(
                contains=("treatment of used lorry, 40 metric ton",)
            ),
            self.find_input_indices(
                contains=("Truck, ",), excludes=("3.5t", "7.5t", "18t", "26t", "32t")
            ),
        ] = 1 * (
            self.array[self.array_inputs["gross mass"], :, index_arr_40t] / 1000 / 40
        )

        # END of vehicle building

        # Add vehicle dataset to transport dataset
        self.add_vehicle_to_transport_dataset()

        self.display_renewable_rate_in_mix()

        self.add_electricity_to_electric_vehicles()

        self.add_hydrogen_to_fuel_cell_vehicles()

        self.add_fuel_to_vehicles("cng", ["ICEV-g"], "EV-g")

        for year in self.scope["year"]:
            cng_idx = self.get_index_vehicle_from_array(
                ["ICEV-g"], [year], method="and"
            )

            self.A[
                :,
                self.find_input_indices(("fuel supply for cng vehicles", str(year))),
                self.find_input_indices(
                    (f"transport, {self.vm.vehicle_type}, ", "ICEV-g", str(year))
                ),
            ] *= (
                1
                + self.array[self.array_inputs["CNG pump-to-tank leakage"], :, cng_idx]
            )

            # Gas leakage to air
            self.A[
                :,
                self.inputs[("Methane, fossil", ("air",), "kilogram")],
                self.find_input_indices(
                    (
                        f"transport, {self.vm.vehicle_type}, ",
                        "ICEV-g",
                        str(year),
                    )
                ),
            ] *= self.array[self.array_inputs["CNG pump-to-tank leakage"], :, cng_idx]

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
        # Hence, we calculate the lifetime of the bus
        # We assume two trucks per charging station

        index = self.get_index_vehicle_from_array(
            ["BEV", "PHEV-d"],
        )

        self.A[
            np.ix_(
                np.arange(self.iterations),
                self.find_input_indices(("EV charger, level 3, plugin, 200 kW",)),
                self.find_input_indices(
                    contains=("Truck, "), excludes=("ICEV", "FCEV", " HEV")
                ),
            )
        ] = (
            -1
            / (
                24
                * (
                    2100
                    / self.array[self.array_inputs["electric energy stored"], :, index]
                )
                * self.array[self.array_inputs["kilometers per year"], :, index]
            )
        ).values[
            :, np.newaxis, :
        ]

        print("*********************************************************************")
