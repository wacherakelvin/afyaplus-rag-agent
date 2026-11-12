"""Functional tool space: small, validated calculators. Each returns a JSON string so the agent
always receives a structured result, never a stack trace."""
import json
import math
from typing import Optional

from langchain_core.tools import tool


class ToolInputError(ValueError):
    """Raised when a tool argument is missing, non-numeric or outside its safe range."""


def _require(value, name: str, low: float, high: float) -> float:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolInputError(f"{name} must be a number")
    if not math.isfinite(value):
        raise ToolInputError(f"{name} must be a finite number")
    if not low <= value <= high:
        raise ToolInputError(f"{name} must be between {low} and {high} (got {value})")
    return float(value)


def _ok(**fields) -> str:
    return json.dumps({"status": "ok", **fields})


def _error(message: str) -> str:
    return json.dumps({"status": "error", "error": message})


@tool
def calculate_medication_volume(weight_kg: float, dose_mg_per_kg: float, concentration_mg_per_ml: float,
                                max_single_dose_mg: Optional[float] = None) -> str:
    """Convert a clinician-PRESCRIBED weight-based dose into a liquid volume in millilitres.
    Arithmetic only: the prescriber must supply the dose, the product concentration and any maximum.
    Never invent or suggest these values.

    Args:
        weight_kg: Patient weight in kilograms (0.5 to 300).
        dose_mg_per_kg: Prescribed dose in milligrams per kilogram (above 0, at most 100).
        concentration_mg_per_ml: Strength of the liquid in milligrams per millilitre (above 0, at most 1000).
        max_single_dose_mg: Optional prescribed ceiling for a single dose, in milligrams.

    Returns:
        JSON with dose_mg, volume_ml and ceiling_applied, or a JSON error message.
    """
    try:
        weight = _require(weight_kg, "weight_kg", 0.5, 300)
        dose_per_kg = _require(dose_mg_per_kg, "dose_mg_per_kg", 0.001, 100)
        concentration = _require(concentration_mg_per_ml, "concentration_mg_per_ml", 0.001, 1000)
        dose = weight * dose_per_kg
        capped = False
        if max_single_dose_mg is not None:
            ceiling = _require(max_single_dose_mg, "max_single_dose_mg", 0.001, 100_000)
            if dose > ceiling:
                dose, capped = ceiling, True
        return _ok(dose_mg=round(dose, 2), volume_ml=round(dose / concentration, 2), ceiling_applied=capped,
                   note="Arithmetic check only. Confirm with the prescriber or pharmacist before administering.")
    except ToolInputError as exc:
        return _error(str(exc))
    except (ArithmeticError, TypeError) as exc:
        return _error(f"calculation failed: {exc}")


@tool
def calculate_bmi(weight_kg: float, height_cm: float) -> str:
    """Calculate adult Body Mass Index and its WHO category.

    Args:
        weight_kg: Weight in kilograms (2 to 400).
        height_cm: Height in centimetres (50 to 250).

    Returns:
        JSON with bmi and who_category, or a JSON error message.
    """
    try:
        weight = _require(weight_kg, "weight_kg", 2, 400)
        height_m = _require(height_cm, "height_cm", 50, 250) / 100
        bmi = weight / (height_m ** 2)
        category = ("Underweight" if bmi < 18.5 else "Normal weight" if bmi < 25
                    else "Overweight" if bmi < 30 else "Obesity")
        return _ok(bmi=round(bmi, 2), who_category=category, note="WHO adult categories; not valid for children.")
    except ToolInputError as exc:
        return _error(str(exc))
    except (ArithmeticError, TypeError) as exc:
        return _error(f"calculation failed: {exc}")


@tool
def calculate_claim_payout(bill_amount_kes: float, coverage_percent: float, remaining_limit_kes: float) -> str:
    """Split an eligible medical bill between AfyaPlus and the member.
    Look up the plan's coverage percentage in the knowledge manual BEFORE calling this tool.

    Args:
        bill_amount_kes: Total eligible bill in Kenya shillings (0 to 100,000,000).
        coverage_percent: Share AfyaPlus pays under the member's plan, as a percentage (0 to 100).
        remaining_limit_kes: Member's remaining annual limit for this benefit, in Kenya shillings.

    Returns:
        JSON with insurer_pays_kes, member_pays_kes, remaining_limit_after_kes and limit_reached,
        or a JSON error message.
    """
    try:
        bill = _require(bill_amount_kes, "bill_amount_kes", 0, 100_000_000)
        coverage = _require(coverage_percent, "coverage_percent", 0, 100)
        remaining = _require(remaining_limit_kes, "remaining_limit_kes", 0, 1_000_000_000)
        eligible = bill * coverage / 100
        insurer = min(eligible, remaining)
        return _ok(insurer_pays_kes=round(insurer, 2), member_pays_kes=round(bill - insurer, 2),
                   remaining_limit_after_kes=round(remaining - insurer, 2), limit_reached=eligible > remaining)
    except ToolInputError as exc:
        return _error(str(exc))
    except (ArithmeticError, TypeError) as exc:
        return _error(f"calculation failed: {exc}")


CALCULATOR_TOOLS = [calculate_medication_volume, calculate_bmi, calculate_claim_payout]