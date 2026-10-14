.. _validity:

Truck calibration and validation
================================

Start with :doc:`validation_examples` for bar charts and an explanation of the
evidence. This page records detailed checks and limitations; dated test totals
and before/after results refer to their stated software snapshots.

The historical VECTO comparison in :doc:`modeling` is calibration against a
simulator, not an independent measurement of every truck class. Its reported
sub-1% agreement applies to that original configuration and model version.
The current 2025 evidence review separates measurement boundaries, road load,
vehicle vintage and route before interpreting discrepancies.

Installed PHEV battery capacity
-------------------------------

Both driving-mode cost calculations price the full electric-mode battery pack.
The combustion-mode intermediate's smaller operating storage no longer reduces
installed battery purchase cost when modes are combined. Purchase-dependent
financing and, for trucks, insurance and residual credit follow that correction.
Unit-price inputs, markup and explicit cost overrides retain their conventions.
The shared model also preserves nominal capacity and computes electric range
from usable capacity. Battery replacement counts are unchanged pending a
separate lifetime-use review.

.. _charging-cost-accounting:

Charging cost accounting
------------------------

Electricity running costs use grid purchases: ``electricity consumption`` in
kWh/km times the electricity tariff. Grid consumption already includes both
battery-charge and charger losses; neither efficiency is applied again when
billing that electricity. Previously the cost formula omitted charger losses.
At 90% charger efficiency it understated the electricity component by 10%; at
80% efficiency it understated it by 20%. This correction changes costs, while
preserving vehicle energy demand, inventory electricity exchanges and LCIA.

BEVs and PHEV electric intermediates use this grid-based calculation. Combined
PHEVs retain the utility-factor-weighted sum of electric and combustion costs,
with the electric share applied once. Fuel-mode costs retain their existing
convention. Tariffs and charging-efficiency assumptions have not been refitted.

Truck costs remain per vehicle-km. The electricity tariff is the weighted
average of depot and public prices using ``share depot charging``; depot
infrastructure remains a separate cost component. The default Swiss 2025
``40t`` BEV on ``Long haul`` costs approximately EUR 27.43/100 km for
electricity, corrected from EUR 24.69/100 km.

Completed model/inventory checks and the shared billing calculation are described
in the `shared charging-cost validation <https://github.com/Laboratory-for-Energy-Systems-Analysis/carculator_utils/blob/master/docs/validity.rst#charging-cost-accounting>`_.


.. _depot-throughput-accounting:

Depot infrastructure throughput
-------------------------------

Depot-infrastructure costs now use ``electricity consumption`` (grid kWh/km)
both to calculate annual charger throughput and to allocate the resulting
EUR/kWh surcharge per vehicle-km. Previously the throughput input omitted
charger losses while the per-km allocation included them. Below the annual
capacity ceiling, this inflated the infrastructure component by 11.1% at
90% charger efficiency, or 25% at 80% efficiency.

The annual cost still consists of capital recovery over the charger lifetime,
fixed operation/maintenance and the capacity charge. Annual throughput is the
smaller of fleet grid-electricity demand and the existing capacity ceiling
(``charger power * 8760 * 0.98 * 0.94``). The 0.98 availability and 0.94
capacity factor, financing assumptions, number of trucks per charger and
depot-share allocation are unchanged. This is an accounting correction,
not new calibration of charger capacity or depot utilization. Zero throughput
retains the existing zero-surcharge convention; noncharging vehicles have no
depot-infrastructure charge.

For the default Swiss 2025 ``40t`` BEV on ``Long haul``, the infrastructure
component falls from EUR 6.62 to EUR 5.96 per 100 vehicle-km. It stays at
approximately EUR 5.96 when charger efficiency changes from 90% to 80%, while
the same annual charger cost is spread over more grid electricity below the
capacity ceiling. Capacity-limited cases continue to use that ceiling.
Vehicle energy demand, purchased electricity and LCIA are unaffected.

