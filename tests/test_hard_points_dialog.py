"""Dialogue "Points durs du projet" : liste libre de points (nom, PK, Z), pente des tronçons
affichée, erreurs signalées pendant la saisie et bloquant la validation. Qt en mode
offscreen, dialogues remplacés."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QDialogButtonBox

from ui.dialogs.hard_points_dialog import COL_NAME, COL_PK, COL_SLOPE, COL_TYPE, COL_Z, HardPointsDialog

POINTS = [
    {"id": 1, "name": "A", "pk": 1000.0, "z": 50.0},
    {"id": 2, "name": "B", "pk": 1200.0, "z": 46.0},
    {"id": 3, "name": "C", "pk": 1400.0, "z": 45.0},
]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def ok_enabled(dialog) -> bool:
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


def cell(dialog, row, col):
    return dialog.table.item(row, col).text()


def fill_row(dialog, row, name, pk, z):
    dialog.table.item(row, COL_NAME).setText(name)
    dialog.table.item(row, COL_PK).setText(pk)
    dialog.table.item(row, COL_Z).setText(z)


def test_empty_dialog_returns_no_point(qapp):
    dialog = HardPointsDialog()

    assert dialog.get_points() == []
    assert ok_enabled(dialog)


def test_points_are_shown_with_the_slope_of_their_downstream_segment_in_m_per_m(qapp):
    dialog = HardPointsDialog(points=POINTS)

    assert [cell(dialog, r, COL_NAME) for r in range(3)] == ["A", "B", "C"]
    assert [cell(dialog, r, COL_PK) for r in range(3)] == ["1000", "1200", "1400"]
    assert [cell(dialog, r, COL_SLOPE) for r in range(3)] == ["0.0200", "0.0050", "—"]
    assert dialog.table.horizontalHeaderItem(COL_SLOPE).text() == "Pente du tronçon aval (m/m)"
    assert dialog.get_points() == [{**p, "family": "existing"} for p in POINTS]


def test_added_point_with_decimal_comma_is_returned_as_new(qapp):
    dialog = HardPointsDialog(points=POINTS[:2])

    dialog.add_point()
    fill_row(dialog, 2, "Seuil", "1300,5", "45,25")

    assert dialog.get_points()[2] == {"id": None, "name": "Seuil", "pk": 1300.5, "z": 45.25, "family": "existing"}
    assert cell(dialog, 1, COL_SLOPE) == "0.0075"  # B -> Seuil : 0.75 m sur 100.5 m
    assert ok_enabled(dialog)


def test_counter_slope_is_reported_and_blocks_ok_until_fixed(qapp):
    dialog = HardPointsDialog(points=POINTS)

    dialog.table.item(1, COL_Z).setText("51")

    assert not ok_enabled(dialog)
    assert "Contre-pente" in dialog.lbl_errors.text()
    dialog.table.item(1, COL_Z).setText("46")
    assert ok_enabled(dialog) and dialog.lbl_errors.isHidden()


def test_text_that_is_not_a_number_is_reported(qapp):
    dialog = HardPointsDialog(points=POINTS)

    dialog.table.item(0, COL_PK).setText("mille")

    assert not ok_enabled(dialog)
    assert "Ligne 1 : le PK « mille » n'est pas un nombre." in dialog.lbl_errors.text()


def test_new_point_without_pk_or_z_is_refused(qapp):
    dialog = HardPointsDialog(points=POINTS)

    dialog.add_point()
    fill_row(dialog, 3, "Incomplet", "1500", "")

    assert not ok_enabled(dialog)
    assert "obligatoires" in dialog.lbl_errors.text()


def test_project_level_errors_from_the_validator_block_ok(qapp):
    """Le validateur (vérification à blanc côté base) signale par exemple un profil qui
    sortirait de la zone couverte."""
    dialog = HardPointsDialog(points=POINTS, validator=lambda pts: ["Ces profils sortiraient de la zone : « P »."]
                              if len(pts) < 3 else [])

    assert ok_enabled(dialog)
    dialog.table.selectRow(2)
    dialog.remove_selected_point()

    assert dialog.table.rowCount() == 2
    assert not ok_enabled(dialog) and "sortiraient de la zone" in dialog.lbl_errors.text()


# --- Deux familles : points durs existants et projet ---

def test_each_family_has_its_own_slopes_and_rules(qapp):
    """Les tronçons ne relient que des points d'une même famille, et une contre-pente n'est
    signalée que dans sa famille."""
    dialog = HardPointsDialog(points=POINTS + [
        {"id": 4, "name": "A'", "pk": 2000.0, "z": 50.0, "family": "project"},
        {"id": 5, "name": "C'", "pk": 2500.0, "z": 45.0, "family": "project"}])

    assert [cell(dialog, r, COL_SLOPE) for r in range(5)] == ["0.0200", "0.0050", "—", "0.0100", "—"]
    assert [p["family"] for p in dialog.get_points()] == ["existing"] * 3 + ["project"] * 2
    assert ok_enabled(dialog)

    dialog.table.item(4, COL_Z).setText("51")  # contre-pente dans le lit projet seulement

    assert "Points durs projet — Contre-pente" in dialog.lbl_errors.text()
    assert "existants" not in dialog.lbl_errors.text() and not ok_enabled(dialog)


def test_type_column_moves_a_point_to_the_other_family(qapp):
    dialog = HardPointsDialog(points=POINTS)
    assert dialog.table.horizontalHeaderItem(COL_TYPE).text() == "Type"

    dialog.set_family(2, "project")  # C seul dans le lit projet : pas de tronçon

    assert [p["family"] for p in dialog.get_points()] == ["existing", "existing", "project"]
    assert [cell(dialog, r, COL_SLOPE) for r in range(3)] == ["0.0200", "—", "—"]


def test_added_point_takes_the_type_of_the_selected_row(qapp):
    dialog = HardPointsDialog(points=[{"id": 1, "name": "A'", "pk": 0.0, "z": 5.0, "family": "project"}])
    dialog.table.setCurrentCell(0, COL_NAME)

    dialog.add_point()

    assert dialog.get_points()[1]["family"] == "project"


# --- Copier les points existants en projet ---

def test_copy_button_makes_the_project_points_a_copy_of_the_existing_ones(qapp):
    dialog = HardPointsDialog(points=POINTS)
    assert dialog.btn_copy_to_project.text() == "Copier les points existants en projet"

    dialog.copy_existing_to_project()

    points = dialog.get_points()
    assert [(p["family"], p["name"], p["pk"], p["z"]) for p in points[3:]] == [
        ("project", p["name"], p["pk"], p["z"]) for p in POINTS]
    assert all(p["id"] is None for p in points[3:])  # nouveaux points
    assert [cell(dialog, r, COL_SLOPE) for r in range(3, 6)] == ["0.0200", "0.0050", "—"]
    assert ok_enabled(dialog)


def test_copy_button_replaces_project_points_only_after_confirmation(qapp, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    project = {"id": 9, "name": "Ancien", "pk": 0.0, "z": 60.0, "family": "project"}
    dialog = HardPointsDialog(points=POINTS + [project])
    answers = []

    def answer(reply):
        def question(parent, title, text, *a, **k):
            answers.append(text)
            return reply
        monkeypatch.setattr(QMessageBox, "question", staticmethod(question))

    answer(QMessageBox.StandardButton.No)
    dialog.copy_existing_to_project()
    assert [p["name"] for p in dialog.get_points() if p["family"] == "project"] == ["Ancien"]
    assert "1 point dur projet déjà saisi sera remplacé" in answers[0]

    answer(QMessageBox.StandardButton.Yes)
    dialog.copy_existing_to_project()
    assert [p["name"] for p in dialog.get_points() if p["family"] == "project"] == ["A", "B", "C"]


def test_copy_button_without_existing_points_explains_why(qapp, info_messages):
    dialog = HardPointsDialog(points=[{"id": 1, "name": "A'", "pk": 0.0, "z": 5.0, "family": "project"}])

    dialog.copy_existing_to_project()

    assert info_messages == [("Copier les points existants en projet", "Aucun point dur existant à copier.")]
    assert len(dialog.get_points()) == 1
