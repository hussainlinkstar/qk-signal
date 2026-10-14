"""Tests for target_country validation on project create/update requests.

A free-text "Target market (ISO)" input with no real validation let a
non-ISO value ("GLO", short for "Global") into a project's target_country.
That value then flows into the AI synthesis prompt as `"market": "glo"`
with nothing else clearly establishing the real brand identity (the
homepage was missing title/meta/H1), and the model hallucinated it as the
brand name, telling the user to add an SEO title tag with "the brand name
'Glo'". Rejecting non-ISO country codes at input time prevents this class
of bad data (and the downstream hallucination risk) for every project.
"""

import pytest
from pydantic import ValidationError

from routers.workspace_router import ProjectCreateRequest, ProjectUpdateRequest


class TestProjectCreateRequestTargetCountry:
    def test_accepts_a_real_iso_3166_1_alpha_2_code(self) -> None:
        payload = ProjectCreateRequest(name="Acme", domain_url="acme.example", target_country="us")
        assert payload.target_country == "US"

    def test_rejects_a_non_iso_three_letter_abbreviation(self) -> None:
        # "GLO" (short for "Global") is exactly the real bad data that led an
        # audit to hallucinate "Glo" as the brand name. A 3-letter value is
        # already too long for an ISO 3166-1 alpha-2 code.
        with pytest.raises(ValidationError):
            ProjectCreateRequest(name="Acme", domain_url="acme.example", target_country="GLO")

    def test_rejects_a_real_looking_but_invalid_two_letter_code(self) -> None:
        with pytest.raises(ValidationError, match="ISO 3166-1 alpha-2"):
            ProjectCreateRequest(name="Acme", domain_url="acme.example", target_country="ZZ")

    def test_leaves_target_country_unset_for_global_targeting(self) -> None:
        # The correct way to express "no single target market" is to leave
        # this field empty, not to type a pseudo-code like "GLOBAL"/"GLO".
        payload = ProjectCreateRequest(name="Acme", domain_url="acme.example")
        assert payload.target_country is None


class TestScanLaunchFreeTextMarketIsNotATargetCountry:
    """The scan launch form's "Main market" is free text, not a country code.

    A scan started with no project selected creates one first, and the client
    used to send that free-text market straight through as `target_country`.
    Every value the form actually produces is rejected here, so project
    creation returned 422 and the scan never started. The client now resolves
    the market to an ISO code, or sends nothing (SIGV2-1110). These cases pin
    the contract the client has to respect.
    """

    @pytest.mark.parametrize(
        "market",
        [
            "",  # the form default, when nothing was detected or typed
            "Romania",  # what the pre-scan autofill writes into the field
            "London, UK",  # the field's own placeholder example
            "United States",
            "Global",
        ],
    )
    def test_free_text_market_values_are_rejected(self, market: str) -> None:
        with pytest.raises(ValidationError):
            ProjectCreateRequest(
                name="https://example.com",
                domain_url="https://example.com",
                language="en",
                target_country=market,
            )

    def test_an_unset_target_country_creates_the_project(self) -> None:
        payload = ProjectCreateRequest(
            name="https://example.com",
            domain_url="https://example.com",
            language="en",
            target_country=None,
        )
        assert payload.target_country is None

    def test_a_resolved_iso_code_creates_the_project(self) -> None:
        payload = ProjectCreateRequest(
            name="https://example.com",
            domain_url="https://example.com",
            language="en",
            target_country="RO",
        )
        assert payload.target_country == "RO"


class TestProjectUpdateRequestTargetCountry:
    def test_accepts_a_real_iso_3166_1_alpha_2_code(self) -> None:
        payload = ProjectUpdateRequest(target_country="gb")
        assert payload.target_country == "GB"

    def test_rejects_a_non_iso_three_letter_abbreviation(self) -> None:
        with pytest.raises(ValidationError):
            ProjectUpdateRequest(target_country="GLO")

    def test_none_is_still_allowed_to_clear_the_field(self) -> None:
        payload = ProjectUpdateRequest(target_country=None)
        assert payload.target_country is None