``tests/test_depot_throughput.py`` checks completed BEV/PHEV runs against
independent discounted annual cash flows and grid-throughput balances, with
reordered years, labelled samples, varying charging efficiencies and depot
shares. Cases below, across and above the capacity ceiling exercise both
branches, alongside noncharging and zero-demand controls. PHEV infrastructure
costs retain electric-driving-share weighting. Completed inventories confirm
grid purchases and finite impacts. Run the focused checks with::

   python -m pytest tests/test_depot_throughput.py tests/test_infrastructure_costs.py

.. _depot-charger-inventory:

Depot charger inventory allocation
----------------------------------

Physical charger production is now allocated over the charger's lifetime and
the fleet service it supplies. Previously each BEV received a fixed fraction
of a charger regardless of charger lifetime or depot-charging share, while
PHEVs received none because the inventory excluded vehicles with combustion
power. Both the impact calculations and exported inventories were affected.

The existing 200-kW reference inventory is scaled by ``depot charger power``.
For one charger, annual grid throughput is the smaller of fleet demand
(``trucks per depot charger * kilometers per year * electric-mode grid kWh/km``)
and the existing capacity ceiling (``power * 8760 * 0.98 * 0.94``). Costs and
inventories now share this throughput calculation. Allocation per vehicle-km is::

   (charger power / 200) * grid kWh/km * depot share
   -------------------------------------------------
       charger lifetime * annual grid throughput

The vehicle-production inventory multiplies this quantity by lifetime km;
transport inventories and ``tkm`` results subsequently normalize by vehicle
use and cargo. Charger lifetime therefore applies independently of truck
lifetime. Active depot charging requires finite positive power, charger life,
fleet size and mileage; invalid inputs raise a error identifying the affected input. Zero grid
demand, zero depot share and unavailable vehicles receive no depot hardware.

PHEV power, charger lifetime, trucks per charger and depot share retain their
electric-mode values through hybrid aggregation. Grid purchases already
include the electric-driving share; that share is applied once to hardware
allocation. The denominator uses electric-mode throughput, consistently with
the existing cost convention. Costs themselves are unchanged. This represents
allocation of shared service, rather than sizing a dedicated station from a
route timetable. Capacity factors and linear power scaling remain engineering
assumptions. Only depot hardware is included here; public-charger production
is not separately modelled by this correction.

In completed Swiss 2025 ``40t`` runs on ``Long haul`` with the ``static``
background, the default BEV charger contribution changes from 32.04 to
14.18 g CO2-eq/vehicle-km. Six- and 24-year charger lives give 28.35 and
7.09 g/km respectively, while zero depot share gives zero. A PHEV with a
50% electric-driving share now includes 7.09 g/km instead of zero. These
figures use the bundled ecoinvent 3.12 cut-off factors and IPCC 2021 GWP100
excluding biogenic CO2 (``recipe``/``midpoint``, ``climate change``).
Paired runs preserve energy, costs and every non-charger inventory exchange.
Regenerate affected impacts and exports made with the previous allocation.

``tests/test_charger_inventory.py`` verifies completed 7.5t/40t models,
reordered 2025/2030 years, named samples, electric-driving shares of 0%, 50%
and 100%, charger life, zero depot use and capacity-limited service. It checks
independent physical allocation, prospective ``vkm``/``tkm`` impacts, invalid
active inputs, and repeated Brightway/SimaPro exports for ecoinvent 3.12.
It also follows vehicle-specific charger suppliers when electricity mixes
differ. Run these and the unchanged cost regressions with::

   python -m pytest tests/test_charger_inventory.py tests/test_depot_throughput.py tests/test_infrastructure_costs.py

.. _adblue-cost-accounting:

AdBlue cost accounting
----------------------

Truck AdBlue costs use diesel-blend consumption in litres per vehicle-km,
the supplied AdBlue-to-diesel volume ratio, an AdBlue density of 1.09 kg/L,
and the supplied price in EUR/kg::

   adblue cost = fuel consumption * adblue use per liter diesel * 1.09 * adblue cost per kg

