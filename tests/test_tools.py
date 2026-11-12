import json

from afyaplus.tools import CALCULATOR_TOOLS, calculate_bmi, calculate_claim_payout, calculate_medication_volume


def run(tool, **kwargs):
    return json.loads(tool.invoke(kwargs))


def test_medication_volume_applies_prescribed_ceiling():
    r = run(calculate_medication_volume, weight_kg=70, dose_mg_per_kg=10, concentration_mg_per_ml=50,
            max_single_dose_mg=600)
    assert r["status"] == "ok" and r["dose_mg"] == 600 and r["volume_ml"] == 12 and r["ceiling_applied"] is True


def test_medication_volume_without_ceiling():
    r = run(calculate_medication_volume, weight_kg=50, dose_mg_per_kg=2, concentration_mg_per_ml=20)
    assert r["dose_mg"] == 100 and r["volume_ml"] == 5 and r["ceiling_applied"] is False


def test_invalid_inputs_return_errors_instead_of_crashing():
    assert run(calculate_medication_volume, weight_kg=-5, dose_mg_per_kg=2, concentration_mg_per_ml=20)["status"] == "error"
    assert run(calculate_medication_volume, weight_kg=50, dose_mg_per_kg=2, concentration_mg_per_ml=0)["status"] == "error"
    assert run(calculate_bmi, weight_kg=70, height_cm=10)["status"] == "error"


def test_bmi():
    r = run(calculate_bmi, weight_kg=70, height_cm=175)
    assert r["bmi"] == 22.86 and r["who_category"] == "Normal weight"


def test_claim_payout_within_limit():
    r = run(calculate_claim_payout, bill_amount_kes=48000, coverage_percent=80, remaining_limit_kes=60000)
    assert r["insurer_pays_kes"] == 38400 and r["member_pays_kes"] == 9600
    assert r["remaining_limit_after_kes"] == 21600 and r["limit_reached"] is False


def test_claim_payout_capped_by_remaining_limit():
    r = run(calculate_claim_payout, bill_amount_kes=100000, coverage_percent=80, remaining_limit_kes=50000)
    assert r["insurer_pays_kes"] == 50000 and r["member_pays_kes"] == 50000 and r["limit_reached"] is True


def test_every_tool_has_a_docstring_and_typed_arguments():
    for t in CALCULATOR_TOOLS:
        assert len(t.description) > 80
        assert all("type" in spec or "anyOf" in spec for spec in t.args.values())