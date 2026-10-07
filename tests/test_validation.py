from app.schemas import RecipientIn
from app.validation import check_recipient, check_recipients


def test_whitespace_is_cleaned_and_email_normalised():
    row = check_recipient(1, RecipientIn(name="  Jane   Doe ", email=" Jane@Example.COM "))
    assert row.is_valid
    assert row.name == "Jane Doe"
    assert row.email == "jane@example.com"


def test_email_is_optional():
    assert check_recipient(1, RecipientIn(name="Jane Doe")).is_valid


def test_accented_latin_names_are_accepted():
    assert check_recipient(1, RecipientIn(name="Zoë Doe")).is_valid


def test_name_length_limit():
    row = check_recipient(1, RecipientIn(name="A" * 101))
    assert row.errors == ["name is longer than 100 characters"]


def test_duplicates_are_detected_case_insensitively():
    rows = check_recipients([
        RecipientIn(name="Jane Doe", email="jane@example.com"),
        RecipientIn(name="JANE DOE", email="jane@example.com"),
        RecipientIn(name="Jane Doe", email="other@example.com"),  # different person, same name
    ])
    assert [r.errors for r in rows] == [[], ["duplicate of row 1"], []]


def test_an_invalid_row_does_not_count_as_the_original_for_duplicates():
    rows = check_recipients([
        RecipientIn(name="Jane Doe", email="bad"),
        RecipientIn(name="Jane Doe", email="bad"),
    ])
    assert all(r.errors and r.errors[0].startswith("email is invalid") for r in rows)
    assert not any("duplicate" in e for r in rows for e in r.errors)
