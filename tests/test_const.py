"""Tests for the SomToday constants and pure helpers.

``unique_id_for`` defines the identity model: one config entry per
``(account, student)`` pair. It is deliberately free of Home Assistant imports
so it can be tested in isolation.
"""

from __future__ import annotations

from custom_components.sometoday.const import unique_id_for


def test_unique_id_for_builds_composite_id() -> None:
    """The composite unique id is ``account_id:student_id``."""
    assert unique_id_for("account-1", 1234) == "account-1:1234"


def test_unique_id_for_distinguishes_students_of_one_account() -> None:
    """Two students of the same account get distinct unique ids."""
    assert unique_id_for("account-1", 1234) != unique_id_for("account-1", 5678)


def test_unique_id_for_distinguishes_accounts_for_one_student() -> None:
    """The same student id under different accounts gets distinct ids."""
    assert unique_id_for("account-1", 1234) != unique_id_for("account-2", 1234)
