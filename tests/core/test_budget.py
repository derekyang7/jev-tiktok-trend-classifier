import pytest

from jevtrends.core.budget import BudgetGuard, Trimmable, trim_to_fit
from jevtrends.core.config import PricingCfg

GUARD = BudgetGuard(5.0, PricingCfg())


def test_budget_guard_unit_cost_math():
    assert GUARD.scraper_cost(10) == pytest.approx(10 * 0.00188)
    assert GUARD.jev_cost(4000) == pytest.approx(1000 * 1.2 * 0.042 / 1e6)
    assert GUARD.llm_cost(4000, 1000) == (1000 * 5.0 + 1000 * 25.0) / 1e6


def test_trim_to_fit_cuts_items_in_order_down_to_their_minimums():
    items = [Trimmable("briefs", 10, 0.1, 5, lambda kept, was: f"{kept} of {was} briefs"),
             Trimmable("comments", 100, 0.002, 0, lambda kept, was: f"{kept} of {was} comments")]
    fits = trim_to_fit(2.0, 0.5, items)
    assert fits.ok and fits.units == {"briefs": 10, "comments": 100} and fits.trims == []
    tight = trim_to_fit(1.0, 0.5, items)  # 0.5 + 1.0 + 0.2 = 1.7: briefs go to 5, then comments to 0
    assert tight.ok and tight.units == {"briefs": 5, "comments": 0}
    assert tight.trims == ["5 of 10 briefs", "0 of 100 comments"]
    assert not trim_to_fit(0.4, 0.5, items).ok