``adblue use per liter diesel`` is a dimensionless ratio of L AdBlue/L diesel;
``fuel consumption`` is L diesel blend/km. The blend's component densities
are already accounted for in that fuel-volume output. The 1.09 kg/L conversion
is for the AdBlue solution, not its urea content. It is the typical density
at 20 degrees C reported in the
`77 Lubricants technical sheet <https://www.77lubricants.nl/wp-content/uploads/2025/11/44850_AdBlue_v0.pdf>`_.
The existing default dosing rate of 0.05 L/L is retained. It lies within the
4--6 L per 100 L diesel range described in the
`Shell AdBlue technical sheet <https://shellcarcareproducts.com/files/products/tds/shell-adblue-tds-en%284%29.pdf>`_.
That broad range supports the units and the generic assumption; it does not
validate dosing for every truck, fuel blend, year or duty cycle. Prices and
the existing applicability of the dosing inputs are retained.

Previously the formula applied the volume ratio directly to diesel mass,
then billed that result as kilograms of AdBlue. For the default Swiss 2025
``40t`` diesel truck on ``Long haul``, 30.21 L diesel/100 km corresponds to
1.51 L or 1.65 kg AdBlue/100 km at the 5% rate. At the existing EUR 1.40/kg
price, the corrected AdBlue cost is EUR 2.31/100 km, previously EUR 1.76.
This adds approximately 0.45% to total ownership costs for that case.

AdBlue remains part of maintenance costs. Explicit maintenance-cost overrides,
including zero, take precedence. PHEV combustion-mode costs receive the
combustion-driving share once during PHEV assembly; fully electric operation
has zero AdBlue cost. This correction changes financial outputs while leaving
vehicle sizing, fuel purchases and environmental inventories unchanged.

``tests/test_adblue_costs.py`` verifies completed model/inventory/LCIA runs
against the volumes of purchased blend components. It covers conventional
diesel and diesel hybrids, PHEV electric shares of 0%, 50% and 100%, non-diesel
controls, pure fuels and mixed fuels with year-specific shares and densities,
reordered years, labelled samples, varied prices/rates, zero dosing, caller
input preservation and maintenance overrides. Run it with::

   python -m pytest tests/test_adblue_costs.py tests/test_cost_defaults.py

.. _end-of-life-signs:

End-of-life waste-flow signs
----------------------------

All three used-lorry treatment routes now receive positive waste outputs in
the calculation matrix. Brightway exports represent these outputs as negative
technosphere exchanges to treatment; SimaPro lists positive quantities under
``Waste to treatment``. This follows the
`Brightway matrix sign convention <https://docs.brightway.dev/en/latest/content/overview/matrix.html>`_.
The bundled treatment factors are characterized per positive unit of the
used-lorry reference product. Physical treatment requires negative demand for
that product, giving a positive disposal burden for the bundled climate factors.

Previously the 28t and 40t treatment exchanges had the opposite sign. This
turned their disposal burdens into credits, affecting the default 26t, 32t,
40t and 60t trucks across powertrains. The 16t treatment route already had the
consistent sign. Characterization factors and the existing gross-mass scaling
are retained: trucks below 26t use the 16t reference vehicle; trucks from 26t
to below 40t use the 28t reference; trucks of 40t and above use the 40t reference.
Each quantity is gross mass divided by reference-vehicle gross mass, then
allocated over lifetime vehicle-km and, for ``tkm``, cargo in tonnes.

For Swiss 2025 ``40t`` trucks on ``Long haul`` with the ``static`` background,
the isolated disposal contribution changes from -2.18 to +2.18 g CO2-eq per
vehicle-km for both diesel and BEV. Total climate impacts increase by about
0.30% for diesel and 0.41% for BEV. These results use the bundled ecoinvent
3.12 cut-off factors and IPCC 2021 GWP100 excluding biogenic CO2 (the
``recipe``/``midpoint`` category ``climate change``). Driving energy, costs and
fuel/electricity purchases are unaffected. Regenerate affected inventories,
impact results and exports made with the former signs.

``tests/test_end_of_life.py`` checks completed diesel runs across all seven
sizes and BEV, fuel-cell, gas and hybrid controls, with reordered 2025/2030
years and labelled samples with different lifetimes. It verifies treatment
selection and scaled mass balance, isolates disposal impacts against physical
waste demand for static/prospective backgrounds and ``vkm``/``tkm``, and
checks both years of Brightway and SimaPro exports for ecoinvent 3.12.
Repeated exports must preserve model and inventory state. Run it with::

   python -m pytest tests/test_end_of_life.py tests/test_inventory.py

