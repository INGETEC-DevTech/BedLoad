"""Réglages communs aux tests.

Les messages d'information (ex. bilan des pentes recalculées après une modification des
points durs) sont des fenêtres modales : affichées pendant un test, elles le bloqueraient
indéfiniment. Ils sont donc enregistrés au lieu d'être affichés ; un test peut les lire
via la fixture `info_messages` (liste de (titre, texte))."""
import pytest
from PyQt6.QtWidgets import QMessageBox


@pytest.fixture(autouse=True)
def info_messages(monkeypatch):
    shown = []

    def record(parent, title, text, *args, **kwargs):
        shown.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", staticmethod(record))
    return shown
