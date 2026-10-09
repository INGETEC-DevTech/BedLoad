"""Points durs multiples et pente hydraulique calculée : base de données, migration,
export/import."""
import json
import sqlite3

import pytest

from database.db_manager import DatabaseManager

# A (PK 1000, Z 50) -> B (PK 1200, Z 46) -> C (PK 1400, Z 45) : zone de distances 0 à 400 m,
# pente 0.02 m/m sur A-B (distances 0 à 200), 0.005 m/m sur B-C (200 à 400).
POINTS = [
    {"name": "A", "pk": 1000.0, "z": 50.0},
    {"name": "B", "pk": 1200.0, "z": 46.0},
    {"name": "C", "pk": 1400.0, "z": 45.0},
]


def make_db(tmp_path, name="test.db") -> DatabaseManager:
    return DatabaseManager(db_path=tmp_path / name)


def project_with_points(db, points=POINTS, name="P"):
    project_id = db.create_project(name)
    db.set_hard_points(project_id, points)
    return project_id, db.create_scenario(project_id, "S")


def params(db, profile_id):
    return db.load_profile_state(profile_id)[1]


def distances(db, scenario_id):
    return {
        p["name"]: p["distance"]
        for project in db.get_all_projects() for s in project["scenarios"] if s["id"] == scenario_id
        for p in s["profiles"]
    }


# --- Liste de points durs ---

