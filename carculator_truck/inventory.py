"""
inventory.py contains Inventory which provides all methods to solve inventories.
"""

import numpy as np
import xarray as xr
from carculator_utils.inventory import Inventory

from . import DATA_DIR
from .infrastructure import annual_charger_throughput

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
                excludes=("Europe without Switzerland",),
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
        starter_packs = (
            self.array.sel(parameter="lifetime kilometers")
            / self.array.sel(parameter="kilometers per year")
            / 5  # years, retained starter-battery lifetime
        )
        starter_mass = xr.where(
            self.array.combined_dim.str.endswith(" - HEV-d"),
            self.array.sel(parameter="starter battery mass")
            * starter_packs.clip(min=1),
            16.0 * starter_packs,
        ).transpose("value", "combined_dim", "year")
        self.A[
            :,
            self.find_input_indices(("lead acid battery, for lorry",)),
            [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
        ] = (starter_mass * (self.array.sel(parameter="combustion power") > 0)) * -1

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
        # Used lorries leave the vehicle as waste: positive matrix outputs,
        # exported as negative Brightway technosphere exchanges in every class.

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
        ] = 1 * (
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
        ] = 1 * (
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
        self.add_methane_leakage()

        self.add_fuel_to_vehicles("diesel", ["ICEV-d", "PHEV-d", "HEV-d"], "EV-d")

        self.add_abrasion_emissions()

        self.add_road_construction()

        self.add_road_maintenance()

        self.add_exhaust_emissions()

        self.add_noise_emissions()

        self.add_refrigerant_emissions()

        self.add_depot_chargers()
        print("*********************************************************************")

    def add_depot_chargers(self):
        """Allocate the 200-kW charger reference over lifetime grid throughput."""
        # Work in the same labelled order as the vehicle columns in the matrix.
        powertrains = xr.DataArray(
            [label.rsplit(" - ", 1)[1] for label in self.array.combined_dim.values],
            dims="combined_dim",
            coords={"combined_dim": self.array.combined_dim},
        )
        available = (self.array.sel(parameter="TtW energy") > 0) & powertrains.isin(
            ["BEV", "PHEV-d", "PHEV-e"]
        )

        def checked(parameter, mask, minimum=0, maximum=None, positive=False):
            value = self.array.sel(parameter=parameter, drop=True)
            invalid = ~np.isfinite(value) | (
                value <= minimum if positive else value < minimum
            )
            if maximum is not None:
                invalid |= value > maximum
            invalid &= mask
            if bool(invalid.any()):
                position = np.argwhere(invalid.values)[0]
                coords = {
                    dim: invalid[dim].isel({dim: int(i)}).item()
                    for dim, i in zip(invalid.dims, position)
                }
                raise ValueError(
                    f"Invalid {parameter!r} for depot charging at {coords}."
                )
            return value

        grid = checked("electricity consumption", available)
        share = checked("share depot charging", available, maximum=1)
        active = available & (grid > 0) & (share > 0)
        power = checked("depot charger power", active, positive=True).where(active, 0)
        life = checked("depot charger lifetime", active, positive=True).where(active, 1)
        trucks = checked("trucks per depot charger", active, positive=True).where(
            active, 1
        )
        annual_km = checked("kilometers per year", active, positive=True).where(
            active, 1
        )
        lifetime_km = checked("lifetime kilometers", active, positive=True).where(
            active, 0
        )
        uf = checked(
            "electric utility factor",
            active & (powertrains == "PHEV-d"),
            maximum=1,
            positive=True,
        )
        uf = xr.where(active & (powertrains == "PHEV-d"), uf, 1)
        grid = grid.where(active, 0)
        # Combined PHEV grid purchases already include the electric-driving share.
        # Recover mode throughput, then apply the share once via those purchases.
        throughput = annual_charger_throughput(power, trucks, annual_km, grid / uf)
        quantity = (
            power
            / 200
            / life
            / throughput.where(active, 1)
            * grid
            * share.where(active, 0)
            * lifetime_km
        )
        if not bool(np.isfinite(quantity).all()):
            raise ValueError(
                "Nonfinite depot charger allocation from active charging inputs."
            )
        # Per vehicle here; the vehicle-to-transport exchange and functional-unit
        # normalization subsequently allocate this over lifetime km and cargo.
        self.A[
            np.ix_(
                np.arange(self.iterations),
                self.find_input_indices(("EV charger, level 3, plugin, 200 kW",)),
                [j for i, j in self.inputs.items() if i[0].startswith("truck, ")],
            )
        ] = -quantity.transpose("value", "combined_dim", "year").values[:, None, :, :]
