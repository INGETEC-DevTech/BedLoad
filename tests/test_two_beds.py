"""Lits existant et projet dissociés (rivière déplacée ou reméandrée) : deux familles de
points durs, deux distances par profil, pente calculée selon le lit du calcul, migration
d'une base de la version précédente et compatibilité des fichiers d'export."""
import json
import os
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from core.hard_points import EXISTING, PROJECT
from database.db_manager import DatabaseManager, ProjectDistanceOutOfZoneError

EXISTING_POINTS = [{"name": "Pont", "pk": 1000.0, "z": 50.0, "family": EXISTING},
                   {"name": "Seuil", "pk": 1400.0, "z": 46.0, "family": EXISTING}]      # 0 à 400 m, 0.01
PROJECT_POINTS = [{"name": "Pont", "pk": 0.0, "z": 50.0, "family": PROJECT},
                  {"name": "Seuil", "pk": 800.0, "z": 46.0, "family": PROJECT}]         # 0 à 800 m, 0.005


def make_db(tmp_path, name="test.db") -> DatabaseManager:
    return DatabaseManager(db_path=tmp_path / name)


def two_beds_project(db, points=EXISTING_POINTS + PROJECT_POINTS):
    project_id = db.create_project("P")
    db.set_hard_points(project_id, points)
    return project_id, db.create_scenario(project_id, "S")


def params(db, profile_id):
    return db.load_profile_state(profile_id)[1]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# --- Familles et distances ---

def test_each_family_has_its_own_zone_and_reference(tmp_path):
    db = make_db(tmp_path)
    project_id, scenario_id = two_beds_project(db)

    assert db.get_distance_zone(project_id, EXISTING) == (0.0, 400.0)
    assert db.get_distance_zone(project_id, PROJECT) == (0.0, 800.0)
    with pytest.raises(ValueError, match="distance existante 500 m.*points durs existants.*0 à 400 m"):
        db.create_profile(scenario_id, "Trop loin", 500.0)
    profile_id = db.create_profile(scenario_id, "PK 300", 300.0)
    db.set_profile_distance(profile_id, 700.0, PROJECT)  # dans la zone projet seulement
    with pytest.raises(ValueError, match="distance projet 900 m.*points durs projet.*0 à 800 m"):
        db.set_profile_distance(profile_id, 900.0, PROJECT)
    assert db.get_profile_distances(profile_id) == (300.0, 700.0)


SHORT_PROJECT_POINTS = [{"name": "Pont", "pk": 0.0, "z": 50.0, "family": PROJECT},
                        {"name": "Seuil", "pk": 250.0, "z": 46.0, "family": PROJECT}]   # 0 à 250 m


def profile_names(db, scenario_id):
    return [p["name"] for project in db.get_all_projects() for s in project["scenarios"]
            if s["id"] == scenario_id for p in s["profiles"]]


def test_new_profile_project_distance_starts_at_the_existing_one(tmp_path):
    db = make_db(tmp_path)
    _, scenario_id = two_beds_project(db, EXISTING_POINTS + SHORT_PROJECT_POINTS)

    inside = db.create_profile(scenario_id, "PK 200", 200.0)

    assert db.get_profile_distances(inside) == (200.0, 200.0)


def test_project_distance_outside_the_project_zone_must_be_given(tmp_path):
    """Lit projet plus court : la distance projet ne reprend pas la distance existante sans
    rien dire ; ProjectDistanceOutOfZoneError (rien n'est créé) propose la valeur autorisée
    la plus proche, et il faut la fournir."""
    db = make_db(tmp_path)
    _, scenario_id = two_beds_project(db, EXISTING_POINTS + SHORT_PROJECT_POINTS)

    with pytest.raises(ProjectDistanceOutOfZoneError) as error:
        db.create_profile(scenario_id, "PK 350", 350.0)

    assert (error.value.profile_name, error.value.distance) == ("PK 350", 350.0)
    assert (error.value.zone, error.value.suggested) == ((0.0, 250.0), 250.0)
    assert profile_names(db, scenario_id) == []
    beyond = db.create_profile(scenario_id, "PK 350", 350.0, project_distance=240.0)
    assert db.get_profile_distances(beyond) == (350.0, 240.0)


