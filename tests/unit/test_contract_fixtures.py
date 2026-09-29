"""The recorded ScrapeCreators fixtures are committed, so they must not carry creators' or commenters' identifiers."""

import json
from pathlib import Path

import pytest

CONTRACT = Path(__file__).resolve().parents[1] / "fixtures" / "contract"
IDENTIFYING = {"unique_id", "nickname", "uid", "sec_uid", "signature", "author_user_id", "avatar_uri", "owner_handle",
               "owner_id", "owner_nickname", "search_user_desc", "search_user_name", "share_desc", "share_title",
               "share_url", "user_id", "sec_user_id", "ins_id", "twitter_id", "youtube_channel_id", "reply_to_username"}


def walk(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield f"{path}/{key}", key, value
            yield from walk(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{path}[{index}]")


@pytest.mark.parametrize("name", ["sc_search.json", "sc_comments.json", "sc_transcript.json"])
def test_scrapecreators_fixtures_hold_no_personal_identifiers(name):
    leaks = []
    for path, key, value in walk(json.loads((CONTRACT / name).read_text())):
        text = value if isinstance(value, str) else ""
        if key in IDENTIFYING and value not in (None, "", 0) and not str(value).startswith("redacted"):
            leaks.append(path)
        elif key == "share_info" or (key.startswith("avatar") and isinstance(value, dict)):
            leaks.append(path)
        elif key == "author" and isinstance(value, str) and value != "redacted":
            leaks.append(path)
        elif key == "title" and text.startswith("original sound - ") and text != "original sound - redacted":
            leaks.append(path)
        elif key in ("url", "share_url") and "/@" in text and "/@redacted" not in text:
            leaks.append(path)
    assert leaks == []
