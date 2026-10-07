import json

import pytest

from database.db_manager import DatabaseManager


def make_db(tmp_path) -> DatabaseManager:
    return DatabaseManager(db_path=tmp_path / "test.db")


def strip_mode(state):
    """État d'un profil sans le mode de pente : après une duplication, un import ou un
    renommage, le recalcul des pentes l'ajoute (ici "imposed", faute de points durs)."""
    existing_data, params = state
    return existing_data, {k: v for k, v in params.items() if k != "slope_mode"}


def hard_points(db, project_id):
    """Points durs du projet sans leurs identifiants en base."""
    return [{k: p[k] for k in ("name", "pk", "z")} for p in db.get_hard_points(project_id)]


TWO_POINTS = [{"name": "Pont Amont", "pk": 0.0, "z": 100.0}, {"name": "Pont Aval", "pk": 500.0, "z": 90.0}]


def populate_profile(db, scenario_id, name="PK 0", distance=0.0):
    profile_id = db.create_or_get_profile(scenario_id, name, distance)
    existing_data = [{"X (m)": 0.0, "Z (m NGF)": 100.0}, {"X (m)": 10.0, "Z (m NGF)": 98.5}]
    # Pente imposée : sa valeur doit traverser intacte export, import et duplication.
    project_params = {"anchor_z": 98.0, "slope": 0.004, "slope_mode": "imposed", "ks_pro": 30.0,
                       "calc_mode": "H_FROM_Q", "q_target": 12.0, "hydro_source": "project"}
    db.save_profile_state(profile_id, existing_data, project_params)
    return profile_id, existing_data, project_params


# --- Résolution de collision (fonctions pures) ---

def test_resolve_name_collision_returns_name_unchanged_when_free():
    assert DatabaseManager._resolve_name_collision({"Autre"}, "Amont") == "Amont"


def test_resolve_name_collision_adds_suffix_then_counter():
    existing = {"Amont"}
    assert DatabaseManager._resolve_name_collision(existing, "Amont") == "Amont - importé"

    existing = {"Amont", "Amont - importé"}
    assert DatabaseManager._resolve_name_collision(existing, "Amont") == "Amont - importé (2)"

    existing = {"Amont", "Amont - importé", "Amont - importé (2)"}
    assert DatabaseManager._resolve_name_collision(existing, "Amont") == "Amont - importé (3)"


def test_resolve_distance_collision_nudges_by_small_step():
    assert DatabaseManager._resolve_distance_collision({100.0}, 50.0) == 50.0
    assert DatabaseManager._resolve_distance_collision({100.0}, 100.0) == 100.001
    assert DatabaseManager._resolve_distance_collision({100.0, 100.001}, 100.0) == 100.002


# --- Export/import d'un profil ---

