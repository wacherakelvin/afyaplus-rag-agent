import pytest

from afyaplus.privacy import PIIVault, detect_pii

PHONES = ["0712345678", "0712 345 678", "0712-345-678", "+254712345678", "+254 712 345 678", "254712345678",
          "(+254) 712 345 678", "0110 123 456", "+254 110 123456", "020 2345678", "+254 20 234 5678"]


@pytest.mark.parametrize("phone", PHONES)
def test_kenyan_phone_formats_are_masked(phone):
    masked, found = PIIVault().mask(f"Call me on {phone} today.")
    assert masked == "Call me on [PHONE_1] today."
    assert found == {"PHONE": 1}


@pytest.mark.parametrize("email", ["wanjiku.m@example.co.ke", "first.last+claims@afyaplus.co.ke", "J.Doe@Example.COM"])
def test_emails_are_masked(email):
    masked, found = PIIVault().mask(f"Email {email}.")
    assert masked == "Email [EMAIL_1]."
    assert found == {"EMAIL": 1}


def test_kra_pin_member_id_and_national_id_are_masked():
    masked, found = PIIVault().mask("KRA PIN A123456789Z, member AFP-204518, ID No. 23456789")
    assert found == {"KRA_PIN": 1, "MEMBER_ID": 1, "NATIONAL_ID": 1}
    assert "ID No. [NATIONAL_ID_1]" in masked and "23456789" not in masked


@pytest.mark.parametrize("text", ["The bill was KES 48,000.", "He weighs 70 kg and takes 600 mg.",
                                  "Claim filed on 2026-11-12 within 90 days.",
                                  "Outpatient limit KES 100,000 at 80%.", "Reply within 2 working hours."])
def test_clinical_and_financial_numbers_are_not_masked(text):
    masked, found = PIIVault().mask(text)
    assert masked == text and found == {}


def test_same_number_in_different_formats_gets_one_token():
    vault = PIIVault()
    assert vault.mask("0712 345 678")[0] == vault.mask("+254712345678")[0] == "[PHONE_1]"


def test_demask_restores_the_original_text():
    vault = PIIVault()
    raw = "Email wanjiku.m@example.co.ke or call 0712 345 678."
    masked, _ = vault.mask(raw)
    assert "0712" not in masked and "@" not in masked
    assert vault.demask(masked) == raw


def test_unknown_tokens_are_left_untouched():
    assert PIIVault().demask("See [PHONE_9]") == "See [PHONE_9]"


def test_masked_text_contains_no_detectable_pii():
    masked, _ = PIIVault().mask("0712345678, a@b.co.ke, A123456789Z, ID 12345678")
    assert detect_pii(masked) == {}