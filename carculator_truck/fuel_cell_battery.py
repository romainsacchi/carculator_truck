"""Coherent FCEV traction-pack proxy, separate from starter-battery inputs."""

from dataclasses import dataclass

import numpy as np

PROFILE_SOURCE = (
    "AKASOL AKASYSTEM 15 OEM 37 PRC, May 2021 manufacturer specification, "
    "explicit proxy for 2020 FCEV trucks: 25 kWh, 238 kg, 36 kW continuous "
    "charge, 50 kW continuous RMS discharge, 150 kW discharge for 10 s. "
    "https://www.act-news.com/wp-content/uploads/2020/11/"
    "210525_LowRes_AK_Datenblatt_AKASystem_15-OEM-37-PRC_2021_2159x2794mm_EN.pdf"
)


@dataclass(frozen=True)
class FuelCellBatteryProfile:
    """Pack-level ratings; nominal energy kWh, mass kg, terminal power kW.

    Continuous RMS discharge is conservatively used as an instantaneous cycle
    ceiling, avoiding an invented pulse-recovery interval. The 10-second rating
    also bounds the rated motor's buffer requirement. These are conditioned-pack
    specifications, not guarantees at arbitrary SOC or ambient temperature.
    No future improvement, SOC window or cycle-life guarantee is inferred.
    """

    nominal_kwh: float = 25.0
    pack_kg: float = 238.0
    charge_kw: float = 36.0
    discharge_kw: float = 50.0
    discharge_10s_kw: float = 150.0
    # Retained manufacturing split, not a measured AKASOL cell fraction.
    cell_mass_share: float = 0.7

    def validate(self):
        for name, value in vars(self).items():
            if not np.isfinite(value) or value <= 0:
                raise ValueError(f"FCEV battery {name} must be finite and positive.")
        if self.cell_mass_share > 1 or self.discharge_kw > self.discharge_10s_kw:
            raise ValueError("Invalid FCEV battery mass share or discharge ratings.")

    @property
    def cell_energy_density(self):
        """Effective allocation density, not a measured cell specification."""
        return self.nominal_kwh / (self.pack_kg * self.cell_mass_share)

    def required_capacity(self, cycle_discharge_kw, rated_buffer_kw):
        """Minimum nominal kWh without assuming repeated short-pulse discharge."""
        return (
            np.maximum(
                cycle_discharge_kw / self.discharge_kw,
                rated_buffer_kw / self.discharge_10s_kw,
            )
            * self.nominal_kwh
        )
