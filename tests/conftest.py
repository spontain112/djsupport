"""Shared pytest fixtures."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def library_xml():
    """Path to the sample Rekordbox XML fixture."""
    return FIXTURES_DIR / "library.xml"
