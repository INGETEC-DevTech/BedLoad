"""Tests de l'arborescence (sidebar), du dialogue de scénario et du routage profil/brouillon
de la fenêtre principale. Qt tourne en mode "offscreen" : aucune fenêtre ne s'affiche, et
les dialogues modaux (saisies, confirmations) sont remplacés par des réponses fixes."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
# QtWebEngine (graphique de la fenêtre principale) exige d'être importé avant la
# création de la QApplication.
from PyQt6 import QtWebEngineWidgets  # noqa: F401
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QInputDialog, QLabel,
                             QMessageBox, QWidget)

from database.db_manager import DatabaseManager, DEFAULT_SCENARIO_NAME
from ui import sidebar as sidebar_module
from ui.dialogs.scenario_dialog import ScenarioDialog
from ui.sidebar import Sidebar, PROJECT, SCENARIO, PROFILE, DRAFT_ROOT, DRAFT


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def db(tmp_path):
    return DatabaseManager(db_path=tmp_path / "test.db")


@pytest.fixture
def sidebar(qapp, db):
    widget = Sidebar(db)
    yield widget
    widget.deleteLater()


def tree_snapshot(sidebar: Sidebar):
    """L'arbre sous forme de listes imbriquées [(type, texte, [enfants])]."""
    def walk(item):
        data = item.data(Qt.ItemDataRole.UserRole)
        children = [walk(item.child(r)) for r in range(item.rowCount())]
        return (data["type"], item.text(), children)

    return [walk(sidebar.model.item(r)) for r in range(sidebar.model.rowCount())]


def click(sidebar: Sidebar, key):
    item = sidebar._find_item(key)
    assert item is not None, key
    index = sidebar.model.indexFromItem(item)
    sidebar.tree_view.setCurrentIndex(index)
    sidebar.on_item_clicked(index)


def record(signal):
    received = []
    signal.connect(lambda *args: received.append(args))
    return received


def answer_inputs(monkeypatch, texts=(), doubles=()):
    """Remplace les saisies QInputDialog par des réponses successives validées."""
    texts, doubles = list(texts), list(doubles)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (texts.pop(0), True)))
    monkeypatch.setattr(QInputDialog, "getDouble", staticmethod(lambda *a, **k: (doubles.pop(0), True)))


# --- Arborescence ---

def test_tree_shows_projects_scenarios_profiles_then_draft_zone(sidebar, db):
    project_id = db.create_project("Rivière")
    scenario_a = db.create_scenario(project_id, "A")
    scenario_b = db.create_scenario(project_id, "B")
    db.create_or_get_profile(scenario_a, "PK 300", 300.0)
    db.create_or_get_profile(scenario_a, "PK 100", 100.0)
    db.create_or_get_profile(scenario_b, "PK 300", 300.0)
    db.create_draft("Essai")

    sidebar.refresh_tree()

    assert tree_snapshot(sidebar) == [
        (PROJECT, "Rivière", [
            (SCENARIO, "A", [(PROFILE, "PK 100", []), (PROFILE, "PK 300", [])]),
            (SCENARIO, "B", [(PROFILE, "PK 300", [])]),
        ]),
        (DRAFT_ROOT, "Draft", [(DRAFT, "Essai", [])]),
    ]


def test_draft_zone_is_present_even_without_projects_or_drafts(sidebar):
    assert tree_snapshot(sidebar) == [(DRAFT_ROOT, "Draft", [])]


def test_new_nodes_are_expanded_and_expansion_survives_refresh(sidebar, db):
    project_id = db.create_project("P")
    scenario_id = db.create_scenario(project_id, "S")
    sidebar.refresh_tree()
    scenario_index = sidebar.model.indexFromItem(sidebar._find_item((SCENARIO, scenario_id)))
    assert sidebar.tree_view.isExpanded(scenario_index)

    sidebar.tree_view.setExpanded(scenario_index, False)
    sidebar.refresh_tree()

    scenario_index = sidebar.model.indexFromItem(sidebar._find_item((SCENARIO, scenario_id)))
    assert not sidebar.tree_view.isExpanded(scenario_index)


# --- Sélection et signaux ---

