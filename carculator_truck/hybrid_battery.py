"""Power and cycle-energy sizing of a non-plug-in hybrid traction buffer.

The source profile is a pre-2020 high-power LFP cell. Continuous current
limits, multiplied by the documented minimum terminal voltage, provide
conservative power limits; short-pulse ratings are not used continuously.
This is an energy-balance model, not an electrothermal or ageing simulation.
"""

from dataclasses import dataclass

import numpy as np

PROFILE_SOURCE = (
    "A123 Systems (2014), Battery Pack Design, Validation, and Assembly Guide "
    "using A123 Systems Nanophosphate Cells, document 493005-002 Rev 02, "
    "Tables 4 and 30-33; AHR32113M1Ultra-B. "
    "https://ctc.chontech.ac.th/files/220427099180464_24051016164406.pdf"
)


@dataclass(frozen=True)
class HybridBatteryProfile:
    """Independently adjustable pack-envelope assumptions, in SI-derived units."""

    # A123 Systems, 2014, document 493005-002 Rev 02, Tables 4 and 30--33.
    # AHR32113M1Ultra-B: 3.3 V, 4.5 Ah, 205 g. At 25 C: 33 A continuous
    # charge and 200 A continuous discharge; end-of-discharge cutoff 2.0 V.
    cell_energy_kwh: float = 3.3 * 4.5 / 1000
    cell_mass_kg: float = 0.205
    cell_charge_kw: float = 33 * 2.0 / 1000
    cell_discharge_kw: float = 200 * 2.0 / 1000
    # Explicit engineering window, not a manufacturer cycle-life guarantee.
    usable_share: float = 0.6
    cell_mass_share: float = 0.7

    def validate(self):
        for name, value in vars(self).items():
            if not np.isfinite(value) or value <= 0:
                raise ValueError(f"Hybrid battery {name} must be finite and positive.")
        for name in ("usable_share", "cell_mass_share"):
            if getattr(self, name) > 1:
                raise ValueError(f"Hybrid battery {name} must be at most one.")


def run_buffer(charge_stored, discharge_opportunity, usable_kwh, *, max_cycles=100):
    """Return a periodic regenerative-only storage balance in kWh.

    Each interval can charge from braking or discharge to positive propulsion.
    No grid or engine charging is introduced. A full warm-up cycle precedes
    the returned cycle when needed, so its initial energy is not free energy.
    """
    charge_stored = np.asarray(charge_stored, dtype=float)
    discharge_opportunity = np.asarray(discharge_opportunity, dtype=float)
    if (
        charge_stored.ndim != 1
        or charge_stored.shape != discharge_opportunity.shape
        or not charge_stored.size
        or not np.isfinite(charge_stored).all()
        or not np.isfinite(discharge_opportunity).all()
        or (charge_stored < 0).any()
        or (discharge_opportunity < 0).any()
        or np.isnan(usable_kwh)
        or usable_kwh < 0
    ):
        raise ValueError("Hybrid buffer requires nonnegative finite energy traces.")
    # Start a surplus-energy cycle full, avoiding arbitrarily many warm-up
    # cycles for a tiny net surplus. Only a periodic balance earns a credit.
    surplus = charge_stored.sum() >= discharge_opportunity.sum()
    state = usable_kwh if surplus and np.isfinite(usable_kwh) else 0.0
    for _ in range(max_cycles):
        initial = state
        maximum = accepted = discharged = spill = 0.0
        for incoming, opportunity in zip(charge_stored, discharge_opportunity):
            stored = min(float(incoming), max(usable_kwh - state, 0))
            accepted += stored
            spill += float(incoming) - stored
            state += stored
            maximum = max(maximum, state)
            delivered = min(state, float(opportunity))
            discharged += delivered
            state -= delivered
        if abs(state - initial) <= 1e-10:
            return dict(
                required_usable_kwh=maximum,
                charged_kwh=accepted,
                discharged_kwh=discharged,
                curtailed_kwh=spill,
                initial_kwh=initial,
                final_kwh=state,
            )
    raise ValueError("Hybrid buffer cannot reach a periodic energy balance.")


