from .energy_consumption import EnergyConsumptionModel
from .hot_emissions import HotEmissionsModel
from .noise_emissions import NoiseEmissionsModel
from .background_systems import BackgroundSystemModel
import numexpr as ne
import numpy as np
import xarray as xr
from prettytable import PrettyTable


DEFAULT_MAPPINGS = {
    "electric": {"BEV", "PHEV-e"},
    "combustion": {"HEV-d", "ICEV-g", "ICEV-d", "PHEV-c-d",},
    "combustion_wo_cng": {"HEV-d", "ICEV-d", "PHEV-c-d"},
    "pure_combustion": {"ICEV-g", "ICEV-d"},
    "petrol": {"PHEV-c-p"},
    "cng": {"ICEV-g"},
    "fuel_cell": {"FCEV"},
    "hybrid": {"PHEV-e", "PHEV-c-d"},
    "combustion_hybrid": {"PHEV-c-d"},
    "electric_hybrid": {"PHEV-e"},
    "diesel": {"ICEV-d", "PHEV-c-d", "HEV-d"},
    "battery": {"BEV"},
}


def finite(array, mask_value=0):
    return np.where(np.isfinite(array), array, mask_value)


class TruckModel:

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

    def __init__(
        self,
        array,
        mappings=None,
        cycle="Urban delivery",
        country=None,
        fuel_blend=None,
        energy_target={2025: 0.85, 2030: 0.7},
    ):

        self.array = array
        self.mappings = mappings or DEFAULT_MAPPINGS
        self.bs = BackgroundSystemModel()

        self.country = country or "RER"
        self.fuel_blend = self.define_fuel_blends(fuel_blend)
        self.cycle = cycle

        self.energy_target = energy_target

        target_ranges = {
            "Urban delivery": 150,
            "Regional delivery": 400,
            "Long haul": 800,
        }

        self["target range"] = target_ranges[self.cycle]

        print(
            "{} driving cycle is selected. Vehicles will be designed to achieve a minimal range of {} km.".format(
                cycle, target_ranges[cycle]
            )
        )

        print("")
        print("Capacity utilization assumed (share of available payload used)")
        t = PrettyTable([""] + array.coords["size"].values.tolist())
        for pt in array.coords["powertrain"].values:
            for y in array.coords["year"].values:
                t.add_row(
                    [pt + ", " + str(y)]
                    + [
                        np.round(i, 2)
                        for i in array.sel(
                            parameter="capacity utilization", powertrain=pt, year=y
                        )
                        .mean(dim="value")
                        .values.tolist()
                    ]
                )

        print(t)

        self.ecm = EnergyConsumptionModel(cycle=cycle)

    def __call__(self, key):
        """
        This method fixes a dimension of the `array` attribute given a powertrain technology selected.

        Set up this class as a context manager, so we can have some nice syntax

        .. code-block:: python

            with class('some powertrain') as cpm:
                cpm['something']. # Will be filtered for the correct powertrain

        On with block exit, this filter is cleared
        https://stackoverflow.com/a/10252925/164864

        :param key: A powertrain type, e.g., "FCEV"
        :type key: str
        :return: An instance of `array` filtered after the powertrain selected.

        """
        self.__cache = self.array
        self.array = self.array.sel(powertrain=key)
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.array = self.__cache
        del self.__cache

    def __getitem__(self, key):
        """
        Make class['foo'] automatically filter for the parameter 'foo'
        Makes the model code much cleaner

        :param key: Parameter name
        :type key: str
        :return: `array` filtered after the parameter selected
        """

        return self.array.sel(parameter=key)

    def __setitem__(self, key, value):
        self.array.loc[{"parameter": key}] = value

    # Make it easier/more flexible to filter by powertrain types
    def __getattr__(self, key):
        if key in self.mappings:
            return self.mappings[key]
        else:
            return super().__getattr__(key)

    def set_all(self):
        """
        This method runs a series of other methods to obtain the tank-to-wheel energy requirement, efficiency
        of the car, costs, etc.

        :meth:`set_component_masses()`, :meth:`set_car_masses()` and :meth:`set_power_parameters()` and
         :meth:`set_energy_stored_properties` relate to one another.
        `powertrain_mass` depends on `power`, `curb_mass` is affected by changes in `powertrain_mass`,
        `combustion engine mass`, `electric engine mass`. `energy battery mass` is influenced by the `curb mass` but also
        by the `target range` the truck has. `power` is also varying with `curb_mass`.

        The current solution is to loop through the methods until the change in payload between two iterations is
        inferior to 0.1%. It is then assumed that the trucks are correctly sized.

        :returns: Does not return anything. Modifies ``self.array`` in place.

        """

        diff = 1.0
        arr = np.array([])

        while abs(diff) > 0.001 or np.std(arr[-5:]) > 0.3:

            old_payload = self["available payload"].sum().values

            self.set_car_masses()
            self.set_power_parameters()
            self.set_component_masses()
            self.set_auxiliaries()
            self.set_ttw_efficiency()
            self.set_recuperation()
            self.set_fuel_cell_parameters()
            self.calculate_ttw_energy()
            self.set_battery_fuel_cell_replacements()
            self.set_energy_stored_properties()

            # if there are vehicles after 2020, we need to ensure CO2 standards compliance
            # return an array with non-compliant vehicles
            non_compliant_vehicles = self.adjust_combustion_power_share()
            arr = np.append(arr, non_compliant_vehicles.sum())

            self.set_car_masses()

            diff = (self["available payload"].sum().values - old_payload) / self[
                "available payload"
            ].sum()

        self.adjust_cost()
        self.set_electric_utility_factor()
        self.set_electricity_consumption()
        self.set_costs()
        self.set_hot_emissions()
        self.set_noise_emissions()
        self.create_PHEV()
        self.drop_hybrid()

        print("")
        print("Payload (in tons)")
        print("Vehicles for which the payload is not specified have either: ")
        print(
            "1. a driving mass superior to the permissible gross weight. Possible solutions include: reducing the "
            "range autonomy for those vehicles, reducing the load factor, increasing the battery cell energy density."
        )
        print(
            "2. an energy efficiency too low to comply with the energy target specified. Possible solutions include: "
            "changing the energy reduction targets specified, increasing the engine efficiency."
        )

        self.array.loc[
            dict(
                powertrain=["ICEV-d", "ICEV-g"],
                parameter="total cargo mass",
                year=[y for y in self.array.year.values if y >= 2020],
            )
        ] *= np.clip((1 - non_compliant_vehicles), 0.001, 1)

        t = PrettyTable([""] + self.array.coords["size"].values.tolist())
        for pt in self.array.coords["powertrain"].values:
            for y in self.array.coords["year"].values:
                t.add_row(
                    [pt + ", " + str(y)]
                    + [
                        np.round(np.mean(v), 1) if np.mean(v) > 0.1 else "-"
                        for v in (
                            self.array.sel(
                                parameter="total cargo mass", powertrain=pt, year=y
                            )
                            / 1000
                        ).values.tolist()
                    ]
                )
        print(t)

    def adjust_combustion_power_share(self):
        """
        If the exhaust CO2 emissions exceed the targets defined in `self.emission_target`,
        compared to 2020, we decrement the power supply share of the combustion engine.

        :returns: `is_compliant`, whether all vehicles are compliant or not.
        """

        list_target_years = [2020] + list(self.energy_target.keys())
        list_target_vals = [1] + list(self.energy_target.values())
        # years under target
        actual_years = [y for y in self.array.year.values if y >= 2020]

        if len(actual_years) > 0:

            fc = (
                self.array.loc[:, ["ICEV-d", "ICEV-g"], "fuel mass", :]
                / self.array.loc[:, ["ICEV-d", "ICEV-g"], "target range", :]
            ).interp(year=list_target_years, kwargs={"fill_value": "extrapolate"})

            fc[:, :, :, :] = (
                fc[:, :, 0, :].values * np.array(list_target_vals).reshape(-1, 1, 1, 1)
            ).transpose(1, 2, 0, 3)

            years_after_last_target = [
                y for y in actual_years if y > list_target_years[-1]
            ]

            fc = fc.interp(year=actual_years, kwargs={"fill_value": "extrapolate"})

            if len(years_after_last_target) > 0:
                fc.loc[dict(year=years_after_last_target)] = fc.loc[
                    dict(year=list_target_years[-1])
                ].values[:, :, None, :]

            arr = (
                fc.values
                < (
                    self.array.loc[:, ["ICEV-d", "ICEV-g"], "fuel mass", actual_years]
                    / self.array.loc[
                        :, ["ICEV-d", "ICEV-g"], "target range", actual_years
                    ]
                ).values
            )

            if arr.sum() > 0:
                new_shares = self.array.loc[
                    dict(
                        powertrain=["ICEV-d", "ICEV-g"],
                        parameter="combustion power share",
                        year=actual_years,
                    )
                ] - (arr * 0.02)
                self.array.loc[
                    dict(
                        powertrain=["ICEV-d", "ICEV-g"],
                        parameter="combustion power share",
                        year=actual_years,
                    )
                ] = np.clip(new_shares, 0.6, 1)
            return arr
        else:
            return np.array([])

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
        else:
            if "reference" in self.array.value.values:
                cost_factor = np.ones((n_iterations, 1))
            else:
                cost_factor = np.random.triangular(0.7, 1, 1.3, (n_iterations, 1))

        # Correction of hydrogen tank cost, per kg
        self.array.loc[:, ["FCEV"], "fuel tank cost per kg", :, :] = np.reshape(
            (1.078e58 * np.exp(-6.32e-2 * self.array.year.values) + 3.43e2)
            * cost_factor,
            (1, 1, n_year, n_iterations),
        )

        # Correction of fuel cell stack cost, per kW
        self.array.loc[:, ["FCEV"], "fuel cell cost per kW", :, :] = np.reshape(
            (3.15e66 * np.exp(-7.35e-2 * self.array.year.values) + 2.39e1)
            * cost_factor,
            (1, 1, n_year, n_iterations),
        )

        # Correction of energy battery system cost, per kWh
        self.array.loc[
            :, ["BEV", "PHEV-e", "PHEV-c-d"], "energy battery cost per kWh", :, :,
        ] = np.reshape(
            (2.75e86 * np.exp(-9.61e-2 * self.array.year.values) + 5.059e1)
            * cost_factor,
            (1, 1, n_year, n_iterations),
        )

        # Correction of power battery system cost, per kW
        self.array.loc[
            :,
            ["ICEV-d", "ICEV-g", "PHEV-c-d", "FCEV", "HEV-d"],
            "power battery cost per kW",
            :,
            :,
        ] = np.reshape(
            (8.337e40 * np.exp(-4.49e-2 * self.array.year.values) + 11.17)
            * cost_factor,
            (1, 1, n_year, n_iterations),
        )

        # Correction of combustion powertrain cost for ICEV-g
        self.array.loc[
            :, ["ICEV-g"], "combustion powertrain cost per kW", :, :,
        ] = np.reshape(
            (5.92e160 * np.exp(-0.1819 * self.array.year.values) + 26.76) * cost_factor,
            (1, 1, n_year, n_iterations),
        )

    def drop_hybrid(self):
        """
        This method drops the powertrains `PHEV-c-p`, `PHEV-c-d` and `PHEV-e` as they were only used to create the
        `PHEV` powertrain.
        :returns: Does not return anything. Modifies ``self.array`` in place.
        """
        self.array = self.array.sel(
            powertrain=["ICEV-d", "ICEV-g", "PHEV-d", "FCEV", "BEV", "HEV-d",]
        )

    def set_electricity_consumption(self):
        """
        This method calculates the total electricity consumption for BEV and plugin-hybrid vehicles
        :returns: Does not return anything. Modifies ``self.array`` in place.
        """
        for pt in ["BEV", "PHEV-e"]:
            with self(pt) as cpm:
                cpm["electricity consumption"] = (
                    cpm["TtW energy"] / cpm["battery charge efficiency"]
                ) / 3600

    def calculate_ttw_energy(self):
        """
        This method calculates the energy required to operate auxiliary services as well
        as to move the car. The sum is stored under the parameter label "TtW energy" in :attr:`self.array`.

        """
        aux_energy = self.ecm.aux_energy_per_km(self["auxiliary power demand"])

        pts = [pt for pt in self.array.powertrain.values if pt != "FCEV"]

        for pt in pts:
            with self(pt) as cpm:
                if self.cycle == "Urban delivery":
                    aux_energy.loc[{"powertrain": pt}] /= cpm[
                        "engine efficiency, empty, urban delivery"
                    ]
                if self.cycle == "Regional delivery":
                    aux_energy.loc[{"powertrain": pt}] /= cpm[
                        "engine efficiency, empty, regional delivery"
                    ]
                if self.cycle == "Long haul":
                    aux_energy.loc[{"powertrain": pt}] /= cpm[
                        "engine efficiency, empty, long haul"
                    ]

        for pt in self.fuel_cell:
            with self(pt) as cpm:
                aux_energy.loc[{"powertrain": pt}] /= cpm["fuel cell system efficiency"]

        self["auxiliary energy"] = aux_energy

        motive_energy = self.ecm.motive_energy_per_km(
            driving_mass=self["driving mass"],
            rr_coef=self["rolling resistance coefficient"],
            drag_coef=self["aerodynamic drag coefficient"],
            frontal_area=self["frontal area"],
            ttw_efficiency=self["TtW efficiency"],
            recuperation_efficiency=self["recuperation efficiency"],
            motor_power=self["electric power"],
        ).sum(axis=0)

        # noinspection PyAttributeOutsideInit
        self.motive_energy = motive_energy.T
        self["TtW energy"] = aux_energy + motive_energy.T

    def set_fuel_cell_parameters(self):
        """
        Specific setup for fuel cells, which are mild hybrids.
        Must be called after :meth:`.set_power_parameters`.
        """

        with self("FCEV"):
            self["fuel cell system efficiency"] = (
                self["fuel cell stack efficiency"] / self["fuel cell own consumption"]
            )
            self["fuel cell power share"] = self["fuel cell power share"].clip(
                min=0, max=1
            )
            self["fuel cell power"] = (
                self["power"]
                * self["fuel cell power share"]
                * self["fuel cell own consumption"]
            )
            # our basic fuel cell mass is based on a car fuel cell with 800 mW/cm2 and 0.51 kg/kW
            self["fuel cell stack mass"] = (
                0.51
                * self["fuel cell power"]
                * (800 / self["fuel cell power area density"])
            )
            self["fuel cell ancillary BoP mass"] = (
                self["fuel cell power"] * self["fuel cell ancillary BoP mass per power"]
            )
            self["fuel cell essential BoP mass"] = (
                self["fuel cell power"] * self["fuel cell essential BoP mass per power"]
            )

            self["battery power"] = self["fuel cell power"] * (
                1 - self["fuel cell power share"]
            )
            self["battery cell mass"] = (
                self["battery power"] / self["battery cell power density"]
            )
            self["battery BoP mass"] = self["battery cell mass"] * (
                1 - self["battery cell mass share"]
            )

    def set_auxiliaries(self):
        """
        Calculates the power needed to operate the auxiliary services of the vehicle (heating, cooling).

        The demand for heat and cold are expressed as a fraction of the heating and cooling capacities

        .. note:

            Auxiliary power demand (W) = Base auxiliary power (W) +
            (Heating demand (dimensionless, between 0 and 1) * Heating power (W)) +
            (Cooling demand (dimensionless, between 0 and 1) * Cooling power (W))

        """
        self["auxiliary power demand"] = (
            self["auxilliary power base demand"]
            + self["heating thermal demand"] * self["heating energy consumption"]
            + self["cooling thermal demand"] * self["cooling energy consumption"]
        )

    def set_recuperation(self):

        if self.cycle == "Urban delivery":
            drivetrain_eff = self["drivetrain efficiency, empty, urban delivery"]

        if self.cycle == "Regional delivery":
            drivetrain_eff = self["drivetrain efficiency, empty, regional delivery"]

        if self.cycle == "Long haul":
            drivetrain_eff = self["drivetrain efficiency, empty, long haul"]

        self["recuperation efficiency"] = (
            drivetrain_eff * self["battery charge efficiency"]
        )

    def set_battery_fuel_cell_replacements(self):
        """
        This methods calculates the fraction of the replacement battery needed to match the vehicle lifetime.

        .. note::
            if ``lifetime kilometers`` = 1000000 (km) and ``battery lifetime`` = 800000 (km) then ``replacement battery``=0.05

        .. note::
            It is debatable whether this is realistic or not. Truck owners may not decide to invest in a new
            battery if the remaining lifetime of the truck is only 200000 km. Also, a battery lifetime may be expressed
            in other terms, e.g., charging cycles.

            Also, if the battery lifetime surpasses the vehicle lifetime, 100% of the burden of the battery production
            is allocated to the vehicle.

        """
        # Here we assume that we can use fractions of a battery/fuel cell
        # (averaged across the fleet)
        self["battery lifetime replacements"] = finite(
            np.clip(
                (self["lifetime kilometers"] / self["battery lifetime kilometers"]) - 1,
                0,
                None,
            )
        )
        self["fuel cell lifetime replacements"] = finite(
            np.clip(
                (self["lifetime kilometers"] / self["fuel cell lifetime kilometers"])
                - 1,
                0,
                None,
            )
        )

    def set_car_masses(self):
        """
        Define ``curb mass``, ``driving mass``, and ``total cargo mass``.

            * `curb mass <https://en.wikipedia.org/wiki/Curb_weight>`__ is the mass of the vehicle and fuel, without people or cargo.
            * ``total cargo mass`` is the mass of the cargo and passengers.
            * ``driving mass`` is the ``curb mass`` plus ``total cargo mass``.

        .. note::
            driving mass = total cargo mass + driving mass

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

        self["available payload"] = np.clip(
            self["gross mass"]
            - (
                self["curb mass"]
                + (self["average passengers"] * self["average passenger mass"])
            ),
            0,
            None,
        )

        self["total cargo mass"] = (
            self["average passengers"] * self["average passenger mass"]
        ) + (self["available payload"] * self["capacity utilization"])

        self["driving mass"] = self["curb mass"] + self["total cargo mass"]

    def set_power_parameters(self):
        """Set electric and combustion motor powers based on input parameter ``power to mass ratio``."""
        # Convert from W/kg to kW
        self["power"] = self["power to mass ratio"] * self["curb mass"] / 1000
        self["combustion power share"] = self["combustion power share"].clip(
            min=0, max=1
        )
        self["combustion power"] = self["power"] * self["combustion power share"]
        self["electric power"] = self["power"] * (1 - self["combustion power share"])

    def set_component_masses(self):
        self["combustion engine mass"] = (
            self["combustion power"] * self["engine mass per power"]
            + self["engine fixed mass"]
        )
        self["electric engine mass"] = (
            self["electric power"] * self["emotor mass per power"]
            + self["emotor fixed mass"]
        )
        self["transmission mass"] = (self["gross mass"] / 1000) * self[
            "transmission mass per ton of gross weight"
        ] + self["transmission fixed mass"]

        self["inverter mass"] = (
            self["electric power"] * self["inverter mass per power"]
            + self["inverter fix mass"]
        )

    def set_electric_utility_factor(self):
        """
        From Plotz et al. 2017
        The electric utility factor is defined by the range
        :return:
        """
        with self("PHEV-e") as cpm:
            cpm["electric utility factor"] = (
                1 - np.exp(-0.01147 * cpm["target range"])
            ) ** 1.186185

    def create_PHEV(self):
        """ PHEV-p/d is the range-weighted average between PHEV-c-p/PHEV-c-d and PHEV-e.
        """

        self.array.loc[{"powertrain": "PHEV-d"}] = (
            self.array.loc[{"powertrain": "PHEV-e"}]
            * self.array.loc[
                {"powertrain": "PHEV-e", "parameter": "electric utility factor"}
            ]
        ) + (
            self.array.loc[{"powertrain": "PHEV-c-d"}]
            * (
                1
                - self.array.loc[
                    {"powertrain": "PHEV-e", "parameter": "electric utility factor"}
                ]
            )
        )

    def set_energy_stored_properties(self):
        """
        First, fuel mass is defined. It is dependent on the range required.
        Then batteries are sized, depending on the range required and the energy consumption.
        :return:
        """
        d_map_fuel = {
            "ICEV-d": "diesel",
            "HEV-d": "diesel",
            "PHEV-c-d": "diesel",
            "ICEV-g": "cng",
            "FCEV": "hydrogen",
        }

        for pt in ["ICEV-d", "HEV-d", "PHEV-c-d", "ICEV-g"]:

            with self(pt) as cpm:

                # calculate the average LHV based on fuel blend
                fuel_type = d_map_fuel[pt]
                primary_fuel_share = self.fuel_blend[fuel_type]["primary"]["share"]
                primary_fuel_lhv = self.fuel_blend[fuel_type]["primary"]["lhv"]
                secondary_fuel_share = self.fuel_blend[fuel_type]["secondary"]["share"]
                secondary_fuel_lhv = self.fuel_blend[fuel_type]["secondary"]["lhv"]

                blend_lhv = (np.array(primary_fuel_share) * primary_fuel_lhv) + (
                    np.array(secondary_fuel_share) * secondary_fuel_lhv
                )

                cpm["fuel mass"] = (
                    cpm["target range"] * (cpm["TtW energy"] / 1000)
                ) / blend_lhv.reshape(-1, 1)

                cpm["oxidation energy stored"] = (
                    cpm["fuel mass"] * blend_lhv.reshape(-1, 1)
                ) / 3.6

                if pt == "ICEV-g":
                    cpm["fuel tank mass"] = (
                        cpm["oxidation energy stored"] * cpm["CNG tank mass slope"]
                    ) + cpm["CNG tank mass intercept"]
                else:
                    # From Wolff et al. 2020, Sustainability, DOI: 10.3390/su12135396.
                    cpm["fuel tank mass"] = (
                        17.159 * np.log(cpm["fuel mass"] * (1 / 0.832)) - 54.98
                    )

        for pt in ["HEV-d", "ICEV-g", "ICEV-d", "PHEV-c-d"]:
            with self(pt) as cpm:
                cpm["battery power"] = cpm["electric power"]
                cpm["battery cell mass"] = (
                    cpm["battery power"] / cpm["battery cell power density"]
                )
                cpm["battery cell mass share"] = cpm["battery cell mass share"].clip(
                    min=0, max=1
                )
                cpm["battery BoP mass"] = cpm["battery cell mass"] * (
                    1 - cpm["battery cell mass share"]
                )

        for pt in ["BEV", "PHEV-e"]:
            with self(pt) as cpm:
                cpm["electric energy stored"] = (
                    cpm["target range"] * (cpm["TtW energy"] / 1000)
                ) / 3.6
                cpm["battery cell mass"] = (
                    cpm["electric energy stored"] / cpm["battery cell energy density"]
                )

                cpm["energy battery mass"] = (
                    cpm["battery cell mass"] / cpm["battery cell mass share"]
                )

                cpm["battery BoP mass"] = (
                    cpm["energy battery mass"] - cpm["battery cell mass"]
                )

        with self("FCEV") as cpm:
            cpm["fuel mass"] = (cpm["target range"] * (cpm["TtW energy"] / 1000)) / cpm[
                "LHV fuel MJ per kg"
            ]
            cpm["oxidation energy stored"] = cpm["fuel mass"] * 120 / 3.6  # kWh
            cpm["fuel tank mass"] = (
                cpm["oxidation energy stored"] * cpm["fuel tank mass per energy"]
            )

        # kWh electricity/kg battery cell
        self["battery cell production energy electricity share"] = self[
            "battery cell production energy electricity share"
        ].clip(min=0, max=1)
        self["battery cell production electricity"] = (
            self["battery cell production energy"]
            * self["battery cell production energy electricity share"]
        )
        # MJ heat/kg battery cell
        self["battery cell production heat"] = (
            self["battery cell production energy"]
            - self["battery cell production electricity"]
        ) * 3.6

    def set_costs(self):
        self["glider cost"] = (
            self["glider base mass"] * self["glider cost slope"]
            + self["glider cost intercept"]
        )
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
            self["energy battery cost per kWh"]
            * self["battery cell mass"]
            * self["battery cell energy density"]
        )
        self["fuel tank cost"] = self["fuel tank cost per kg"] * self["fuel mass"]
        # Per km
        self["energy cost"] = self["energy cost per kWh"] * self["TtW energy"] / 3600

        # For battery, need to divide cost of electricity in battery by efficiency of charging
        for pt in ["BEV", "PHEV-e"]:
            with self(pt) as cpm:
                cpm["energy cost"] /= cpm["battery charge efficiency"]

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

        # per km
        self["amortised purchase cost"] = (
            self["purchase cost"] * amortisation_factor / self["kilometers per year"]
        )
        # per km
        self["maintenance cost"] = (
            self["maintenance cost per glider cost"]
            * self["glider cost"]
            / self["kilometers per year"]
        )

        # simple assumption that component replacement occurs at half of life.
        km_per_year = self["kilometers per year"]
        com_repl_cost = self["component replacement cost"]
        self["amortised component replacement cost"] = ne.evaluate(
            "(com_repl_cost * ((1 - i) ** lifetime / 2) * amortisation_factor / km_per_year)"
        )

        self["total cost per km"] = (
            self["energy cost"]
            + self["amortised purchase cost"]
            + self["maintenance cost"]
            + self["amortised component replacement cost"]
        )

    def set_ttw_efficiency(self):
        """
        The efficiency of the engine and drivetrain is calibrated after VECTO simulations for current vehicles (2020).
        Efficiencies of both components vary depending on the torque and rpm required at the wheels.
        Torque and rpm required are calculated after a complex model in VECTO, where several factors,
        such as the driving factor and the load factor, are important. For that reason, efficiencies here
        are defined according to the driving cycle, and the load factor. Also, the engine efficiency of hybrid
        drivetrains are the product of the efficiency of the combustion engine and the electric motor.
        :return:
        """

        _ = lambda array: np.where(array == 0, 1, array)

        if self.cycle == "Urban delivery":
            engine_eff_empty = self["engine efficiency, empty, urban delivery"]
            engine_eff_full = self["engine efficiency, full, urban delivery"]

            engine_eff = (self["capacity utilization"] * engine_eff_full) + (
                (1 - self["capacity utilization"]) * engine_eff_empty
            )

            engine_eff_empty_elec = self.array.sel(
                powertrain="BEV", parameter="engine efficiency, empty, urban delivery"
            )
            engine_eff_full_elec = self.array.sel(
                powertrain="BEV", parameter="engine efficiency, full, urban delivery"
            )

            elec_engine_eff = (self["capacity utilization"] * engine_eff_empty_elec) + (
                (1 - self["capacity utilization"]) * engine_eff_full_elec
            )

            engine_eff *= self["combustion power share"]
            engine_eff += (1 - self["combustion power share"]) * elec_engine_eff

            drivetrain_eff = self["drivetrain efficiency, empty, urban delivery"]

        if self.cycle == "Regional delivery":
            engine_eff_empty = self["engine efficiency, empty, regional delivery"]
            engine_eff_full = self["engine efficiency, full, regional delivery"]

            engine_eff = (self["capacity utilization"] * engine_eff_full) + (
                (1 - self["capacity utilization"]) * engine_eff_empty
            )

            engine_eff_empty_elec = self.array.sel(
                powertrain="BEV",
                parameter="engine efficiency, empty, regional delivery",
            )
            engine_eff_full_elec = self.array.sel(
                powertrain="BEV", parameter="engine efficiency, full, regional delivery"
            )

            elec_engine_eff = (self["capacity utilization"] * engine_eff_empty_elec) + (
                (1 - self["capacity utilization"]) * engine_eff_full_elec
            )

            engine_eff *= self["combustion power share"]
            engine_eff += (1 - self["combustion power share"]) * elec_engine_eff

            drivetrain_eff = self["drivetrain efficiency, empty, regional delivery"]

        if self.cycle == "Long haul":
            engine_eff_empty = self["engine efficiency, empty, long haul"]
            engine_eff_full = self["engine efficiency, full, long haul"]

            engine_eff = (self["capacity utilization"] * engine_eff_full) + (
                (1 - self["capacity utilization"]) * engine_eff_empty
            )

            engine_eff_empty_elec = self.array.sel(
                powertrain="BEV", parameter="engine efficiency, empty, long haul"
            )
            engine_eff_full_elec = self.array.sel(
                powertrain="BEV", parameter="engine efficiency, full, long haul"
            )

            elec_engine_eff = (self["capacity utilization"] * engine_eff_empty_elec) + (
                (1 - self["capacity utilization"]) * engine_eff_full_elec
            )

            engine_eff *= self["combustion power share"]
            engine_eff += (1 - self["combustion power share"]) * elec_engine_eff

            drivetrain_eff = self["drivetrain efficiency, empty, long haul"]

        self["TtW efficiency"] = (
            _(self["battery discharge efficiency"])
            * _(self["fuel cell system efficiency"])
            * drivetrain_eff
            * engine_eff
        )

    def set_hot_emissions(self):
        """
        Calculate hot pollutant emissions based on ``driving cycle``.
        The driving cycle is passed to the :class:`HotEmissionsModel` class and :meth:`get_emissions_per_powertrain`
        return emissions per substance per second of driving cycle.
        :return: Does not return anything. Modifies ``self.array`` in place.
        """
        hem = HotEmissionsModel(self.ecm.cycle, self.ecm.cycle_name)

        list_direct_emissions = [
            "Hydrocarbons direct emissions, urban",
            "Carbon monoxide direct emissions, urban",
            "Nitrogen oxides direct emissions, urban",
            "Particulate matters direct emissions, urban",
            "Nitrogen dioxide direct emissions, urban",
            "Methane direct emissions, urban",
            "NMVOC direct emissions, urban",
            "Sulfur dioxide direct emissions, urban",
            "Dinitrogen oxide direct emissions, urban",
            "Ammonia direct emissions, urban",
            "Benzene direct emissions, urban",
            "Hydrocarbons direct emissions, suburban",
            "Carbon monoxide direct emissions, suburban",
            "Nitrogen oxides direct emissions, suburban",
            "Particulate matters direct emissions, suburban",
            "Nitrogen dioxide direct emissions, suburban",
            "Methane direct emissions, suburban",
            "NMVOC direct emissions, suburban",
            "Sulfur dioxide direct emissions, suburban",
            "Dinitrogen oxide direct emissions, suburban",
            "Ammonia direct emissions, suburban",
            "Benzene direct emissions, suburban",
            "Hydrocarbons direct emissions, rural",
            "Carbon monoxide direct emissions, rural",
            "Nitrogen oxides direct emissions, rural",
            "Particulate matters direct emissions, rural",
            "Nitrogen dioxide direct emissions, rural",
            "Methane direct emissions, rural",
            "NMVOC direct emissions, rural",
            "Sulfur dioxide direct emissions, rural",
            "Dinitrogen oxide direct emissions, rural",
            "Ammonia direct emissions, rural",
            "Benzene direct emissions, rural",
        ]

        l_y = []
        for y in self.array.year.values:
            if 2000 <= y < 2005:
                l_y.append(3)
            if 2005 <= y < 2008:
                l_y.append(4)
            if 2008 <= y < 2012:
                l_y.append(5)
            if y >= 2012:
                l_y.append(6)

        self.array.loc[
            dict(
                powertrain=["ICEV-d", "PHEV-c-d", "HEV-d"],
                parameter=list_direct_emissions,
            )
        ] = hem.get_emissions_per_powertrain("diesel", euro_classes=l_y)

        # Applies an emission factor, useful for sensitivity purpose
        self.array.loc[
            dict(
                powertrain=["ICEV-d", "PHEV-c-d", "HEV-d"],
                parameter=list_direct_emissions,
            )
        ] *= self.array.loc[
            dict(
                powertrain=["ICEV-d", "PHEV-c-d", "HEV-d"], parameter="emission factor"
            )
        ]

        # For CNG vehicles
        self.array.loc[
            dict(powertrain="ICEV-g", parameter=list_direct_emissions)
        ] = hem.get_emissions_per_powertrain("CNG", euro_classes=l_y)

        # Applies an emission factor, useful for sensitivity purpose
        self.array.loc[
            dict(powertrain="ICEV-g", parameter=list_direct_emissions)
        ] *= self.array.loc[dict(powertrain="ICEV-g", parameter="emission factor")]

        # Emissions are scaled to the combustion power share
        self.array.loc[:, :, list_direct_emissions, :] *= self.array.loc[
            :, :, "combustion power share", :
        ]

    def set_noise_emissions(self):
        """
        Calculate noise emissions based on ``driving cycle``.
        The driving cycle is passed to the :class:`NoiseEmissionsModel` class and :meth:`get_sound_power_per_compartment`
        returns emissions per compartment type ("rural", "non-urban" and "urban") per second of driving cycle.

        Noise emissions are not differentiated by size classes at the moment, but only by powertrain "type"
        (e.g., combustion, hybrid and electric)

        :return: Does not return anything. Modifies ``self.array`` in place.
        """
        nem = NoiseEmissionsModel(self.ecm.cycle, self.ecm.cycle_name)

        list_noise_emissions = [
            "noise, octave 1, day time, urban",
            "noise, octave 2, day time, urban",
            "noise, octave 3, day time, urban",
            "noise, octave 4, day time, urban",
            "noise, octave 5, day time, urban",
            "noise, octave 6, day time, urban",
            "noise, octave 7, day time, urban",
            "noise, octave 8, day time, urban",
            "noise, octave 1, day time, suburban",
            "noise, octave 2, day time, suburban",
            "noise, octave 3, day time, suburban",
            "noise, octave 4, day time, suburban",
            "noise, octave 5, day time, suburban",
            "noise, octave 6, day time, suburban",
            "noise, octave 7, day time, suburban",
            "noise, octave 8, day time, suburban",
            "noise, octave 1, day time, rural",
            "noise, octave 2, day time, rural",
            "noise, octave 3, day time, rural",
            "noise, octave 4, day time, rural",
            "noise, octave 5, day time, rural",
            "noise, octave 6, day time, rural",
            "noise, octave 7, day time, rural",
            "noise, octave 8, day time, rural",
        ]

        self.array.loc[
            dict(
                powertrain=["ICEV-g", "ICEV-d", "PHEV-c-d",],
                parameter=list_noise_emissions,
                size=["3.5t", "7.5t", "18t", "26t"],
            )
        ] = nem.get_sound_power_per_compartment("combustion", "medium")

        self.array.loc[
            dict(
                powertrain=["ICEV-g", "ICEV-d", "PHEV-c-d",],
                parameter=list_noise_emissions,
                size=["40t", "60t"],
            )
        ] = nem.get_sound_power_per_compartment("combustion", "heavy")
        self.array.loc[
            dict(
                powertrain=["BEV", "FCEV", "PHEV-e"],
                parameter=list_noise_emissions,
                size=["3.5t", "7.5t", "18t", "26t"],
            )
        ] = nem.get_sound_power_per_compartment("electric", "medium")
        self.array.loc[
            dict(
                powertrain=["BEV", "FCEV", "PHEV-e"],
                parameter=list_noise_emissions,
                size=["40t", "60t"],
            )
        ] = nem.get_sound_power_per_compartment("electric", "heavy")

        self.array.loc[
            dict(
                powertrain=["HEV-d"],
                parameter=list_noise_emissions,
                size=["3.5t", "7.5t", "18t", "26t"],
            )
        ] = nem.get_sound_power_per_compartment("hybrid", "medium")

        self.array.loc[
            dict(
                powertrain=["HEV-d"],
                parameter=list_noise_emissions,
                size=["40t", "60t"],
            )
        ] = nem.get_sound_power_per_compartment("hybrid", "heavy")

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
            scope = {"size": self.array.coords["size"].values.tolist(),
                     "powertrain": self.array.coords["powertrain"].values.tolist(),
                     "year": self.array.coords["year"].values.tolist()}
        else:
            scope["size"] = scope.get("size", self.array.coords["size"].values.tolist())
            scope["powertrain"] = scope.get(
                "powertrain", self.array.coords["powertrain"].values.tolist()
            )
            scope["year"] = scope.get("year", self.array.coords["year"].values.tolist())

        list_cost_cat = [
            "purchase",
            "maintenance",
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
                ["purchase", "maintenance", "component replacement", "energy", "total"],
                scope["year"],
                self.array.coords["value"].values.tolist(),
            ],
            dims=["size", "powertrain", "cost_type", "year", "value"],
        )

        response.loc[
            :,
            :,
            ["purchase", "maintenance", "component replacement", "energy", "total"],
            :,
            :,
        ] = self.array.sel(
            powertrain=scope["powertrain"],
            size=scope["size"],
            year=scope["year"],
            parameter=[
                "amortised purchase cost",
                "maintenance cost",
                "amortised component replacement cost",
                "energy cost",
                "total cost per km",
            ],
        ).values

        if not sensitivity:
            return response
        else:
            return response / response.sel(value="reference")

    def get_share_biofuel(self):
        region = self.bs.region_map[self.country]["RegionCode"]
        scenario = "SSP2-Base"

        share_biofuel = (
            self.bs.biofuel.sel(
                region=region, value=0, fuel_type="Biomass fuel", scenario=scenario,
            )
            .interp(
                year=self.array.coords["year"].values,
                kwargs={"fill_value": "extrapolate"},
            )
            .values
        )
        return share_biofuel

    def find_fuel_shares(self, fuel_blend, fuel_type):

        default_fuels = {
            "diesel": {
                "primary": "diesel",
                "secondary": "biodiesel - cooking oil",
                "all": [
                    "diesel",
                    "biodiesel - cooking oil",
                    "biodiesel - algae",
                    "synthetic diesel",
                ],
            },
            "cng": {
                "primary": "cng",
                "secondary": "biogas - sewage sludge",
                "all": ["cng", "biogas - sewage sludge", "syngas", "biogas - biowaste"],
            },
            "hydrogen": {
                "primary": "electrolysis",
                "secondary": "smr - natural gas",
                "all": [
                    "electrolysis",
                    "smr - natural gas",
                    "smr - natural gas with CCS",
                    "smr - biogas",
                    "smr - biogas with CCS",
                    "coal gasification",
                    "wood gasification",
                    "wood gasification with CCS",
                ],
            },
        }

        if fuel_type in fuel_blend:
            primary = fuel_blend[fuel_type]["primary"]["type"]

            try:
                # See of a secondary fuel type has been specified
                secondary = fuel_blend[fuel_type]["secondary fuel"]["type"]
            except:
                # A secondary fuel has not been specified, set one by default
                # Check first if the default fuel is not similar to the primary fuel

                if default_fuels[fuel_type]["secondary"] != primary:
                    secondary = default_fuels[fuel_type]["secondary"]
                else:
                    secondary = [
                        f for f in default_fuels[fuel_type]["all"] if f != primary
                    ][0]

            primary_share = fuel_blend[fuel_type]["primary"]["share"]
            secondary_share = 1 - np.array(primary_share)

        else:
            primary = default_fuels[fuel_type]["primary"]
            secondary = default_fuels[fuel_type]["secondary"]
            secondary_share = self.get_share_biofuel()
            primary_share = 1 - np.array(secondary_share)

        return primary, secondary, primary_share, secondary_share

    def define_fuel_blends(self, fuel_blend=None):
        """
        This function defines fuel blends from what is passed in `fuel_blend`.
        It populates a dictionary `self.fuel_blends` that contains the respective shares, lower heating values
        and CO2 emission factors of the fuels used.
        :return:
        """

        fuels_lhv = {
            "diesel": 42.8,
            "biodiesel - cooking oil": 31.7,
            "biodiesel - algae": 31.7,
            "synthetic diesel": 43.3,
            "cng": 55.5,
            "biogas - sewage sludge": 55.5,
            "biogas - biowaste": 55.5,
            "syngas": 55.5,
            "electrolysis": 120,
            "smr - natural gas": 120,
            "smr - natural gas with CCS": 120,
            "smr - biogas": 120,
            "smr - biogas with CCS": 120,
            "atr - natural gas": 120,
            "atr - natural gas with CCS": 120,
            "atr - biogas": 120,
            "atr - biogas with CCS": 120,
            "coal gasification": 120,
            "wood gasification": 120,
            "wood gasification with CCS": 120,
            "wood gasification with EF": 120,
            "wood gasification with EF with CCS": 120,
        }

        fuels_CO2 = {
            "diesel": 3.14,
            "biodiesel - cooking oil": 2.85,
            "biodiesel - algae": 2.85,
            "synthetic diesel": 3.16,
            "cng": 2.65,
            "biogas - sewage sludge": 2.65,
            "biogas - biowaste": 2.65,
            "syngas": 2.65,
            "electrolysis": 0,
            "smr - natural gas": 0,
            "smr - natural gas with CCS": 0,
            "smr - biogas": 0,
            "smr - biogas with CCS": 0,
            "atr - natural gas": 0,
            "atr - natural gas with CCS": 0,
            "atr - biogas": 0,
            "atr - biogas with CCS": 0,
            "coal gasification": 0,
            "wood gasification": 0,
            "wood gasification with CCS": 0,
            "wood gasification with EF": 0,
            "wood gasification with EF with CCS": 0,
        }

        if fuel_blend is None:
            fuel_blend = dict()

        fuel_types = ["diesel", "cng", "hydrogen"]

        for fuel_type in fuel_types:
            primary, secondary, primary_share, secondary_share = self.find_fuel_shares(
                fuel_blend, fuel_type
            )

            fuel_blend[fuel_type] = {
                "primary": {
                    "type": primary,
                    "share": primary_share,
                    "lhv": fuels_lhv[primary],
                    "CO2": fuels_CO2[primary],
                },
                "secondary": {
                    "type": secondary,
                    "share": secondary_share,
                    "lhv": fuels_lhv[secondary],
                    "CO2": fuels_CO2[secondary],
                },
            }

        return fuel_blend
