from copy import deepcopy
from itertools import product
from numbers import Integral, Real

import numexpr as ne
import numpy as np
import xarray as xr
import yaml
from carculator_utils.energy_consumption import (
    EnergyConsumptionModel,
    get_default_driving_cycle_name,
)
from carculator_utils.model import VehicleModel
from carculator_utils.model_run import repeatable_run
from carculator_utils.numerical import capital_recovery_factor
from prettytable import PrettyTable

from . import DATA_DIR
from .fuel_cell_battery import FuelCellBatteryProfile
from .hybrid_battery import (
    HybridBatteryProfile,
    avoided_propulsion_fuel,
    size_hybrid_buffer,
)
from .infrastructure import annual_charger_throughput

CARGO_MASSES = DATA_DIR / "payloads.yaml"
# Typical AdBlue density at 20 degrees C; sources in docs/validity.rst.
ADBLUE_DENSITY_KG_PER_L = 1.09


def finite(array, mask_value=0):
    return np.where(np.isfinite(array), array, mask_value)


def _crf(i, n):
    # Capital Recovery Factor with i==0 → 1/n
    return capital_recovery_factor(i, n)


class TruckModel(VehicleModel):
    """
    This class represents the entirety of the vehicles considered, with useful attributes, such as an array that stores
    all the vehicles parameters.

    ``array`` is the labelled parameter array. ``ecm`` is the energy-consumption
    model created for the selected driving cycle during a completed run.

    """

    def __init__(
        self,
        array,
        *args,
        cost_overrides=None,
        hybrid_battery=None,
        fuel_cell_battery=None,
        **kwargs,
    ):
        """Initialize a truck model with optional explicit cost overrides.

        :param cost_overrides: Cost parameter names mapped to dictionaries of
            (powertrain, size, year): amount. Purchase cost is per vehicle;
            maintenance, insurance, toll and CO2 tax costs are per vehicle-km.
            Explicit zero overrides are retained. Without an explicit override,
            zero array entries continue to request calculated defaults.
        :param hybrid_battery: Overrides for the high-power HEV cell and pack
            envelope; see :class:`HybridBatteryProfile` for names and units.
            Ratings assume a conditioned pack, not ambient-temperature cells.
        :param fuel_cell_battery: Overrides for the FCEV pack-level energy,
            mass and power proxy; see :class:`FuelCellBatteryProfile`. Chemistry
            remains the inventory/cost proxy; pack specifications are independent.
        """
        self.hybrid_battery_profile = HybridBatteryProfile(**(hybrid_battery or {}))
        self.hybrid_battery_profile.validate()
        self.fuel_cell_battery_profile = FuelCellBatteryProfile(
            **(fuel_cell_battery or {})
        )
        self.fuel_cell_battery_profile.validate()
        super().__init__(array, *args, **kwargs)
        self.cost_overrides = deepcopy({} if cost_overrides is None else cost_overrides)
        allowed = {
            "purchase cost",
            "maintenance cost",
            "insurance cost",
            "toll cost",
            "CO2 tax cost",
        }
        if not isinstance(self.cost_overrides, dict):
            raise ValueError("cost_overrides must be a dictionary.")
        for parameter, overrides in self.cost_overrides.items():
            if parameter not in allowed:
                raise ValueError(f"Unsupported cost override {parameter!r}.")
            if not isinstance(overrides, dict):
                raise ValueError(f"Cost override {parameter!r} must be a dictionary.")
            for key, amount in overrides.items():
                if (
                    not isinstance(key, tuple)
                    or len(key) != 3
                    or not all(isinstance(label, str) for label in key[:2])
                    or isinstance(key[2], (bool, np.bool_))
                    or not isinstance(key[2], Integral)
                ):
                    raise ValueError(
                        f"Cost override {parameter!r}: expected "
                        "(powertrain, size, year) keys."
                    )
                for dimension, label in zip(("powertrain", "size", "year"), key):
                    if label not in self.array.get_index(dimension):
                        raise ValueError(
                            f"Cost override {parameter!r}: unknown {dimension} {label!r}."
                        )
                if (
                    isinstance(amount, (bool, np.bool_))
                    or not isinstance(amount, Real)
                    or not np.isfinite(amount)
                    or amount < 0
                ):
                    raise ValueError(
                        f"Cost override {parameter!r} at {key!r} "
                        "must be finite and nonnegative."
                    )

    def _set_cost_with_default(self, parameter, default):
        """Fill legacy zero cells while preserving explicit overrides."""
        self[parameter] = self[parameter].where(self[parameter] != 0, default)
        for (powertrain, size, year), amount in self.cost_overrides.get(
            parameter, {}
        ).items():
            self.array.loc[
                dict(parameter=parameter, powertrain=powertrain, size=size, year=year)
            ] = amount

    def set_power_parameters(self):
        """Use a declared shaft rating where supplied, then caller overrides.

        Zero or absent ``rated power`` retains mass-based sizing. Keeping a
        documented rating independent of curb mass avoids shrinking a motor
        when storage or other components become lighter. Values are in kW.
        """
        super().set_power_parameters()
        if "rated power" not in self.array.parameter.values:
            return
        rated = self["rated power"]
        if np.any(~np.isfinite(rated)) or np.any(rated < 0):
            raise ValueError("Rated power must be finite and nonnegative.")
        use_rated = rated > 0
        for key, value in (self.power or {}).items():
            if value:
                use_rated.loc[dict(zip(("powertrain", "size", "year"), key))] = False
        self["power"] = xr.where(use_rated, rated, self["power"])
        self["combustion power"] = self["power"] * self["combustion power share"]
        electric_share = 1 - self["combustion power share"]
        if "electric motor power share" in self.array.parameter.values:
            share = self["electric motor power share"]
            electric_share = xr.where(share > 0, share, electric_share)
        self["electric power"] = self["power"] * electric_share

    @repeatable_run
    def set_all(self, electric_utility_factor: float = None):
        """
        This method runs a series of other methods to obtain the tank-to-wheel energy requirement,
        efficiency of the vehicle, costs, etc.

        :meth:`set_component_masses()`, :meth:`set_vehicle_masses()` and :meth:`set_power_parameters()` and
        :meth:`set_energy_stored_properties` relate to one another.
        `powertrain_mass` depends on `power`, `curb_mass` is affected by changes in `powertrain_mass`,
        `combustion engine mass`, `electric engine mass`. `energy battery mass` is influencedby the `curb mass` but also
        by the `target range` the truck has. `power` is also varying with `curb_mass`.

        Sizing converges driving mass, available payload, battery mass, fuel
        mass and TtW energy together to a relative tolerance of 1e-6 per active
        vehicle, year and sample. Payload limits are applied within the loop.
        The final energy trace uses the final driving mass. Iterations are
        bounded; nonconvergence raises rather than returning a partial vehicle.
        Numerical convergence does not establish real-world duty feasibility.

        :param electric_utility_factor: the share of km driven in battery-depleting mode over the required range autonomy
        :return: Does not return anything. Modifies ``self.array`` in place.
        """

        # repeatable_run restores caller inputs before each completed run.
        # Keep those inputs separate from values calculated by this routine.
        self._replacement_inputs = self.array.sel(
            parameter=[
                "battery lifetime replacements",
                "fuel cell lifetime replacements",
            ]
        ).copy(deep=True)
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

        # The availability policy below excludes electrified trucks before 2020.
        # PHEV intermediates inherit the same policy as their final powertrain.
        sizing_available = (self.array.year >= 2020) | ~self.array.powertrain.isin(
            ["BEV", "FCEV", "PHEV-d", "HEV-d", "PHEV-e", "PHEV-c-d"]
        )
        requested_cargo = self["cargo mass"].copy(deep=True)
        for _ in self.iterate_sizing(
            [
                "driving mass",
                "available payload",
                "energy battery mass",
                "fuel mass",
                "TtW energy",
            ],
            rtol=1e-6,
            mask=sizing_available,
        ):

            if self.target_mass:
                self.override_vehicle_mass()
            else:
                self.set_vehicle_masses()

            self.set_power_parameters()
            self.set_auxiliaries()
            self.set_fuel_cell_power()
            self.set_fuel_cell_mass()

            self.set_component_masses()
            self.set_recuperation()
            self.set_battery_preferences()

            self.calculate_ttw_energy()
            self.set_ttw_efficiency()

            self.set_share_recuperated_energy()

            self.set_energy_stored_properties()
            self.set_power_battery_properties()

            self.set_vehicle_masses()
            # Reapply the requested load, not the previous clipped value: a
            # lighter converging powertrain can free payload in the next step.
            self["cargo mass"] = np.minimum(
                requested_cargo.clip(min=0), self["available payload"].clip(min=0)
            )
            self.set_vehicle_masses()

        # Storage was sized from the last cycle calculation. Its residual is
        # bounded above; refresh energy at the final mass before costs, direct
        # emissions, fuel/grid purchases and inventories consume those outputs.
        self.calculate_ttw_energy()
        self.check_fuel_cell_battery_power()
        self.set_ttw_efficiency()
        self.set_share_recuperated_energy()
        self.set_electric_utility_factor(electric_utility_factor)
        self.set_battery_fuel_cell_replacements()

        self["capacity utilization"] = np.clip(
            (self["cargo mass"] / self["available payload"]), 0, 1
        )

        self.set_electricity_consumption()
        self.set_costs()
        self.set_particulates_emission()
        self.set_noise_emissions()
        self.set_hot_emissions()
        self.create_PHEV()
        if self.drop_hybrids:
            self.drop_hybrid()

        self.remove_energy_consumption_from_unavailable_vehicles()

    def create_PHEV(self):
        """Combine driving modes while retaining the actual depot charger specs."""
        super().create_PHEV()
        if "PHEV-d" in self.array.powertrain.values:
            # Hardware characteristics and depot share are not weighted prices
            # or energy demands. Retain them even at zero electric-driving share.
            parameters = [
                "depot charger power",
                "depot charger lifetime",
                "trucks per depot charger",
                "share depot charging",
                "battery cycle life",
            ]
            self.array.loc[dict(powertrain="PHEV-d", parameter=parameters)] = (
                self.array.sel(powertrain="PHEV-e", parameter=parameters, drop=True)
            )

    def set_cargo_mass_and_annual_mileage(self):
        """Set the cargo mass and annual mileage of the vehicles."""

        if self.payload:
            for s in self.array.coords["size"].values:
                for p in self.array.coords["powertrain"].values:
                    for y in self.array.coords["year"].values:
                        if (p, s, y) in self.payload:
                            self.array.loc[
                                dict(
                                    size=s, powertrain=p, year=y, parameter="cargo mass"
                                )
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
                        if (p, s, y) in self.annual_mileage:
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
                self.array.loc[dict(size=s, parameter="kilometers per year")] = (
                    annual_mileage[cycle][s]
                )

    def set_battery_chemistry(self):
        # override default values for batteries
        # if provided by the user
        if "electric" not in self.energy_storage:
            self.energy_storage["electric"] = {}

        default_chemistries = {
            2000: "NMC-111",
            2005: "NMC-111",
            2010: "NMC-111",
            2015: "NMC-111",
            2020: "NMC-622",
            2025: "NMC-811",
            2030: "NMC-811",
            2035: "NMC-955",
        }

        years_sorted = sorted(default_chemistries.keys())

        for x in product(
            self.array.coords["powertrain"].values,
            self.array.coords["size"].values,
            self.array.year.values,
        ):
            year = x[-1]

            if x not in self.energy_storage["electric"]:
                if x[0] == "HEV-d":
                    self.energy_storage["electric"][x] = "LFP"
                elif year in default_chemistries:
                    # exact match
                    self.energy_storage["electric"][x] = default_chemistries[year]
                elif year < years_sorted[0]:
                    # below the lowest year
                    self.energy_storage["electric"][x] = default_chemistries[
                        years_sorted[0]
                    ]
                elif year > years_sorted[-1]:
                    # above the highest year
                    self.energy_storage["electric"][x] = default_chemistries[
                        years_sorted[-1]
                    ]
                else:
                    # find the closest lower year
                    lower_years = [y for y in years_sorted if y <= year]
                    closest = max(lower_years)
                    self.energy_storage["electric"][x] = default_chemistries[closest]

        if "origin" not in self.energy_storage:
            self.energy_storage.update({"origin": "CN"})

    def set_battery_preferences(self):
        """Apply high-power cell density to the default HEV LFP pack.

        Other explicit chemistries retain their density and cycle life; the
        electrical envelope is a transfer assumption unless the caller also
        supplies a matching ``hybrid_battery`` profile.
        """
        super().set_battery_preferences()
        if "FCEV" in self.array.powertrain.values:
            profile = self.fuel_cell_battery_profile
            for name, value in {
                "battery cell mass share": profile.cell_mass_share,
                "battery cell energy density": profile.cell_energy_density,
                "battery cell power density": profile.discharge_10s_kw
                / (profile.pack_kg * profile.cell_mass_share),
            }.items():
                if name in self.array.parameter.values:
                    self.array.loc[dict(powertrain="FCEV", parameter=name)] = value
        profile = self.hybrid_battery_profile
        self.hybrid_battery_profile_transfers = []
        for (pt, size, year), chemistry in self.energy_storage.get(
            "electric", {}
        ).items():
            if (
                pt != "HEV-d"
                or chemistry is None
                or any(
                    label not in self.array[dimension].values
                    for dimension, label in (
                        ("powertrain", pt),
                        ("size", size),
                        ("year", year),
                    )
                )
            ):
                continue
            selection = dict(powertrain=pt, size=size, year=year)
            if chemistry == "LFP":
                self.array.loc[
                    dict(parameter="battery cell energy density", **selection)
                ] = (profile.cell_energy_kwh / profile.cell_mass_kg)
                self.array.loc[
                    dict(parameter="battery cell mass share", **selection)
                ] = profile.cell_mass_share
            else:
                self.hybrid_battery_profile_transfers.append(
                    (pt, size, year, chemistry)
                )
            self.array.loc[dict(parameter="battery DoD", **selection)] = (
                profile.usable_share
            )

    def calculate_hybrid_buffer(self):
        """Size and cycle the HEV pack on the current mass-dependent trace."""
        self.hybrid_buffer_results = {}
        if "HEV-d" not in self.array.powertrain.values:
            return
        for size, year, sample in product(
            self.array["size"].values, self.array.year.values, self.array.value.values
        ):
            if year < 2020:
                continue
            selection = dict(size=size, powertrain="HEV-d", year=year, value=sample)
            cell = self.array.sel(selection)
            val = lambda name: float(cell.sel(parameter=name))
            trace = self.energy.sel(selection)
            motor_efficiency = float(
                self.get_electric_motor_efficiency().sel(selection)
            )
            eta_charge = val("battery charge efficiency")
            eta_discharge = val("battery discharge efficiency")
            if (
                not 0 < motor_efficiency <= 1
                or not 0 < eta_charge <= 1
                or not 0 < eta_discharge <= 1
            ):
                raise ValueError(
                    "Active HEV motor and battery efficiencies must be in (0, 1]."
                )
            recovered_dc = -trace.sel(parameter="recuperated energy").values
            generator_dc = recovered_dc / eta_charge / eta_discharge
            wheels = trace.sel(parameter="motive energy at wheels").values
            transmission = trace.sel(parameter="transmission efficiency").values
            shaft = np.divide(
                wheels, transmission, out=np.zeros_like(wheels), where=transmission > 0
            )
            motor_dc = val("electric power") / motor_efficiency
            propulsion_dc = np.minimum(shaft / motor_efficiency, motor_dc)
            override = self.energy_storage.get("capacity", {}).get(
                ("HEV-d", size, year)
            )
            result = size_hybrid_buffer(
                generator_dc,
                propulsion_dc,
                motor_dc,
                eta_charge,
                eta_discharge,
                profile=self.hybrid_battery_profile,
                capacity_kwh=None if override is None or override == 0 else override,
            )
            distance = float(trace.sel(parameter="velocity").sum("second")) / 1000
            if not np.isfinite(distance) or distance <= 0:
                raise ValueError(
                    "Active HEV battery cycling requires a positive cycle distance."
                )
            result["discharged_stored_kwh_per_km"] = result["discharged_kwh"] / distance
            result["unconstrained_reusable_dc_kwh"] = float(recovered_dc.sum()) / 3600
            self.hybrid_buffer_results[(size, year, sample)] = result
            # Keep the existing cycle-average fuel-conversion boundary, but
            # apply the fuel cap only after the finite pack's energy balance.
            credit = avoided_propulsion_fuel(
                result["discharged_dc_kwh"],
                motor_efficiency,
                wheels,
                transmission,
                trace.sel(parameter="motive energy").values,
            )
            self.regeneration_credit.loc[selection] = -credit / distance

    def override_range(self):
        """
        Set storage size or range for each powertrain.
        """

        target_ranges = {
            "Urban delivery": 150,
            "Regional delivery": 400,
            "Long haul": 800,
        }

        if self.target_range is not None:
            target_range = self.target_range
        elif isinstance(self.cycle, str):
            target_range = {}
            for pwt in self.array.coords["powertrain"].values:
                for size in self.array.coords["size"].values:
                    for year in self.array.coords["year"].values:
                        target_range[(pwt, size, year)] = target_ranges[self.cycle]

        else:
            target_range = {}
            for pwt in self.array.coords["powertrain"].values:
                for size in self.array.coords["size"].values:
                    for year in self.array.coords["year"].values:
                        target_range[(pwt, size, year)] = 800

        for key, val in target_range.items():
            pwt, size, year = key
            self.array.loc[
                dict(
                    powertrain=pwt,
                    size=size,
                    year=year,
                    parameter="target range",
                )
            ] = val

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
            f"a minimal range of {set(target_range.values())} km."
        )

        print("")

    def set_share_recuperated_energy(self):
        """Apply the finite HEV buffer to the inherited brake-wear credit."""
        super().set_share_recuperated_energy()
        if "FCEV" in self.array.powertrain.values:
            trace = self.energy.sel(parameter="negative motive energy", drop=True)
            direct = (
                xr.DataArray(
                    self.ecm.regenerative_auxiliary_dc_kw,
                    dims=trace.dims,
                    coords=trace.coords,
                )
                .sel(powertrain="FCEV", drop=True)
                .sum("second")
            )
            # Retain the inherited conservative wear proxy, including its
            # conversion discount. Direct auxiliary use still avoids braking;
            # curtailed energy receives no wear credit.
            accepted = -self.energy.sel(
                parameter="recuperated energy", powertrain="FCEV", drop=True
            ).sum("second") + direct * (
                self["battery charge efficiency"] * self["battery discharge efficiency"]
            ).sel(
                powertrain="FCEV", drop=True
            )
            braking = -trace.sel(powertrain="FCEV", drop=True).sum("second")
            ratio = (accepted / xr.where(braking > 0, braking, 1)).clip(0, 1)
            self.array.loc[
                dict(parameter="share recuperated energy", powertrain="FCEV")
            ] = ratio.transpose("size", "year", "value")
        for (size, year, sample), balance in getattr(
            self, "hybrid_buffer_results", {}
        ).items():
            potential = balance["unconstrained_reusable_dc_kwh"]
            fraction = balance["discharged_dc_kwh"] / potential if potential > 0 else 0
            self.array.loc[
                dict(
                    parameter="share recuperated energy",
                    powertrain="HEV-d",
                    size=size,
                    year=year,
                    value=sample,
                )
            ] *= min(fraction, 1)

    def calculate_ttw_energy(self):
        """
        This method calculates the energy required to operate
        auxiliary services as well as to move the vehicle.
        The sum is stored under the parameter label "TtW energy"
        in :attr:`self.array`.
        """

        self.energy = self.ecm.motive_energy_per_km(
            engine_efficiency=self.get_energy_efficiency_override("engine efficiency"),
            engine_efficiency_factor=xr.where(
                self.array.powertrain == "ICEV-g",
                1 - self["CNG engine efficiency correction factor"],
                1.0,
            ).transpose("size", "powertrain", "year", "value"),
            transmission_efficiency=self.get_energy_efficiency_override(
                "transmission efficiency"
            ),
            driving_mass=self["driving mass"],
            rr_coef=self["rolling resistance coefficient"],
            drag_coef=self["aerodynamic drag coefficient"],
            frontal_area=self["frontal area"],
            electric_motor_power=self["electric power"],
            engine_power=self["power"],
            combustion_engine_power=self["combustion power"],
            recuperation_efficiency=self["recuperation efficiency"],
            electric_motor_efficiency=self.get_electric_motor_efficiency(),
            aux_power=self["auxiliary power demand"],
            battery_charge_eff=self["battery charge efficiency"],
            battery_discharge_eff=self["battery discharge efficiency"],
            fuel_cell_system_efficiency=self["fuel cell system efficiency"],
            battery_charge_power=xr.where(
                self.array.powertrain == "FCEV",
                self["electric energy stored"]
                * self.fuel_cell_battery_profile.charge_kw
                / self.fuel_cell_battery_profile.nominal_kwh,
                np.inf,
            ).transpose("size", "powertrain", "year", "value"),
        )

        self.energy = self.energy.assign_coords(
            {
                "powertrain": self.array.powertrain,
                "year": self.array.year,
                "size": self.array.coords["size"],
                "value": self.array.coords["value"],
            }
        )

        if self.energy_consumption:
            self.override_ttw_energy()

        distance = self.energy.sel(parameter="velocity").sum(dim="second") / 1000

        self["transmission efficiency"] = (
            np.ma.array(
                self.energy.loc[dict(parameter="transmission efficiency")],
                mask=self.energy.loc[dict(parameter="power load")] == 0.0,
            )
            .mean(axis=0)
            .T
        )

        self["engine efficiency"] = (
            np.ma.array(
                self.energy.loc[dict(parameter="engine efficiency")],
                mask=self.energy.loc[dict(parameter="power load")] == 0.0,
            )
            .mean(axis=0)
            .T
        )

        self["TtW energy"] = (
            self.energy.sel(
                parameter=[
                    "motive energy",
                    "auxiliary energy",
                ]
            ).sum(dim=["second", "parameter"])
            / distance
        ).T

        self.get_regeneration_credit()
        self.calculate_hybrid_buffer()
        self["TtW energy"] += self.regeneration_credit.transpose(
            "size", "powertrain", "year", "value"
        )
        self.set_battery_energy_balance()

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
        Calculate battery and fuel-cell replacement demand.

        After sizing, each zero supplied battery replacement input requests a
        calculation from final lifetime energy throughput and chemistry-specific
        cycle life, clipped to 0–3 for charger-equipped vehicles. Nonzero supplied
        inputs are retained per vehicle, year and sample. The factor
        is not rounded up and there is no mandatory replacement battery.
        Production is allocated to this vehicle without a second-life credit.
        Fuel cells use a separate lifetime-hours calculation, rounded up.

        PHEV lifetime energy is weighted by electric driving share BEFORE
        subtracting the initial pack and clipping. The resulting physical count
        belongs to both modes. Nonzero PHEV count inputs are whole-vehicle counts;
        conflicting values for the same pack are rejected rather than averaged.
        This retains the net stored-energy approximation, nominal-capacity EFC
        convention and absence of a separate truck calendar-age limit.
        """

        _ = lambda array: np.where(array == 0, 1, array)

        if not hasattr(self, "_replacement_inputs"):
            # Support explicit component calls as well as completed runs.
            self._replacement_inputs = self.array.sel(
                parameter=[
                    "battery lifetime replacements",
                    "fuel cell lifetime replacements",
                ]
            ).copy(deep=True)

        def supplied(parameter):
            current = self[parameter]
            return self._replacement_inputs.sel(
                parameter=parameter,
                **{dim: current[dim] for dim in current.dims},
            )

        lifetime_energy = self["lifetime kilometers"] * self["TtW energy"] / 3600
        if "PHEV-d" in self.array.powertrain.values:
            share = self["electric utility factor"].sel(powertrain="PHEV-e", drop=True)
            if bool((~np.isfinite(share) | (share < 0) | (share > 1)).any()):
                raise ValueError(
                    "PHEV electric utility factor must be finite and in [0, 1]."
                )
            lifetime_energy.loc[dict(powertrain="PHEV-e")] *= share
        battery = np.clip(
            (
                lifetime_energy
                / _(self["electric energy stored"])
                / _(self["battery cycle life"])
                - 1
            ),
            0,
            3,
        ) * (self["charger mass"] > 0)
        inputs = supplied("battery lifetime replacements")
        self["battery lifetime replacements"] = inputs.where(inputs != 0, battery)
        for (size, year, sample), result in getattr(
            self, "hybrid_buffer_results", {}
        ).items():
            selection = dict(size=size, powertrain="HEV-d", year=year, value=sample)
            life = float(self["lifetime kilometers"].sel(selection))
            cycles = float(self["battery cycle life"].sel(selection))
            capacity = float(self["electric energy stored"].sel(selection))
            if any(not np.isfinite(x) or x <= 0 for x in (life, cycles, capacity)):
                raise ValueError(
                    "Active HEV batteries require positive finite lifetime, cycle life and capacity."
                )
            count = np.clip(
                life * result["discharged_stored_kwh_per_km"] / capacity / cycles - 1,
                0,
                3,
            )
            supplied_count = float(inputs.sel(selection))
            if not np.isfinite(supplied_count) or supplied_count < 0:
                raise ValueError(
                    "HEV battery replacement counts must be finite and nonnegative."
                )
            self.array.loc[
                dict(parameter="battery lifetime replacements", **selection)
            ] = (supplied_count or count)
        if "PHEV-d" in self.array.powertrain.values:
            explicit = inputs.sel(powertrain=["PHEV-e", "PHEV-c-d", "PHEV-d"])
            if bool((~np.isfinite(explicit) | (explicit < 0)).any()):
                raise ValueError(
                    "PHEV battery replacement inputs must be finite and nonnegative."
                )
            specified = explicit.max("powertrain")
            if bool(((explicit != 0) & (explicit != specified)).any()):
                raise ValueError(
                    "Conflicting PHEV battery replacement counts for one physical pack."
                )
            count = specified.where(
                specified != 0, battery.sel(powertrain="PHEV-e", drop=True)
            )
            self.array.loc[
                dict(powertrain="PHEV-e", parameter="battery lifetime replacements")
            ] = count
            self.share_phev_battery_replacements()

        # The number of fuel cell replacements is based on the
        # average distance driven with a set of fuel cells given
        # their lifetime expressed in hours of use.
        # The number of replacement is rounded *up* as we assume
        # no allocation of burden with a second life

        # 1) Pull velocity (m/s) over the whole drive cycle; include zeros for stops.
        vel = self.energy.sel(parameter="velocity")
        vel = vel.fillna(0)

        if "value" in vel.dims and vel.sizes["value"] == 1:
            vel = vel.squeeze("value", drop=True)

        # 2) Duration of the representative cycle in hours (1 sec timestep assumed by your coords).
        duration_h = vel.sizes["second"] / 3600.0

        # 3) Distance covered by the representative cycle in km (∑ v*dt, with dt=1 s).
        duty_km = vel.sum(dim="second") / 1000.0

        # Guard against degenerate cycles
        duty_km = xr.where(duty_km > 0, duty_km, np.nan)

        # 4) Convert lifetime kilometers → required stack operating hours, including idle:
        #    lifetime_hours_required = lifetime_km * (duration_h / duty_km)
        lifetime_hours_required = self["lifetime kilometers"] * (duration_h / duty_km)

        # 5) Stacks needed and replacements
        fc_life_h = _(self["fuel cell lifetime hours"])
        stacks_needed = lifetime_hours_required / fc_life_h

        replacements = xr.apply_ufunc(np.ceil, stacks_needed) - 1
        replacements = replacements.clip(min=0, max=5)

        inputs = supplied("fuel cell lifetime replacements")
        self["fuel cell lifetime replacements"] = inputs.where(
            inputs != 0, replacements * (self["fuel cell stack mass"] > 0)
        )

    def set_vehicle_masses(self):
        """
        Define ``curb mass``, ``driving mass``, and ``cargo mass``.

        * `curb mass <https://en.wikipedia.org/wiki/Curb_weight>`__ is the mass of the vehicle and fuel, without people or cargo.
        * ``cargo mass`` is the mass of the cargo and passengers.
        * ``driving mass`` is the ``curb mass`` plus ``cargo mass``.

        .. note:: driving mass = cargo mass + driving mass
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
            "starter battery mass",
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
        The electric utility factor is the share of km driven in battery-depleting mode
        over the required range autonomy. Scania's PHEV tractor can drive 60 km in electric mode
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
        Then batteries are sized, depending on the range required and the energy consumption.
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

        if "capacity" in self.energy_storage:
            self.override_battery_capacity()
        else:
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
            minimum = self.fuel_cell_battery_capacity_requirement()
            self.array.loc[
                dict(powertrain="FCEV", parameter="electric energy stored")
            ] = np.maximum(
                self["electric energy stored"].sel(powertrain="FCEV"), minimum
            )
            # Explicit capacity is authoritative. Validate it at the converged
            # vehicle mass, rather than silently replacing it by the heuristic.
            for (pt, size, year), capacity in self.energy_storage.get(
                "capacity", {}
            ).items():
                if pt == "FCEV" and np.any(np.asarray(capacity) != 0):
                    if np.any(~np.isfinite(capacity)) or np.any(
                        np.asarray(capacity) <= 0
                    ):
                        raise ValueError(
                            "Explicit FCEV capacity must be finite and positive."
                        )
                    self.array.loc[
                        dict(
                            powertrain=pt,
                            size=size,
                            year=year,
                            parameter="electric energy stored",
                        )
                    ] = capacity

        for (size, year, sample), result in getattr(
            self, "hybrid_buffer_results", {}
        ).items():
            self.array.loc[
                dict(
                    parameter="electric energy stored",
                    powertrain="HEV-d",
                    size=size,
                    year=year,
                    value=sample,
                )
            ] = result["nominal_kwh"]

        self["battery cell mass"] = self["electric energy stored"] / _(
            self["battery cell energy density"]
        )

        self["energy battery mass"] = self["battery cell mass"] / _(
            self["battery cell mass share"]
        )

        self["battery BoP mass"] = (
            self["energy battery mass"] - self["battery cell mass"]
        )

    def set_fuel_cell_mass(self):
        """Size the stack without replacing the truck's final energy-sized pack."""
        names = [
            "battery cell mass",
            "energy battery mass",
            "battery BoP mass",
            "electric energy stored",
        ]
        saved = None
        if "FCEV" in self.array.powertrain.values:
            saved = self.array.sel(powertrain="FCEV", parameter=names).copy(deep=True)
        super().set_fuel_cell_mass()
        if saved is not None:
            self.array.loc[dict(powertrain="FCEV", parameter=names)] = saved

    def fuel_cell_battery_capacity_requirement(self):
        """Check cycle discharge at the DC bus, retaining unmet speed-trace demand."""
        trace = self.energy.sel(parameter="motive energy", drop=True)
        auxiliary = xr.DataArray(
            self.ecm.auxiliary_dc_demand_kw, dims=trace.dims, coords=trace.coords
        )
        demand = (trace * self["fuel cell system efficiency"] + auxiliary).sel(
            powertrain="FCEV", drop=True
        )
        stack = (self["fuel cell power"] / self["fuel cell own consumption"]).sel(
            powertrain="FCEV", drop=True
        )
        discharge = (demand - stack).clip(min=0).max("second")
        return self.fuel_cell_battery_profile.required_capacity(
            discharge, self["battery power"].sel(powertrain="FCEV", drop=True)
        ).transpose("size", "year", "value")

    def check_fuel_cell_battery_power(self):
        """Reject an undersized supplied pack after the mass iteration converges."""
        if "FCEV" not in self.array.powertrain.values:
            return
        required = self.fuel_cell_battery_capacity_requirement()
        capacity = self["electric energy stored"].sel(powertrain="FCEV", drop=True)
        invalid = ((capacity < required * (1 - 3e-6)) | ~np.isfinite(capacity)) & (
            capacity.year >= 2020
        )
        if bool(invalid.any()):
            raise ValueError(
                "FCEV battery cannot supply the requested cycle or rated motor buffer; "
                "increase explicit capacity or supply a justified fuel_cell_battery profile."
            )

    def set_power_battery_properties(self):
        """Keep the HEV starter separate from its lithium-ion traction pack."""
        if "HEV-d" not in self.array.powertrain.values:
            return super().set_power_battery_properties()
        components = ["battery cell mass", "battery BoP mass"]
        traction = self.array.sel(powertrain="HEV-d", parameter=components).copy(
            deep=True
        )
        super().set_power_battery_properties()
        self.array.loc[dict(powertrain="HEV-d", parameter=components)] = traction
        power = self["battery power"].sel(powertrain="HEV-d")
        density = self["battery cell power density"].sel(powertrain="HEV-d")
        if bool(((power > 0) & (~np.isfinite(density) | (density <= 0))).any()):
            raise ValueError(
                "Active HEV starter batteries require positive power density."
            )
        cell_mass = power / density.where(power > 0, 1)
        # Retain the inherited starter-mass heuristic, separately from Li-ion
        # capacity and manufacture. Traction cell mass must not inflate it.
        self.array.loc[dict(powertrain="HEV-d", parameter="starter battery mass")] = (
            cell_mass * (2 - self["battery cell mass share"].sel(powertrain="HEV-d"))
        )

    def set_depot_infrastructure_costs(
        self,
        charger_power_kw,
        charger_life_years,
        infra_wacc,
        capex_per_kw,
        install_per_kw,
        connection_per_kw,
        fixed_om_share,
        capacity_charge_per_kw_year,
        trucks_per_charger,
        annual_km_per_truck,
        consumption_kwh_per_km_at_plug,
        availability=0.98,
        efficiency=0.94,
    ):
        """
        Returns a DataArray of depot infra surcharge in €/kWh with full xarray broadcasting.
        All inputs can be scalars or DataArrays aligned/broadcastable to your model dims.
        """

        # Non-charging vehicles have zero charger lifetime in the parameter
        # grid. Validate financial inputs only for actual charging infrastructure.
        has_charger = charger_power_kw > 0
        i = xr.where(has_charger, infra_wacc, 0.0)
        N = xr.where(has_charger, charger_life_years, 1.0)
        CRF = _crf(i, N)

        # Upfront per charger (€/kW * kW)
        upfront_per_charger = charger_power_kw * (
            capex_per_kw + install_per_kw + connection_per_kw
        )

        # Annualized fixed cost per charger (€/year)
        annual_capital = CRF * upfront_per_charger
        annual_om = fixed_om_share * upfront_per_charger
        annual_capacity = capacity_charge_per_kw_year * charger_power_kw
        annual_cost_per_charger = annual_capital + annual_om + annual_capacity

        # Annual energy per charger (kWh/year)
        E = annual_charger_throughput(
            charger_power_kw,
            trucks_per_charger,
            annual_km_per_truck,
            consumption_kwh_per_km_at_plug,
            availability,
            efficiency,
        )

        # Guard against zero/near-zero energy to avoid div-by-zero
        E = xr.where(E > 0, E, np.nan)

        # €/kWh surcharge
        surcharge_per_kWh = annual_cost_per_charger / E

        # replace NaN with 0
        return xr.where(np.isfinite(surcharge_per_kWh), surcharge_per_kWh, 0.0)

    def set_costs(self):
        _nz = lambda x: np.where(x < 1, 1, x)

        glider_components = [
            "glider base mass",
            "suspension mass",
            "braking system mass",
            "wheels and tires mass",
            "cabin mass",
        ]

        self["glider cost"] = self["glider base cost per kg"] * self[
            glider_components
        ].sum(axis=2)

        # Discount glider cost for 40t and 60t trucks
        # because of the added trailer mass

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
            self["energy battery cost per kWh"] * self.battery_capacity_for_purchase()
        )

        self["fuel tank cost"] = self["fuel tank cost per kg"] * self["fuel mass"]

        # Per vkm, with the existing depot/public tariff weighting.
        energy_price = self["energy cost per kWh (depot)"] * self[
            "share depot charging"
        ] + self["energy cost per kWh (public)"] * (1 - self["share depot charging"])
        self["energy cost"] = energy_price * self["TtW energy"] / 3600
        self.set_electricity_costs(energy_price)

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
            "battery onboard charging infrastructure cost",
            "combustion exhaust treatment cost",
            "heat pump cost",
        ]

        self[to_markup] *= self["markup factor"]

        # calculate costs per km:
        self["lifetime"] = self["lifetime kilometers"] / self["kilometers per year"]
        i = self["interest rate"]
        lifetime = self["lifetime"]
        amortisation_factor = _crf(i, lifetime)

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

        # we leave the possibility to override the purchase cost
        self._set_cost_with_default(
            "purchase cost", self[purchase_cost_list].sum(dim="parameter")
        )

        # per vkm
        self["amortised purchase cost"] = (
            self["purchase cost"] * amortisation_factor / self["kilometers per year"]
        )

        # EUR/vkm: diesel L/km * AdBlue L/L diesel * AdBlue kg/L * EUR/kg.
        # PHEV combustion costs receive their driving share in create_PHEV().
        self["adblue cost"] = (
            self["adblue cost per kg"]
            * self["adblue use per liter diesel"]
            * self["fuel consumption"]
            * ADBLUE_DENSITY_KG_PER_L
        )

        self._set_cost_with_default(
            "maintenance cost", self["maintenance cost per km"] + self["adblue cost"]
        )

        # --- Insurance (property + liability + optional cargo) with depreciation and discounting ---

        # Inputs
        i = self["interest rate"]  # per year
        n = self["lifetime"]  # years (can be float)
        km_y = self["kilometers per year"]  # vkm/year

        P_ins = self["insured share of purchase cost"] * self["purchase cost"]
        d = self["depreciation rate per year"]  # e.g., 0.18
        if not np.isfinite(d).all() or ((d < 0) | (d > 1)).any():
            raise ValueError(
                "depreciation rate per year must be finite and within [0, 1]."
            )
        r_prop = self["property insurance rate"]  # per € per year
        r_liab = self["liability insurance rate per km"]  # €/km

        loading = 1.0 + self["broker loading share"]
        ipt = 1.0 + self["insurance premium tax"]

        # Capital recovery factor you already computed
        amortisation_factor = _crf(i, n)

        # --- Present value (PV) of premiums in closed form ---

        # Property: PV of r_prop * P_ins * (1 - d)^(t-1) / (1 + i)^(t-1), t=1..n
        # Geometric series with ratio q = (1 - d) / (1 + i)
        q = (1 - d) / (1 + i)
        use_series = np.abs(1 - q) < 1e-12
        # Both branches of where are evaluated. Make the unused denominator and
        # logarithm safe, including the fully depreciated (q == 0) case.
        safe_q = q.where(q > 0, 1)
        geom_sum = -np.expm1(n * np.log(safe_q)) / (1 - q).where(~use_series, 1)
        geom_sum = xr.where(use_series, n, xr.where(q == 0, 1, geom_sum))
        prem_prop_pv = r_prop * P_ins * geom_sum

        # Liability: PV of r_liab * km_y each year for n years, discounted at i
        prem_liab_pv = r_liab * km_y / amortisation_factor
        # Combine, apply loadings & IPT
        prem_total_pv = (prem_prop_pv + prem_liab_pv) * loading * ipt

        # Annualize to €/year, then convert to €/vkm

        self._set_cost_with_default(
            "insurance cost", prem_total_pv * amortisation_factor / km_y
        )

        # --- Other costs ---
        self._set_cost_with_default(
            "toll cost", self["road toll cost per km"] * self["share tolled roads"]
        )

        self._set_cost_with_default("CO2 tax cost", self["CO2 road charge per km"])

        # simple assumption that component replacement occurs at half of life.
        km_per_year = self["kilometers per year"]
        com_repl_cost = self["component replacement cost"]

        df_mid = ne.evaluate("(1 + i) ** (-lifetime / 2)")
        self["amortised component replacement cost"] = ne.evaluate(
            "(com_repl_cost * df_mid * amortisation_factor) / km_per_year"
        )

        # Use grid purchases for both annual throughput and the per-km charge.
        self["energy infrastructure cost"] = (
            self.set_depot_infrastructure_costs(
                charger_power_kw=self["depot charger power"],
                charger_life_years=self["depot charger lifetime"],
                infra_wacc=self["interest rate"],
                capex_per_kw=self["depot charger capex per kW"],
                install_per_kw=self["depot charger installation per kW"],
                connection_per_kw=self["depot charger connection per kW"],
                fixed_om_share=self["depot charger O&M share"],
                trucks_per_charger=self["trucks per depot charger"],
                annual_km_per_truck=self["kilometers per year"],
                consumption_kwh_per_km_at_plug=self["electricity consumption"],
                capacity_charge_per_kw_year=self[
                    "depot charger capacity charger per kW-year"
                ],
            )
            * self["share depot charging"]
            * self["electricity consumption"]
            * (self["TtW energy"] > 0)
        )

        # --- Residual value credit ---
        # per vkm
        rv_share = self["residual value share"]
        sell_year = self["lifetime"]
        fee_share = self["resale fee share"]
        purchase_cost = self["purchase cost"]

        rv = ne.evaluate("rv_share * (1 - fee_share) * purchase_cost")
        df_end = ne.evaluate("(1 + i) ** (-sell_year)")
        self["amortised residual credit"] = ne.evaluate(
            "(-rv * df_end * amortisation_factor) / km_per_year"
        )

        self["total cost per km"] = (
            self["energy cost"]
            + self["energy infrastructure cost"]
            + self["amortised purchase cost"]
            + self["maintenance cost"]
            + self["insurance cost"]
            + self["toll cost"]
            + self["CO2 tax cost"]
            + self["amortised component replacement cost"]
            + self["amortised residual credit"]
        )

    def calculate_cost_impacts(self, sensitivity=False, scope=None):
        """
        This method returns an array with cost values per vehicle-km, subdivided into the following groups:

        * Purchase
        * Maintenance
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
            "CO2 tax",
            "charging infrastructure",
            "component replacement",
            "energy",
            "residual credit",
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
                "CO2 tax cost",
                "energy infrastructure cost",
                "amortised component replacement cost",
                "energy cost",
                "amortised residual credit",
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

        self["is_compliant"] *= self["driving mass"] <= self["gross mass"] + 1e-6

        # we flag trucks that are not compliant
        self["TtW energy"] = np.where(
            (self["is_compliant"] == 0), 0, self["TtW energy"]
        )

        # we zero-out costs for non-compliant vehicles
        cost_params = [
            "total cost per km",
            "energy cost",
            "amortised purchase cost",
            "maintenance cost",
            "insurance cost",
            "toll cost",
            "amortised component replacement cost",
            "amortised residual credit",
            "energy infrastructure cost",
        ]
        self.array.loc[dict(parameter=cost_params)] = np.where(
            (
                self.array.loc[
                    dict(
                        parameter=[
                            "is_compliant",
                        ]
                    )
                ]
                == 0
            ),
            0,
            self.array.loc[dict(parameter=cost_params)],
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

        self.mask_energy_outputs(
            (self["is_available"] != 0) & (self["is_compliant"] != 0)
        )

        # same for costs
        self.array.loc[dict(parameter=cost_params)] = np.where(
            (
                self.array.loc[
                    dict(
                        parameter=[
                            "is_available",
                        ]
                    )
                ]
                == 0
            ),
            0,
            self.array.loc[dict(parameter=cost_params)],
        )

        # Report the sensitivity reference, or the first retained sample.
        # Masses and availability must describe the same sample.
        sample = (
            "reference"
            if "reference" in self.array.coords["value"].values
            else self.array.coords["value"].values[0]
        )
        display = self.array.sel(value=sample)
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
                        (
                            np.round(cargo, 1)
                            if (gross - driving) > 0
                            else f"-{np.round(cargo)}-"
                        )
                        for gross, driving, cargo in (
                            display.sel(
                                parameter=["gross mass", "driving mass", "cargo mass"],
                                powertrain=pt,
                                year=y,
                            )
                            / 1000
                        )
                        .transpose("size", "parameter")
                        .values
                    ]
                )

                # indicate vehicles that are not commercially available
                vals = np.where(
                    display.sel(parameter="is_available", powertrain=pt, year=y).values,
                    vals,
                    "/",
                )

                t.add_row(row + vals.tolist())
        print(t)