def test_duplicate_import_and_draft_copy_ask_for_the_project_distance_too(tmp_path):
    db = make_db(tmp_path)
    _, scenario_id = two_beds_project(db, EXISTING_POINTS + SHORT_PROJECT_POINTS)
    source = db.create_profile(scenario_id, "PK 100", 100.0)
    old_file = {"type": "profile", "version": 2, "name": "Ancien", "distance": 300.0,
                "existing_data": [], "project_params": {}}
    draft_id = db.create_draft("Essai")

    with pytest.raises(ProjectDistanceOutOfZoneError):
        db.duplicate_profile(source, "Copie", 380.0)
    with pytest.raises(ProjectDistanceOutOfZoneError):
        db.import_profile_into_scenario(scenario_id, old_file)
    with pytest.raises(ProjectDistanceOutOfZoneError):
        db.copy_draft_to_scenario(draft_id, scenario_id, 320.0)
    assert profile_names(db, scenario_id) == ["PK 100"]

    copy = db.duplicate_profile(source, "Copie", 380.0, project_distance=200.0)
    imported = db.import_profile_into_scenario(scenario_id, old_file, project_distance=210.0)
    drafted = db.copy_draft_to_scenario(draft_id, scenario_id, 320.0, project_distance=220.0)
    assert [db.get_profile_distances(p) for p in (copy, imported, drafted)] == [
        (380.0, 200.0), (300.0, 210.0), (320.0, 220.0)]


def test_scenario_import_names_the_profile_whose_project_distance_is_needed(tmp_path):
    """Import d'un scénario d'une version antérieure : le profil concerné est désigné
    (`profile_index`) et rien n'est importé ; avec sa distance projet, l'import passe."""
    db = make_db(tmp_path)
    project_id, _ = two_beds_project(db, EXISTING_POINTS + SHORT_PROJECT_POINTS)
    old_scenario = {"type": "scenario", "version": 2, "name": "Ancien", "profiles": [
        {"name": "PK 100", "distance": 100.0, "existing_data": [], "project_params": {}},
        {"name": "PK 300", "distance": 300.0, "existing_data": [], "project_params": {}}]}

    with pytest.raises(ProjectDistanceOutOfZoneError) as error:
        db.import_scenario_into_project(project_id, old_scenario)

    assert error.value.profile_index == 1 and error.value.profile_name == "PK 300"
    assert [s["name"] for s in db.get_scenarios(project_id)] == ["S"]
    old_scenario["profiles"][1]["project_distance"] = 230.0
    scenario_id = db.import_scenario_into_project(project_id, old_scenario)
    distances = {p["name"]: db.get_profile_distances(p["id"])
                 for p in db.get_all_projects()[0]["scenarios"][1]["profiles"]}
    assert scenario_id and distances == {"PK 100": (100.0, 100.0), "PK 300": (300.0, 230.0)}


def test_only_the_existing_distance_is_unique_in_a_scenario(tmp_path):
    db = make_db(tmp_path)
    _, scenario_id = two_beds_project(db)
    first = db.create_profile(scenario_id, "A", 100.0)
    second = db.create_profile(scenario_id, "B", 200.0)

    db.set_profile_distance(second, 100.0, PROJECT)  # même distance projet : permis

    assert db.get_profile_distances(first) == (100.0, 100.0)
    assert db.get_profile_distances(second) == (200.0, 100.0)
    with pytest.raises(ValueError):
        db.set_profile_distance(second, 100.0, EXISTING)


def test_moving_the_first_project_point_shifts_only_the_project_distances(tmp_path):
    db = make_db(tmp_path)
    project_id, scenario_id = two_beds_project(db)
    profile_id = db.create_profile(scenario_id, "PK", 100.0, project_distance=300.0)
    points = db.get_hard_points(project_id)
    for point in points:
        if point["family"] == PROJECT and point["name"] == "Pont":
            point["pk"] = -50.0

    db.set_hard_points(project_id, points)

    assert db.get_profile_distances(profile_id) == (100.0, 350.0)


