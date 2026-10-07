"""Récapitulatif d'un projet : chiffres par scénario (core) et page qui les affiche (Qt en
mode offscreen)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from core.controller import ProfileController
from core.longitudinal import StationEarthworks
from core.project_summary import earthwork_volumes
from ui.views.project_summary_view import ProjectSummaryView

EXISTING = [{"X (m)": x, "Z (m NGF)": z} for x, z in [(-5, 52), (0, 49), (5, 48), (10, 49), (20, 52)]]
HYDRO_EXISTING = {"calc_mode": "Q_FROM_H", "hydro_source": "existing", "slope": 0.001, "ks_pro": 30.0}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# --- Volumes par la méthode des moyennes des aires ---

def test_volumes_average_the_areas_of_consecutive_computed_profiles():
    stations = [
        StationEarthworks(distance=100.0, name="B", cut=4.0, fill=0.0),
        StationEarthworks(distance=0.0, name="A", cut=2.0, fill=1.0),
        StationEarthworks(distance=50.0, name="Trou", note="profil projet non renseigné"),
        StationEarthworks(distance=300.0, name="C", cut=0.0, fill=3.0),
    ]
    # A→B (100 m, le profil non calculé est sauté) puis B→C (200 m).
    cut, fill = earthwork_volumes(stations)
    assert cut == pytest.approx((2 + 4) / 2 * 100 + (4 + 0) / 2 * 200)
    assert fill == pytest.approx((1 + 0) / 2 * 100 + (0 + 3) / 2 * 200)


def test_no_volume_with_fewer_than_two_computed_profiles():
    assert earthwork_volumes([StationEarthworks(distance=0.0, name="A", cut=2.0, fill=1.0)]) == (None, None)


# --- Contrôle hydraulique d'un profil ---

@pytest.mark.parametrize("h_eau,expected", [(1.0, False), (10.0, True)])
def test_profile_overflow_follows_the_hydraulics_tab_warning(h_eau, expected):
    """Berges à 52 m, fond à 48 m : 1 m d'eau reste dans le profil, 10 m débordent."""
    assert ProfileController().profile_overflows(EXISTING, {**HYDRO_EXISTING, "h_eau": h_eau}) is expected


def test_profile_without_hydraulic_settings_is_not_checked():
    controller = ProfileController()
    assert controller.profile_overflows(EXISTING, {}) is None
    # Source "projet" sans profil projet enregistré : rien de significatif à contrôler.
    assert controller.profile_overflows(EXISTING, {"calc_mode": "Q_FROM_H"}) is None


# --- Chiffres d'un scénario ---

def _states():
    return [
        {"name": "Amont", "distance": 0.0, "existing_data": EXISTING,
         "project_params": {"anchor_z": 48.5, **HYDRO_EXISTING, "h_eau": 10.0}},
        {"name": "Aval", "distance": 100.0, "existing_data": EXISTING,
         "project_params": {"anchor_z": 47.0, **HYDRO_EXISTING, "h_eau": 1.0}},
        {"name": "Vide", "distance": 150.0, "existing_data": [], "project_params": {}},
    ]


def test_scenario_summary_counts_and_totals():
    controller = ProfileController()
    states = _states()
    summary = controller.scenario_summary(7, "Base", states)
    stations = controller.station_earthworks(states)

    assert (summary.scenario_id, summary.name) == (7, "Base")
    assert (summary.n_profiles, summary.n_complete) == (3, 2)
    assert summary.distance_range == (0.0, 150.0)
    assert summary.n_earthworks == 2
    assert summary.cut_area == pytest.approx(stations[0].cut + stations[1].cut)
    assert summary.fill_area == pytest.approx(stations[0].fill + stations[1].fill)
    assert (summary.cut_volume, summary.fill_volume) == pytest.approx(earthwork_volumes(stations))
    assert summary.n_hydraulics == 2 and summary.overflow_names == ["Amont"]


def test_project_summary_lists_hard_points_and_segment_slopes():
    hard_points = [{"name": "A", "pk": 1000.0, "z": 50.0}, {"name": "B", "pk": 1200.0, "z": 46.0},
                   {"name": "Incomplet", "pk": None, "z": 40.0}]
    summary = ProfileController().project_summary("P", hard_points, [(1, "S", _states())])

    assert [p.name for p in summary.hard_points] == ["A", "B"]
    assert [s.slope for s in summary.segments] == pytest.approx([0.02])
    assert [s.name for s in summary.scenarios] == ["S"]


# --- Page du récapitulatif ---

@pytest.fixture
def view(qapp):
    widget = ProjectSummaryView()
    controller = ProfileController()
    scenarios = [
        (1, "Base", _states()),
        (2, "Variante", _states()[1:2]),
        (3, "Vide", []),
    ]
    widget.set_summary(controller.project_summary("Rivière X", [], scenarios))
    yield widget
    widget.deleteLater()


def _column(view, label):
    return next(c for c in range(view.table.columnCount())
                if view.table.horizontalHeaderItem(c).text().replace("\n", " ") == label)


def _texts(view, label):
    col = _column(view, label)
    return [view.table.item(r, col).text() for r in range(view.table.rowCount())]


def test_one_row_per_scenario_with_its_key_figures(view):
    assert view.lbl_title.text() == "Projet « Rivière X »"
    assert "3 scénarios" in view.lbl_subtitle.text()
    assert _texts(view, "Scénario") == ["Base", "Variante", "Vide"]
    assert _texts(view, "Profils") == ["3", "1", "0"]
    assert _texts(view, "Complets") == ["2/3", "1/1", "0/0"]
    assert _texts(view, "Linéaire (m)") == ["0 → 150", "100 → 100", "—"]
    # Un seul profil calculé : surfaces, mais pas de volume (pas de longueur d'application).
    assert _texts(view, "Déblai (m³)")[1:] == ["—", "—"]
    assert _texts(view, "Débordements") == ["1 ⚠", "0", "—"]
    assert "Amont" in view.table.item(0, _column(view, "Débordements")).toolTip()


def test_numeric_columns_sort_by_value_and_unavailable_values_last(view):
    col = _column(view, "Profils")
    view.table.sortItems(col, Qt.SortOrder.AscendingOrder)
    assert _texts(view, "Profils") == ["0", "1", "3"]

    col = _column(view, "Déblai (m³)")
    view.table.sortItems(col, Qt.SortOrder.AscendingOrder)
    assert _texts(view, "Scénario")[0] == "Base"  # seule valeur disponible


def test_double_click_opens_the_scenario_even_after_sorting(view):
    view.table.sortItems(_column(view, "Profils"), Qt.SortOrder.AscendingOrder)
    opened = []
    view.scenario_activated.connect(opened.append)

    view.table.cellDoubleClicked.emit(0, 3)

    assert opened == [3]  # "Vide" (0 profil) est maintenant en tête


def test_copy_includes_the_headers(view, qapp):
    view.table.selectRow(1)
    view.table.copy_selection_to_clipboard()
    lines = qapp.clipboard().text().split("\n")
    assert lines[0].startswith("Scénario\tProfils\tComplets")
    assert lines[1].startswith("Variante\t1\t1/1")


def test_project_without_scenario_shows_a_message(qapp):
    widget = ProjectSummaryView()
    widget.set_summary(ProfileController().project_summary("P", [], []))
    assert widget.table.isHidden() and not widget.lbl_empty.isHidden()
    widget.deleteLater()