def test_clicks_emit_the_signal_of_each_node_type(sidebar, db):
    project_id = db.create_project("P")
    scenario_id = db.create_scenario(project_id, "S")
    profile_id = db.create_or_get_profile(scenario_id, "PK 0", 0.0)
    draft_id = db.create_draft("Essai")
    sidebar.refresh_tree()
    signals = {
        "project": record(sidebar.project_selected),
        "scenario": record(sidebar.scenario_selected),
        "profile": record(sidebar.profile_selected),
        "draft": record(sidebar.draft_selected),
        "draft_zone": record(sidebar.draft_zone_selected),
    }

    click(sidebar, (PROJECT, project_id))
    click(sidebar, (SCENARIO, scenario_id))
    click(sidebar, (PROFILE, profile_id))
    assert sidebar.current_context() == ("P", "S", "PK 0")
    click(sidebar, (DRAFT_ROOT, None))
    assert sidebar.current_context() is None
    click(sidebar, (DRAFT, draft_id))
    assert sidebar.current_context() == ("Draft", "Essai")

    assert signals == {
        "project": [(project_id,)], "scenario": [(scenario_id,)], "profile": [(profile_id,)],
        "draft": [(draft_id,)], "draft_zone": [()],
    }


def test_active_path_marks_parents_of_selected_profile(sidebar, db):
    project_id = db.create_project("P")
    scenario_a = db.create_scenario(project_id, "A")
    scenario_b = db.create_scenario(project_id, "B")
    profile_id = db.create_or_get_profile(scenario_a, "PK 0", 0.0)
    sidebar.refresh_tree()

    click(sidebar, (PROFILE, profile_id))

    assert sidebar.is_active({"type": PROJECT, "id": project_id})
    assert sidebar.is_active({"type": SCENARIO, "id": scenario_a})
    assert not sidebar.is_active({"type": SCENARIO, "id": scenario_b})
    # Même id numérique, autre type : pas de confusion.
    assert not sidebar.is_active({"type": DRAFT, "id": profile_id})


def test_deleting_the_open_item_or_a_parent_clears_the_selection(sidebar, db):
    project_id = db.create_project("P")
    scenario_id = db.create_scenario(project_id, "S")
    profile_id = db.create_or_get_profile(scenario_id, "PK 0", 0.0)
    sidebar.refresh_tree()
    cleared = record(sidebar.selection_cleared)

    click(sidebar, (PROFILE, profile_id))
    db.delete_scenario(scenario_id)  # le parent du profil ouvert
    sidebar.refresh_tree()

    assert cleared == [()]
    assert sidebar.current_context() is None


def test_deleting_an_unrelated_item_keeps_the_selection(sidebar, db):
    project_id = db.create_project("P")
    scenario_id = db.create_scenario(project_id, "S")
    kept = db.create_or_get_profile(scenario_id, "PK 0", 0.0)
    other = db.create_or_get_profile(scenario_id, "PK 100", 100.0)
    sidebar.refresh_tree()
    cleared = record(sidebar.selection_cleared)

    click(sidebar, (PROFILE, kept))
    db.delete_profile(other)
    sidebar.refresh_tree()

    assert cleared == []
    assert sidebar.current_context() == ("P", "S", "PK 0")
    assert sidebar.tree_view.currentIndex().data(Qt.ItemDataRole.UserRole)["id"] == kept


def test_renaming_the_open_scenario_updates_the_context(sidebar, db):
    project_id = db.create_project("P")
    scenario_id = db.create_scenario(project_id, "S")
    profile_id = db.create_or_get_profile(scenario_id, "PK 0", 0.0)
    sidebar.refresh_tree()
    changed = record(sidebar.context_changed)
    click(sidebar, (PROFILE, profile_id))

    db.rename_scenario(scenario_id, "Variante")
    sidebar.refresh_tree()

    assert changed == [()]
    assert sidebar.current_context() == ("P", "Variante", "PK 0")


# --- Actions ---

def test_add_project_creates_it_with_a_default_scenario(sidebar, db, monkeypatch):
    answer_inputs(monkeypatch, texts=["Nouveau"])
    monkeypatch.setattr(sidebar_module.HardPointsDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    selected = record(sidebar.scenario_selected)

    sidebar.add_project()

    project = db.get_all_projects()[0]
    assert [s["name"] for s in project["scenarios"]] == [DEFAULT_SCENARIO_NAME]
    assert selected == [(project["scenarios"][0]["id"],)]


def test_add_profile_goes_to_the_selected_scenario(sidebar, db, monkeypatch):
    project_id = db.create_project("P")
    scenario_a = db.create_scenario(project_id, "A")
    scenario_b = db.create_scenario(project_id, "B")
    sidebar.refresh_tree()
    click(sidebar, (SCENARIO, scenario_b))
    answer_inputs(monkeypatch, texts=["PK 300"], doubles=[300.0])

    sidebar.add_profile()

    scenarios = db.get_all_projects()[0]["scenarios"]
    assert scenarios[0]["profiles"] == []
    assert [p["name"] for p in scenarios[1]["profiles"]] == ["PK 300"]


def test_add_profile_on_project_with_several_scenarios_asks_to_choose(sidebar, db, monkeypatch):
    project_id = db.create_project("P")
    db.create_scenario(project_id, "A")
    db.create_scenario(project_id, "B")
    sidebar.refresh_tree()
    click(sidebar, (PROJECT, project_id))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a[2])))

    sidebar.add_profile()

    assert warnings and "scénario" in warnings[0]
    assert all(s["profiles"] == [] for s in db.get_all_projects()[0]["scenarios"])


