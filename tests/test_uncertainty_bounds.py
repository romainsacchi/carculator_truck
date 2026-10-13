"""All truck defaults must sample before selecting vehicle and year scope."""

import hashlib
import json
from copy import deepcopy

import numpy as np
import pytest
import xarray as xr

from carculator_truck import (
    InventoryTruck,
    TruckInputParameters,
    TruckModel,
    fill_xarray_from_input_parameters,
)


def test_bound_repairs_preserve_all_central_values_and_unaffected_records():
    current = json.loads(TruckInputParameters.DEFAULT.read_text(encoding="utf-8"))
    provenance = json.loads(
        (
            TruckInputParameters.DEFAULT.parent / "cost_uncertainty_provenance.json"
        ).read_text(encoding="utf-8")
    )
    # Undo the separately documented HEV price-proxy scope extension before
    # checking the historical uncertainty repair. No price, bound or source
    # changed: only HEV-d coverage and an explicit proxy comment were added.
    historical = deepcopy(current)
    proxy_note = (
        " Extended to HEV-d as a generic chemistry price proxy; "
        "not a high-power pack quotation."
    )
    extended = 0
    for record in historical.values():
        if record["name"].startswith("energy battery cost per kWh,"):
            assert record["powertrain"][0] == "HEV-d"
            assert record["comment"].endswith(proxy_note)
            record["powertrain"] = record["powertrain"][1:]
            record["comment"] = record["comment"].removesuffix(proxy_note)
            extended += 1
    assert extended == 55
    restored = deepcopy(historical)
    assert provenance["changed_record_count"] == len(provenance["records"]) == 21
    for entry in provenance["records"]:
        key = entry["record_id"]
        original = entry["original_record"]
        revised = historical[key]
        anchor = historical[entry["anchor_record_id"]]
        assert anchor == entry["anchor_record"]
        assert original["year"] in (2030, 2040, 2050)
        assert not original["minimum"] <= original["loc"] <= original["maximum"]
        assert revised["minimum"] < revised["loc"] < revised["maximum"]
        assert {
            k: v for k, v in revised.items() if k not in ("minimum", "maximum")
        } == {k: v for k, v in original.items() if k not in ("minimum", "maximum")}
        for bound in ("minimum", "maximum"):
            assert revised[bound] == pytest.approx(entry["corrected_bounds"][bound])
            assert revised[bound] / revised["loc"] == pytest.approx(
                anchor[bound] / anchor["loc"]
            )
        restored[key] = original
    # Undo the independently documented methane-boundary change as well, so
    # the historical cost audit still protects every other default record.
    leakage = json.loads(
        (
            TruckInputParameters.DEFAULT.parent / "methane_leakage_provenance.json"
        ).read_text(encoding="utf-8")
    )
    for key, original in leakage["original_records"].items():
        assert original["name"] == current[key]["name"] == "CNG pump-to-tank leakage"
        assert current[key]["amount"] == leakage["default_additional_loss_ratio"] == 0
        restored[key] = original
    # Undo the independently approved chemistry identifier migration before
    # comparing with the historical, pre-migration source hash.
    # Restoring all migrations recovers the entire original data, including
    # all 2025 records and unrelated physical assumptions.
    digest = hashlib.sha256(
        json.dumps(restored, sort_keys=True, separators=(",", ":"))
        .replace("NMC-532", "NMC-523")
        .encode()
    ).hexdigest()
    assert digest == provenance["source_records_sha256"]
    inputs = TruckInputParameters()
    inputs.static()
    for key, record in current.items():
        np.testing.assert_array_equal(inputs.values[key], record["amount"])


def test_all_default_distributions_sample_reproducibly_with_valid_bounds():
    records = json.loads(TruckInputParameters.DEFAULT.read_text(encoding="utf-8"))
    first = TruckInputParameters()
    first.stochastic(64, seed=42)
    second = TruckInputParameters()
    second.stochastic(64, seed=42)
    assert first.values.keys() == records.keys()
    for key, values in first.values.items():
        assert np.isfinite(values).all(), key
        np.testing.assert_array_equal(values, second.values[key], err_msg=key)
        record = records[key]
        if record.get("uncertainty_type") == 5:
            assert (values >= record["minimum"]).all(), key
            assert (values <= record["maximum"]).all(), key


@pytest.mark.parametrize("chemistry", [None, "LTO"], ids=["default", "LTO"])
def test_default_sampling_reaches_completed_models_and_inventories(chemistry):
    inputs = TruckInputParameters()
    inputs.stochastic(3, seed=42)
    years = [2025, 2030, 2040, 2050]
    _, array = fill_xarray_from_input_parameters(
        inputs,
        scope={"size": ["40t"], "powertrain": ["BEV", "ICEV-d"], "year": years},
    )
    original = array.copy(deep=True)
    kwargs = {}
    if chemistry:
        kwargs["energy_storage"] = {
            "electric": {("BEV", "40t", year): chemistry for year in years}
        }
    model = TruckModel(array, cycle="Urban delivery", **kwargs)
    model.set_all()
    xr.testing.assert_identical(array, original)
    for parameter in ("TtW energy", "cargo mass", "purchase cost"):
        assert np.isfinite(model[parameter]).all()
        assert (model[parameter] > 0).all()
    assert (model["electric energy stored"].sel(powertrain="BEV") > 0).all()
    assert (model["purchase cost"].std("value") > 0).all()
    if chemistry:
        np.testing.assert_allclose(
            model["energy battery cost per kWh"].sel(powertrain="BEV"),
            original.sel(
                parameter=f"energy battery cost per kWh, {chemistry}", powertrain="BEV"
            ),
        )
    inventory = InventoryTruck(model, scenario="static", functional_unit="tkm")
    impacts = inventory.calculate_impacts()
    assert np.isfinite(inventory.A).all()
    assert np.isfinite(impacts).all()
    climate = impacts.sel(impact_category="climate change").sum("impact")
    assert (climate > 0).all()
    assert impacts.sizes["value"] == 3
    assert impacts.year.values.tolist() == years
