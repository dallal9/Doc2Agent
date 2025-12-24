"""Validation tools - placeholders for implementation."""

from src.agents_config import PersonalInfo


async def validate_personal_info(claim: str, personal_info: PersonalInfo) -> dict:
    """Validate a claim against user's personal information.

    Checks if names, dates, addresses, etc. match what the user provided.
    """
    result = {"claim": claim, "matches": [], "mismatches": [], "unknown": []}

    claim_lower = claim.lower()
    for key, value in personal_info.data.items():
        if value is None:
            continue
        value_str = str(value).lower()
        if value_str in claim_lower:
            result["matches"].append({"field": key, "value": value})
        elif key.lower() in claim_lower:
            result["mismatches"].append({"field": key, "expected": value, "found_in_claim": True})

    return result


async def validate_dates(dates: list[dict], reference_date: str | None = None) -> list[dict]:
    """Validate extracted dates for consistency and reasonableness.

    TODO: Implement date parsing and validation:
        - Check if dates are in the past/future as expected
        - Check if date ranges make sense (start < end)
        - Flag suspicious dates (too far in past/future)
    """
    return dates