def test_add_profile_in_draft_zone_creates_a_draft_not_a_profile(sidebar, db, monkeypatch):
    project_id = db.create_project("P")
    db.create_scenario(project_id, "S")
    sidebar.refresh_tree()
    click(sidebar, (DRAFT_ROOT, None))
    answer_inputs(monkeypatch, texts=["Essai berge"])
    opened = record(sidebar.draft_selected)

    sidebar.add_profile()

    drafts = db.get_all_drafts()
    assert [d["name"] for d in drafts] == ["Essai berge"]
    assert opened == [(drafts[0]["id"],)]
    assert db.get_all_projects()[0]["scenarios"][0]["profiles"] == []


class _FakeScenarioDialog:
    """Remplace ScenarioDialog : valide avec les valeurs choisies par le test, et garde
    trace des arguments reçus (scénarios proposés, source pré-choisie)."""
    answer = None
    received = None

    def __init__(self, parent=None, scenarios=None, default_name="", source_scenario_id=None, title=""):
        type(self).received = {"scenarios": scenarios, "default_name": default_name,
                               "source_scenario_id": source_scenario_id}

    def exec(self):
        return QDialog.DialogCode.Accepted

    def get_values(self):
        return type(self).answer


def test_create_scenario_keeping_profiles_of_an_existing_one(sidebar, db, monkeypatch):
    project_id = db.create_project("P")
    source = db.create_scenario(project_id, DEFAULT_SCENARIO_NAME)
    db.create_or_get_profile(source, "PK 0", 0.0)
    db.create_or_get_profile(source, "PK 300", 300.0)
    sidebar.refresh_tree()
    click(sidebar, (SCENARIO, source))
    monkeypatch.setattr(sidebar_module, "ScenarioDialog", _FakeScenarioDialog)
    _FakeScenarioDialog.answer = ("Variante", source)

    sidebar.add_scenario()

    assert _FakeScenarioDialog.received["scenarios"] == [{"id": source, "name": DEFAULT_SCENARIO_NAME}]
    assert _FakeScenarioDialog.received["default_name"] == "Scénario 2"
    scenarios = db.get_all_projects()[0]["scenarios"]
    assert [(s["name"], [p["name"] for p in s["profiles"]]) for s in scenarios] == [
        (DEFAULT_SCENARIO_NAME, ["PK 0", "PK 300"]),
        ("Variante", ["PK 0", "PK 300"]),
    ]


def test_duplicate_scenario_preselects_it_as_source(sidebar, db, monkeypatch):
    project_id = db.create_project("P")
    source = db.create_scenario(project_id, "A")
    db.create_or_get_profile(source, "PK 0", 0.0)
    sidebar.refresh_tree()
    monkeypatch.setattr(sidebar_module, "ScenarioDialog", _FakeScenarioDialog)
    _FakeScenarioDialog.answer = ("A - copie", source)

    sidebar.duplicate_scenario({"type": SCENARIO, "id": source, "project_id": project_id}, "A")

    assert _FakeScenarioDialog.received["source_scenario_id"] == source
    assert _FakeScenarioDialog.received["default_name"] == "A - copie"
    assert [s["name"] for s in db.get_scenarios(project_id)] == ["A", "A - copie"]


def test_add_scenario_without_project_selected_warns(sidebar, db, monkeypatch):
    db.create_draft("Essai")
    sidebar.refresh_tree()
    click(sidebar, (DRAFT_ROOT, None))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a[2])))

    sidebar.add_scenario()

    assert warnings == ["Sélectionnez d'abord un projet."]


# --- Dialogue de scénario ---

def test_scenario_dialog_without_existing_scenario_cannot_keep_profiles(qapp):
    dialog = ScenarioDialog(scenarios=[], default_name="Scénario 1")

    assert not dialog.keep_profiles_check.isEnabled()
    assert dialog.get_values() == ("Scénario 1", None)


