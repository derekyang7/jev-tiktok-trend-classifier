import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from jevtrends.config import RetriesCfg
from jevtrends.sources.scrapecreators import ScrapeCreatorsSource, date_posted_for, parse_video, vtt_to_text
from tests.helpers import make_video

CONTRACT = Path(__file__).resolve().parents[1] / "fixtures" / "contract"
RETRIES = RetriesCfg(max_attempts=1)
SEARCH_JSON = {
    "success": True, "credits_charged": 1, "cursor": 12, "has_more": 1,
    "search_item_list": [
        {"aweme_info": {
            "aweme_id": "111", "desc": "My bank app is useless #budgeting #fintech", "create_time": 1790380800,
            "statistics": {"play_count": 5000, "digg_count": 300, "comment_count": 40, "share_count": 7},
            "author": {"uid": "u1", "unique_id": "alice", "nickname": "Alice", "signature": "saving money daily"},
            "text_extra": [{"hashtag_name": "budgeting"}, {"hashtag_name": "fintech"}, {"user_id": "x"}],
            "music": {"title": "original sound"}, "desc_language": "en", "video": {"duration": 30}}},
        {"aweme_info": {"aweme_id": "222", "desc": "", "create_time": 1790467200, "statistics": {},
                        "author": {"unique_id": "bob"}}},
        {"not_a_video": True},
    ],
}


def source_for(handler) -> ScrapeCreatorsSource:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ScrapeCreatorsSource(client, "test-key", RETRIES)


def test_date_posted_mapping():
    assert [date_posted_for(d) for d in (1, 7, 30, 90, 180, 365)] == [
        "yesterday", "this-week", "this-month", "last-3-months", "last-6-months", "all-time"]


def test_parse_video_maps_fields():
    video = parse_video(SEARCH_JSON["search_item_list"][0]["aweme_info"])
    assert video.id == "111"
    assert video.url == "https://www.tiktok.com/@alice/video/111"
    assert (video.author_id, video.author_handle, video.author_bio) == ("u1", "alice", "saving money daily")
    assert video.hashtags == ["budgeting", "fintech"]
    assert video.posted_at == datetime(2026, 9, 26, tzinfo=UTC)
    assert (video.views, video.likes, video.comment_count, video.shares) == (5000, 300, 40, 7)
    assert (video.sound, video.language) == ("original sound", "en")
    assert "video" not in video.raw


def test_parse_video_tolerates_missing_fields():
    video = parse_video(SEARCH_JSON["search_item_list"][1]["aweme_info"])
    assert (video.caption, video.hashtags, video.author_bio, video.views, video.language) == ("", [], "", 0, None)
    assert video.author_id == "bob"


async def test_search_sends_params_and_skips_non_videos():
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        seen["key"] = request.headers.get("x-api-key")
        seen["path"] = request.url.path
        return httpx.Response(200, json=SEARCH_JSON)

    page = await source_for(handler).search("budgeting app", 30, "US")
    assert seen["path"] == "/v1/tiktok/search/keyword"
    assert seen["params"] == {"query": "budgeting app", "date_posted": "this-month", "sort_by": "relevance", "region": "US"}
    assert seen["key"] == "test-key"
    assert [v.id for v in page.videos] == ["111", "222"]
    assert (page.next_cursor, page.credits) == (12, 1)


async def test_search_stops_when_has_more_is_zero():
    body = {**SEARCH_JSON, "has_more": 0}
    page = await source_for(lambda r: httpx.Response(200, json=body)).search("x", 30, "US", cursor=12)
    assert page.next_cursor is None


def test_vtt_to_text():
    vtt = "WEBVTT\n\n00:00:00.120 --> 00:00:01.840\nAlright, pizza review time.\n\n00:00:01.840 --> 00:00:03.000\nAlright, pizza review time.\n\n2\n00:00:03.000 --> 00:00:04.000\nFive stars."
    assert vtt_to_text(vtt) == "Alright, pizza review time. Five stars."
    assert vtt_to_text("WEBVTT\n\n") is None
    assert vtt_to_text("") is None
    assert vtt_to_text(None) is None
    assert vtt_to_text("   ") is None


async def test_transcript_ok_and_missing_variants():
    video = make_video()
    ok = source_for(lambda r: httpx.Response(200, json={"credits_charged": 1, "transcript": "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello"}))
    assert (await ok.transcript(video)).text == "hello"
    null = source_for(lambda r: httpx.Response(200, json={"credits_charged": 1, "transcript": None}))
    assert (await null.transcript(video)).text is None
    not_found = source_for(lambda r: httpx.Response(404, json={"message": "no transcript"}))
    result = await not_found.transcript(video)
    assert result.text is None and result.credits == 1


async def test_comments_sorted_by_likes_truncated_and_limited():
    body = {"credits_charged": 1, "comments": [
        {"text": "short", "digg_count": 5},
        {"text": "   ", "digg_count": 99},
        {"text": "x" * 500, "digg_count": 50},
        {"text": "what's the name of this app?", "digg_count": 20},
    ]}
    result = await source_for(lambda r: httpx.Response(200, json=body)).comments(make_video(), limit=2, max_chars=300)
    assert [c.likes for c in result.comments] == [50, 20]
    assert len(result.comments[0].text) == 300


@pytest.mark.skipif(not (CONTRACT / "sc_search.json").exists(), reason="Task 1 fixtures not recorded")
def test_parses_recorded_contract_fixtures():
    search = json.loads((CONTRACT / "sc_search.json").read_text())
    videos = [parse_video(item["aweme_info"]) for item in search["search_item_list"]]
    assert videos and all(v.id and v.posted_at.tzinfo for v in videos)
    transcript = json.loads((CONTRACT / "sc_transcript.json").read_text())["body"]
    text = vtt_to_text(transcript.get("transcript"))
    assert text is None or isinstance(text, str)
