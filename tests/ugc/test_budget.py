import pytest

from jevtrends.ugc.budget import UgcWork, decide_ugc, project_ugc, ugc_remaining_work
from jevtrends.ugc.config import UgcSettings

S = UgcSettings()


def default_work() -> UgcWork:
    return ugc_remaining_work("collect", {"searches": 38}, S, comment_videos=100, slides_per_post=3, max_briefs=11)


def test_default_run_projects_about_4_70_and_fits_without_cuts():
    work = default_work()
    assert (work.search_requests, work.transcript_requests, work.comment_requests, work.sound_requests) == (
        76, 432, 100, 53)
    assert (work.vision_requests, work.cover_images, work.extra_slides, work.brief_count) == (480, 480, 96, 11)
    projection = project_ugc(work, S)
    assert projection.scraper == pytest.approx(661 * 0.00188)
    assert 4.5 < projection.total < 4.95
    decision = decide_ugc(0.0, work, S, slideshows=48, slides_per_post=3)
    assert decision.ok and decision.trims == []
    assert (decision.brief_count, decision.comment_requests, decision.slides_per_post) == (11, 100, 3)


def test_cuts_briefs_then_comments_then_extra_slides():
    decision = decide_ugc(1.295, default_work(), S, slideshows=48, slides_per_post=3)  # $3.705 left of about $4.71
    assert decision.ok
    assert (decision.brief_count, decision.comment_requests, decision.slides_per_post) == (5, 0, 1)
    assert decision.trims[0] == "5 briefs written instead of 11"
    assert decision.trims[1] == "comments fetched for 0 videos instead of 100"
    assert decision.trims[2].endswith("extra slideshow slides read instead of 96")


def test_stops_when_required_work_cannot_fit():
    assert not decide_ugc(4.9, default_work(), S, slideshows=48, slides_per_post=3).ok


def test_remaining_work_uses_known_counts_and_skips_finished_stages():
    counts = {"searches": 38, "collected": 500, "gate_passed": 300, "slideshows": 20, "relevant": 200, "sounds": 30}
    work = ugc_remaining_work("look", counts, S, comment_videos=100, slides_per_post=3, max_briefs=11)
    assert (work.search_requests, work.transcript_requests, work.comment_requests) == (0, 0, 0)
    assert (work.vision_requests, work.extra_slides) == (300, 40)
    assert ugc_remaining_work("brief", {"searches": 38, "kept": 3, "sounds": 2}, S, 100, 3, 11) == UgcWork(
        brief_count=5)


def test_no_vision_work_when_vision_is_off():
    settings = UgcSettings()
    settings.vision = settings.vision.model_copy(update={"enabled": False})
    work = ugc_remaining_work("collect", {"searches": 38}, settings, 100, 3, 11)
    assert (work.vision_requests, work.cover_images, work.extra_slides) == (0, 0, 0)