def size_hybrid_buffer(
    generator_dc_kw,
    propulsion_dc_kw,
    motor_dc_kw,
    charge_efficiency,
    discharge_efficiency,
    *,
    profile=None,
    capacity_kwh=None,
):
    """Size nominal kWh against motor discharge power and usable cycle energy.

    Traces use one-second intervals. ``motor_dc_kw`` is the DC demand at full
    rated motor output, whereas ``propulsion_dc_kw`` is the cycle's opportunity
    to reuse energy, already limited by that motor rating. Explicit capacity
    must support the declared motor power. Regeneration is curtailed at the
    resulting pack's continuous charging limit: accepting every braking peak
    is not a requirement for a charge-sustaining hybrid.
    """
    profile = HybridBatteryProfile() if profile is None else profile
    profile.validate()
    charge = np.asarray(generator_dc_kw, dtype=float)
    discharge = np.asarray(propulsion_dc_kw, dtype=float)
    if (
        charge.ndim != 1
        or charge.shape != discharge.shape
        or not charge.size
        or not np.isfinite(charge).all()
        or not np.isfinite(discharge).all()
        or (charge < 0).any()
        or (discharge < 0).any()
        or not np.isfinite(motor_dc_kw)
        or motor_dc_kw <= 0
    ):
        raise ValueError(
            "Active HEV battery sizing needs finite nonnegative power traces."
        )
    if any(
        not np.isfinite(x) or not 0 < x <= 1
        for x in (charge_efficiency, discharge_efficiency)
    ):
        raise ValueError("Hybrid battery efficiencies must be in (0, 1].")
    if (discharge > motor_dc_kw * (1 + 1e-6)).any():
        raise ValueError("Battery propulsion opportunity exceeds motor DC power.")
    discharge_minimum = (
        motor_dc_kw / profile.cell_discharge_kw * profile.cell_energy_kwh
    )
    power_minimum = discharge_minimum
    charge_stored = charge * charge_efficiency / 3600
    discharge_stored = discharge / discharge_efficiency / 3600
    if charge_stored.sum() >= discharge_stored.sum():
        # A repeating downhill duty cannot reuse all braking energy. A whole
        # cycle's discharge is a finite conservative energy-buffer target;
        # the bounded balance below spills the unreusable surplus.
        energy_minimum = float(discharge_stored.sum()) / profile.usable_share
    else:
        unrestricted = run_buffer(charge_stored, discharge_stored, np.inf)
        energy_minimum = unrestricted["required_usable_kwh"] / profile.usable_share
    nominal = max(power_minimum, energy_minimum)
    if capacity_kwh is not None:
        if not np.isfinite(capacity_kwh) or capacity_kwh < discharge_minimum * (
            1 - 1e-6
        ):
            raise ValueError(
                "Explicit HEV battery capacity cannot supply the rated motor power."
            )
        nominal = float(capacity_kwh)
    cells = nominal / profile.cell_energy_kwh
    accepted_charge = np.minimum(charge, cells * profile.cell_charge_kw)
    result = run_buffer(
        accepted_charge * charge_efficiency / 3600,
        discharge_stored,
        nominal * profile.usable_share,
    )
    result["curtailed_kwh"] += float(
        (charge - accepted_charge).sum() * charge_efficiency / 3600
    )
    result.update(
        nominal_kwh=nominal,
        power_minimum_kwh=power_minimum,
        energy_minimum_kwh=energy_minimum,
        maximum_charge_kw=cells * profile.cell_charge_kw,
        maximum_discharge_kw=cells * profile.cell_discharge_kw,
        discharged_dc_kwh=result["discharged_kwh"] * discharge_efficiency,
    )
    return result


def avoided_propulsion_fuel(
    reused_dc_kwh, motor_efficiency, wheels, transmission, fuel
):
    """Convert accepted/reused DC energy to avoided fuel input, in kJ.

    Power traces have one-second intervals. Apply the positive-fuel limit
    after constraining energy reuse, including cycles with surplus braking.
    """
    positive_wheels = float(np.sum(wheels))
    positive_fuel = float(np.sum(fuel))
    if positive_wheels <= 0:
        return 0.0
    weighted_transmission = float(np.sum(wheels * transmission)) / positive_wheels
    return min(
        reused_dc_kwh
        * 3600
        * motor_efficiency
        * weighted_transmission
        * positive_fuel
        / positive_wheels,
        positive_fuel,
    )
