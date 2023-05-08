import warnings
from itertools import product

import numexpr as ne
import numpy as np
import xarray as xr
import yaml
from carculator_utils.energy_consumption import (
    EnergyConsumptionModel,
    get_default_driving_cycle_name,
)
from carculator_utils.model import VehicleModel
from prettytable import PrettyTable

from . import DATA_DIR

warnings.simplefilter(action="ignore", category=FutureWarning)

CARGO_MASSES = DATA_DIR / "payloads.yaml"


def finite(array, mask_value=0):
    return np.where(np.isfinite(array), array, mask_value)


class TruckModel(VehicleModel):

    """
    This class represents the entirety of the vehicles considered, with useful attributes, such as an array that stores
    all the vehicles parameters.

    :ivar array: multi-dimensional numpy-like array that contains parameters' value(s)
    :vartype array: xarray.DataArray
    :ivar mappings: Dictionary with names correspondence
    :vartype mappings: dict
    :ivar ecm: instance of :class:`EnergyConsumptionModel` class for a given driving cycle
    :vartype ecm: coarse.energy_consumption.EnergyConsumptionModel

    """

    def set_all(self, electric_utility_factor: float = None):
        """
        This method runs a series of other methods to obtain the tank-to-wheel energy requirement,
        efficiency of the vehicle, costs, etc.

        :meth:`set_component_masses()`, :meth:`set_vehicle_masses()` and :meth:`set_power_parameters()` and
         :meth:`set_energy_stored_properties` relate to one another.
        `powertrain_mass` depends on `power`, `curb_mass` is affected by changes in `powertrain_mass`,
        `combustion engine mass`, `electric engine mass`. `energy battery mass` is influenced
        by the `curb mass` but also
        by the `target range` the truck has. `power` is also varying with `curb_mass`.

        The current solution is to loop through the methods until the change in payload between
        two iterations is
        inferior to 0.1%. It is then assumed that the trucks are correctly sized.

        :returns: Does not return anything. Modifies ``self.array`` in place.

        """

        diff = 1.0

        self["is_compliant"] = True
        self["is_available"] = True

        self.set_cargo_mass_and_annual_mileage()

        self.ecm = EnergyConsumptionModel(
            vehicle_type="truck",
            vehicle_size=self.array.coords["size"].values.tolist(),
            cycle=self.cycle,
            gradient=self.gradient,
            country=self.country,
            powertrains=self.array.coords["powertrain"].values.tolist(),
        )

        print("Finding solutions for trucks...")
        self.override_range()

        while abs(diff) > 0.01:
            old_payload = self["available payload"].sum().values

            if self.target_mass:
                self.override_vehicle_mass()
            else:
                self.set_vehicle_masses()

            self.set_power_parameters()
            self.set_fuel_cell_power()
            self.set_fuel_cell_mass()

            self.set_component_masses()
            self.set_auxiliaries()
            self.set_recuperation()

            self.set_ttw_efficiency()
            self.calculate_ttw_energy()

            self.set_share_recuperated_energy()
            self.set_battery_fuel_cell_replacements()

            self.set_energy_stored_properties()
            self.set_power_battery_properties()
            self.set_vehicle_masses()

            diff = (self["available payload"].sum().values - old_payload) / self[
                "available payload"
            ].sum()

        self.adjust_cost()

        self.set_electric_utility_factor(electric_utility_factor)
        self.set_electricity_consumption()
        self.set_costs()
        self.set_particulates_emission()
        self.set_noise_emissions()
        self.set_hot_emissions()
        self.create_PHEV()
        if self.drop_hybrids:
            self.drop_hybrid()

        self.remove_energy_consumption_from_unavailable_vehicles()

    def set_cargo_mass_and_annual_mileage(self):
        """Set the cargo mass and annual mileage of the vehicles."""

        if self.payload:
            for s in self.array.coords["size"].values:
                for p in self.array.coords["powertrain"].values:
                    for y in self.array.coords["year"].values:
                        self.array.loc[
                            dict(size=s, powertrain=p, year=y, parameter="cargo mass")
                        ] = self.payload[(p, s, y)]
        else:
            with open(CARGO_MASSES, "r", encoding="utf-8") as stream:
                generic_payload = yaml.safe_load(stream)["payload"]

            for s in self.array.coords["size"].values:
                cycle = self.cycle if isinstance(self.cycle, str) else "Urban delivery"
                self.array.loc[dict(size=s, parameter="cargo mass")] = generic_payload[
                    cycle
                ][s]

        if self.annual_mileage:
            for s in self.array.coords["size"].values:
                for p in self.array.coords["powertrain"].values:
                    for y in self.array.coords["year"].values:
                        self.array.loc[
                            dict(
                                size=s,
                                powertrain=p,
                                year=y,
                                parameter="kilometers per year",
                            )
                        ] = self.annual_mileage[(p, s, y)]
        else:
            with open(CARGO_MASSES, "r", encoding="utf-8") as stream:
                annual_mileage = yaml.safe_load(stream)["annual mileage"]

            for s in self.array.coords["size"].values:
                cycle = self.cycle if isinstance(self.cycle, str) else "Urban delivery"
                self.array.loc[
                    dict(size=s, parameter="kilometers per year")
                ] = annual_mileage[cycle][s]

    def adjust_cost(self):
        """
        This method adjusts costs of energy storage over time, to correct for the overly optimistic linear
        interpolation between years.

        """

        n_iterations = self.array.shape[-1]
        n_year = len(self.array.year.values)

        # If uncertainty is not considered, teh cost factor equals 1.
        # Otherwise, a variability of +/-30% is added.

        if n_iterations == 1:
            cost_factor = 1

            # reflect a scaling effect for fuel cells
            # according to
            # FCEV trucks should cost the triple of an ICEV-d in 2020
            cost_factor_fcev = 5

        else:
            if "reference" in self.array.value.values.tolist():
                cost_factor = np.ones((n_iterations, 1))
                cost_factor_fcev = np.full((n_iterations, 1), 5)
            else:
                cost_factor = np.random.triangular(0.7, 1, 1.3, (n_iterations, 1))
                cost_factor_fcev = np.random.triangular(3, 5, 6, (n_iterations, 1))

        # Correction of hydrogen tank cost, per kg
        if "FCEV" in self.array.powertrain.values.tolist():
            self.array.loc[:, ["FCEV"], "fuel tank cost per kg", :, :] = np.reshape(
                (1.078e58 * np.exp(-6.32e-2 * self.array.year.values) + 3.43e2)
                * cost_factor_fcev,
                (1, 1, n_year, n_iterations),
            )

            # Correction of fuel cell stack cost, per kW
            self.array.loc[:, ["FCEV"], "fuel cell cost per kW", :, :] = np.reshape(
                (3.15e66 * np.exp(-7.35e-2 * self.array.year.values) + 2.39e1)
                * cost_factor_fcev,
                (1, 1, n_year, n_iterations),
            )

        # Correction of energy battery system cost, per kWh
        l_pwt = [
            p
            for p in self.array.powertrain.values
            if p in ["BEV", "PHEV-e", "PHEV-c-d"]
        ]

        if len(l_pwt) > 0:
            self.array.loc[:, l_pwt, "energy battery cost per kWh", :, :] = np.reshape(
                (2.75e86 * np.exp(-9.61e-2 * self.array.year.values) + 5.059e1)
                * cost_factor,
                (1, 1, n_year, n_iterations),
            )

        # Correction of power battery system cost, per kW
        l_pwt = [
            p
            for p in self.array.powertrain.values
            if p in ["ICEV-d", "ICEV-g", "PHEV-c-d", "FCEV", "HEV-d"]
        ]

        if len(l_pwt) > 0:
            self.array.loc[:, l_pwt, "power battery cost per kW", :, :] = np.reshape(
                (8.337e40 * np.exp(-4.49e-2 * self.array.year.values) + 11.17)
                * cost_factor,
                (1, 1, n_year, n_iterations),
            )

        # Correction of combustion powertrain cost for ICEV-g
        if "ICEV-g" in self.array.powertrain.values:
            self.array.loc[
                :,
                ["ICEV-g"],
                "combustion powertrain cost per kW",
                :,
                :,
            ] = np.reshape(
                (5.92e160 * np.exp(-0.1819 * self.array.year.values) + 26.76)
                * cost_factor,
                (1, 1, n_year, n_iterations),
            )

    def set_battery_chemistry(self):
        energy_storage = {
            "electric": {
                x: "NMC-622"
                for x in product(
                    ["BEV", "PHEV-e", "HEV-d", "FCEV"],
                    self.array.coords["size"].values,
                    self.array.year.values,
                )
            },
            "origin": "CN",
        }

        # override default values for batteries
        # if provided by the user

        if self.energy_storage is not None:
            energy_storage.update(self.energy_storage)

        self.energy_storage = energy_storage

    def override_range(self):
        """
        Set storage size or range for each powertrain.
        :return:
        """

        target_ranges = {
            "Urban delivery": 150,
            "Regional delivery": 400,
            "Long haul": 800,
        }

        if self.target_range is not None:
            target_range = self.target_range
        elif isinstance(self.cycle, str):
            target_range = target_ranges[self.cycle]
        else:
            target_range = 800

        self["target range"] = target_range

        # exception for PHEVs trucks
        # which are assumed ot eb able to drive 60 km in battery-depleting mode
        if "PHEV-e" in self.array.powertrain.values:
            self.array.loc[
                {
                    "powertrain": "PHEV-e",
                    "parameter": "target range",
                }
            ] = 60

        print(
            f"{self.cycle if isinstance(self.cycle, str) else 'A custom'} "
            f"driving cycle is selected. \n"
            f"Vehicles will be designed to achieve "
            f"a minimal range of {target_range} km."
        )

        print("")

    def calculate_ttw_energy(self):
        """
        This method calculates the energy required to operate
        auxiliary services as well as to move the vehicle.
        The sum is stored under the parameter label "TtW energy"
        in :attr:`self.array`.

        """

        self.energy = self.ecm.motive_energy_per_km(
            driving_mass=self["driving mass"],
            rr_coef=self["rolling resistance coefficient"],
            drag_coef=self["aerodynamic drag coefficient"],
            frontal_area=self["frontal area"],
            electric_motor_power=self["electric power"],
            engine_power=self["power"],
            recuperation_efficiency=self["recuperation efficiency"],
            aux_power=self["auxiliary power demand"],
            battery_charge_eff=self["battery charge efficiency"],
            battery_discharge_eff=self["battery discharge efficiency"],
            fuel_cell_system_efficiency=self["fuel cell system efficiency"],
        )

        self.energy = self.energy.assign_coords(
            {
                "powertrain": self.array.powertrain,
                "year": self.array.year,
                "size": self.array.coords["size"],
            }
        )

        if self.energy_consumption:
            self.override_ttw_energy()

        distance = self.energy.sel(parameter="velocity").sum(dim="second") / 1000

        # Correction for CNG trucks
        if "ICEV-g" in self.array.powertrain.values:
            self.energy.loc[
                dict(parameter="engine efficiency", powertrain="ICEV-g")
            ] *= (
                1
                - self.array.sel(
                    parameter="CNG engine efficiency correction factor",
                    powertrain="ICEV-g",
                )
            ).T.values

        self["TtW energy"] = (
            self.energy.sel(
                parameter=["motive energy", "auxiliary energy", "recuperated energy"]
            )
            .sum(dim=["second", "parameter"])
            .values
            / distance.values
        ).T

        self["engine efficiency"] = (
            np.ma.array(
                self.energy.loc[dict(parameter="engine efficiency")],
                mask=self.energy.loc[dict(parameter="power load")] == 0.0,
            )
            .mean(axis=0)
            .T
        )

        self["transmission efficiency"] = (
            np.ma.array(
                self.energy.loc[dict(parameter="transmission efficiency")],
                mask=self.energy.loc[dict(parameter="power load")] == 0.0,
            )
            .mean(axis=0)
            .T
        )

        self["TtW energy, combustion mode"] = self["TtW energy"] * (
            self["combustion power share"] > 0
        )
        self["TtW energy, electric mode"] = self["TtW energy"] * (
            self["combustion power share"] == 0
        )

        self["auxiliary energy"] = (
            self.energy.sel(parameter="auxiliary energy").sum(dim="second").values
            / distance.values
        ).T

    def set_battery_fuel_cell_replacements(self):
        """
        This methods calculates the number of replacement batteries needed
        to match the vehicle lifetime. Given the chemistry used,
        the cycle life is known. Given the lifetime kilometers and
        the kilometers per charge, the number of charge cycles can be inferred.

        If the battery lifetime surpasses the vehicle lifetime,
        100% of the burden of the battery production is allocated to the vehicle.
        Also, the number of replacement is rounded up.
        This means that the entirety of the battery replacement is allocated
        to the vehicle (and not to its potential second life).

        """
        # Number of replacement of battery is rounded *up*

        _ = lambda array: np.where(array == 0, 1, array)

        self["battery lifetime replacements"] = np.clip(
            (
                (self["lifetime kilometers"] * self["TtW energy"] / 3600)
                / _(self["electric energy stored"])
                / _(self["battery cycle life"])
                - 1
            ),
            1,
            3,
        ) * (self["charger mass"] > 0)

        # The number of fuel cell replacements is based on the
        # average distance driven with a set of fuel cells given
        # their lifetime expressed in hours of use.
        # The number of replacement is rounded *up* as we assume
        # no allocation of burden with a second life

        average_speed = (
            np.nanmean(
                np.where(
                    self.energy.sel(parameter="velocity") > 0,
                    self.energy.sel(parameter="velocity"),
                    np.nan,
                ),
                0,
            )
            * 3.6
        )

        self["fuel cell lifetime replacements"] = np.ceil(
            np.clip(
                self["lifetime kilometers"]
                / (average_speed.T * _(self["fuel cell lifetime hours"]))
                - 1,
                0,
                5,
            )
        ) * (self["fuel cell lifetime hours"] > 0)

    def set_vehicle_masses(self):
        """
        Define ``curb mass``, ``driving mass``, and ``cargo mass``.

            * `curb mass <https://en.wikipedia.org/wiki/Curb_weight>`__ is the mass of the vehicle and fuel, without people or cargo.
            * ``cargo mass`` is the mass of the cargo and passengers.
            * ``driving mass`` is the ``curb mass`` plus ``cargo mass``.

        .. note::
            driving mass = cargo mass + driving mass

        """

        # Base components, common to all powertrains
        base_components = [
            "glider base mass",
            "suspension mass",
            "braking system mass",
            "wheels and tires mass",
            "cabin mass",
            "electrical system mass",
            "other components mass",
            "transmission mass",
        ]

        self["curb mass"] = self[base_components].sum(axis=2) * (
            1 - self["lightweighting"]
        )

        curb_mass_includes = [
            "fuel mass",
            "charger mass",
            "converter mass",
            "inverter mass",
            "power distribution unit mass",
            # Updates with set_components_mass
            "combustion engine mass",
            # Updates with set_components_mass
            "electric engine mass",
            # Updates with set_components_mass
            "exhaust system mass",
            "fuel cell stack mass",
            "fuel cell ancillary BoP mass",
            "fuel cell essential BoP mass",
            "battery cell mass",
            "battery BoP mass",
            "fuel tank mass",
        ]
        self["curb mass"] += self[curb_mass_includes].sum(axis=2)

        self["total cargo mass"] = (
            self["average passengers"] * self["average passenger mass"]
        ) + self["cargo mass"]

        self["driving mass"] = (
            self["curb mass"]
            + self["cargo mass"]
            + (self["average passengers"] * self["average passenger mass"])
        )

        self["available payload"] = (
            self["gross mass"]
            - self["curb mass"]
            - (self["average passengers"] * self["average passenger mass"])
        )

        self["cargo mass"] = np.clip(self["cargo mass"], 0, self["available payload"])

        self["capacity utilization"] = np.clip(
            (self["cargo mass"] / self["available payload"]), 0, 1
        )

    def set_component_masses(self):
        self["combustion engine mass"] = (
            self["combustion power"] * self["engine mass per power"]
            + self["engine fixed mass"]
        )
        self["electric engine mass"] = np.clip(
            (24.56 * np.exp(0.0078 * self["electric power"])), 0, 600
        ) * (self["electric power"] > 0)

        self["transmission mass"] = (self["gross mass"] / 1000) * self[
            "transmission mass per ton of gross weight"
        ]

        self["inverter mass"] = (
            self["electric power"] * self["inverter mass per power"]
            + self["inverter fix mass"]
        )

    def set_electric_utility_factor(self, uf: float = None) -> None:
        """
        The electric utility factor
        is the share of km driven in battery-depleting mode
        over the required range autonomy.
        Scania's PHEV tractor can drive 60 km in electric mode
        :return:
        """
        if "PHEV-e" in self.array.coords["powertrain"].values:
            range = (
                self.array.loc[
                    dict(parameter="electric energy stored", powertrain="PHEV-e")
                ]
                * self.array.loc[dict(parameter="battery DoD", powertrain="PHEV-e")]
            ) / (
                self.array.loc[dict(parameter="TtW energy", powertrain="PHEV-e")]
                / 1000
                / 3.6
            )

            if uf is None:
                self.array.loc[
                    dict(powertrain="PHEV-e", parameter="electric utility factor")
                ] = (
                    range
                    / self.array.loc[
                        dict(powertrain="PHEV-c-d", parameter="target range")
                    ]
                )
            else:
                self.array.loc[
                    dict(powertrain="PHEV-e", parameter="electric utility factor")
                ] = uf

    def set_energy_stored_properties(self):
        """
        First, fuel mass is defined. It is dependent on the range required.
        Then batteries are sized, depending on the range
        required and the energy consumption.
        :return:
        """

        _ = lambda x: np.where(x == 0, 1, x)
        _nz = lambda x: np.where(x < 1, 1, x)

        self.set_average_lhv()

        self["fuel mass"] = (
            self["target range"]
            * self["TtW energy"]
            / 1000
            / _(self["LHV fuel MJ per kg"])
            * (self["LHV fuel MJ per kg"] > 0)
        )

        if "ICEV-g" in self.array.coords["powertrain"].values:
            # Based on manufacturer data
            # We use a four-cylinder configuration
            # Of 320L each
            # A cylinder of 320L @ 200 bar can hold 57.6 kg of CNG
            nb_cylinder = np.ceil(
                self.array.loc[dict(powertrain="ICEV-g", parameter="fuel mass")] / 57.6
            )

            self.array.loc[dict(powertrain="ICEV-g", parameter="fuel tank mass")] = (
                (0.018 * np.power(57.6, 2)) - (0.6011 * 57.6) + 52.235
            ) * nb_cylinder

        for pt in [
            pwt
            for pwt in ["ICEV-d", "HEV-d", "PHEV-c-d"]
            if pwt in self.array.coords["powertrain"].values
        ]:
            # From Wolff et al. 2020, Sustainability, DOI: 10.3390/su12135396.
            # We adjusted though the intercept from the original function (-54)
            # because we size here trucks based on the range autonomy
            # a low range autonomy would produce a negative fuel tank mass

            self.array.loc[dict(powertrain=pt, parameter="fuel tank mass")] = np.clip(
                17.159
                * np.log(
                    _nz(
                        self.array.loc[dict(powertrain=pt, parameter="fuel mass")]
                        * (1 / 0.832)
                    )
                )
                - 30,
                0,
                None,
            )

        if "FCEV" in self.array.coords["powertrain"].values:
            # Based on manufacturer data
            # We use a four-cylinder configuration
            # Of 650L each
            # A cylinder of 650L @ 700 bar can hold 14.4 kg of H2
            nb_cylinder = np.ceil(
                self.array.loc[dict(powertrain="FCEV", parameter="fuel mass")] / 14.4
            )

            self.array.loc[dict(powertrain="FCEV", parameter="fuel tank mass")] = (
                (
                    -0.1916
                    * np.power(
                        14.4,
                        2,
                    )
                )
                + (14.586 * 14.4)
                + 10.805
            ) * nb_cylinder

        self["oxidation energy stored"] = (
            self["fuel mass"] * self["LHV fuel MJ per kg"] / 3.6
        )

        self["electric energy stored"] = (
            self["target range"]
            * self["TtW energy"]
            / 1000
            / _(self["battery DoD"])
            / 3.6
            * (self["combustion power share"] == 0)
        )

        if "FCEV" in self.array.powertrain.values:
            # Fuel cell buses do also have a battery, which capacity
            # corresponds roughly to 6% of the capacity contained in the
            # H2 tank

            self.array.loc[
                dict(powertrain="FCEV", parameter="electric energy stored")
            ] = 20 + (
                self.array.loc[dict(powertrain="FCEV", parameter="fuel mass")]
                * 120
                / 3.6
                * 0.06
            )

        self["battery cell mass"] = self["electric energy stored"] / _(
            self["battery cell energy density"]
        )

        self["energy battery mass"] = self["battery cell mass"] / _(
            self["battery cell mass share"]
        )

        self["battery BoP mass"] = (
            self["energy battery mass"] - self["battery cell mass"]
        )

    def set_costs(self):
        _nz = lambda x: np.where(x < 1, 1, x)

        glider_components = [
            "glider base mass",
            "suspension mass",
            "braking system mass",
            "wheels and tires mass",
            "cabin mass",
        ]

        self["glider cost"] = np.clip(
            (
                (38747 * np.log(_nz(self[glider_components].sum(dim="parameter"))))
                - 252194
            ),
            33500,
            110000,
        )

        # Discount glider cost for 40t and 60t trucks because of the added trailer mass

        for size in [
            s for s in ["40t", "60t"] if s in self.array.coords["size"].values
        ]:
            self.array.loc[dict(parameter="glider cost", size=size)] *= 0.7

        self["lightweighting cost"] = (
            self["glider base mass"]
            * self["lightweighting"]
            * self["glider lightweighting cost per kg"]
        )
        self["electric powertrain cost"] = (
            self["electric powertrain cost per kW"] * self["electric power"]
        )
        self["combustion powertrain cost"] = (
            self["combustion power"] * self["combustion powertrain cost per kW"]
        )

        self["fuel cell cost"] = self["fuel cell power"] * self["fuel cell cost per kW"]

        self["power battery cost"] = (
            self["battery power"] * self["power battery cost per kW"]
        )
        self["energy battery cost"] = (
            self["energy battery cost per kWh"] * self["electric energy stored"]
        )
        self["fuel tank cost"] = self["fuel tank cost per kg"] * self["fuel mass"]
        # Per ton-km
        self["energy cost"] = (
            self["energy cost per kWh"]
            * self["TtW energy"]
            / 3600
            / (self["cargo mass"] / 1000)
        )

        # For battery, need to divide cost of electricity in battery by efficiency of charging
        for pt in [
            pwt
            for pwt in ["BEV", "PHEV-e"]
            if pwt in self.array.coords["powertrain"].values
        ]:
            self.array.loc[
                dict(powertrain=pt, parameter="energy cost")
            ] /= self.array.loc[
                dict(powertrain=pt, parameter="battery charge efficiency")
            ]

        self["component replacement cost"] = (
            self["energy battery cost"] * self["battery lifetime replacements"]
            + self["fuel cell cost"] * self["fuel cell lifetime replacements"]
        )

        to_markup = [
            "combustion powertrain cost",
            "component replacement cost",
            "electric powertrain cost",
            "energy battery cost",
            "fuel cell cost",
            "fuel tank cost",
            "glider cost",
            "lightweighting cost",
            "power battery cost",
        ]

        self[to_markup] *= self["markup factor"]

        # calculate costs per km:
        self["lifetime"] = self["lifetime kilometers"] / self["kilometers per year"]
        i = self["interest rate"]
        lifetime = self["lifetime"]
        amortisation_factor = ne.evaluate("i + (i / ((1 + i) ** lifetime - 1))")

        purchase_cost_list = [
            "battery onboard charging infrastructure cost",
            "combustion exhaust treatment cost",
            "combustion powertrain cost",
            "electric powertrain cost",
            "energy battery cost",
            "fuel cell cost",
            "fuel tank cost",
            "glider cost",
            "heat pump cost",
            "lightweighting cost",
            "power battery cost",
        ]

        self["purchase cost"] = self[purchase_cost_list].sum(axis=2)

        # per ton-km
        self["amortised purchase cost"] = (
            self["purchase cost"]
            * amortisation_factor
            / (self["cargo mass"] / 1000)
            / self["kilometers per year"]
        )

        # per km
        self["adblue cost"] = (
            self["adblue cost per kg"] * 0.06 * self["fuel mass"]
        ) / self["target range"]
        self["maintenance cost"] = self["maintenance cost per km"]
        self["maintenance cost"] += self["adblue cost"]
        self["maintenance cost"] /= self["cargo mass"] / 1000

        self["insurance cost"] = (
            self["insurance cost per year"]
            / (self["cargo mass"] / 1000)
            / self["kilometers per year"]
        )

        self["toll cost"] = self["toll cost per km"] / (self["cargo mass"] / 1000)

        # simple assumption that component replacement occurs at half of life.
        km_per_year = self["kilometers per year"]
        com_repl_cost = self["component replacement cost"]
        cargo = self["cargo mass"] / 1000

        self["amortised component replacement cost"] = ne.evaluate(
            "(com_repl_cost * ((1 - i) ** lifetime / 2) * amortisation_factor) / km_per_year / cargo"
        )

        self["total cost per km"] = (
            self["energy cost"]
            + self["amortised purchase cost"]
            + self["maintenance cost"]
            + self["insurance cost"]
            + self["toll cost"]
            + self["amortised component replacement cost"]
        )

    def calculate_cost_impacts(self, sensitivity=False, scope=None):
        """
        This method returns an array with cost values per vehicle-km, sub-divided into the following groups:

            * Purchase
            * Maintentance
            * Component replacement
            * Energy
            * Total cost of ownership

        :return: A xarray array with cost information per vehicle-km
        :rtype: xarray.core.dataarray.DataArray
        """

        if scope is None:
            scope = {
                "size": self.array.coords["size"].values.tolist(),
                "powertrain": self.array.coords["powertrain"].values.tolist(),
                "year": self.array.coords["year"].values.tolist(),
            }
        else:
            scope["size"] = scope.get("size", self.array.coords["size"].values.tolist())
            scope["powertrain"] = scope.get(
                "powertrain", self.array.coords["powertrain"].values.tolist()
            )
            scope["year"] = scope.get("year", self.array.coords["year"].values.tolist())

        list_cost_cat = [
            "purchase",
            "maintenance",
            "insurance",
            "toll",
            "component replacement",
            "energy",
            "total",
        ]

        response = xr.DataArray(
            np.zeros(
                (
                    len(scope["size"]),
                    len(scope["powertrain"]),
                    len(list_cost_cat),
                    len(scope["year"]),
                    len(self.array.coords["value"].values),
                )
            ),
            coords=[
                scope["size"],
                scope["powertrain"],
                list_cost_cat,
                scope["year"],
                self.array.coords["value"].values.tolist(),
            ],
            dims=["size", "powertrain", "cost_type", "year", "value"],
        )

        response.loc[:, :, list_cost_cat, :, :] = self.array.sel(
            powertrain=scope["powertrain"],
            size=scope["size"],
            year=scope["year"],
            parameter=[
                "amortised purchase cost",
                "maintenance cost",
                "insurance cost",
                "toll cost",
                "amortised component replacement cost",
                "energy cost",
                "total cost per km",
            ],
        ).values

        if not sensitivity:
            return response * (self.array.sel(parameter="cargo mass") > 100)
        else:
            return response / response.sel(value="reference")

    def remove_energy_consumption_from_unavailable_vehicles(self):
        """
        This method sets the energy consumption of vehicles that are not available to zero.
        """

        print("")
        print("'-' vehicle with driving mass superior to the permissible gross weight.")
        print("'/' vehicle not available for the specified year.")

        self["is_compliant"] *= self["driving mass"] < self["gross mass"]

        # we flag trucks that are not compliant
        self["TtW energy"] = np.where(
            (self["is_compliant"] == 0), 0, self["TtW energy"]
        )

        # Indicate vehicles not available before 2020
        l_pwt = [
            p
            for p in self.array.powertrain.values
            if p in ["BEV", "FCEV", "PHEV-d", "HEV-d"]
        ]

        if len(l_pwt) > 0:
            self.array.loc[
                dict(
                    powertrain=l_pwt,
                    parameter="is_available",
                    year=[y for y in self.array.year.values if y < 2020],
                )
            ] = 0

        self["TtW energy"] = np.where(
            (self["is_available"] == 0), 0, self["TtW energy"]
        )

        t = PrettyTable(
            ["Payload (in tons)"] + self.array.coords["size"].values.tolist()
        )

        for pt in self.array.coords["powertrain"].values:
            for y in self.array.coords["year"].values:
                row = [pt + ", " + str(y)]

                # indicate vehicles with lower cargo
                # as a result of curb mass being too large
                vals = np.asarray(
                    [
                        np.round(v[2][0], 1)
                        if (v[0][0] - v[1][0]) > 0
                        else f"-{np.round(v[2][0])}-"
                        for v in (
                            self.array.sel(
                                parameter=["gross mass", "driving mass", "cargo mass"],
                                powertrain=pt,
                                year=y,
                            )
                            / 1000
                        ).values.tolist()
                    ]
                )

                # indicate vehicles that are not commercially available
                vals = np.where(
                    self.array.sel(
                        parameter="is_available",
                        powertrain=pt,
                        year=y,
                        value="reference"
                        if "reference" in self.array.coords["value"]
                        else 0,
                    ).values,
                    vals,
                    "/",
                )

                t.add_row(row + vals.tolist())
        print(t)
