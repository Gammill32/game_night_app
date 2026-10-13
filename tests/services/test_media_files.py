"""Uploaded files: the decompression-bomb limit, and files kept in step with
their database rows when a commit fails."""

import io
import os

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage, MultiDict

from app.extensions import db as _db
from app.models import FoodExpense, GameNightPhoto
from app.services import food_services, media_services, photo_services


def _png(width, height):
    buf = io.BytesIO()
    Image.new("L", (width, height)).save(buf, "PNG")
    buf.seek(0)
    return FileStorage(buf, filename="big.png")


def _jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), "red").save(buf, "JPEG")
    buf.seek(0)
    return FileStorage(buf, filename="IMG.jpg")


def _files(app, folder):
    root = os.path.join(app.config["MEDIA_DIR"], folder)
    return sorted(os.listdir(root)) if os.path.isdir(root) else []


@pytest.fixture()
def small_limit(monkeypatch):
    monkeypatch.setattr(media_services, "MAX_PIXELS", 1000)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)


@pytest.mark.parametrize("size", [(40, 40), (50, 50)])  # 1.6x and 2.5x the limit
def test_images_over_the_pixel_limit_are_rejected(app, small_limit, size):
    """Pillow only raises above 2x MAX_IMAGE_PIXELS; between 1x and 2x it just
    warns and would decode the lot."""
    with pytest.raises(media_services.MediaError, match="too large"):
        media_services.save_image(_png(*size), "bombs")
    assert _files(app, "bombs") == []


def test_images_at_the_limit_are_fine(app, small_limit):
    rel, _ = media_services.save_image(_png(25, 40), "bombs")  # exactly 1000 px
    media_services.delete(rel)


class CommitFailed(Exception):
    pass


@pytest.fixture()
def failing_commit(monkeypatch):
    """Call it to make db.session.commit() raise; monkeypatch.undo() disarms."""

    def fail(self):
        raise CommitFailed()

    def arm():
        monkeypatch.setattr(type(_db.session), "commit", fail)

    yield arm
    monkeypatch.undo()
    _db.session.rollback()


def test_photo_upload_removes_files_when_the_commit_fails(
    app, make_person, make_night, failing_commit
):
    ann = make_person("Ann")
    gn = make_night(ann)
    failing_commit()
    with pytest.raises(CommitFailed):
        photo_services.upload(gn, ann, _jpeg())
    _db.session.rollback()
    assert _files(app, f"photos/{gn.id}") == []


def test_photo_delete_keeps_files_when_the_commit_fails(
    app, make_person, make_night, failing_commit, monkeypatch
):
    ann = make_person("Ann")
    gn = make_night(ann)
    assert photo_services.upload(gn, ann, _jpeg())[0]
    photo = GameNightPhoto.query.filter_by(game_night_id=gn.id).one()
    files = _files(app, f"photos/{gn.id}")
    assert len(files) == 2

    failing_commit()
    with pytest.raises(CommitFailed):
        photo_services.delete(photo, ann)
    _db.session.rollback()
    assert _files(app, f"photos/{gn.id}") == files

    monkeypatch.undo()
    assert photo_services.delete(_db.session.get(GameNightPhoto, photo.id), ann)[0]
    assert _files(app, f"photos/{gn.id}") == []


def _expense_form(payer):
    return MultiDict({"description": "Pizza", "amount": "20", "paid_by": str(payer.id)})


def test_expense_receipt_removed_when_the_commit_fails(
    app, make_person, make_night, failing_commit
):
    ann = make_person("Ann")
    gn = make_night(ann, food_mode="split")
    failing_commit()
    with pytest.raises(CommitFailed):
        food_services.add_expense(gn, ann, _expense_form(ann), receipt=_jpeg())
    _db.session.rollback()
    assert _files(app, f"receipts/{gn.id}") == []


def test_expense_delete_keeps_receipt_when_the_commit_fails(
    app, make_person, make_night, failing_commit
):
    ann = make_person("Ann")
    gn = make_night(ann, food_mode="split")
    assert food_services.add_expense(gn, ann, _expense_form(ann), receipt=_jpeg())[0]
    expense = FoodExpense.query.filter_by(game_night_id=gn.id).one()
    assert len(_files(app, f"receipts/{gn.id}")) == 1

    failing_commit()
    with pytest.raises(CommitFailed):
        food_services.delete_expense(gn, expense, ann)
    _db.session.rollback()
    assert len(_files(app, f"receipts/{gn.id}")) == 1
