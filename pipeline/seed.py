"""Seed data for the Corridor scenarios.

All money is integer minor units (EUR cents). Rails, fees and the sanctions
sample are fictional.
"""
from dataclasses import dataclass

CURRENCY = "EUR"


@dataclass(frozen=True)
class Party:
    id: str
    name: str
    country: str


BUYER = Party("halvorsen-cole", "Halvorsen & Cole", "GB")
SUPPLIER = Party("brunnerteknik", "BrunnerTeknik GmbH", "DE")
ALLOWED_PAYEES = (SUPPLIER.id,)

# Halvorsen open payment mandate
MANDATE_CAP_MINOR = 34_500_000        # per payment, EUR 345,000
MANDATE_BUDGET_MINOR = 140_000_000    # cumulative, EUR 1,400,000
MANDATE_MAX_USES = 4
MANDATE_FREQUENCY = "QUARTERLY"

# Negotiation policy: accepted drift from the agreed price, in basis points
PRICE_TOLERANCE_BPS = 100


@dataclass(frozen=True)
class Scenario:
    ref: str
    agreed_minor: int
    quoted_minor: int
    expected_tier: int


FP_88213 = Scenario("FP-88213", 34_000_000, 34_000_000, 1)   # in policy
FP_88214 = Scenario("FP-88214", 34_000_000, 35_200_000, 2)   # price drift


@dataclass(frozen=True)
class Rail:
    id: str
    name: str
    fee_minor: int
    settlement_hours: int
    max_minor: int | None = None      # None means no limit
    via_pisp: bool = False


RAILS = (
    Rail("sepa_sct", "SEPA Credit Transfer", 150, 24),
    Rail("sepa_inst", "SEPA Instant", 40, 0, max_minor=10_000_000),
    Rail("swift", "SWIFT", 4_500, 48),
    Rail("farside", "Farside (PISP)", 900, 1, via_pisp=True),
)

# Fictional entities for the Compliance Screening Gate
SANCTIONS_SAMPLE = (
    "Zelmarin Trading FZE",
    "Voskhod-Brandt Logistics",
    "Kessling Marine Holdings",
)
