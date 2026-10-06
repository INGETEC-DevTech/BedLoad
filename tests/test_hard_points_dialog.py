"""Dialogue "Points durs du projet" : liste libre de points (nom, PK, Z), pente des tronçons
affichée, erreurs signalées pendant la saisie et bloquant la validation. Qt en mode
offscreen, dialogues remplacés."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QDialogButtonBox

from ui.dialogs.hard_points_dialog import COL_NAME, COL_PK, COL_SLOPE, COL_Z, HardPointsDialog

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
    assert dialog.get_points() == POINTS


def test_added_point_with_decimal_comma_is_returned_as_new(qapp):
    dialog = HardPointsDialog(points=POINTS[:2])

    dialog.add_point()
    fill_row(dialog, 2, "Seuil", "1300,5", "45,25")

    assert dialog.get_points()[2] == {"id": None, "name": "Seuil", "pk": 1300.5, "z": 45.25}
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