def test_a_family_error_names_its_family(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    counter_slope = PROJECT_POINTS + [{"name": "Aval", "pk": 900.0, "z": 47.0, "family": PROJECT}]

    with pytest.raises(ValueError, match="Points durs projet — Contre-pente"):
        db.set_hard_points(project_id, EXISTING_POINTS + counter_slope)


# --- Pente calculée selon le lit du calcul ---

def test_computed_slope_uses_the_family_and_distance_of_the_calculation_bed(tmp_path):
    db = make_db(tmp_path)
    _, scenario_id = two_beds_project(db)
    profile_id = db.create_profile(scenario_id, "PK", 100.0, project_distance=600.0)

    info = db.profile_slope_info(profile_id)
    assert info[EXISTING]["slope"] == pytest.approx(0.01) and info[PROJECT]["slope"] == pytest.approx(0.005)
    # Nouveau profil : calcul sur le lit projet (par défaut).
    assert params(db, profile_id)["slope"] == pytest.approx(0.005)

    db.save_profile_state(profile_id, [], {"hydro_source": "existing", "slope_mode": "computed"})
    db.set_profile_distance(profile_id, 150.0)  # recalcul
    assert params(db, profile_id)["slope"] == pytest.approx(0.01)


def test_a_bed_without_two_hard_points_imposes_the_slope_of_its_profiles(tmp_path):
    db = make_db(tmp_path)
    _, scenario_id = two_beds_project(db, EXISTING_POINTS)  # aucun point dur projet

    profile_id = db.create_profile(scenario_id, "PK", 100.0)

    assert params(db, profile_id) == {"slope_mode": "imposed"}
    info = db.profile_slope_info(profile_id)
    assert info[EXISTING]["slope"] == pytest.approx(0.01)
    assert "au moins deux points durs projet" in info[PROJECT]["reason"]


# --- Récapitulatif ---

def test_project_summary_shows_both_families_and_their_slopes(tmp_path):
    from core.controller import ProfileController
    db = make_db(tmp_path)
    project_id, _ = two_beds_project(db)

    summary = ProfileController().project_summary("P", db.get_hard_points(project_id), [])

    assert [(p.name, p.pk) for p in summary.hard_points] == [("Pont", 1000.0), ("Seuil", 1400.0)]
    assert [(p.name, p.pk) for p in summary.project_hard_points] == [("Pont", 0.0), ("Seuil", 800.0)]
    assert [s.slope for s in summary.segments] == [pytest.approx(0.01)]
    assert [s.slope for s in summary.project_segments] == [pytest.approx(0.005)]


def test_summary_view_lists_both_families(qapp, tmp_path):
    from core.controller import ProfileController
    from ui.views.project_summary_view import ProjectSummaryView
    db = make_db(tmp_path)
    project_id, _ = two_beds_project(db)

    view = ProjectSummaryView()
    view.set_summary(ProfileController().project_summary("P", db.get_hard_points(project_id), []))

    assert "2 points durs existants (PK 1000 → 1400)" in view.lbl_subtitle.text()
    assert "2 points durs projet (PK 0 → 800)" in view.lbl_subtitle.text()
    assert view.lbl_segments.text().split("\n") == [
        "Pentes des tronçons entre points durs existants : I = 0.0100 m/m",
        "Pentes des tronçons entre points durs projet : I = 0.0050 m/m",
    ]
    view.deleteLater()


# --- Migration d'une base de la version précédente (un seul lit) ---

def _make_previous_version_db(path):
    """Base de la version précédente : table `hard_points` sans famille, profils sans
    distance projet (schéma et contenu écrits tels quels)."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
            hard_point_upstream_name TEXT, hard_point_upstream_x REAL, hard_point_upstream_z REAL,
            hard_point_downstream_name TEXT, hard_point_downstream_x REAL, hard_point_downstream_z REAL,
            archived INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE scenarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, name TEXT NOT NULL,
            longitudinal_orthonormal INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE, UNIQUE (project_id, name));
        CREATE TABLE profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT, scenario_id INTEGER NOT NULL, name TEXT NOT NULL,
            distance REAL NOT NULL, existing_data TEXT, project_params TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (scenario_id) REFERENCES scenarios (id) ON DELETE CASCADE,
            UNIQUE (scenario_id, name), UNIQUE (scenario_id, distance));
        CREATE TABLE hard_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, name TEXT, pk REAL, z REAL,
            FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE);
        INSERT INTO projects (id, name) VALUES (1, 'Rivière');
        INSERT INTO scenarios (id, project_id, name) VALUES (1, 1, 'S');
        INSERT INTO hard_points (id, project_id, name, pk, z) VALUES
            (4, 1, 'Pont', 1000.0, 50.0), (7, 1, 'Seuil', 1400.0, 46.0), (9, 1, 'Ancien', NULL, 48.0);
        INSERT INTO profiles (id, scenario_id, name, distance, existing_data, project_params) VALUES
            (3, 1, 'PK 100', 100.0, '[]', '{"slope": 0.01, "slope_mode": "computed"}'),
            (12, 1, 'PK 300', 300.0, '[]', '{"slope": 0.0123, "slope_mode": "imposed"}');
    """)
    conn.commit()
    conn.close()


def test_migration_copies_hard_points_into_both_families_and_nothing_changes(tmp_path):
    path = tmp_path / "previous.db"
    _make_previous_version_db(path)

    db = DatabaseManager(db_path=path)

    for family in (EXISTING, PROJECT):
        assert [(p["name"], p["pk"], p["z"]) for p in db.get_hard_points(1, family)] == [
            ("Pont", 1000.0, 50.0), ("Seuil", 1400.0, 46.0), ("Ancien", None, 48.0)]
    # Les points d'origine gardent leurs ids (famille existante) ; les copies en ont de nouveaux.
    assert [p["id"] for p in db.get_hard_points(1, EXISTING)] == [4, 7, 9]
    assert min(p["id"] for p in db.get_hard_points(1, PROJECT)) > 9
    assert db.get_profile_distances(3) == (100.0, 100.0)
    assert db.get_profile_distances(12) == (300.0, 300.0)
    assert params(db, 3) == {"slope": 0.01, "slope_mode": "computed"}
    assert params(db, 12) == {"slope": 0.0123, "slope_mode": "imposed"}
    info = db.profile_slope_info(3)
    assert info[EXISTING] == info[PROJECT] and info[PROJECT]["slope"] == pytest.approx(0.01)
    assert not db.startup_slope_report.message()