This is a sign-accounting correction. The existing gross-mass treatment proxy
and material-recovery assumptions have not been recalibrated, and export
checks do not establish LCIA equivalence inside SimaPro.

Delivery-truck evidence
-----------------------

Full-model diagnostics use the source dynamometer road-load polynomials and
documented test inertias: 13,175 lb for the Smith Newton and 11,500 lb for the
MT-45. All runs still use 2025 technology assumptions, so these historical
vehicles are screening checks rather than calibration targets.

.. list-table:: Source-road-load comparisons
   :header-rows: 1

   * - Vehicle / cycle
     - Boundary and unit
     - Model
     - Measured
   * - Smith Newton / OCBC
     - Battery DC, kWh/100 km
     - 44.99
     - 44.74
   * - Smith Newton / OCBC
     - Charging AC, kWh/100 km
     - 52.42
     - 54.68
   * - MT-45 / OCBC
     - Diesel, L/100 km
     - 21.32
     - 24.71
   * - MT-45 / NYCC x 3
     - Diesel, L/100 km
     - 30.42
     - 38.69

The MT-45 cases remove the generic class's small electric-power share to
represent the conventional test vehicle. Smith's remaining deviations are
+0.6% at the battery and -4.1% at charging; MT-45 remains low by 13.7% and
21.4%. The road-load match does not prove the component efficiencies correct,
and the two electrical boundaries are not independent vehicles.

Heavy electric trucks
---------------------

The eActros 600 tour reports 103 kWh/100 km and the Volvo FH Electric road test
110 kWh/100 km, both at 40 t. Their published electrical boundaries are
insufficiently precise for a like-for-like residual. The generic long-haul
model gives respectively 143.00/123.75 and 142.33/123.15 kWh/100 km at charging
AC/battery DC. Flat-grade and road-load sensitivities reduce the differences,
but do not recreate either measured route. No generic default was fitted to
these results.

The measurement catalog includes six paired observations for four trucks.
See `truck diagnostics, primary sources and reproduction
<https://github.com/Laboratory-for-Energy-Systems-Analysis/carculator_utils/blob/master/docs/truck_energy_diagnostics.rst>`_ for the source polynomials, trace lengths,
power constraints and individual sensitivity runs. Stronger evidence is still
needed for route elevation, vehicle-specific road loads, auxiliaries and
matched AC/DC meters. The retained 32 t VECTO trace is explicitly unverified;
its source trace could not be independently recovered.

Coverage limits
---------------

Diesel controls and low-speed operation remain important diagnostic targets.
The car-only opt-in petrol controller is not implemented for trucks. The
available comparisons do not establish independent consumption validation for
every size, gas, hybrid, plug-in hybrid or fuel-cell truck. Inspect availability,
payload and power-deficit diagnostics before accepting a result.

Energy boundaries and time trends
---------------------------------

``TtW energy`` is kJ/km. For a BEV it represents net stored-energy depletion;
``model.battery_terminal_energy`` reports net terminal DC energy separately.
``electricity consumption`` is charging electricity in kWh/km. Multiplying it
by 100 gives kWh/100 km. A meter boundary must be identified before comparing
these outputs. Regeneration and battery/charger losses must not be counted twice.

The 2025 motor/inverter (0.90), electric transmission (0.97), charger (0.90)
and symmetric battery one-way (sqrt(0.97)) values are component assumptions in their
documented scopes, not universally measured efficiencies. For relevant hybrid
scopes, the independent motor peak/system-power ratio is 0.65. The temporal
update preserves all 2025 scalar values and uncertainty distributions. Storage
and charger trends preserve relative legacy losses; newly explicit component
assumptions are extended across tabulated years to avoid interpolating from missing
zero values. Historical estimates and future projections therefore change.

The family audit completes 546 annual cases (21 configurations, 2015–2040),
including availability-masked historical cells. The former inputs caused 20
sizing failures in this grid. All 40 existing 2025 measurement-comparison runs
retain their energy use and driving mass exactly. These are consistency and
regression checks, not 546 empirical validations. See
`temporal method, plots and limitations <https://github.com/Laboratory-for-Energy-Systems-Analysis/carculator_utils/blob/master/docs/temporal_energy.rst>`_.

