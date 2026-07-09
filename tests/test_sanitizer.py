import pytest
import sanitizer
from sanitizer import sanitize_prompt


@pytest.fixture(scope="module", autouse=True)
def _init_sanitizer():
    # Phase D made the sanitizer lazy-load (matches router.py's pattern) — these tests
    # call sanitize_prompt directly, bypassing the app lifespan, so they must initialize it themselves.
    sanitizer.initialize_sanitizer()


def test_redacts_indian_pan_number():
    result = sanitize_prompt("My PAN is ABCDE1234F, please use it for KYC.")
    assert "ABCDE1234F" not in result
    assert "[IN_PAN]" in result


def test_redacts_indian_aadhaar_number():
    result = sanitize_prompt("My Aadhaar number is 234123412346.")
    assert "234123412346" not in result
    assert "[IN_AADHAAR]" in result


def test_still_redacts_email():
    result = sanitize_prompt("Contact me at someone@example.com")
    assert "someone@example.com" not in result
    assert "[EMAIL_ADDRESS]" in result
