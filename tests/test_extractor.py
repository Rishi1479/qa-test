from app.parsing.requirement_extractor import extract_requirements

SAMPLE_FR_STYLE = """
3. Functional Requirements
● FR-1: Patient Registration and Authentication
  ○ Description: The system must allow new patients to create an account using an
    email address and a password of at least 8 characters.
  ○ Validation Conditions: Email must be unique in the database.
  ○ Edge Case: Patient attempts to register with an email that already exists; system
    returns the error "Email already registered".
● FR-2: Provider Availability Management
  ○ Description: The system must allow authenticated providers to set their weekly
    recurring availability in 30-minute time slots.
  ○ Edge Case: Provider sets an availability slot in the past.
"""

SAMPLE_GENERIC = """
The user shall be able to log in with a valid email and password.
Random line of prose with no keyword.
The system must send a confirmation email after registration.
"""


def test_fr_style_extraction_finds_all_requirements():
    reqs = extract_requirements(SAMPLE_FR_STYLE)
    ids = [r.req_id for r in reqs]
    assert ids == ["FR-1", "FR-2"]


def test_fr_style_extraction_captures_description_and_edge_case():
    reqs = extract_requirements(SAMPLE_FR_STYLE)
    fr1 = reqs[0]
    assert "8 characters" in fr1.description
    assert "Edge Case" in fr1.raw_text
    assert "already registered" in fr1.raw_text


def test_generic_fallback_used_when_no_fr_headers():
    reqs = extract_requirements(SAMPLE_GENERIC)
    assert len(reqs) == 2
    assert reqs[0].req_id == "REQ-001"
    assert "log in" in reqs[0].description


def test_empty_document_returns_empty_list():
    assert extract_requirements("") == []
