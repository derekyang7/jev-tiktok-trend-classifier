from datetime import UTC, datetime

from jevtrends.models import Video


def make_video(**overrides) -> Video:
    vid = overrides.pop("id", "7000000000000000001")
    handle = overrides.pop("author_handle", "creator1")
    fields = {
        "id": vid,
        "url": f"https://www.tiktok.com/@{handle}/video/{vid}",
        "author_id": overrides.pop("author_id", f"uid-{handle}"),
        "author_handle": handle,
        "caption": "My bank app is useless #budgeting",
        "hashtags": ["budgeting"],
        "posted_at": datetime(2026, 9, 20, tzinfo=UTC),
        "views": 1000,
        "likes": 100,
        "comment_count": 10,
    }
    fields.update(overrides)
    return Video(**fields)