def test_export_profile_has_type_and_full_state(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    scenario_id = db.create_scenario(project_id, "S")
    profile_id, existing_data, project_params = populate_profile(db, scenario_id)

    data = db.export_profile(profile_id)

    assert data["type"] == "profile"
    assert data["name"] == "PK 0"
    assert data["distance"] == 0.0
    assert data["existing_data"] == existing_data
    assert data["project_params"] == project_params


def test_export_draft_has_no_distance(tmp_path):
    db = make_db(tmp_path)
    draft_id = db.create_draft("Essai")
    db.save_draft_state(draft_id, [{"X (m)": 1.0, "Z (m NGF)": 2.0}], {"anchor_z": 1.0})

    data = db.export_draft(draft_id)

    assert data["type"] == "profile"
    assert data["distance"] is None
    assert data["existing_data"] == [{"X (m)": 1.0, "Z (m NGF)": 2.0}]


def test_import_profile_into_scenario_round_trip_without_collision(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    source_scenario = db.create_scenario(project_id, "Source")
    target_scenario = db.create_scenario(project_id, "Cible")
    profile_id, existing_data, project_params = populate_profile(db, source_scenario, "PK 300", 300.0)
    exported = db.export_profile(profile_id)

    new_id = db.import_profile_into_scenario(target_scenario, exported)

    profiles = {p["name"]: p for p in db.get_all_projects()[0]["scenarios"][1]["profiles"]}
    assert profiles["PK 300"]["id"] == new_id
    assert profiles["PK 300"]["distance"] == 300.0
    assert db.load_profile_state(new_id) == (existing_data, project_params)


def test_import_profile_into_same_scenario_renames_and_shifts_distance(tmp_path):
    """Réimporter un profil dans le scénario dont il vient (collision garantie sur le nom
    ET la distance) : renommage et léger décalage automatiques, sans écraser l'original."""
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    scenario_id = db.create_scenario(project_id, "S")
    profile_id, existing_data, project_params = populate_profile(db, scenario_id, "PK 0", 0.0)
    exported = db.export_profile(profile_id)

    new_id = db.import_profile_into_scenario(scenario_id, exported)
    again_id = db.import_profile_into_scenario(scenario_id, exported)

    profiles = {p["id"]: p for p in db.get_all_projects()[0]["scenarios"][0]["profiles"]}
    assert profiles[profile_id]["name"] == "PK 0" and profiles[profile_id]["distance"] == 0.0
    assert profiles[new_id]["name"] == "PK 0 - importé" and profiles[new_id]["distance"] == 0.001
    assert profiles[again_id]["name"] == "PK 0 - importé (2)" and profiles[again_id]["distance"] == 0.002
    for pid in (profile_id, new_id, again_id):
        assert db.load_profile_state(pid) == (existing_data, project_params)


def test_import_profile_into_unknown_scenario_raises(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    scenario_id = db.create_scenario(project_id, "S")
    profile_id, *_ = populate_profile(db, scenario_id)

    with pytest.raises(ValueError, match="introuvable"):
        db.import_profile_into_scenario(999, db.export_profile(profile_id))


def test_import_profile_into_drafts_ignores_distance_and_renames_on_collision(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    scenario_id = db.create_scenario(project_id, "S")
    profile_id, existing_data, project_params = populate_profile(db, scenario_id, "Essai", 150.0)
    exported = db.export_profile(profile_id)
    db.create_draft("Essai")  # collision garantie

    new_id = db.import_profile_into_drafts(exported)

    drafts = {d["name"]: d for d in db.get_all_drafts()}
    assert "Essai - importé" in drafts
    assert drafts["Essai - importé"]["id"] == new_id
    assert db.load_draft_state(new_id) == (existing_data, project_params)


def test_profile_file_round_trip(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    source_scenario = db.create_scenario(project_id, "Source")
    target_scenario = db.create_scenario(project_id, "Cible")
    profile_id, existing_data, project_params = populate_profile(db, source_scenario, "PK 50", 50.0)
    path = tmp_path / "profil.json"

    db.export_profile_to_file(profile_id, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["type"] == "profile" and raw["name"] == "PK 50"

    data = db.read_export_file(path)
    new_id = db.import_profile_into_scenario(target_scenario, data)

    assert db.load_profile_state(new_id) == (existing_data, project_params)


# --- Export/import d'un scénario ---

def test_export_scenario_lists_all_its_profiles(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    scenario_id = db.create_scenario(project_id, "S")
    populate_profile(db, scenario_id, "PK 0", 0.0)
    populate_profile(db, scenario_id, "PK 300", 300.0)

    data = db.export_scenario(scenario_id)

    assert data["type"] == "scenario" and data["name"] == "S"
    assert sorted((p["name"], p["distance"]) for p in data["profiles"]) == [
        ("PK 0", 0.0), ("PK 300", 300.0)
    ]


def test_scenario_file_round_trip_into_another_project(tmp_path):
    db = make_db(tmp_path)
    source_project = db.create_project("Source projet")
    source_scenario = db.create_scenario(source_project, "Variante")
    populate_profile(db, source_scenario, "PK 0", 0.0)
    populate_profile(db, source_scenario, "PK 300", 300.0)
    target_project = db.create_project("Cible projet")
    path = tmp_path / "scenario.json"

    db.export_scenario_to_file(source_scenario, path)
    data = db.read_export_file(path)
    new_scenario_id = db.import_scenario_into_project(target_project, data)

    by_project = {p["name"]: p for p in db.get_all_projects()}
    imported = next(s for s in by_project["Cible projet"]["scenarios"] if s["id"] == new_scenario_id)
    original = by_project["Source projet"]["scenarios"][0]
    assert imported["name"] == "Variante"
    assert sorted((p["name"], p["distance"]) for p in imported["profiles"]) == \
        sorted((p["name"], p["distance"]) for p in original["profiles"])

    original_by_name = {p["name"]: p["id"] for p in original["profiles"]}
    imported_by_name = {p["name"]: p["id"] for p in imported["profiles"]}
    for name in original_by_name:
        assert strip_mode(db.load_profile_state(imported_by_name[name])) == strip_mode(db.load_profile_state(original_by_name[name]))
        # Nouvelles lignes indépendantes, pas des références vers la source.
        assert imported_by_name[name] != original_by_name[name]


def test_import_scenario_renames_on_name_collision(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    scenario_id = db.create_scenario(project_id, "Variante")
    populate_profile(db, scenario_id, "PK 0", 0.0)
    exported = db.export_scenario(scenario_id)

    new_id = db.import_scenario_into_project(project_id, exported)

    names = [s["name"] for s in db.get_scenarios(project_id)]
    assert names == ["Variante", "Variante - importé"]
    assert db.get_scenarios(project_id)[1]["id"] == new_id


def test_import_scenario_with_duplicate_profile_names_renames_the_second(tmp_path):
    """Fichier "scénario" hand-forgé contenant deux profils homonymes : le second doit
    être renommé automatiquement au moment de l'import, pas planter."""
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    data = {
        "type": "scenario", "version": 1, "name": "Importé",
        "profiles": [
            {"name": "PK 0", "distance": 0.0, "existing_data": [], "project_params": {}},
            {"name": "PK 0", "distance": 100.0, "existing_data": [], "project_params": {}},
        ],
    }

    scenario_id = db.import_scenario_into_project(project_id, data)

    imported_scenario = next(s for s in db.get_all_projects()[0]["scenarios"] if s["id"] == scenario_id)
    assert sorted(p["name"] for p in imported_scenario["profiles"]) == ["PK 0", "PK 0 - importé"]


def test_import_scenario_into_unknown_project_raises(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    scenario_id = db.create_scenario(project_id, "S")

    with pytest.raises(ValueError, match="introuvable"):
        db.import_scenario_into_project(999, db.export_scenario(scenario_id))


# --- Export/import d'un projet ---

def test_export_project_includes_hard_points_and_all_scenarios(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    db.set_hard_points(project_id, TWO_POINTS)
    scenario_a = db.create_scenario(project_id, "A")
    scenario_b = db.create_scenario(project_id, "B")
    populate_profile(db, scenario_a, "PK 0", 0.0)
    populate_profile(db, scenario_b, "PK 0", 0.0)

    data = db.export_project(project_id)

    assert data["type"] == "project" and data["name"] == "P"
    assert data["hard_points"] == hard_points(db, project_id) == TWO_POINTS
    assert [s["name"] for s in data["scenarios"]] == ["A", "B"]
    assert all(len(s["profiles"]) == 1 for s in data["scenarios"])


def test_project_file_round_trip_creates_a_new_project(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("Rivière")
    db.set_hard_points(project_id, TWO_POINTS)
    scenario_a = db.create_scenario(project_id, "A")
    scenario_b = db.create_scenario(project_id, "B")
    populate_profile(db, scenario_a, "PK 0", 0.0)
    populate_profile(db, scenario_a, "PK 300", 300.0)
    populate_profile(db, scenario_b, "PK 0", 0.0)
    path = tmp_path / "projet.json"

    db.export_project_to_file(project_id, path)
    data = db.read_export_file(path)
    new_project_id = db.import_project(data)

    assert new_project_id != project_id
    projects = {p["name"]: p for p in db.get_all_projects()}
    assert set(projects) == {"Rivière", "Rivière - importé"}  # nom déjà pris : renommé

    original = projects["Rivière"]
    imported = projects["Rivière - importé"]
    assert hard_points(db, imported["id"]) == hard_points(db, original["id"]) == TWO_POINTS
    assert [s["name"] for s in imported["scenarios"]] == [s["name"] for s in original["scenarios"]]
    for orig_s, imp_s in zip(original["scenarios"], imported["scenarios"]):
        assert sorted((p["name"], p["distance"]) for p in orig_s["profiles"]) == \
            sorted((p["name"], p["distance"]) for p in imp_s["profiles"])
        orig_by_name = {p["name"]: p["id"] for p in orig_s["profiles"]}
        imp_by_name = {p["name"]: p["id"] for p in imp_s["profiles"]}
        for name in orig_by_name:
            assert db.load_profile_state(imp_by_name[name]) == db.load_profile_state(orig_by_name[name])


def test_import_project_never_modifies_an_existing_project(tmp_path):
    """Réimporter un fichier "projet" ne fusionne jamais dans le projet existant du même
    nom : le projet d'origine reste identique, y compris son nombre de scénarios/profils."""
    db = make_db(tmp_path)
    project_id = db.create_project("Rivière")
    scenario_id = db.create_scenario(project_id, "S")
    populate_profile(db, scenario_id, "PK 0", 0.0)
    before = db.export_project(project_id)

    db.import_project(db.export_project(project_id))
    db.import_project(db.export_project(project_id))  # deuxième collision : "(2)"

    after = db.export_project(project_id)
    assert after == before  # le projet source, lui, n'a pas bougé d'un octet
    names = sorted(p["name"] for p in db.get_all_projects())
    assert names == ["Rivière", "Rivière - importé", "Rivière - importé (2)"]


def test_import_project_with_empty_hard_points_and_no_scenarios(tmp_path):
    """Un projet minimal (jamais de points durs saisis, aucun scénario) s'exporte et se
    réimporte sans erreur."""
    db = make_db(tmp_path)
    project_id = db.create_project("Vide")

    new_id = db.import_project(db.export_project(project_id))

    assert db.get_hard_points(new_id) == []
    assert db.get_scenarios(new_id) == []


# --- Copie interne Draft → Scénario ---

def test_copy_draft_to_scenario_leaves_the_draft_untouched(tmp_path):
    db = make_db(tmp_path)
    draft_id = db.create_draft("Essai berge")
    existing_data = [{"X (m)": 0.0, "Z (m NGF)": 5.0}]
    project_params = {"anchor_z": 4.5, "slope": 0.01}
    db.save_draft_state(draft_id, existing_data, project_params)
    project_id = db.create_project("P")
    scenario_id = db.create_scenario(project_id, "S")

    new_profile_id = db.copy_draft_to_scenario(draft_id, scenario_id)

    # Le brouillon source est intact...
    assert db.get_all_drafts() == [{"id": draft_id, "name": "Essai berge"}]
    assert db.load_draft_state(draft_id) == (existing_data, project_params)
    # ...et la copie, dans le scénario, porte les mêmes données.
    profiles = db.get_all_projects()[0]["scenarios"][0]["profiles"]
    assert [p["name"] for p in profiles] == ["Essai berge"]
    assert profiles[0]["id"] == new_profile_id
    assert strip_mode(db.load_profile_state(new_profile_id)) == (existing_data, project_params)

    # Et modifier la copie ensuite ne touche pas le brouillon.
    db.save_profile_state(new_profile_id, [{"X (m)": 9.0, "Z (m NGF)": 9.0}], {"anchor_z": 1.0})
    assert db.load_draft_state(draft_id) == (existing_data, project_params)


def test_copy_draft_to_scenario_renames_on_collision(tmp_path):
    db = make_db(tmp_path)
    draft_id = db.create_draft("Essai")
    project_id = db.create_project("P")
    scenario_id = db.create_scenario(project_id, "S")
    db.create_or_get_profile(scenario_id, "Essai", 0.0)  # collision garantie sur le nom

    new_id = db.copy_draft_to_scenario(draft_id, scenario_id)

    profiles = {p["id"]: p for p in db.get_all_projects()[0]["scenarios"][0]["profiles"]}
    assert profiles[new_id]["name"] == "Essai - importé"
    assert db.get_all_drafts() == [{"id": draft_id, "name": "Essai"}]  # toujours "Essai"


def test_copy_draft_to_unknown_scenario_raises(tmp_path):
    db = make_db(tmp_path)
    draft_id = db.create_draft("Essai")

    with pytest.raises(ValueError, match="introuvable"):
        db.copy_draft_to_scenario(draft_id, 999)


# --- Fichiers invalides ---

def test_read_export_file_rejects_unknown_type(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"type": "banana", "name": "X"}), encoding="utf-8")

    with pytest.raises(ValueError, match="valide"):
        DatabaseManager.read_export_file(path)


def test_read_export_file_rejects_missing_name(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"type": "profile"}), encoding="utf-8")

    with pytest.raises(ValueError, match="incomplet"):
        DatabaseManager.read_export_file(path)


def test_read_export_file_rejects_malformed_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{ceci n'est pas du json", encoding="utf-8")

    with pytest.raises(ValueError, match="Impossible de lire"):
        DatabaseManager.read_export_file(path)


def test_read_export_file_rejects_missing_file(tmp_path):
    with pytest.raises(ValueError, match="Impossible de lire"):
        DatabaseManager.read_export_file(tmp_path / "n_existe_pas.json")



def test_export_import_keeps_both_background_profile_boxes(tmp_path):
    db = DatabaseManager(db_path=tmp_path / "test.db")
    scenario_id = db.create_scenario(db.create_project("P"), "S")
    profile_id = db.create_or_get_profile(scenario_id, "PK 0", 0.0)
    params = {"show_overlay_project": True, "show_overlay_hydraulics": False}
    db.save_profile_state(profile_id, [], params)
    path = tmp_path / "profil.json"
    db.export_profile_to_file(profile_id, path)

    new_id = db.import_profile_into_scenario(scenario_id, db.read_export_file(path))

    restored = db.load_profile_state(new_id)[1]
    assert (restored["show_overlay_project"], restored["show_overlay_hydraulics"]) == (True, False)


# --- Paramètres hérités de l'Excel, retirés du modèle ---

# Clés que des profils et exports anciens contiennent encore (d50, x_end_*...) : elles ne
# servent plus nulle part et doivent être ignorées, sans empêcher le chargement.
LEGACY_PARAMS = {
    "d50": 0.004, "x_end_profile_left": 0.1, "x_end_profile_right": 11.0,
    "x_end_equals_profile_width": False, "x_end_rd": 11.0, "keep_existing_slope": False,
    "delete_point_left_bank": False, "delete_point_right_bank": True,
}


def test_old_export_with_legacy_parameters_still_imports_and_draws(tmp_path):
    from core.controller import ProfileController, ViewMode
    db = make_db(tmp_path)
    scenario_id = db.create_scenario(db.create_project("P"), "S")
    profile_id, existing_data, project_params = populate_profile(db, scenario_id)
    data = db.export_profile(profile_id)
    data["project_params"] = {**data["project_params"], **LEGACY_PARAMS}
    path = tmp_path / "ancien.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    imported = db.import_profile_into_scenario(scenario_id, db.read_export_file(path))
    existing, params = db.load_profile_state(imported)

    controller = ProfileController()
    merged = {**controller.default_project_params(), **params}
    for mode in ViewMode:
        assert controller.build_figure(existing, merged, mode) is not None
    assert controller.station_earthworks(db.get_scenario_profile_states(scenario_id))[0].computed
