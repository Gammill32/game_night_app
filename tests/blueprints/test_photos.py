import io
import os

from PIL import Image

from app.models import GameNightPhoto
from tests.conftest import login


def _jpeg_with_gps():
    img = Image.new("RGB", (3000, 1500), "red")
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # Make
    exif[0x8825] = {1: "N", 2: (41.0, 52.0, 0.0)}  # GPS IFD
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    buf.seek(0)
    return buf


def _upload(client, gn, data, caption="Us"):
    return client.post(
        f"/game_night/{gn.id}/photos",
        data={"photo": (data, "IMG_0001.jpg"), "caption": caption},
        content_type="multipart/form-data",
    )


def test_player_uploads_photo_metadata_is_stripped(app, client, make_person, make_night):
    ann = make_person("Ann")
    gn = make_night(ann)
    login(client, ann)
    resp = _upload(client, gn, _jpeg_with_gps())
    assert resp.status_code == 302

    photo = GameNightPhoto.query.filter_by(game_night_id=gn.id).one()
    assert photo.caption == "Us" and photo.uploader_id == ann.id
    full = os.path.join(app.config["MEDIA_DIR"], photo.path)
    with Image.open(full) as saved:
        assert max(saved.size) == 2400
        assert not saved.getexif()

    page = client.get(f"/game_night/{gn.id}").get_data(as_text=True)
    assert f"/photos/{photo.id}/thumb" in page and "gallery.js" in page
    thumb = client.get(f"/game_night/{gn.id}/photos/{photo.id}/thumb")
    assert thumb.status_code == 200 and thumb.mimetype == "image/jpeg"
    assert "private" in thumb.headers["Cache-Control"]


def test_non_player_cannot_upload_or_view(client, make_person, make_night):
    ann, bo = make_person("Ann"), make_person("Bo")
    gn = make_night(ann)
    login(client, ann)
    _upload(client, gn, _jpeg_with_gps())
    photo = GameNightPhoto.query.filter_by(game_night_id=gn.id).one()

    login(client, bo)
    assert _upload(client, gn, _jpeg_with_gps()).status_code == 302
    assert GameNightPhoto.query.filter_by(game_night_id=gn.id).count() == 1
    resp = client.get(f"/game_night/{gn.id}/photos/{photo.id}/full")
    assert resp.status_code == 302  # bounced by game_night_access_required


def test_rejects_non_images(client, make_person, make_night):
    ann = make_person("Ann")
    gn = make_night(ann)
    login(client, ann)
    resp = _upload(client, gn, io.BytesIO(b"%PDF-1.4 not a photo"))
    assert resp.status_code == 302
    assert GameNightPhoto.query.filter_by(game_night_id=gn.id).count() == 0
    page = client.get(f"/game_night/{gn.id}").get_data(as_text=True)
    assert "doesn&#39;t look like a JPEG" in page or "doesn't look like a JPEG" in page


def test_uploader_deletes_photo_and_files(app, client, make_person, make_night):
    ann, bo = make_person("Ann"), make_person("Bo")
    gn = make_night(ann, bo)
    login(client, ann)
    _upload(client, gn, _jpeg_with_gps())
    photo = GameNightPhoto.query.filter_by(game_night_id=gn.id).one()
    full = os.path.join(app.config["MEDIA_DIR"], photo.path)

    login(client, bo)  # not the uploader, not an admin
    client.post(f"/game_night/{gn.id}/photos/{photo.id}/delete")
    assert os.path.exists(full)

    login(client, ann)
    client.post(f"/game_night/{gn.id}/photos/{photo.id}/delete")
    assert GameNightPhoto.query.filter_by(game_night_id=gn.id).count() == 0
    assert not os.path.exists(full)


def test_deleting_night_removes_photo_files(app, client, make_person, make_night):
    from app.services import game_night_services

    ann = make_person("Ann")
    gn = make_night(ann)
    login(client, ann)
    _upload(client, gn, _jpeg_with_gps())
    photo = GameNightPhoto.query.filter_by(game_night_id=gn.id).one()
    full = os.path.join(app.config["MEDIA_DIR"], photo.path)

    assert game_night_services.delete_game_night(gn.id)[0]
    assert not os.path.exists(full)