def test_migration_is_done_once(tmp_path):
    path = tmp_path / "previous.db"
    _make_previous_version_db(path)
    DatabaseManager(db_path=path)

    reopened = DatabaseManager(db_path=path)

    assert len(reopened.get_hard_points(1)) == 6
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


# --- Fichiers d'export ---

def test_new_export_keeps_the_existing_bed_under_the_former_keys(tmp_path):
    """Version 3 : points durs existants sous "hard_points" (lus par une version
    antérieure), points durs projet sous "project_hard_points", et chaque profil a sa
    "project_distance"."""
    db = make_db(tmp_path)
    project_id, scenario_id = two_beds_project(db)
    db.create_profile(scenario_id, "PK", 100.0, project_distance=600.0)

    data = db.export_project(project_id)

    assert data["version"] == 3
    assert data["hard_points"] == [{k: p[k] for k in ("name", "pk", "z")} for p in EXISTING_POINTS]
    assert data["project_hard_points"] == [{k: p[k] for k in ("name", "pk", "z")} for p in PROJECT_POINTS]
    profile = data["scenarios"][0]["profiles"][0]
    assert (profile["distance"], profile["project_distance"]) == (100.0, 600.0)


def test_two_beds_project_round_trip(tmp_path):
    db = make_db(tmp_path)
    project_id, scenario_id = two_beds_project(db)
    db.create_profile(scenario_id, "PK", 100.0, project_distance=600.0)
    path = tmp_path / "projet.json"
    db.export_project_to_file(project_id, path)

    new_id = db.import_project(db.read_export_file(path))

    assert ([(p["family"], p["name"], p["pk"]) for p in db.get_hard_points(new_id)]
            == [(p["family"], p["name"], p["pk"]) for p in EXISTING_POINTS + PROJECT_POINTS])
    profile_id = next(p for p in db.get_all_projects() if p["id"] == new_id)["scenarios"][0]["profiles"][0]["id"]
    assert db.get_profile_distances(profile_id) == (100.0, 600.0)


def test_profile_file_from_a_previous_version_gets_its_project_distance_initialised(tmp_path):
    db = make_db(tmp_path)
    _, scenario_id = two_beds_project(db)
    old_file = {"type": "profile", "version": 2, "name": "Ancien", "distance": 120.0,
                "existing_data": [], "project_params": {}}

    profile_id = db.import_profile_into_scenario(scenario_id, old_file)

    assert db.get_profile_distances(profile_id) == (120.0, 120.0)


def test_profile_file_keeps_its_project_distance(tmp_path):
    db = make_db(tmp_path)
    _, source = two_beds_project(db)
    profile_id = db.create_profile(source, "PK", 100.0, project_distance=600.0)
    target = db.create_scenario(db.get_scenario_project_id(source), "Cible")

    new_id = db.import_profile_into_scenario(target, db.export_profile(profile_id))

    assert db.get_profile_distances(new_id) == (100.0, 600.0)


def test_scenario_copy_keeps_both_distances(tmp_path):
    db = make_db(tmp_path)
    project_id, source = two_beds_project(db)
    db.create_profile(source, "PK", 100.0, project_distance=600.0)

    copy = db.create_scenario(project_id, "Copie", source_scenario_id=source)

    profile_id = db.get_all_projects()[0]["scenarios"][1]["profiles"][0]["id"]
    assert db.get_profile_distances(profile_id) == (100.0, 600.0) and copy


def test_new_export_file_is_still_valid_json_with_the_former_keys(tmp_path):
    """Ce qu'une version antérieure lit d'un nouveau fichier : un projet à un seul lit (le
    lit existant), les profils à leur distance existante."""
    db = make_db(tmp_path)
    project_id, scenario_id = two_beds_project(db)
    db.create_profile(scenario_id, "PK", 100.0, project_distance=600.0)
    path = tmp_path / "projet.json"
    db.export_project_to_file(project_id, path)

    raw = json.loads(path.read_text(encoding="utf-8"))

    assert {"type", "version", "name", "hard_points", "scenarios"} <= set(raw)
    assert all(set(p) == {"name", "pk", "z"} for p in raw["hard_points"])
    profile = raw["scenarios"][0]["profiles"][0]
    assert {"name", "distance", "existing_data", "project_params"} <= set(profile)
