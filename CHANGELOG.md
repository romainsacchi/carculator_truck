# Changelog

Notable user-facing changes to `carculator_truck`.

## [0.5.2] - 2026-10-11

### Migration to ecoinvent 3.12

- Use IEA PVPS 2026 photovoltaic production mixes through the shared background: country-specific coefficients and generation-weighted GLO/EU27 aggregates replace the fixed Swiss solar proxy. An explicit legacy option remains; exports require matching premise PV suppliers.
- Correct HDPE- and aluminium-lined 700-bar hydrogen tank inventories to one kg of dry assembly and convert manufacturing electricity from MJ to kWh. FCEV tank sizing is unchanged; recalculate affected life-cycle impacts.
- Use the coordinated `carculator_utils 1.3.7` background with premise 2.5.4 and ecoinvent 3.12 cutoff. The foreground matrix, activity index and all 57 LCIA coefficient matrices were rebuilt together. Recalculate saved LCA results; results from the previous background are not directly interchangeable.
- Rename explicit battery chemistry selections and chemistry-specific custom parameter names from `NMC-523` to `NMC-532`. The new inventory uses the actual 5:3:2 Ni:Mn:Co chemistry. Existing engineering and price assumptions carry forward; this is not an alias for the former inventory.
- Inventory exports now default to ecoinvent 3.12. Match exported suppliers against the documented compatible background. Ecoinvent 3.9/3.10 remain explicit legacy targets, but suppliers without verified older links raise an error; requesting an older version does not convert the new background automatically.
- Brightpath supplies Brightway Excel, SimaPro CSV and foreground openLCA JSON-LD exports. Select one sample before export; all selected years are retained. Brightway requires background matching, and openLCA requires provider and elementary-flow mapping before calculation. SimaPro uses Latin-1 and retains unsupported noise quantities in audit comments.
- Python support remains `>=3.12,<3.13` with NumPy `>=1.26.4,<2`. Install matching family versions and rebuild saved models/arrays when applying the corrected inputs, costs or inventory accounting described below.

### Other changes

- Review the documentation against current code, explain units and assumptions
  in plain English, and add validation bar charts with sources and explicit
  limits. Correct outdated descriptions of exports, repeated runs and scientific
  accounting; preserve dated historical results as such.
- Remove import-time global warning suppression and refresh API/documentation contracts; shared sulfur-table reductions use explicit pandas axis arguments.
- Default additional CNG pump-to-tank leakage to zero beyond the delivered-fuel supplier boundary. Remove the unqualified 0.4% overlay while retaining upstream and exhaust methane; explicit measured residuals remain supported.

### Compatibility and installation

- Require the stable `carculator_utils>=1.3.7` release, including its Brightpath runtime dependency.
- Keep core model/LCIA calculations independent of Brightway projects and imports. Export writers now come through Brightpath; `excel` remains a compatibility alias and `brightway` selects the legacy stack (`bw2io<0.9`, `bw2data<4`, `bw2calc<2`).

### Model and inventory changes

- Calculate battery and fuel-cell replacements after truck sizing. Preserve
  supplied nonzero values per vehicle, year and sample, independently of automatic
  results. This removes premature three-battery replacement counts for default
  electric trucks and prevents one override from suppressing other calculations.
