import io

import httpx
from PIL import Image

from jevtrends.config import RetriesCfg
from jevtrends.models import Answer
from jevtrends.ugc.images import ImageFetcher, prepare_image
from jevtrends.ugc.prompts import VisionOut
from jevtrends.ugc.stages.look import run_look
from tests.helpers import make_video
from tests.ugc.fakes import FakeImages, FakeVision, make_ugc_ctx, sequential, tiny_png


def jpeg(size: tuple[int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, format="JPEG")
    return buffer.getvalue()


def survivors(ctx, *videos) -> None:
    for video in videos:
        ctx.store.upsert_video(video)
        ctx.store.add_run_video(ctx.run_id, video.id, "keyword:apps you need")
        ctx.store.upsert_judgment(ctx.run_id, "video", video.id, "ugc_gate.relevant", 1, Answer(value=0.9))


def test_prepare_image_passes_small_supported_images_through_and_shrinks_large_ones():
    small = tiny_png((1, 2, 3))
    part = prepare_image(small, 960)
    assert part.data == small and part.media_type == "image/png"
    shrunk = prepare_image(jpeg((1440, 2560)), 960)
    with Image.open(io.BytesIO(shrunk.data)) as image:
        assert image.size == (540, 960) and image.format == "JPEG"
    assert shrunk.media_type == "image/jpeg"
    assert prepare_image(b"not an image", 960) is None


async def test_image_fetcher_sends_no_api_key_and_maps_errors_and_size_to_none():
    seen = []

    def handler(request):
        seen.append({k.lower() for k in request.headers})
        if request.url.path == "/expired":
            return httpx.Response(403)
        if request.url.path == "/big":
            return httpx.Response(200, content=b"x" * 50)
        return httpx.Response(200, content=b"ok")

    fetcher = ImageFetcher(httpx.AsyncClient(transport=httpx.MockTransport(handler)), RetriesCfg(max_attempts=1))
    assert await fetcher.fetch("https://cdn.example/ok", 10) == b"ok"
    assert await fetcher.fetch("https://cdn.example/expired", 10) is None
    assert await fetcher.fetch("https://cdn.example/big", 10) is None
    assert all("x-api-key" not in headers and "authorization" not in headers for headers in seen)


async def test_look_reads_covers_and_slides_and_saves_clean_text():
    cover, s1, s2, s3, s4 = (tiny_png((i, i, i)) for i in range(5))
    images = FakeImages({"https://cdn/cover-a": cover, "https://cdn/s1": s1, "https://cdn/s2": s2,
                         "https://cdn/s3": s3, "https://cdn/s4": s4})
    vision = FakeVision(reads={
        cover: VisionOut(on_screen_text="  POV: you   found the app ", setup="woman talking to camera in a car"),
        s1: VisionOut(on_screen_text="5 apps you need", setup="slides of app screenshots")})
    ctx = make_ugc_ctx(images=images, vision=vision)
    survivors(ctx, make_video(id="a", cover_url="https://cdn/cover-a"),
              make_video(id="s", is_slideshow=True,
                         slide_urls=["https://cdn/s1", "https://cdn/s2", "https://cdn/s3", "https://cdn/s4"]))
    await run_look(ctx)
    read = ctx.store.get_enrichment("a").vision
    assert (read.on_screen_text, read.setup, read.status) == ("POV: you found the app",
                                                              "woman talking to camera in a car", "ok")
    assert ctx.store.get_enrichment("s").vision.on_screen_text == "5 apps you need"
    slideshow_images = next(parts for user, parts in vision.calls if "slides" in user)
    assert [part.data for part in slideshow_images] == [s1, s2, s3]
    assert ctx.store.spend_by_provider(ctx.run_id)["vision"] > 0
    calls = len(vision.calls)
    await run_look(ctx)
    assert len(vision.calls) == calls


async def test_the_budget_limit_on_slides_is_respected():
    s1, s2 = tiny_png((1, 1, 1)), tiny_png((2, 2, 2))
    vision = FakeVision()
    ctx = make_ugc_ctx(images=FakeImages({"https://cdn/s1": s1, "https://cdn/s2": s2}), vision=vision)
    survivors(ctx, make_video(id="s", is_slideshow=True, slide_urls=["https://cdn/s1", "https://cdn/s2"]))
    ctx.limits["slides_per_post"] = 1
    await run_look(ctx)
    assert [part.data for part in vision.calls[0][1]] == [s1]


async def test_unreadable_images_are_no_image_and_never_failures():
    heic = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 40
    images = FakeImages({"https://cdn/heic": heic, "https://cdn/huge": jpeg((64, 64))})
    settings = sequential()
    settings.vision = settings.vision.model_copy(update={"max_image_bytes": 200})
    ctx = make_ugc_ctx(images=images, settings=settings)
    survivors(ctx, make_video(id="none"), make_video(id="expired", cover_url="https://cdn/gone"),
              make_video(id="heic", cover_url="https://cdn/heic"), make_video(id="huge", cover_url="https://cdn/huge"))
    await run_look(ctx)
    statuses = {v: ctx.store.get_enrichment(v).vision.status for v in ("none", "expired", "heic", "huge")}
    assert statuses == {"none": "no_image", "expired": "no_image", "heic": "no_image", "huge": "no_image"}
    assert ctx.store.failures_by_stage(ctx.run_id) == {}  # Review Focus 1: never an item failure


async def test_vision_errors_are_item_failures_and_are_retried_on_resume():
    bad = tiny_png((200, 0, 0))
    vision = FakeVision(fail_on={bad})
    ctx = make_ugc_ctx(images=FakeImages({"https://cdn/bad": bad}), vision=vision)
    survivors(ctx, *[make_video(id=f"v{i}") for i in range(9)], make_video(id="bad", cover_url="https://cdn/bad"))
    await run_look(ctx)  # 1 of 10 failed: under the 20% limit, so the stage passes
    assert ctx.store.get_enrichment("bad").vision.status == "error"
    assert ctx.store.failures_by_stage(ctx.run_id) == {"look": 1}
    await run_look(ctx)
    assert len(vision.calls) == 2


async def test_look_is_skipped_when_vision_is_off():
    settings = sequential()
    settings.vision = settings.vision.model_copy(update={"enabled": False})
    images = FakeImages()
    ctx = make_ugc_ctx(images=images, settings=settings)
    survivors(ctx, make_video(id="a", cover_url="https://cdn/a"))
    await run_look(ctx)
    assert ctx.store.get_enrichment("a") is None and images.calls == []
    assert any("Vision was switched off" in note for note in ctx.store.notes(ctx.run_id))
