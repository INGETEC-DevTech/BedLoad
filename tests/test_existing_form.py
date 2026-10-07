"""Tests du formulaire "Profil existant" : signalement des saisies invalides."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QTableWidgetItem

from ui import theme
from ui.forms.existing_form import ExistingProfileForm


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def form(qapp):
    widget = ExistingProfileForm()
    widget.set_data([{"X (m)": 0.0, "Z (m NGF)": 50.0}, {"X (m)": 5.0, "Z (m NGF)": 48.0}])
    yield widget
    widget.deleteLater()


def is_red(form, row, col) -> bool:
    return form.table.item(row, col).background().color().name() == theme.DANGER_LIGHT


def warning_shown(form) -> bool:
    return not form.lbl_invalid.isHidden()


def test_valid_data_shows_no_warning(form):
    assert not warning_shown(form)
    assert len(form.get_data()) == 2


def test_invalid_value_is_highlighted_signaled_and_excluded(form):
    emitted = []
    form.data_changed.connect(emitted.append)

    form.table.item(1, 1).setText("48,5m")

    assert is_red(form, 1, 1)
    assert not is_red(form, 1, 0)
    assert "ignoré" in form.table.item(1, 1).toolTip()
    assert warning_shown(form)
    assert "Ligne 2" in form.lbl_invalid.text()
    # Le point invalide reste exclu des calculs (et de la sauvegarde).
    assert emitted[-1] == [{"X (m)": 0.0, "Z (m NGF)": 50.0}]


def test_correcting_the_value_clears_the_warning(form):
    form.table.item(1, 1).setText("abc")
    form.table.item(1, 1).setText("48,5")

    assert not is_red(form, 1, 1)
    assert form.table.item(1, 1).toolTip() == ""
    assert not warning_shown(form)
    assert form.get_data()[1] == {"X (m)": 5.0, "Z (m NGF)": 48.5}


def test_nan_and_half_filled_rows_are_invalid_but_empty_rows_are_not(form):
    form.table.item(0, 0).setText("nan")
    form._is_loading = True
    form.table.insertRow(2)
    form.table.setItem(2, 0, QTableWidgetItem("10"))
    form.table.setItem(2, 1, QTableWidgetItem(""))
    form.table.insertRow(3)
    form.table.setItem(3, 0, QTableWidgetItem(""))
    form.table.setItem(3, 1, QTableWidgetItem(" "))
    form._is_loading = False
    form.on_item_changed()

    assert is_red(form, 0, 0)
    assert is_red(form, 2, 1) and not is_red(form, 2, 0)
    assert not is_red(form, 3, 0) and not is_red(form, 3, 1)
    assert "2 lignes ignorées (1, 3)" in form.lbl_invalid.text()
    assert form.get_data() == [{"X (m)": 5.0, "Z (m NGF)": 48.0}]


def test_loading_another_profile_resets_the_warning(form):
    form.table.item(0, 0).setText("abc")
    form.set_data([{"X (m)": 1.0, "Z (m NGF)": 2.0}])
    assert not warning_shown(form)
    assert not is_red(form, 0, 0)


def test_pasting_a_single_column_marks_the_missing_cell(form, qapp):
    qapp.clipboard().setText("10\n11")
    form.table.setCurrentCell(1, 0)
    form.paste_from_clipboard()

    # Ligne 2 : X remplacé, Z conservé -> valide. Ligne 3 : créée avec X seul -> Z manquant.
    assert form.table.rowCount() == 3
    assert is_red(form, 2, 1)
    assert "Valeur manquante" in form.table.item(2, 1).toolTip()
    assert "Ligne 3" in form.lbl_invalid.text()
