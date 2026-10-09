"""Tests du formulaire "Profil projet" (Qt en mode offscreen, dialogues remplacés)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from core.controller import ProfileController
from ui.dialogs.point_picker_dialog import PointPickerDialog
from ui.forms.project_form import ProjectProfileForm


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def form(qapp, monkeypatch):
    widget = ProjectProfileForm()
    widget.set_data(ProfileController.default_project_params())
    widget.set_existing_points([{"X (m)": 1.0, "Z (m NGF)": 50.0}, {"X (m)": 6.0, "Z (m NGF)": 47.25}])
    # Le dialogue de choix renvoie toujours le 2e point (X = 6, Z = 47.25).
    monkeypatch.setattr(PointPickerDialog, "exec",
                        lambda self: (self.list_widget.setCurrentRow(1), QDialog.DialogCode.Accepted)[1])
    yield widget
    widget.deleteLater()


def anchor_message_shown(form) -> bool:
    return not form.lbl_anchor_confirm.isHidden()


def test_anchor_message_disappears_when_x_or_z_is_edited_after_picking(form):
    form._pick_anchor_point()
    assert anchor_message_shown(form)
    assert "X = 6.00" in form.lbl_anchor_confirm.text()

    form.inputs['anchor_x'].setValue(6.5)
    assert not anchor_message_shown(form)

    # Revenir exactement sur le point choisi : le message redevient vrai.
    form.inputs['anchor_x'].setValue(6.0)
    assert anchor_message_shown(form)

    form.inputs['anchor_z'].setValue(47.0)
    assert not anchor_message_shown(form)


def test_anchor_message_is_reset_when_another_profile_is_loaded(form):
    form._pick_anchor_point()

    form.set_data({**ProfileController.default_project_params(), "anchor_x": 6.0, "anchor_z": 47.25})

    assert not anchor_message_shown(form)
    # Et une saisie ultérieure ne le fait pas réapparaître.
    form.inputs['anchor_x'].setValue(6.0)
    assert not anchor_message_shown(form)


def test_invalid_connect_point_message_names_the_floodplain_end(form, monkeypatch):
    """Le point choisi (X = 6) est à droite du bout gauche du profil projet : refusé, avec
    la règle réelle (bout du lit majeur, ou haut de berge sans lit majeur), comme le
    message affiché quand une modification rend un raccord invalide."""
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda parent, title, text, *a, **k: warnings.append((title, text))))

    form._pick_connect_point('left')

    assert warnings == [(
        "Point de raccord invalide",
        "Le point de raccord gauche est plus proche de l'axe du lit que le bout du lit "
        "majeur (ou le haut de berge) actuel — géométrie invalide.",
    )]
    assert form._connect_left is None


def test_connect_point_beyond_bank_top_is_recorded(form):
    """Ancrage à X = -1 : le haut de berge droit est à X = 5.34, donc le point choisi
    (X = 6) est accepté comme raccord droit."""
    form.inputs['anchor_x'].setValue(-1.0)
    emitted = []
    form.data_changed.connect(emitted.append)

    form._pick_connect_point('right')

    assert form._connect_right == (6.0, 47.25)
    assert not form.lbl_connect_confirm_right.isHidden()
    assert emitted[-1]['connect_x_right'] == 6.0


def test_edit_that_invalidates_connect_point_can_be_cancelled(form, monkeypatch):
    """Ancrage repassé de X = -1 à X = 0 : le haut de berge droit (X = 6.34) dépasserait le
    raccord (X = 6). Le dialogue fermé sans choix vaut "Annuler la modification"."""
    form.inputs['anchor_x'].setValue(-1.0)
    form._pick_connect_point('right')
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)

    form.inputs['anchor_x'].setValue(0.0)

    assert form.inputs['anchor_x'].value() == -1.0
    assert form._connect_right == (6.0, 47.25)
