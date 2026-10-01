import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from jevtrends.config import RetriesCfg
from jevtrends.http import FatalAPIError
from jevtrends.sources.scrapecreators import (ScrapeCreatorsSource, aweme_list_page, parse_song, parse_top_item,
                                              unwrap_data)

UGC_CONTRACT = Path(__file__).resolve().parents[1] / "fixtures" / "contract" / "ugc"
AWEME = {"aweme_id": "9", "desc": "apps #apps", "create_time": 1790380800, "author": {"unique_id": "a"},
         "statistics": {}}


def source_for(handler) -> tuple[ScrapeCreatorsSource, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def wrapped(request):
        requests.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
    return ScrapeCreatorsSource(client, "test-key", RetriesCfg(max_attempts=1)), requests


async def test_search_hashtag_sends_the_bare_tag_and_parses_aweme_list():
    body = {"aweme_list": [AWEME, {"aweme_id": "no-time"}], "cursor": 20, "has_more": 1, "credits_charged": 1}
    source, requests = source_for(lambda r: httpx.Response(200, json=body))
    page = await source.search_hashtag("#appsyouneed", "US", cursor=10)
    assert requests[0].url.path == "/v1/tiktok/search/hashtag"
    assert dict(requests[0].url.params) == {"hashtag": "appsyouneed", "region": "US", "cursor": "10"}
    assert requests[0].headers["x-api-key"] == "test-key"
    assert [v.id for v in page.videos] == ["9"] and (page.next_cursor, page.credits) == (20, 1)


async def test_unavailable_hashtags_and_songs_are_empty_pages_but_bad_keys_stay_fatal():
    source, _ = source_for(lambda r: httpx.Response(404, json={"message": "not found"}))
    assert (await source.search_hashtag("gone", "US")).videos == []
    assert (await source.song_videos("123")).videos == []
    source, _ = source_for(lambda r: httpx.Response(401, json={"message": "bad key"}))
    with pytest.raises(FatalAPIError):
        await source.search_hashtag("x", "US")


async def test_search_top_maps_the_window_and_parses_photo_posts():
    item = {"id": "44", "desc": "apps #apps", "content_type": "multi_photo", "create_time": 1790380800,
            "author": {"unique_id": "b"}, "images": ["https://cdn.example/1.jpeg"]}
    source, requests = source_for(lambda r: httpx.Response(200, json={"items": [item], "cursor": 30,
                                                                     "credits_charged": 1}))
    page = await source.search_top("apps you need", 14, "US")
    assert requests[0].url.path == "/v1/tiktok/search/top"
    assert dict(requests[0].url.params) == {"query": "apps you need", "publish_time": "this-month",
                                            "sort_by": "relevance", "region": "US"}
    assert page.videos[0].is_slideshow and page.next_cursor == 30


def test_parse_song_sorts_the_trend_and_reads_the_business_flag():
    song = parse_song({"clip_id": "7", "title": "Song", "author": "Artist", "rank": 3,
                       "link": "https://www.tiktok.com/music/song-7", "if_cml": True,
                       "trend": [{"time": 2, "value": 0.5}, {"time": 1, "value": 0.2}]})
    assert (song.sound_id, song.rank, song.commercial, song.trend) == ("7", 3, True, [0.2, 0.5])
    bare = parse_song({"song_id": "8"})
    assert (bare.sound_id, bare.commercial, bare.trend) == ("8", None, [])


async def test_popular_songs_sends_params_and_reads_wrapped_or_flat_payloads():
    body = {"credits_charged": 1, "data": {"pagination": {"page": 1, "has_more": True},
                                           "sound_list": [{"clip_id": "7", "title": "Song", "rank": 1}]}}
    source, requests = source_for(lambda r: httpx.Response(200, json=body))
    page = await source.popular_songs(7, "US", 1, commercial_only=False)
    assert requests[0].url.path == "/v1/tiktok/songs/popular"
    assert dict(requests[0].url.params) == {"page": "1", "timePeriod": "7", "rankType": "popular",
                                            "countryCode": "US"}
    assert [s.sound_id for s in page.songs] == ["7"] and page.has_more and page.credits == 1
    await source.popular_songs(7, "US", 2, commercial_only=True)
    assert requests[1].url.params["commercialMusic"] == "true"
    flat, _ = source_for(lambda r: httpx.Response(200, json={"sound_list": [], "pagination": {"has_more": True}}))
    assert (await flat.popular_songs(7, "US", 1, commercial_only=False)).has_more is False


async def test_song_videos_sends_the_clip_id():
    source, requests = source_for(lambda r: httpx.Response(200, json={"aweme_list": [AWEME], "cursor": 30,
                                                                     "has_more": 0}))
    page = await source.song_videos("7603640959766711053")
    assert requests[0].url.path == "/v1/tiktok/song/videos"
    assert dict(requests[0].url.params) == {"clipId": "7603640959766711053"}
    assert [v.id for v in page.videos] == ["9"] and page.next_cursor is None


@pytest.mark.parametrize("name", ["sc_hashtag.json", "sc_top.json", "sc_songs_popular.json", "sc_song_videos.json"])
def test_recorded_ugc_fixtures_parse(name):
    path = UGC_CONTRACT / name
    if not path.exists():  # the popular-songs list was down when the fixtures were recorded (contract check D3)
        pytest.skip(f"{name} not recorded")
    data = json.loads(path.read_text())
    if name == "sc_top.json":
        assert all(parse_top_item(item).id for item in data["items"])
    elif name == "sc_songs_popular.json":
        assert all(parse_song(item).sound_id for item in unwrap_data(data)["sound_list"])
    else:
        assert aweme_list_page(data).videos


def test_parse_top_item_reads_iso_create_time():
    # Recorded Top-search items carry ISO 8601 times, unlike keyword search's epoch seconds (contract check D2).
    item = {"id": "45", "desc": "apps", "content_type": "video", "create_time": "2026-09-04T09:57:58.000Z",
            "author": {"unique_id": "c"}, "music": {"id": "991", "title": "Song"}}
    video = parse_top_item(item)
    assert video.posted_at == datetime(2026, 9, 4, 9, 57, 58, tzinfo=UTC)
    assert video.sound_info.id == "991"
