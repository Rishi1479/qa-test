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

SAMPLE_WITH_SECTION_BOUNDARY = """
3. Functional Requirements
● FR-5: Video Consultation Link
  ○ Description: The system generates a unique video link for each appointment.
  ○ Edge Case: Link activates 10 minutes before the start time.
## 4. Non-Functional Requirements
● NFR-1: Performance
  ○ Description: The system must handle 100 concurrent users.
● NFR-2: Security
  ○ Description: All data must be encrypted at rest.
5. Constraints
● CR-1: Browser Support
  ○ Description: The system must support Chrome, Firefox, and Safari.
"""

SAMPLE_WITH_DASH_SEPARATOR = """
FR-4 - Appointment Cancellation
  ○ Description: Patients must be able to cancel an appointment at least 24 hours before.
"""

SAMPLE_WITH_EN_DASH_SEPARATOR = """
FR-3 – Appointment Booking
  ○ Description: Authenticated patients must be able to book an open slot.
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


# ---------- Section-boundary tests (Fix #1) ----------

def test_section_boundary_stops_fr_edge_case_bleed():
    """FR-5's edge case should NOT contain NFR text."""
    reqs = extract_requirements(SAMPLE_WITH_SECTION_BOUNDARY)
    fr5 = next(r for r in reqs if r.req_id == "FR-5")
    assert "Non-Functional" not in fr5.raw_text
    assert "encrypted" not in fr5.raw_text
    assert "concurrent users" not in fr5.raw_text


def test_nfr_extracted_as_separate_requirements():
    """NFR-1 and NFR-2 should be extracted as their own requirements."""
    reqs = extract_requirements(SAMPLE_WITH_SECTION_BOUNDARY)
    ids = [r.req_id for r in reqs]
    assert "NFR-1" in ids
    assert "NFR-2" in ids


def test_nfr_type_is_non_functional():
    """NFR requirements should have type='Non-Functional'."""
    reqs = extract_requirements(SAMPLE_WITH_SECTION_BOUNDARY)
    nfr1 = next(r for r in reqs if r.req_id == "NFR-1")
    assert nfr1.type == "Non-Functional"


def test_constraint_extracted_with_correct_type():
    """CR-1 should be extracted with type='Constraint'."""
    reqs = extract_requirements(SAMPLE_WITH_SECTION_BOUNDARY)
    cr1 = next(r for r in reqs if r.req_id == "CR-1")
    assert cr1.type == "Constraint"


def test_all_requirements_extracted_from_multi_section_doc():
    """Should extract FR-5, NFR-1, NFR-2, CR-1 = 4 requirements."""
    reqs = extract_requirements(SAMPLE_WITH_SECTION_BOUNDARY)
    assert len(reqs) == 4


# ---------- Separator variant tests (Fix #6) ----------

def test_dash_separator_accepted():
    """FR-4 - Title (space-dash-space) should be recognised."""
    reqs = extract_requirements(SAMPLE_WITH_DASH_SEPARATOR)
    assert len(reqs) == 1
    assert reqs[0].req_id == "FR-4"
    assert "cancellation" in reqs[0].title.lower() or "cancel" in reqs[0].description.lower()


def test_en_dash_separator_accepted():
    """FR-3 – Title (en-dash) should be recognised."""
    reqs = extract_requirements(SAMPLE_WITH_EN_DASH_SEPARATOR)
    assert len(reqs) == 1
    assert reqs[0].req_id == "FR-3"


def test_markdown_heading_prefix_accepted():
    """Docling parses some FRs as markdown headings (e.g. ## ● FR-4)."""
    text = "## ● FR-4: Appointment Cancellation\n- Description: Patients must cancel."
    reqs = extract_requirements(text)
    assert len(reqs) == 1
    assert reqs[0].req_id == "FR-4"


def test_implicit_description_capture():
    """Lines immediately following a header without a 'Description:' prefix should be captured as the description."""
    text = "NFR-1: Security\nAll passwords must be hashed."
    reqs = extract_requirements(text)
    assert len(reqs) == 1
    assert reqs[0].req_id == "NFR-1"
    assert "hashed" in reqs[0].description
