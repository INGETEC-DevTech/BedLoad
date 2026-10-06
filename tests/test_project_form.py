"""Tests du formulaire "Profil projet" (Qt en mode offscreen, dialogues remplacés)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QDialog

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
