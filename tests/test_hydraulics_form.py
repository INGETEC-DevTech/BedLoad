"""Tests du formulaire "Hydraulique" : choix de la zone d'écoulement (tout le profil, un
seul bras, entre deux X). Qt en mode offscreen, dialogues remplacés."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QDialog

from ui.dialogs.point_picker_dialog import PointPickerDialog
from ui.forms.hydraulics_form import HydraulicsForm

# Deux bras séparés par une île culminant à z=3 en x=6.
TWO_ARMS = [{"X (m)": x, "Z (m NGF)": z}
            for x, z in [(0, 2), (1, 0), (4, 0), (5, 2), (6, 3), (7, 2), (8, 0), (11, 0), (12, 2)]]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def form(qapp):
    widget = HydraulicsForm()
    widget.set_existing_points(TWO_ARMS)
    yield widget
    widget.deleteLater()


def test_default_is_the_whole_profile(form):
    assert form.get_data()["hydro_zone"] == "all"
    assert not form.arm_panel.isEnabled() and not form.custom_panel.isEnabled()


def test_choosing_one_arm_proposes_the_crest_between_the_arms(form):
    emitted = []
    form.data_changed.connect(emitted.append)

    form.radio_zone_arm.setChecked(True)

    assert form.arm_panel.isEnabled() and not form.custom_panel.isEnabled()
    assert form.inputs["hydro_arm_split_x"].value() == 6.0
    assert emitted[-1]["hydro_zone"] == "left_arm"
    assert emitted[-1]["hydro_arm_split_x"] == 6.0

    form.combo_arm.setCurrentIndex(1)
    assert emitted[-1]["hydro_zone"] == "right_arm"


def test_an_already_set_separation_is_not_overwritten(form):
    form.inputs["hydro_arm_split_x"].setValue(5.5)

    form.radio_zone_arm.setChecked(True)

    assert form.inputs["hydro_arm_split_x"].value() == 5.5


def test_set_data_restores_the_chosen_arm(form):
    form.set_data({"hydro_zone": "right_arm", "hydro_arm_split_x": 6.0})

    assert form.radio_zone_arm.isChecked() and form.combo_arm.currentData() == "right_arm"
    assert form.arm_panel.isEnabled()
    assert form.get_data()["hydro_zone"] == "right_arm"


def test_legacy_bounds_checkbox_reloads_as_between_two_x(form):
    form.set_data({"hydro_bounds_enabled": True, "hydro_x_left": 2.0, "hydro_x_right": 9.0})

    assert form.radio_zone_custom.isChecked() and form.custom_panel.isEnabled()
    data = form.get_data()
    assert (data["hydro_zone"], data["hydro_x_left"], data["hydro_x_right"]) == ("custom", 2.0, 9.0)
    assert "hydro_bounds_enabled" not in data


def test_profile_without_zone_settings_resets_to_defaults(form):
    form.set_data({"hydro_zone": "left_arm", "hydro_arm_split_x": 6.0})

    form.set_data({"calc_mode": "Q_FROM_H"})  # profil enregistré avant cette fonctionnalité

    data = form.get_data()
    assert (data["hydro_zone"], data["hydro_arm_split_x"]) == ("all", 0.0)


@pytest.mark.parametrize("entered, kept", [
    (0.025, 0.025),   # 3 décimales : n'est plus arrondi à 0.03
    (0.001, 0.001),   # 1 L/s, le minimum
    (0.0004, 0.001),  # sous le minimum : ramené à 1 L/s
])
def test_target_discharge_accepts_down_to_1_litre_per_second_with_3_decimals(form, entered, kept):
    form.set_data({"calc_mode": "H_FROM_Q", "q_target": entered})

    assert form.get_data()["q_target"] == pytest.approx(kept)


def test_pick_dialog_preselects_the_crest_and_sets_the_separation(form, monkeypatch):
    seen = {}

    def fake_exec(dialog):
        seen["row"] = dialog.list_widget.currentRow()
        seen["label"] = dialog.list_widget.currentItem().text()
        dialog.list_widget.setCurrentRow(5)  # l'utilisateur choisit X = 7
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(PointPickerDialog, "exec", fake_exec)
    form.radio_zone_arm.setChecked(True)

    form._pick_arm_split()

    assert seen["row"] == 4 and "point haut entre les deux bras" in seen["label"]
    assert form.inputs["hydro_arm_split_x"].value() == 7.0
