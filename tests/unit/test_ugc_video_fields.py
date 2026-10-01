import json
from pathlib import Path

import pytest

from jevtrends.models import Enrichment, SoundInfo, VisionRead
from jevtrends.sources.scrapecreators import parse_top_item, parse_video
from jevtrends.store import Store

UGC_CONTRACT = Path(__file__).resolve().parents[1] / "fixtures" / "contract" / "ugc"
AWEME = {
    "aweme_id": "333", "desc": "5 apps you need #apps #iphone", "create_time": 1790380800, "desc_language": "en",
    "statistics": {"play_count": 20000, "digg_count": 900, "comment_count": 40, "share_count": 70,
                   "collect_count": 310},
    "author": {"uid": "u3", "unique_id": "cara", "follower_count": 5400},
    "text_extra": [{"hashtag_name": "apps"}, {"hashtag_name": "iphone"}],
    "music": {"id": 7603640959766711000, "id_str": "7603640959766711053", "title": "original sound - cara",
              "author": "cara", "is_original_sound": True, "user_count": 306093, "is_commerce_music": True,
              "is_commerce_music_strict": False, "has_commerce_right": True, "unrelated": 1},
    "video": {"duration": 18434, "origin_cover": {"url_list": ["https://cdn.example/origin.jpeg"]},
              "cover": {"url_list": ["https://cdn.example/cover.jpeg"]}},
    "creation_info": {"creation_used_functions": ["text", "green_screen"]},
    "anchors": [{"keyword": "Green Screen", "type": 28}, {"type": 35}],
    "is_ad": True, "is_paid_partnership": False, "commerce_info": {"branded_content_type": 7},
}
TOP_PHOTO = {"id": "444", "desc": "apps that feel illegal to know #apps #fyp", "content_type": "multi_photo",
             "create_time": 1790380800, "statistics": {"play_count": 100}, "author": {"unique_id": "dee"},
             "images": ["https://cdn.example/p1.jpeg", "https://cdn.example/p2.jpeg"],
             "music": {"id_str": "9", "title": "Song"}, "url": "https://www.tiktok.com/@dee/photo/444"}


def test_parse_video_extracts_ugc_fields():
    video = parse_video(AWEME)
    assert (video.duration_ms, video.is_slideshow, video.slide_urls) == (18434, False, [])
    assert video.cover_url == "https://cdn.example/cover.jpeg"  # Task 1 ruling: the JPEG cover, not the HEIC origin_cover
    assert video.sound_info == SoundInfo(
        id="7603640959766711053", title="original sound - cara", author="cara", is_original=True, use_count=306093,
        licensing={"is_commerce_music": True, "is_commerce_music_strict": False, "has_commerce_right": True})
    assert (video.author_followers, video.saves) == (5400, 310)
    assert video.editing_features == ["text", "green_screen"]
    assert video.anchors == ["Green Screen"]
    assert video.ad_flags == {"is_ad": True, "is_paid_partnership": False, "branded_content_type": 7}
    assert "video" not in video.raw


def test_parse_video_reads_slideshow_images_and_tolerates_missing_media():
    images = [{"display_image": {"url_list": ["https://cdn.example/s1.jpeg"]}}, {"display_image": {"url_list": []}},
              {"display_image": {"url_list": ["https://cdn.example/s2.jpeg"]}}]
    video = parse_video({**AWEME, "video": {}, "image_post_info": {"images": images}, "music": None})
    assert video.is_slideshow and video.slide_urls == ["https://cdn.example/s1.jpeg", "https://cdn.example/s2.jpeg"]
    assert (video.cover_url, video.duration_ms, video.sound_info) == (None, None, None)


def test_minimal_video_gets_empty_ugc_defaults():
    bare = parse_video({"aweme_id": "1", "create_time": 1790380800, "author": {"unique_id": "x"}})
    assert (bare.author_followers, bare.saves, bare.editing_features, bare.anchors) == (None, 0, [], [])
    assert bare.ad_flags == {"is_ad": False, "is_paid_partnership": False, "branded_content_type": 0}


def test_parse_top_item_normalizes_photo_posts_and_reads_hashtags_from_the_caption():
    video = parse_top_item(TOP_PHOTO)
    assert video.id == "444" and video.is_slideshow
    assert video.slide_urls == ["https://cdn.example/p1.jpeg", "https://cdn.example/p2.jpeg"]
    assert video.hashtags == ["apps", "fyp"]
    assert video.url == "https://www.tiktok.com/@dee/video/444"
    assert video.sound_info.id == "9"


def test_parse_top_item_video_keeps_its_text_extra():
    video = parse_top_item({**TOP_PHOTO, "content_type": "video", "images": None,
                            "text_extra": [{"hashtag_name": "tech"}]})
    assert not video.is_slideshow and video.hashtags == ["tech"]


def test_videos_and_enrichments_with_ugc_fields_roundtrip_through_the_store():
    store = Store(":memory:")
    video = parse_video(AWEME)
    store.upsert_video(video)
    assert store.get_video("333") == video
    enrichment = Enrichment(video_id="333", transcript_status="not_applicable",
                            vision=VisionRead(on_screen_text="5 APPS", setup="phone screen recording", model="m"))
    store.upsert_enrichment(enrichment)
    assert store.get_enrichment("333") == enrichment


@pytest.mark.skipif(not (UGC_CONTRACT / "sc_hashtag.json").exists(), reason="Task 1 fixtures not recorded")
def test_recorded_hashtag_items_parse_with_ugc_fields():
    items = json.loads((UGC_CONTRACT / "sc_hashtag.json").read_text())["aweme_list"]
    videos = [parse_video(item) for item in items]
    assert videos and all(v.author_followers is not None and v.sound_info for v in videos)