Reproducibility
---------------

The installed package includes :download:`2025 record provenance
<../carculator_truck/data/defaults_2025_provenance.json>` and
:download:`temporal provenance and original affected records
<../carculator_truck/data/temporal_energy_provenance.json>`. Overrides should use measured
vehicle-specific inputs where available. Retain source, year, cycle, driving
mass, meter boundary and uncertainty assumptions with each comparison.

With matching Python 3.12 sibling checkouts, run from ``carculator_utils``::

   python scripts/validate_energy_measurements.py --output /tmp/measurements-new
   python scripts/audit_energy_time_trends.py --output /tmp/temporal-new

The shared `measurement catalog and outputs <https://github.com/Laboratory-for-Energy-Systems-Analysis/carculator_utils/blob/master/docs/energy_measurements.rst>`_
record excluded observations as well as paired values. Multiple cycles of one
vehicle and AC/DC measurements from one run are not independent vehicles.

Additional methane leakage
--------------------------

Gas trucks now emit the methane represented by their additional fuel-purchase allowance; previously the lost gas was absent from direct emissions.
The shared calculation preserves the existing convention: loss in kg per km
is engine fuel times the ``CNG pump-to-tank leakage`` ratio, and purchased fuel
is engine fuel plus that loss. Fossil/non-fossil methane follows the blend.
Both generic-air methane flows now enter non-exhaust impacts and exports;
combustion CO2 and HBEFA exhaust emissions are unchanged.

The current default is **zero additional leakage** at all tabulated years.
The former 0.4% assumption combined several delivery and vehicle stages and did
not establish an extra loss after the selected supplier. Losses already present
in the supplier inventory and HBEFA exhaust factors remain included. Set
``CNG pump-to-tank leakage`` only when evidence supports an additional loss
outside that supplier's boundary; a value of zero does not mean the whole gas
supply chain is leak-free.
See the shared `methane leakage boundary and verification notes
<https://github.com/Laboratory-for-Energy-Systems-Analysis/carculator_utils/blob/master/docs/methane_leakage.rst>`_.

Completed regressions include 40t long-haul trucks, diesel/BEV controls,
2020/2025/2030, two samples, fossil gas, sewage biomethane, biological synthetic
methane and mixed fuels. They check mass balance, unchanged upstream inventories,
ReCiPe/EF climate contributions, and repeated multi-year Brightway exports.
These establish accounting consistency, not measured leakage-rate validation.


Retained uncertainty samples
----------------------------

The shared ``tests/test_sample_labels.py`` completes 40t long-haul diesel runs
in 2025/2030 after selecting a single nonzero-labelled Monte Carlo sample.
Relabelling that same draw to zero leaves physical outputs, inventories and
LCIA unchanged. Reordered completed samples preserve their corresponding LCIA
results, and sensitivity ratios use the named reference even when it is last.
Repeated Brightway/SimaPro exports preserve both years and the source inventory;
exported fuel inputs equal consumption divided by cargo in tonnes.
Truck component tests separately check payload-table selection, availability
and weight warnings with distinct sample values. These are software consistency
checks and do not change the physical calibration.


.. _sizing-consistency:

Consistent sizing, energy and inventory
---------------------------------------

The October 2026 end-to-end audit found a small numerical residual in the
2025 26t fuel-cell truck on the Regional delivery cycle in Germany. Energy
was calculated at 17,611.60 kg, while the reported final mass was 17,691.40 kg.
Refreshing energy at the reported mass increased consumption by 0.25%.
The former stopping condition, a 1% change in available payload, permitted
this difference even though the complete run returned successfully.

Sizing now checks driving mass, available payload, battery mass, fuel mass
and TtW energy together to a relative tolerance of ``1e-6`` per active cell.
Payload limits participate in the iteration; the final energy trace is
refreshed before consumption, costs, direct emissions and inventories are
calculated. This is a numerical correction, not a new fuel-cell calibration.

