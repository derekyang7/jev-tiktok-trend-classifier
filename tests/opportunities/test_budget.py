from jevtrends.core.budget import BudgetGuard
from jevtrends.opportunities.budget import RemainingWork, decide_opportunities, project_opportunities, remaining_work
from jevtrends.opportunities.config import Settings

SETTINGS = Settings()
GUARD = BudgetGuard(SETTINGS.budget.max_usd_per_scan, SETTINGS.pricing)


def test_default_scan_projection_uses_pilot_pass_rate_and_fits_by_trimming_briefs():
    work = remaining_work("collect", {"queries": 65}, SETTINGS, comment_videos=150, max_briefs=20)
    assert (work.search_requests, work.transcript_requests, work.comment_requests) == (130, 1000, 150)
    projection = project_opportunities(GUARD, work)
    assert round(projection.scraper, 4) == 2.4064
    assert 5.5 < projection.total < 6.0
    decision = decide_opportunities(GUARD, 0.0, work, min_briefs=5)
    assert decision.ok and (decision.brief_count, decision.comment_requests) == (12, 150)


def test_remaining_work_skips_finished_stages():
    work = remaining_work("brief", {"kept": 10}, SETTINGS, comment_videos=150, max_briefs=20)
    assert work == RemainingWork(brief_count=10)
    assert remaining_work("brief", {"kept": 0}, SETTINGS, 150, 20).brief_count == 0


def test_decide_keeps_everything_when_it_fits():
    decision = decide_opportunities(GUARD, 0.0, RemainingWork(comment_requests=150, brief_count=20), min_briefs=5)
    assert decision.ok and decision.trims == []
    assert (decision.comment_requests, decision.brief_count) == (150, 20)


def test_decide_trims_briefs_before_comments():
    work = RemainingWork(comment_requests=150, brief_count=20)  # 0.282 + 2.0 = 2.282
    decision = decide_opportunities(GUARD, 5.0 - 2.2, work, min_briefs=5)
    assert decision.ok
    assert (decision.brief_count, decision.comment_requests) == (19, 150)
    assert len(decision.trims) == 1


def test_decide_trims_comments_only_after_briefs_reach_minimum():
    work = RemainingWork(comment_requests=150, brief_count=20)
    decision = decide_opportunities(GUARD, 4.4, work, min_briefs=5)  # 0.60 available
    assert decision.ok
    assert (decision.brief_count, decision.comment_requests) == (5, 53)
    assert len(decision.trims) == 2


def test_decide_fails_when_required_work_cannot_fit():
    decision = decide_opportunities(GUARD, 4.99, RemainingWork(transcript_requests=600), min_briefs=5)
    assert not decision.ok