def test_scenario_dialog_returns_source_only_when_option_checked(qapp):
    scenarios = [{"id": 4, "name": "A"}, {"id": 7, "name": "B"}]
    dialog = ScenarioDialog(scenarios=scenarios, default_name="  Nouveau  ")
    assert not dialog.source_combo.isEnabled()
    assert dialog.get_values() == ("Nouveau", None)

    dialog.keep_profiles_check.setChecked(True)
    dialog.source_combo.setCurrentIndex(1)

    assert dialog.source_combo.isEnabled()
    assert dialog.get_values() == ("Nouveau", 7)


def test_scenario_dialog_preselected_source_and_empty_name(qapp):
    dialog = ScenarioDialog(scenarios=[{"id": 4, "name": "A"}, {"id": 7, "name": "B"}],
                            default_name="B - copie", source_scenario_id=7)
    assert dialog.get_values() == ("B - copie", 7)

    dialog.name_edit.setText("   ")
    assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


# --- Fenêtre principale : un brouillon s'enregistre dans les brouillons, jamais ailleurs ---

class _FakePlotView(QWidget):
    """Remplace PlotView : son QWebEngineView (Chromium) ne démarre pas sans affichage et
    fait tomber le processus en mode offscreen. On ne garde que ce que MainWindow utilise."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lbl_title = QLabel()
        self.figures = []

    def update_plot(self, fig, error_message=None):
        self.figures.append((fig, error_message))


@pytest.fixture
def main_window(qapp, tmp_path, monkeypatch):
    from ui import main_window as main_window_module
    db_path = tmp_path / "window.db"
    # Jamais la vraie base (data/hydrotopo.db) : la fenêtre ouvre une base de test.
    monkeypatch.setattr(main_window_module, "DatabaseManager", lambda: DatabaseManager(db_path=db_path))
    monkeypatch.setattr(main_window_module, "PlotView", _FakePlotView)
    window = main_window_module.MainWindow()
    yield window
    window.deleteLater()


def test_editing_a_draft_never_touches_the_profile_with_the_same_id(main_window):
    db = main_window.db_manager
    scenario_id = db.create_scenario(db.create_project("P"), "S")
    profile_id = db.create_or_get_profile(scenario_id, "PK 0", 0.0)
    profile_state = ([{"X (m)": 0.0, "Z (m NGF)": 1.0}, {"X (m)": 1.0, "Z (m NGF)": 0.5}], {"anchor_z": 0.2})
    db.save_profile_state(profile_id, *profile_state)
    draft_id = db.create_draft("Essai")
    assert draft_id == profile_id
    main_window.sidebar.refresh_tree()

    click(main_window.sidebar, (DRAFT, draft_id))
    assert main_window._current_target == ("draft", draft_id)
    assert main_window.lbl_context.text().count("&rsaquo;") == 1  # Draft › Essai
    draft_points = [{"X (m)": 0.0, "Z (m NGF)": 9.0}, {"X (m)": 4.0, "Z (m NGF)": 8.0}]
    main_window.form_existing.set_data(draft_points)
    main_window.save_and_update_plot()

    assert db.load_draft_state(draft_id)[0] == draft_points
    assert db.load_profile_state(profile_id) == profile_state

    # Et l'inverse : le profil s'ouvre avec ses propres données.
    click(main_window.sidebar, (PROFILE, profile_id))
    assert main_window._current_target == ("profile", profile_id)
    assert main_window.form_existing.get_data() == profile_state[0]
    assert main_window.lbl_context.text().count("&rsaquo;") == 2  # P › S › PK 0


def test_scenario_click_shows_longitudinal_and_stops_editing(main_window):
    db = main_window.db_manager
    scenario_id = db.create_scenario(db.create_project("P"), "S")
    profile_id = db.create_or_get_profile(scenario_id, "PK 0", 0.0)
    main_window.sidebar.refresh_tree()

    click(main_window.sidebar, (PROFILE, profile_id))
    click(main_window.sidebar, (SCENARIO, scenario_id))

    assert main_window._current_target is None
    assert main_window.plot_view.lbl_title.text() == "Profil en long du scénario"


def test_deleting_the_open_draft_returns_to_the_welcome_page(main_window):
    db = main_window.db_manager
    draft_id = db.create_draft("Essai")
    main_window.sidebar.refresh_tree()
    click(main_window.sidebar, (DRAFT, draft_id))

    db.delete_draft(draft_id)
    main_window.sidebar.refresh_tree()

    assert main_window._current_target is None
    assert main_window.forms_stack.currentIndex() == 0
