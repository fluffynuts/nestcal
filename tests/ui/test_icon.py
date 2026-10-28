import pytest

import nestcal_tray

GLYPH = (0x04, 0x89, 0x6A)


def pixel(image, x, y):
    colour = image.pixelColor(x, y)
    return None if colour.alpha() == 0 else (colour.red(), colour.green(), colour.blue())


@pytest.fixture
def glyph(qapp):
    return nestcal_tray.draw_calendar_glyph(1).toImage()


def test_glyph_draws_the_tabs_the_body_outline_and_the_day_squares(glyph):
    assert pixel(glyph, 0, 0) == GLYPH      # left tab
    assert pixel(glyph, 5, 1) == GLYPH      # header
    assert pixel(glyph, 15, 2) == GLYPH     # right tab
    assert pixel(glyph, 0, 10) == GLYPH     # body outline, left edge
    assert pixel(glyph, 8, 15) == GLYPH     # body outline, bottom edge
    assert pixel(glyph, 3, 5) == GLYPH      # first day square
    assert pixel(glyph, 11, 11) == GLYPH    # the lone third-row square


def test_glyph_leaves_the_gaps_transparent(glyph):
    assert pixel(glyph, 2, 0) is None       # between the left tab and the header
    assert pixel(glyph, 8, 10) is None      # inside the body
    assert pixel(glyph, 5, 5) is None       # between day squares
    assert pixel(glyph, 3, 11) is None      # the missing third-row squares


def test_glyph_scales_with_the_unit(qapp):
    big = nestcal_tray.draw_calendar_glyph(8).toImage()
    assert (big.width(), big.height()) == (128, 128)
    assert pixel(big, 0, 0) == GLYPH
    assert pixel(big, 3 * 8 + 4, 5 * 8 + 4) == GLYPH


def test_a_themed_icon_is_preferred_when_the_theme_has_one(qapp, monkeypatch):
    themed = nestcal_tray.QIcon(nestcal_tray.draw_calendar_glyph(2))
    monkeypatch.setattr(nestcal_tray.QIcon, "fromTheme", staticmethod(lambda name: themed))
    assert nestcal_tray.make_icon() is themed


def test_the_drawn_glyph_is_the_fallback_when_no_theme_icon_exists(qapp, monkeypatch):
    monkeypatch.setattr(nestcal_tray.QIcon, "fromTheme", staticmethod(lambda name: nestcal_tray.QIcon()))
    icon = nestcal_tray.make_icon()
    assert not icon.isNull()
    assert pixel(icon.pixmap(128, 128).toImage(), 0, 0) == GLYPH