- Converge driving mass, payload, battery mass, fuel mass and energy together, then refresh energy at the final mass. Apply payload limits within sizing and preserve fixed-mass overrides. This removes the previous-mass energy residual and keeps fuel/grid purchases and LCIA consistent with the completed truck; see [sizing validation](docs/validity.rst#sizing-consistency).
- Replace the NMC-523 option with NMC-532 for the ecoinvent 3.12 background refresh. Update explicit chemistry selections and custom parameter names; engineering priors retain their previous numerical values.
- Use the matching shared premise 2.5.4 / ecoinvent 3.12 coefficient bundle; exports default to 3.12 and reject unverified older supplier links.
- Make repeated `set_all()` calls rebuild from retained inputs, with stable costs/energy and retained PHEV components. Preserve explicit input edits and selected sample prices; see the shared repeat-run guide.
- Allocate depot charger production over charger lifetime and capacity-limited fleet throughput, applying depot and PHEV electric-driving shares once. Preserve actual PHEV charger specifications, reject invalid active settings, and verify completed inventories, LCIA and exports. Energy and costs are unchanged; regenerate affected impacts and exports. See [charger inventory accounting](docs/validity.rst#depot-charger-inventory).
- Correct reversed waste-output signs for the 28t and 40t used-lorry treatment routes, removing artificial disposal credits for heavier trucks. Preserve treatment selection and mass scaling; verify completed model/LCIA runs and Brightway/SimaPro exports across years and weight classes. Regenerate affected impacts and exports; see [end-of-life accounting](docs/validity.rst#end-of-life-signs).
- Correct AdBlue costs by applying the dosing ratio to diesel litres and converting AdBlue volume to mass at 1.09 kg/L before billing EUR/kg. Retain dosing rates, prices, PHEV driving-share weighting and maintenance overrides; verify completed diesel/hybrid runs, fuel blends and zero-use controls. See [AdBlue cost accounting](docs/validity.rst#adblue-cost-accounting).
- Use grid electricity consistently for annual depot-charger throughput and per-km infrastructure allocation. Remove the artificial surcharge caused by mixing electricity with and without charger losses; retain financing, capacity ceilings and depot-share assumptions. Verify completed BEV/PHEV runs, capacity transitions, noncharging and zero-demand cases. See [depot throughput accounting](docs/validity.rst#depot-throughput-accounting).
- Bill BEVs and PHEV electric operation from grid electricity consumption, including charger losses. Preserve fuel-mode costs, PHEV driving-share weighting and model-specific cost units; verify costs against completed inventory purchases. See [charging cost accounting](docs/validity.rst#charging-cost-accounting).
- Complete runs after selecting a nonzero sample label. Display payload, weight warnings and availability from the same retained sample: the named sensitivity reference when present, otherwise the first sample. Inherit preserved LCIA sample labels and selected-sample export support from the shared release.
- Gas trucks now emit the methane represented by their additional fuel-purchase allowance; previously the lost gas was absent from direct emissions. Use the shared mass balance, include both origins in impacts/exports, and document the historical loss-rate boundary; see [validation](docs/validity.rst#additional-methane-leakage).
- Repair 21 invalid triangular battery/glider cost distributions by scaling bounds from valid 2020 relative uncertainty. Preserve every central value and all 2025 records; restore sampling of the full defaults and verify completed stochastic models/inventories. Ship original-record provenance and document the shared contextual validation.

### Inventory export

- Inherit Brightpath (`>=1.0.0a6,<1.1`, v1 alpha API) writers for Brightway Excel, SimaPro CSV and foreground-only openLCA JSON-LD from `carculator_utils`; document examples and return values in the [export guide](docs/inventory_export.rst).
- Default to ecoinvent 3.12 cut-off; older 3.9/3.10 targets reject suppliers without verified links. Retain one selected sample per export, every selected year and unchanged source inventories/impacts. Brightway importers still require background matching and writing.
- Document the SimaPro Latin-1 layout and identifier changes, warnings for omitted custom noise flows, and openLCA provider/elementary-flow mapping required before calculation. Remove obsolete presamples and uncertainty-export claims.

### Documentation and verification

- Preserve the supplier axis in the charger-impact test when SciPy returns a vector for one supplier. Exercise deterministic single- and multiple-supplier cases for both functional units and all PHEV electric-driving shares, fixing Linux/Windows CI failures without changing model calculations.
- Read uncertainty-bound provenance JSON explicitly as UTF-8 on Windows, preserving euro-denominated units and exact comparisons with the source records.

### Known limitations

- VECTO agreement is a simulator comparison. Measured truck comparisons retain road-load, route and AC/DC boundary limitations.
- The retained 32 t VECTO trace remains unverified; the original source trace could not be independently recovered.
- Inspect payload, availability and power-deficit diagnostics before interpreting zero consumption or tonne-kilometre results.

See [release preparation](RELEASING.md) for coordinated versions and verification.

## [0.5.1] - 2026-10-08

### Compatibility and installation

- Require Python 3.12 (`>=3.12,<3.13`); older Python environments must be recreated.
- Use NumPy `>=1.26.4,<2` through the shared runtime.
- Require the stable `carculator_utils>=1.3.6` release, including its export extras.
- Build wheels and source distributions from centralized `pyproject.toml` metadata.
- Keep core model/LCIA use independent of Brightway; install `excel` or `brightway` extras for export. The Brightway extra targets the legacy stack (`bw2io<0.9`, `bw2data<4`, `bw2calc<2`).
- Align documentation versions with the package version and provide complete documentation-build dependencies.

### Model and inventory changes

- Add native 2025 inputs, explicit component-efficiency priors and consistent temporal extensions across model years.
- Apply corrected shared energy boundaries and regenerative accounting, and apply the CNG efficiency correction before fuel conversion.
- Bound sizing per available vehicle/sample and preserve custom inputs, payload, range, power and cost overrides.
- Correct year-based financial calculations, zero-rate capital recovery, inactive charging infrastructure and insurance calculations.
- Refine charging infrastructure costs and inventory fractions, including annual throughput limits and discounted replacements/residual values.
- Apply availability masks consistently to energy and supply outputs; document VECTO trace provenance and measured-truck comparison limits.
- Inherit corrected fuel blend, PHEV carbon, hot pollutant and multi-year export accounting from the shared release.

### Documentation and verification

- Add current installation and executable 2025 quick-start examples, migration notes and a release checklist.
- Record calibration scope, measurement boundaries and numerical consistency separately from empirical validation.
- Verify built wheels and sdist-built wheels, packaged resource hashes, installed tests with export extras and offline core-only model/LCIA smoke runs.

### Known limitations

- VECTO agreement is a simulator comparison. Measured truck comparisons retain road-load, route and AC/DC boundary limitations.
- The retained 32 t VECTO trace remains unverified; the original source trace could not be independently recovered.
- Inspect payload, availability and power-deficit diagnostics before interpreting zero consumption or tonne-kilometre results.

See [validation](docs/validity.rst) and [release preparation](RELEASING.md) for scope and verification instructions.