``tests/test_sizing_consistency.py`` independently reconstructs rolling work
from final mass and the driving cycle, checks usable-energy/range balance,
and verifies fuel/grid purchases and finite LCIA results. Cases include
fuel-cell, battery-electric and diesel trucks, fixed curb mass, a payload
limited by gross mass, labelled samples, multiple years, unavailable historical
vehicles and bounded nonconvergence. Run it with::

   python -m pytest tests/test_sizing_consistency.py

The shared end-to-end audit and Brightway comparisons are recorded in the
``carculator_utils`` repository under ``results/pipeline_audit_20261010``.

Hybrid traction storage
-------------------------

Non-plug-in hybrids use a finite regenerative traction buffer, separate from
the lead-acid starter. Motor power and cycle-energy demand determine its size
inside the mass/energy iteration. The 2020 Regional-delivery templates have
3.75--13.01 kWh; the 40 t pack is about 9.96 kWh and 196 kg. Braking beyond
the pack's charging capability receives no fuel or brake-wear credit.

The physical reference is the A123 AHR32113M1Ultra-B cell, documented in the
2014 Battery Pack Design, Validation, and Assembly Guide, revision 02, Tables
4 and 30--33. ``hybrid_battery.py`` records the source URL, continuous-current
ratings at 25 degrees C and conservative 2 V cutoff conversion. The 60% usable
window and 70% cell allocation are engineering assumptions. Generic LFP cycle
life and chemistry prices are explicit proxies, not qualified high-power pack
durability or market-price measurements. Premise retains its MIX capacity
market despite the documented physical mass/chemistry mismatch.

The fixing campaign closed on 14 October 2026. Broader PHEV cycling and future
FCEV tank resizing were skipped; these remain documented limitations, not
claims of completed validation. See the shared
`campaign guide <https://github.com/Laboratory-for-Energy-Systems-Analysis/carculator_utils/blob/master/docs/premise_vehicle_update.rst>`_.

FCEV traction-pack proxy
------------------------

FCEV trucks use the AKASOL AKASYSTEM 15 OEM 37 PRC pack as an explicit 2020
proxy. The May 2021 manufacturer sheet pairs 25 kWh with 238 kg, 36 kW
continuous charging, 50 kW continuous RMS discharge, and 150 kW discharge
for ten seconds. The product is also documented in the earlier brochure.
Source: https://www.act-news.com/wp-content/uploads/2020/11/210525_LowRes_AK_Datenblatt_AKASystem_15-OEM-37-PRC_2021_2159x2794mm_EN.pdf

The original ``20 kWh + 6% of hydrogen chemical energy`` rule remains an energy
floor. A larger pack is installed if instantaneous battery assistance on the
chosen cycle exceeds the reference's continuous discharge rating. Using the
RMS rating as an instantaneous ceiling is conservative and avoids inventing a
pulse-recovery interval. The full rated motor's buffer requirement must also
fit the ten-second rating; this does not establish indefinite full motor power.
Explicit capacity overrides are retained and rejected when insufficient for
the final sized vehicle. Propulsion demand is never clipped to hide a deficit.

Regeneration first supplies simultaneous DC auxiliaries, then charges the pack
up to its continuous terminal-power limit. Battery losses apply only to the
stored portion; excess braking earns neither fuel nor brake-wear credit.
The inherited conservative wear conversion discount is retained. Sizing
converges pack, fuel, vehicle mass and payload together.

The 70% cell/pack mass allocation and chemistry-specific inventory, costs and
replacement assumptions are retained proxies, not measured AKASOL cell data.
The effective cell density merely reproduces the documented complete-pack
mass. ``fuel_cell_battery={...}`` accepts alternate pack specifications using
the fields in ``FuelCellBatteryProfile``; explicit chemistry choices remain
inventory proxies and do not replace this physical pack specification.

Ratings assume a conditioned pack. No SOC-window, fuel-cell ramp, electrothermal
or ageing validation is claimed. The profile is held constant for later model
years unless overridden. Premise separately retains the regenerated 2020 FCEV
hardware and buys its approved MIX capacity market per nominal kWh including
replacements; the market's manufacturing mass may differ from the physical pack.

``tests/test_fuel_cell_battery.py`` covers native Regional-delivery power,
mass/energy accounting, explicit capacity, repeated runs and invalid profiles.