def test_hard_points_are_listed_by_pk_whatever_the_input_order(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")

    db.set_hard_points(project_id, [POINTS[2], POINTS[0], POINTS[1]])

    assert [p["name"] for p in db.get_hard_points(project_id)] == ["A", "B", "C"]
    assert db.get_distance_zone(project_id) == (0.0, 400.0)


@pytest.mark.parametrize("points,message", [
    ([{"name": "A", "pk": 0.0, "z": 50.0}, {"name": "B", "pk": 100.0, "z": 51.0}], "Contre-pente"),
    ([{"name": "A", "pk": 0.0, "z": 50.0}, {"name": "B", "pk": 100.0, "z": 50.0}], "Pente nulle"),
    ([{"name": "A", "pk": 0.0, "z": 50.0}, {"name": "B", "pk": None, "z": 49.0}], "obligatoires"),
])
def test_invalid_hard_points_are_refused_and_nothing_is_saved(tmp_path, points, message):
    db = make_db(tmp_path)
    project_id = db.create_project("P")

    with pytest.raises(ValueError, match=message):
        db.set_hard_points(project_id, points)
    assert db.get_hard_points(project_id) == []


def test_no_point_upstream_of_the_first_one(tmp_path):
    db = make_db(tmp_path)
    project_id, _ = project_with_points(db)
    current = db.get_hard_points(project_id)

    with pytest.raises(ValueError, match="amont du premier"):
        db.set_hard_points(project_id, current + [{"name": "Avant", "pk": 900.0, "z": 52.0}])


def test_moving_hard_points_cannot_leave_existing_profiles_outside(tmp_path):
    db = make_db(tmp_path)
    project_id, scenario_id = project_with_points(db)
    db.create_profile(scenario_id, "PK 1350", 350.0)
    shrunk = db.get_hard_points(project_id)[:2]  # sans C : zone ramenée à 0-200 m

    with pytest.raises(ValueError, match="« S › PK 1350 » \\(PK 1350\\)"):
        db.set_hard_points(project_id, shrunk)
    assert len(db.get_hard_points(project_id)) == 3


def test_moving_the_first_point_keeps_the_real_position_of_profiles(tmp_path):
    """Le premier point dur passe de PK 1000 à PK 950 : les profils ne bougent pas sur le
    terrain, leur distance (relative au premier point) augmente donc de 50 m."""
    db = make_db(tmp_path)
    project_id, scenario_id = project_with_points(db)
    db.create_profile(scenario_id, "PK 1100", 100.0)
    db.create_profile(scenario_id, "PK 1300", 300.0)
    moved = db.get_hard_points(project_id)
    moved[0]["pk"] = 950.0

    db.set_hard_points(project_id, moved)

    assert distances(db, scenario_id) == {"PK 1100": 150.0, "PK 1300": 350.0}


# --- Distance des profils bornée par les points durs ---

def test_profile_distance_must_be_inside_the_zone(tmp_path):
    db = make_db(tmp_path)
    _, scenario_id = project_with_points(db)

    with pytest.raises(ValueError, match="hors de la zone.*0 à 400 m"):
        db.create_profile(scenario_id, "Trop loin", 450.0)
    profile_id = db.create_profile(scenario_id, "PK 0", 0.0)
    with pytest.raises(ValueError, match="hors de la zone"):
        db.rename_profile(profile_id, "PK 0", -1.0)
    with pytest.raises(ValueError, match="hors de la zone"):
        db.duplicate_profile(profile_id, "Copie", 400.5)
    assert distances(db, scenario_id) == {"PK 0": 0.0}


def test_without_two_complete_points_distances_are_free_and_slopes_imposed(tmp_path):
    db = make_db(tmp_path)
    project_id, scenario_id = project_with_points(db, points=[{"name": "Seul", "pk": 0.0, "z": 50.0}])

    profile_id = db.create_profile(scenario_id, "Loin", 5000.0)

    assert db.get_distance_zone(project_id) is None
    # Né en pente imposée, sans message (il n'a jamais été en pente calculée)...
    assert params(db, profile_id) == {"slope_mode": "imposed"}
    assert db.last_slope_report.message() == ""
    # ...la raison reste disponible pour l'onglet Hydraulique.
    assert "au moins deux points durs" in db.profile_slope_info(profile_id)["reason"]


# --- Pente calculée / imposée ---

@pytest.mark.parametrize("distance,slope", [(0.0, 0.02), (150.0, 0.02), (200.0, 0.005), (400.0, 0.005)])
def test_new_profile_gets_the_slope_of_its_segment(tmp_path, distance, slope):
    db = make_db(tmp_path)
    _, scenario_id = project_with_points(db)

    profile_id = db.create_profile(scenario_id, "P", distance)

    assert params(db, profile_id)["slope_mode"] == "computed"
    assert params(db, profile_id)["slope"] == pytest.approx(slope)


def test_profile_slope_info_names_the_segment(tmp_path):
    db = make_db(tmp_path)
    _, scenario_id = project_with_points(db)
    profile_id = db.create_profile(scenario_id, "P", 250.0)

    info = db.profile_slope_info(profile_id)

    assert info["slope"] == pytest.approx(0.005) and info["segment"] == "« B » → « C »"


def test_changing_the_distance_recomputes_the_slope(tmp_path):
    db = make_db(tmp_path)
    _, scenario_id = project_with_points(db)
    profile_id = db.create_profile(scenario_id, "P", 100.0)

    report = db.rename_profile(profile_id, "P", 300.0)

    assert params(db, profile_id)["slope"] == pytest.approx(0.005)
    assert report.updated == ["S › P"]


def test_changing_hard_points_updates_computed_slopes_but_not_imposed_ones(tmp_path):
    db = make_db(tmp_path)
    project_id, scenario_id = project_with_points(db)
    computed = db.create_profile(scenario_id, "Calculée", 100.0)
    imposed = db.create_profile(scenario_id, "Imposée", 300.0)
    db.save_profile_state(imposed, [], {"slope_mode": "imposed", "slope": 0.0123})
    changed = db.get_hard_points(project_id)
    changed[0]["z"] = 52.0  # tronçon A-B : 6 m sur 200 m

    report = db.set_hard_points(project_id, changed)

    assert params(db, computed)["slope"] == pytest.approx(0.03)
    assert params(db, imposed) == {"slope_mode": "imposed", "slope": 0.0123}
    assert report.updated == ["S › Calculée"] and report.imposed_kept == ["S › Imposée"]
    message = report.message()
    assert "1 profil(s) mis à jour" in message and "1 profil(s) en pente imposée, non modifié(s)" in message


def test_removing_hard_points_switches_computed_profiles_to_imposed(tmp_path):
    db = make_db(tmp_path)
    project_id, scenario_id = project_with_points(db)
    profile_id = db.create_profile(scenario_id, "P", 0.0)

    report = db.set_hard_points(project_id, [])

    assert params(db, profile_id) == {"slope_mode": "imposed", "slope": pytest.approx(0.02)}
    assert report.switched_to_imposed and "passé(s) en pente imposée" in report.message()


# --- Migration d'une base existante (points amont/aval) ---

def _make_pre_list_db(tmp_path, upstream, downstream, profiles):
    """Base au format précédent : points durs amont/aval dans les colonnes de `projects`,
    pas encore de table `hard_points`, profils sans mode de pente."""
    db = make_db(tmp_path, "old.db")
    project_id = db.create_project("Rivière")
    scenario_id = db.create_scenario(project_id, "S")
    conn = sqlite3.connect(db.db_path)
    conn.execute("DROP TABLE hard_points")
    conn.execute(
        """UPDATE projects SET hard_point_upstream_name = ?, hard_point_upstream_x = ?, hard_point_upstream_z = ?,
               hard_point_downstream_name = ?, hard_point_downstream_x = ?, hard_point_downstream_z = ?
           WHERE id = ?""", (*upstream, *downstream, project_id))
    for i, (name, distance, slope) in enumerate(profiles, start=1):
        conn.execute("INSERT INTO profiles (id, scenario_id, name, distance, existing_data, project_params) "
                     "VALUES (?, ?, ?, ?, '[]', ?)", (i, scenario_id, name, distance, json.dumps({"slope": slope})))
    conn.commit()
    conn.close()
    return db.db_path


def test_migration_turns_upstream_and_downstream_into_first_and_last_points(tmp_path):
    path = _make_pre_list_db(tmp_path, ("Début", 0.0, 51.0), ("Fin", 500.0, 40.0),
                             [("PK 100", 100.0, 0.058), ("PK 300", 300.0, 0.005)])

    db = DatabaseManager(db_path=path)

    assert [(p["name"], p["pk"], p["z"]) for p in db.get_hard_points(1)] == [("Début", 0.0, 51.0), ("Fin", 500.0, 40.0)]
    # Les profils existants passent en pente calculée : 11 m sur 500 m.
    assert params(db, 1) == {"slope": pytest.approx(0.022), "slope_mode": "computed"}
    assert params(db, 2) == {"slope": pytest.approx(0.022), "slope_mode": "computed"}
    assert db.startup_slope_report.updated == ["S › PK 100", "S › PK 300"]
    # Idempotent : rouvrir la base ne refait pas la migration.
    reopened = DatabaseManager(db_path=path)
    assert len(reopened.get_hard_points(1)) == 2 and not reopened.startup_slope_report.message()


def test_migration_puts_impossible_profiles_in_imposed_slope(tmp_path):
    """Ancien profil hors zone, et points incomplets : pente imposée (valeur conservée)."""
    path = _make_pre_list_db(tmp_path, ("Début", 0.0, 51.0), ("Fin", 500.0, 40.0),
                             [("Dedans", 100.0, 0.058), ("Dehors", 700.0, 0.005)])

    db = DatabaseManager(db_path=path)

    assert params(db, 2) == {"slope": 0.005, "slope_mode": "imposed"}
    assert db.startup_slope_report.switched_to_imposed[0][0] == "S › Dehors"
    assert "hors de la zone" in db.startup_slope_report.message()


def test_migration_keeps_an_incomplete_point_as_is(tmp_path):
    path = _make_pre_list_db(tmp_path, ("Pont", None, 51.0), (None, None, None), [("PK 0", 0.0, 0.01)])

    db = DatabaseManager(db_path=path)

    assert [(p["name"], p["pk"], p["z"]) for p in db.get_hard_points(1)] == [("Pont", None, 51.0)]
    assert params(db, 1) == {"slope": 0.01, "slope_mode": "imposed"}
    # Le point incomplet hérité peut rester tel quel lors d'une modification.
    db.set_hard_points(1, db.get_hard_points(1))


# --- Export / import / duplication ---

def test_project_export_import_keeps_hard_points_and_slope_modes(tmp_path):
    db = make_db(tmp_path)
    project_id, scenario_id = project_with_points(db)
    computed = db.create_profile(scenario_id, "Calculée", 100.0)
    imposed = db.create_profile(scenario_id, "Imposée", 300.0)
    db.save_profile_state(imposed, [], {"slope_mode": "imposed", "slope": 0.0123})
    path = tmp_path / "projet.json"
    db.export_project_to_file(project_id, path)

    data = db.read_export_file(path)
    new_id = db.import_project(data)

    assert data["version"] == 2
    assert [(p["name"], p["pk"], p["z"]) for p in db.get_hard_points(new_id)] == [("A", 1000.0, 50.0), ("B", 1200.0, 46.0), ("C", 1400.0, 45.0)]
    imported = {p["name"]: p["id"] for p in next(x for x in db.get_all_projects() if x["id"] == new_id)["scenarios"][0]["profiles"]}
    assert params(db, imported["Calculée"]) == params(db, computed)
    assert params(db, imported["Imposée"]) == {"slope_mode": "imposed", "slope": 0.0123}


def test_legacy_project_file_with_upstream_and_downstream_still_imports(tmp_path):
    db = make_db(tmp_path)
    legacy = {
        "type": "project", "version": 1, "name": "Ancien",
        "hard_points": {"upstream": {"name": "Amont", "x": 0.0, "z": 30.0},
                        "downstream": {"name": "Aval", "x": 100.0, "z": 29.0}},
        "scenarios": [{"name": "S", "profiles": [
            {"name": "PK 50", "distance": 50.0, "existing_data": [], "project_params": {"slope": 0.1}}]}],
    }

    project_id = db.import_project(legacy)

    assert [(p["name"], p["pk"], p["z"]) for p in db.get_hard_points(project_id)] == [("Amont", 0.0, 30.0), ("Aval", 100.0, 29.0)]
    profile_id = db.get_all_projects()[0]["scenarios"][0]["profiles"][0]["id"]
    assert params(db, profile_id) == {"slope": pytest.approx(0.01), "slope_mode": "computed"}


def test_imported_computed_profile_takes_the_slope_of_its_new_project(tmp_path):
    db = make_db(tmp_path)
    _, source_scenario = project_with_points(db, name="Source")
    profile_id = db.create_profile(source_scenario, "PK 100", 100.0)
    other_points = [{"name": "X", "pk": 0.0, "z": 10.0}, {"name": "Y", "pk": 1000.0, "z": 9.0}]
    _, target_scenario = project_with_points(db, points=other_points, name="Cible")

    new_id = db.import_profile_into_scenario(target_scenario, db.export_profile(profile_id))

    assert params(db, new_id) == {"slope": pytest.approx(0.001), "slope_mode": "computed"}


def test_importing_a_scenario_with_profiles_outside_the_zone_is_refused_entirely(tmp_path):
    db = make_db(tmp_path)
    _, source_scenario = project_with_points(db, name="Source")
    db.create_profile(source_scenario, "PK 50", 50.0)
    db.create_profile(source_scenario, "PK 350", 350.0)
    short = [{"name": "X", "pk": 0.0, "z": 10.0}, {"name": "Y", "pk": 100.0, "z": 9.0}]
    target_project, _ = project_with_points(db, points=short, name="Cible")

    with pytest.raises(ValueError, match="(?s)Import refusé.*« PK 350 ».*0 à 100 m"):
        db.import_scenario_into_project(target_project, db.export_scenario(source_scenario))
    assert [s["name"] for s in db.get_scenarios(target_project)] == ["S"]


def test_duplicate_project_copies_hard_points_and_slope_modes(tmp_path):
    db = make_db(tmp_path)
    project_id, scenario_id = project_with_points(db)
    imposed = db.create_profile(scenario_id, "Imposée", 300.0)
    db.save_profile_state(imposed, [], {"slope_mode": "imposed", "slope": 0.0123})

    new_id = db.duplicate_project(project_id, "Copie")

    assert [(p["name"], p["pk"]) for p in db.get_hard_points(new_id)] == [("A", 1000.0), ("B", 1200.0), ("C", 1400.0)]
    copy = next(p for p in db.get_all_projects() if p["id"] == new_id)["scenarios"][0]["profiles"][0]
    assert params(db, copy["id"]) == {"slope_mode": "imposed", "slope": 0.0123}


def test_draft_copied_to_a_scenario_switches_to_computed_slope(tmp_path):
    db = make_db(tmp_path)
    _, scenario_id = project_with_points(db)
    draft_id = db.create_draft("Essai")
    db.save_draft_state(draft_id, [], {"slope": 0.5, "slope_mode": "imposed"})

    new_id = db.copy_draft_to_scenario(draft_id, scenario_id, 0.0)

    assert params(db, new_id) == {"slope": pytest.approx(0.02), "slope_mode": "computed"}
    assert db.load_draft_state(draft_id)[1] == {"slope": 0.5, "slope_mode": "imposed"}
