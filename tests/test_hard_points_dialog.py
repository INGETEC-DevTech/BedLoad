"""Dialogue "Points durs du projet" : un champ PK ou Z laissé vide est enregistré comme non
renseigné (None), et non comme 0. Qt en mode offscreen, dialogues remplacés."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from core.longitudinal import build_longitudinal_profile
from database.db_manager import DatabaseManager
from ui import sidebar as sidebar_module
from ui.dialogs.hard_points_dialog import HardPointsDialog
from ui.sidebar import Sidebar


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def ok_enabled(dialog) -> bool:
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_empty_fields_are_returned_as_not_filled(qapp):
    dialog = HardPointsDialog()

    assert dialog.get_values() == {
        "upstream": {"name": None, "x": None, "z": None},
        "downstream": {"name": None, "x": None, "z": None},
    }
    assert ok_enabled(dialog)


def test_partially_filled_point_keeps_its_empty_fields_empty(qapp):
    dialog = HardPointsDialog()
    dialog.name_downstream.setText("Seuil")
    dialog.z_downstream.setText("101,25")  # virgule décimale acceptée

    assert dialog.get_values()["downstream"] == {"name": "Seuil", "x": None, "z": 101.25}


def test_existing_values_are_shown_and_a_real_zero_is_kept(qapp):
    """Valeurs déjà en base (y compris un 0 réellement enregistré) : réaffichées telles
    quelles et renvoyées inchangées si l'utilisateur valide sans rien toucher."""
    upstream = {"name": "Pont", "x": 0.0, "z": 98.5}
    downstream = {"name": "Seuil", "x": 1250.125, "z": None}

    dialog = HardPointsDialog(upstream=upstream, downstream=downstream)

    assert (dialog.x_upstream.text(), dialog.z_upstream.text()) == ("0", "98.5")
    assert dialog.z_downstream.text() == ""
    assert dialog.get_values() == {"upstream": upstream, "downstream": downstream}


def test_incomplete_number_disables_ok(qapp):
    dialog = HardPointsDialog()

    dialog.z_upstream.setText("-")
    assert not ok_enabled(dialog)

    dialog.z_upstream.setText("-2.5")
    assert ok_enabled(dialog)
    assert dialog.get_values()["upstream"]["z"] == -2.5


def test_new_project_with_unfilled_hard_points_saves_none_and_shows_no_ghost_point(qapp, tmp_path, monkeypatch):
    """Scénario rapporté : création d'un projet, dialogue des points durs validé sans saisir
    l'aval. Avant, l'aval était enregistré à PK = 0 / Z = 0 et apparaissait sur le profil en long."""
    db = DatabaseManager(db_path=tmp_path / "test.db")
    sidebar = Sidebar(db)
    monkeypatch.setattr(sidebar_module.QInputDialog, "getText", staticmethod(lambda *a, **k: ("Rivière", True)))

    def fill_upstream_only(dialog):
        dialog.name_upstream.setText("Pont")
        dialog.z_upstream.setText("98.5")
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(HardPointsDialog, "exec", fill_upstream_only)

    sidebar.add_project()

    project_id = db.get_all_projects()[0]["id"]
    hard_points = db.get_hard_points(project_id)
    assert hard_points == {
        "upstream": {"name": "Pont", "x": None, "z": 98.5},
        "downstream": {"name": None, "x": None, "z": None},
    }
    profile = build_longitudinal_profile([], hard_points)
    assert profile.hard_point_downstream is None
    assert profile.hard_point_upstream.z == 98.5
    sidebar.deleteLater()
