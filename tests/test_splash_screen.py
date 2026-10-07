"""Écran de démarrage de l'exe : sans effet depuis les sources, jamais bloquant dans l'exe,
et image cohérente avec la zone du texte d'étape (cf. HydroTopo_V2.spec)."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication

from core.utils import get_assets_dir
from ui import splash_screen, theme


class _FakePyiSplash:
    """Module pyi_splash de PyInstaller, tel qu'il se comporte dans l'exe."""

    def __init__(self, fail=False):
        self.texts = []
        self.closed = False
        self.fail = fail

    def is_alive(self):
        return not self.closed

    def update_text(self, text):
        if self.fail:
            raise ConnectionError("écran de démarrage disparu")
        self.texts.append(text)

    def close(self):
        if self.fail:
            raise OSError("connexion perdue")
        self.closed = True


def test_without_pyinstaller_the_functions_do_nothing(monkeypatch):
    monkeypatch.setattr(splash_screen, "pyi_splash", None)

    splash_screen.show_step("Chargement…")
    splash_screen.close()


def test_in_the_exe_steps_are_shown_until_closed(monkeypatch):
    fake = _FakePyiSplash()
    monkeypatch.setattr(splash_screen, "pyi_splash", fake)

    splash_screen.show_step("Préparation de l'interface…")
    splash_screen.close()
    splash_screen.show_step("Trop tard")

    assert fake.texts == ["Préparation de l'interface…"]
    assert fake.closed


def test_a_lost_splash_screen_never_blocks_the_startup(monkeypatch):
    monkeypatch.setattr(splash_screen, "pyi_splash", _FakePyiSplash(fail=True))

    splash_screen.show_step("Chargement…")
    splash_screen.close()


def test_an_unhandled_error_closes_the_splash_before_being_reported(monkeypatch):
    # L'écran, toujours au premier plan, masquerait le message d'erreur de PyInstaller.
    fake = _FakePyiSplash()
    monkeypatch.setattr(splash_screen, "pyi_splash", fake)
    reported = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: reported.append((fake.closed, exc)))

    splash_screen.close_on_error()
    error = RuntimeError("module introuvable")
    sys.excepthook(RuntimeError, error, None)

    assert reported == [(True, (RuntimeError, error, None))]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_splash_image_matches_the_layout_and_leaves_the_text_zone_empty(qapp):
    image = QImage(str(get_assets_dir() / "splash.png"))
    assert (image.width(), image.height()) == splash_screen.IMAGE_SIZE

    # Zone où PyInstaller écrit le texte d'étape (coin inférieur gauche en TEXT_POS) : rien
    # de l'image ne doit s'y trouver. Sinon, relancer tools/make_splash.py.
    x, bottom = splash_screen.TEXT_POS
    background = QColor(theme.SURFACE)
    for px in range(x, image.width() - splash_screen.MARGIN):
        for py in range(bottom - 2 * splash_screen.TEXT_SIZE_PX, bottom + 4):
            assert image.pixelColor(px, py) == background, (px, py)
