import json
import logging
import sqlite3

import pytest

from database.db_manager import DatabaseManager, DEFAULT_SCENARIO_NAME


def make_db(tmp_path) -> DatabaseManager:
    return DatabaseManager(db_path=tmp_path / "test.db")


def make_scenario(db: DatabaseManager, project_name: str = "P", scenario_name: str = "S") -> int:
    project_id = db.create_project(project_name)
    return db.create_scenario(project_id, scenario_name)


def raw_rows(db: DatabaseManager, sql: str, params=()):
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(sql, params)]
    finally:
        conn.close()


def strip_mode(state):
    """État d'un profil sans le mode de pente : après une duplication, un import ou un
    renommage, le recalcul des pentes l'ajoute (ici "imposed", faute de points durs)."""
    existing_data, params = state
    return existing_data, {k: v for k, v in params.items() if k != "slope_mode"}


def hard_points(db, project_id):
    """Points durs du projet sans leurs identifiants en base."""
    return [{k: p[k] for k in ("name", "pk", "z")} for p in db.get_hard_points(project_id)]


TWO_POINTS = [{"name": "Pont Amont", "pk": 0.0, "z": 100.0}, {"name": "Pont Aval", "pk": 500.0, "z": 90.0}]


# --- Structure Projet → Scénario → Profil ---

def test_create_project_scenario_and_profile_round_trip(tmp_path):
    db = make_db(tmp_path)

    project_id = db.create_project("Rivière Test")
    scenario_id = db.create_scenario(project_id, "Variante A")
    profile_id = db.create_or_get_profile(scenario_id, "Pont de la Gare", 125.4)

    assert db.get_all_projects() == [
        {"id": project_id, "name": "Rivière Test", "scenarios": [
            {"id": scenario_id, "name": "Variante A",
             "profiles": [{"id": profile_id, "name": "Pont de la Gare", "distance": 125.4}]},
        ]}
    ]


def test_create_project_has_no_scenario_by_default(tmp_path):
    """La base ne crée pas de scénario d'office : c'est la sidebar qui ajoute le scénario
    initial d'un nouveau projet (et duplicate_project recopie ceux de la source)."""
    db = make_db(tmp_path)
    project_id = db.create_project("P")

    assert db.get_scenarios(project_id) == []


def test_scenarios_listed_in_creation_order(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    first = db.create_scenario(project_id, "Zeta")
    second = db.create_scenario(project_id, "Alpha")

    assert db.get_scenarios(project_id) == [
        {"id": first, "name": "Zeta"}, {"id": second, "name": "Alpha"},
    ]


def test_scenario_name_unique_per_project_but_not_globally(tmp_path):
    db = make_db(tmp_path)
    project_a = db.create_project("A")
    project_b = db.create_project("B")
    db.create_scenario(project_a, "Variante")

    with pytest.raises(ValueError):
        db.create_scenario(project_a, "Variante")
    # Même nom dans un autre projet : autorisé.
    db.create_scenario(project_b, "Variante")

    other = db.create_scenario(project_a, "Autre")
    with pytest.raises(ValueError):
        db.rename_scenario(other, "Variante")


def test_create_scenario_in_unknown_project_raises(tmp_path):
    db = make_db(tmp_path)

    with pytest.raises(ValueError, match="introuvable"):
        db.create_scenario(999, "S")


def test_get_scenario_project_id(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    scenario_id = db.create_scenario(project_id, "S")

    assert db.get_scenario_project_id(scenario_id) == project_id
    assert db.get_scenario_project_id(999) is None


def test_create_or_get_profile_returns_existing_id_by_name(tmp_path):
    """Une deuxième création avec le même nom ne recrée pas de profil : elle renvoie
    l'existant sans toucher à sa distance."""
    db = make_db(tmp_path)
    scenario_id = make_scenario(db)

    first_id = db.create_or_get_profile(scenario_id, "Amont", 0.0)
    second_id = db.create_or_get_profile(scenario_id, "Amont", 999.0)

    assert first_id == second_id
    profiles = db.get_all_projects()[0]["scenarios"][0]["profiles"]
    assert profiles == [{"id": first_id, "name": "Amont", "distance": 0.0}]


def test_profile_name_must_be_unique_per_scenario(tmp_path):
    db = make_db(tmp_path)
    scenario_id = make_scenario(db)
    db.create_or_get_profile(scenario_id, "Amont", 0.0)

    with pytest.raises(ValueError):
        db.rename_profile(
            db.create_or_get_profile(scenario_id, "Aval", 100.0),
            "Amont", 200.0,
        )


def test_profile_distance_must_be_unique_per_scenario(tmp_path):
    db = make_db(tmp_path)
    scenario_id = make_scenario(db)
    db.create_or_get_profile(scenario_id, "Amont", 0.0)

    with pytest.raises(ValueError):
        db.create_or_get_profile(scenario_id, "Autre nom", 0.0)


def test_same_profile_name_and_distance_allowed_in_two_scenarios_of_same_project(tmp_path):
    """L'unicité (nom, distance) est par scénario : deux scénarios d'un même projet
    peuvent chacun avoir leur "PK 300"."""
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    scenario_a = db.create_scenario(project_id, "A")
    scenario_b = db.create_scenario(project_id, "B")

    profile_a = db.create_or_get_profile(scenario_a, "PK 300", 300.0)
    profile_b = db.create_or_get_profile(scenario_b, "PK 300", 300.0)

    assert profile_a != profile_b
    scenarios = db.get_all_projects()[0]["scenarios"]
    assert [s["profiles"] for s in scenarios] == [
        [{"id": profile_a, "name": "PK 300", "distance": 300.0}],
        [{"id": profile_b, "name": "PK 300", "distance": 300.0}],
    ]


def test_same_name_or_distance_allowed_across_different_projects(tmp_path):
    db = make_db(tmp_path)
    scenario_a = make_scenario(db, "A")
    scenario_b = make_scenario(db, "B")

    db.create_or_get_profile(scenario_a, "Amont", 0.0)
    db.create_or_get_profile(scenario_b, "Amont", 0.0)

    projects = db.get_all_projects()
    assert len(projects[0]["scenarios"][0]["profiles"]) == 1
    assert len(projects[1]["scenarios"][0]["profiles"]) == 1


def test_create_profile_in_unknown_scenario_raises(tmp_path):
    db = make_db(tmp_path)

    with pytest.raises(ValueError, match="introuvable"):
        db.create_or_get_profile(999, "Amont", 0.0)


def test_profiles_sorted_by_distance_not_creation_order(tmp_path):
    db = make_db(tmp_path)
    scenario_id = make_scenario(db)
    db.create_or_get_profile(scenario_id, "C", 300.0)
    db.create_or_get_profile(scenario_id, "A", 100.0)
    db.create_or_get_profile(scenario_id, "B", 200.0)

    names = [p["name"] for p in db.get_all_projects()[0]["scenarios"][0]["profiles"]]
    assert names == ["A", "B", "C"]


def test_duplicate_profile_stays_in_its_scenario(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    scenario_a = db.create_scenario(project_id, "A")
    scenario_b = db.create_scenario(project_id, "B")
    source = db.create_or_get_profile(scenario_a, "Amont", 0.0)
    db.save_profile_state(source, [{"X (m)": 0.0, "Z (m NGF)": 10.0}], {"anchor_z": 9.0})
    # Un profil homonyme dans un AUTRE scénario ne bloque pas la duplication.
    db.create_or_get_profile(scenario_b, "Copie", 50.0)

    copy_id = db.duplicate_profile(source, "Copie", 50.0)

    scenarios = db.get_all_projects()[0]["scenarios"]
    assert [p["name"] for p in scenarios[0]["profiles"]] == ["Amont", "Copie"]
    assert [p["name"] for p in scenarios[1]["profiles"]] == ["Copie"]
    assert strip_mode(db.load_profile_state(copy_id)) == strip_mode(db.load_profile_state(source))


def test_longitudinal_data_is_per_scenario(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    scenario_a = db.create_scenario(project_id, "A")
    scenario_b = db.create_scenario(project_id, "B")
    db.create_or_get_profile(scenario_a, "Nom quelconque", 200.0)
    db.create_or_get_profile(scenario_a, "Autre nom", 100.0)
    db.create_or_get_profile(scenario_b, "Seul", 50.0)

    assert [r[0] for r in db.get_longitudinal_data(scenario_a)] == [100.0, 200.0]
    assert [r[0] for r in db.get_longitudinal_data(scenario_b)] == [50.0]


# --- Création de scénario avec conservation des profils d'un scénario existant ---

def test_create_scenario_without_source_starts_empty(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    source = db.create_scenario(project_id, "Source")
    db.create_or_get_profile(source, "Amont", 0.0)

    new_scenario = db.create_scenario(project_id, "Vide")

    scenarios = {s["id"]: s for s in db.get_all_projects()[0]["scenarios"]}
    assert scenarios[new_scenario]["profiles"] == []
    assert len(scenarios[source]["profiles"]) == 1


def _populate_source_scenario(db: DatabaseManager, scenario_id: int) -> dict:
    """Trois profils aux données géométriques et hydrauliques distinctes. Retourne
    {nom: (distance, existing_data, project_params)}."""
    expected = {
        "PK 0": (0.0,
                 [{"X (m)": 0.0, "Z (m NGF)": 100.0}, {"X (m)": 10.0, "Z (m NGF)": 98.5}],
                 {"anchor_z": 98.0, "slope": 0.004, "ks_pro": 30.0, "calc_mode": "H_FROM_Q",
                  "q_target": 12.0, "hydro_source": "project"}),
        "PK 150": (150.0,
                   [{"X (m)": 0.0, "Z (m NGF)": 99.0}, {"X (m)": 12.0, "Z (m NGF)": 97.2}],
                   {"anchor_z": 97.0, "slope": 0.006, "ks_pro": 25.0, "calc_mode": "Q_FROM_H",
                    "h_eau": 0.8, "hydro_source": "existing"}),
        "Seuil aval": (300.0, [], {}),
    }
    for name, (distance, existing_data, params) in expected.items():
        profile_id = db.create_or_get_profile(scenario_id, name, distance)
        db.save_profile_state(profile_id, existing_data, params)
    return expected


def _profiles_by_name(db: DatabaseManager, scenario_id: int) -> dict:
    project = next(
        p for p in db.get_all_projects()
        if any(s["id"] == scenario_id for s in p["scenarios"])
    )
    scenario = next(s for s in project["scenarios"] if s["id"] == scenario_id)
    return {p["name"]: p for p in scenario["profiles"]}


def test_create_scenario_from_source_copies_all_profiles_identically(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    source = db.create_scenario(project_id, "Source")
    expected = _populate_source_scenario(db, source)

    copy = db.create_scenario(project_id, "Variante", source_scenario_id=source)

    copied = _profiles_by_name(db, copy)
    originals = _profiles_by_name(db, source)
    assert set(copied) == set(expected)
    for name, (distance, existing_data, params) in expected.items():
        assert copied[name]["distance"] == distance
        # Nouvelles lignes, pas des références vers celles de la source.
        assert copied[name]["id"] != originals[name]["id"]
        assert db.load_profile_state(copied[name]["id"]) == (existing_data, params)


def test_copied_scenario_is_independent_from_its_source(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    source = db.create_scenario(project_id, "Source")
    expected = _populate_source_scenario(db, source)
    copy = db.create_scenario(project_id, "Variante", source_scenario_id=source)
    source_ids = {n: p["id"] for n, p in _profiles_by_name(db, source).items()}
    copy_ids = {n: p["id"] for n, p in _profiles_by_name(db, copy).items()}

    # Modifier la copie (données, nom/distance, suppression, ajout)...
    db.save_profile_state(copy_ids["PK 0"], [{"X (m)": 5.0, "Z (m NGF)": 50.0}], {"anchor_z": 1.0})
    db.rename_profile(copy_ids["PK 150"], "PK 175", 175.0)
    db.delete_profile(copy_ids["Seuil aval"])
    db.create_or_get_profile(copy, "Nouveau", 500.0)

    # ...ne touche en rien à la source.
    source_now = _profiles_by_name(db, source)
    assert {n: p["distance"] for n, p in source_now.items()} == {
        n: d for n, (d, _, _) in expected.items()
    }
    for name, (_, existing_data, params) in expected.items():
        assert strip_mode(db.load_profile_state(source_ids[name])) == (existing_data, params)

    # Et inversement : modifier la source ne touche pas la copie.
    db.save_profile_state(source_ids["PK 150"], [], {"anchor_z": 0.0})
    assert strip_mode(db.load_profile_state(copy_ids["PK 150"])) == (expected["PK 150"][1], expected["PK 150"][2])

    # Supprimer la source laisse la copie intacte.
    db.delete_scenario(source)
    assert set(_profiles_by_name(db, copy)) == {"PK 0", "PK 175", "Nouveau"}


def test_create_scenario_from_source_of_another_project_is_refused_atomically(tmp_path):
    db = make_db(tmp_path)
    project_a = db.create_project("A")
    project_b = db.create_project("B")
    source_in_a = db.create_scenario(project_a, "Source")
    db.create_or_get_profile(source_in_a, "Amont", 0.0)

    with pytest.raises(ValueError, match="même projet"):
        db.create_scenario(project_b, "Variante", source_scenario_id=source_in_a)
    with pytest.raises(ValueError, match="introuvable"):
        db.create_scenario(project_b, "Variante", source_scenario_id=999)

    # Rien n'a été créé dans le projet B.
    assert db.get_scenarios(project_b) == []


def test_create_scenario_with_existing_name_does_not_copy_profiles(tmp_path):
    """Si le nom est déjà pris, l'échec survient avant toute copie de profils."""
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    source = db.create_scenario(project_id, "Source")
    db.create_or_get_profile(source, "Amont", 0.0)

    with pytest.raises(ValueError):
        db.create_scenario(project_id, "Source", source_scenario_id=source)

    assert len(raw_rows(db, "SELECT id FROM profiles")) == 1


# --- Points durs : au niveau du projet, partagés par ses scénarios ---

def test_hard_points_default_to_empty_then_round_trip(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")

    assert db.get_hard_points(project_id) == []

    db.set_hard_points(project_id, TWO_POINTS)

    assert hard_points(db, project_id) == TWO_POINTS
    assert all(p["id"] is not None for p in db.get_hard_points(project_id))


def test_hard_points_are_not_duplicated_per_scenario(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    db.set_hard_points(project_id, TWO_POINTS)
    source = db.create_scenario(project_id, "A")
    db.create_scenario(project_id, "B", source_scenario_id=source)

    scenario_columns = {row["name"] for row in raw_rows(db, "PRAGMA table_info(scenarios)")}
    assert not any(col.startswith("hard_point") for col in scenario_columns)
    # Les deux scénarios renvoient au même (unique) jeu de points durs du projet.
    assert {db.get_scenario_project_id(s["id"]) for s in db.get_scenarios(project_id)} == {project_id}


# --- Duplication / suppression en cascade ---

def test_duplicate_project_copies_hard_points_scenarios_and_profiles(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("Original")
    db.set_hard_points(project_id, TWO_POINTS)
    scenario_a = db.create_scenario(project_id, "A")
    scenario_b = db.create_scenario(project_id, "B")
    profile_a = db.create_or_get_profile(scenario_a, "Amont", 0.0)
    db.save_profile_state(profile_a, [{"X (m)": 0.0, "Z (m NGF)": 10.0}], {"anchor_z": 9.0})
    db.create_or_get_profile(scenario_b, "Amont", 0.0)
    db.create_or_get_profile(scenario_b, "Aval", 400.0)

    new_project_id = db.duplicate_project(project_id, "Copie")

    assert hard_points(db, new_project_id) == hard_points(db, project_id) == TWO_POINTS
    by_name = {p["name"]: p for p in db.get_all_projects()}
    copied = by_name["Copie"]["scenarios"]
    assert [s["name"] for s in copied] == ["A", "B"]
    assert [p["name"] for p in copied[0]["profiles"]] == ["Amont"]
    assert [p["name"] for p in copied[1]["profiles"]] == ["Amont", "Aval"]
    assert db.load_profile_state(copied[0]["profiles"][0]["id"]) == db.load_profile_state(profile_a)


def test_duplicate_project_with_existing_name_raises(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("A")
    db.create_project("B")

    with pytest.raises(ValueError):
        db.duplicate_project(project_id, "B")


def test_delete_project_cascades_to_scenarios_and_profiles(tmp_path):
    """Les clés étrangères sont désormais activées : supprimer un projet ne laisse plus
    aucun scénario ni profil orphelin en base."""
    db = make_db(tmp_path)
    kept = make_scenario(db, "Gardé")
    db.create_or_get_profile(kept, "Amont", 0.0)
    project_id = db.create_project("Supprimé")
    scenario_id = db.create_scenario(project_id, "S")
    db.create_or_get_profile(scenario_id, "Amont", 0.0)

    db.delete_project(project_id)

    assert raw_rows(db, "SELECT id FROM scenarios") == [{"id": kept}]
    assert [r["scenario_id"] for r in raw_rows(db, "SELECT scenario_id FROM profiles")] == [kept]


def test_delete_scenario_removes_only_its_profiles(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    scenario_a = db.create_scenario(project_id, "A")
    scenario_b = db.create_scenario(project_id, "B")
    db.create_or_get_profile(scenario_a, "PK 300", 300.0)
    db.create_or_get_profile(scenario_b, "PK 300", 300.0)

    db.delete_scenario(scenario_a)

    assert db.get_scenarios(project_id) == [{"id": scenario_b, "name": "B"}]
    assert [r["scenario_id"] for r in raw_rows(db, "SELECT scenario_id FROM profiles")] == [scenario_b]


# --- Zone Draft ---

def test_draft_crud_and_state_round_trip(tmp_path):
    db = make_db(tmp_path)

    draft_id = db.create_draft("Essai berge")
    assert db.get_all_drafts() == [{"id": draft_id, "name": "Essai berge"}]
    assert db.load_draft_state(draft_id) == ([], {})

    points = [{"X (m)": 0.0, "Z (m NGF)": 10.0}, {"X (m)": 5.0, "Z (m NGF)": 9.0}]
    params = {"anchor_z": 8.5, "slope": 0.01, "calc_mode": "H_FROM_Q"}
    db.save_draft_state(draft_id, points, params)
    assert db.load_draft_state(draft_id) == (points, params)

    db.rename_draft(draft_id, "Essai lit")
    copy_id = db.duplicate_draft(draft_id, "Essai lit bis")
    assert db.load_draft_state(copy_id) == (points, params)
    assert [d["name"] for d in db.get_all_drafts()] == ["Essai lit", "Essai lit bis"]

    db.delete_draft(draft_id)
    assert db.get_all_drafts() == [{"id": copy_id, "name": "Essai lit bis"}]


def test_draft_name_must_be_unique(tmp_path):
    db = make_db(tmp_path)
    draft_id = db.create_draft("A")
    db.create_draft("B")

    with pytest.raises(ValueError):
        db.create_draft("A")
    with pytest.raises(ValueError):
        db.rename_draft(draft_id, "B")
    with pytest.raises(ValueError):
        db.duplicate_draft(draft_id, "B")


def test_drafts_are_fully_isolated_from_projects(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    scenario_id = db.create_scenario(project_id, "S")
    profile_id = db.create_or_get_profile(scenario_id, "Essai", 0.0)
    profile_state = ([{"X (m)": 0.0, "Z (m NGF)": 1.0}], {"anchor_z": 0.5})
    db.save_profile_state(profile_id, *profile_state)
    projects_before = db.get_all_projects()

    # Même nom qu'un profil : aucun conflit, ce sont deux espaces distincts.
    draft_id = db.create_draft("Essai")
    # Les ids des deux tables se recoupent (1 et 1 ici) : écrire dans le brouillon ne
    # doit jamais atteindre le profil de même id.
    assert draft_id == profile_id
    db.save_draft_state(draft_id, [{"X (m)": 9.0, "Z (m NGF)": 9.0}], {"anchor_z": 9.0})
    db.duplicate_draft(draft_id, "Essai 2")

    assert db.get_all_projects() == projects_before
    assert db.load_profile_state(profile_id) == profile_state

    # Et dans l'autre sens : supprimer tout le projet laisse les brouillons en place.
    db.delete_project(project_id)
    assert [d["name"] for d in db.get_all_drafts()] == ["Essai", "Essai 2"]

    # Aucune clé étrangère sur la table des brouillons.
    assert raw_rows(db, "PRAGMA foreign_key_list(drafts)") == []
    draft_columns = {row["name"] for row in raw_rows(db, "PRAGMA table_info(drafts)")}
    assert draft_columns.isdisjoint({"project_id", "scenario_id", "distance"})


# --- Migrations ---

def _create_legacy_db(db_path) -> None:
    """Construit une base au format d'une version antérieure de l'app (table `profiles`
    avec un unique champ `pk_name`), pour tester la migration automatique."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            pk_name TEXT NOT NULL,
            existing_data TEXT,
            project_params TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
            UNIQUE (project_id, pk_name)
        )
    """)
    conn.execute("INSERT INTO projects (id, name) VALUES (1, 'Legacy')")
    conn.execute(
        "INSERT INTO profiles (id, project_id, pk_name, existing_data, project_params) "
        "VALUES (2, 1, '100', '[]', '{}')"
    )
    conn.execute(
        "INSERT INTO profiles (id, project_id, pk_name, existing_data, project_params) "
        "VALUES (5, 1, '125,4', '[]', '{}')"
    )
    # Ancien nom non numérique (déjà une incohérence sous l'ancien schéma, cf.
    # get_longitudinal_data qui l'ignorait silencieusement) : doit migrer sans planter.
    conn.execute(
        "INSERT INTO profiles (id, project_id, pk_name, existing_data, project_params) "
        "VALUES (9, 1, 'test 2', '[]', '{}')"
    )
    conn.commit()
    conn.close()


def test_migration_from_legacy_pk_name_schema(tmp_path):
    """Les deux migrations s'enchaînent : pk_name → name/distance, puis rattachement à un
    scénario par défaut."""
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path)

    db = DatabaseManager(db_path=db_path)

    scenarios = db.get_all_projects()[0]["scenarios"]
    assert [s["name"] for s in scenarios] == [DEFAULT_SCENARIO_NAME]
    profiles = {p["id"]: p for p in scenarios[0]["profiles"]}
    # Le nom reprend l'ancien pk_name tel quel, la distance sa valeur numérique (virgule
    # comprise), et les ids d'origine sont préservés.
    assert profiles[2] == {"id": 2, "name": "100", "distance": 100.0}
    assert profiles[5] == {"id": 5, "name": "125,4", "distance": 125.4}
    # pk_name non numérique : distance de repli = l'id du profil, garanti unique.
    assert profiles[9] == {"id": 9, "name": "test 2", "distance": 9.0}


def test_migration_preserves_autoincrement_continuity(tmp_path):
    """Un nouveau profil créé après migration ne doit pas réutiliser un id déjà migré."""
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path)

    db = DatabaseManager(db_path=db_path)
    scenario_id = db.get_all_projects()[0]["scenarios"][0]["id"]
    new_id = db.create_or_get_profile(scenario_id, "Nouveau", 50.0)

    assert new_id > 9


def test_migration_adds_hard_point_columns_to_existing_projects_table(tmp_path):
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path)

    db = DatabaseManager(db_path=db_path)

    assert db.get_hard_points(1) == []


def _create_pre_scenario_db(db_path) -> None:
    """Base au format de la version précédente (points durs sur `projects`, profils
    `name`/`distance` rattachés directement au projet), reproduisant les cas de la vraie
    base : plusieurs projets, un projet sans profil, des trous dans les ids, et des
    profils orphelins dont le projet a été supprimé alors que les clés étrangères
    n'étaient pas actives (le dernier id attribué est justement celui d'un orphelin)."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            hard_point_upstream_name TEXT, hard_point_upstream_x REAL, hard_point_upstream_z REAL,
            hard_point_downstream_name TEXT, hard_point_downstream_x REAL, hard_point_downstream_z REAL
        )
    """)
    conn.execute("""
        CREATE TABLE profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            distance REAL NOT NULL,
            existing_data TEXT,
            project_params TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
            UNIQUE (project_id, name),
            UNIQUE (project_id, distance)
        )
    """)
    conn.execute(
        "INSERT INTO projects (id, name, hard_point_upstream_name, hard_point_upstream_x, "
        "hard_point_upstream_z) VALUES (1, 'Test', 'Début', 0.0, 101.5)"
    )
    conn.execute("INSERT INTO projects (id, name) VALUES (3, 'Sans profil')")
    conn.execute("INSERT INTO projects (id, name) VALUES (4, 'Autre')")
    rows = [
        (2, 1, "Test 1", 100.0, '[{"X (m)": 0.0, "Z (m NGF)": 99.0}]', '{"anchor_z": 98.0}',
         "2026-09-20 10:00:00"),
        (4, 1, "test 2", 300.0, '[{"X (m)": 0.0, "Z (m NGF)": 97.0}]', '{"anchor_z": 96.0}',
         "2026-09-21 11:00:00"),
        (5, 4, "Test 1", 100.0, "{}", "{}", "2026-09-22 12:00:00"),
        # Orphelins : projets 2 et 5 supprimés.
        (3, 2, "test 3", 200.0, "{}", "{}", "2026-09-19 09:00:00"),
        (7, 5, "300", 300.0, "[]", "{}", "2026-09-19 09:30:00"),
    ]
    conn.executemany(
        "INSERT INTO profiles (id, project_id, name, distance, existing_data, project_params, "
        "last_updated) VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.execute("UPDATE sqlite_sequence SET seq = 6 WHERE name = 'projects'")
    conn.commit()
    conn.close()


def test_migration_to_scenarios_creates_one_default_scenario_per_project(tmp_path):
    db_path = tmp_path / "pre_scenario.db"
    _create_pre_scenario_db(db_path)

    db = DatabaseManager(db_path=db_path)

    projects = {p["id"]: p for p in db.get_all_projects()}
    assert set(projects) == {1, 3, 4}
    for project in projects.values():
        assert [s["name"] for s in project["scenarios"]] == [DEFAULT_SCENARIO_NAME]
    # Un projet sans profil reçoit lui aussi son scénario (vide).
    assert projects[3]["scenarios"][0]["profiles"] == []


def test_migration_to_scenarios_preserves_profiles_ids_and_data(tmp_path):
    db_path = tmp_path / "pre_scenario.db"
    _create_pre_scenario_db(db_path)

    db = DatabaseManager(db_path=db_path)

    projects = {p["id"]: p for p in db.get_all_projects()}
    assert projects[1]["scenarios"][0]["profiles"] == [
        {"id": 2, "name": "Test 1", "distance": 100.0},
        {"id": 4, "name": "test 2", "distance": 300.0},
    ]
    assert projects[4]["scenarios"][0]["profiles"] == [
        {"id": 5, "name": "Test 1", "distance": 100.0},
    ]
    assert strip_mode(db.load_profile_state(2)) == ([{"X (m)": 0.0, "Z (m NGF)": 99.0}], {"anchor_z": 98.0})
    assert strip_mode(db.load_profile_state(4)) == ([{"X (m)": 0.0, "Z (m NGF)": 97.0}], {"anchor_z": 96.0})
    # Projets sans points durs : les profils migrés passent en pente imposée.
    assert db.load_profile_state(2)[1]["slope_mode"] == "imposed"
    last_updated = {r["id"]: r["last_updated"] for r in raw_rows(db, "SELECT id, last_updated FROM profiles")}
    assert last_updated == {2: "2026-09-20 10:00:00", 4: "2026-09-21 11:00:00", 5: "2026-09-22 12:00:00"}
    # Les points durs restent sur le projet, inchangés.
    assert hard_points(db, 1)[0] == {"name": "Début", "pk": 0.0, "z": 101.5}


def test_migration_to_scenarios_moves_uniqueness_to_scenario_level(tmp_path):
    db_path = tmp_path / "pre_scenario.db"
    _create_pre_scenario_db(db_path)

    db = DatabaseManager(db_path=db_path)
    default_scenario = db.get_scenarios(1)[0]["id"]

    # Toujours unique au sein du scénario migré...
    with pytest.raises(ValueError):
        db.create_or_get_profile(default_scenario, "Autre nom", 100.0)
    with pytest.raises(ValueError):
        db.rename_profile(4, "Test 1", 300.0)
    # ...mais un autre scénario du même projet peut reprendre nom et distance.
    other = db.create_scenario(1, "Variante", source_scenario_id=default_scenario)
    assert [p["name"] for p in _profiles_by_name(db, other).values()] == ["Test 1", "test 2"]

    unique_indexes = [
        [c["name"] for c in raw_rows(db, f"PRAGMA index_info('{idx['name']}')")]
        for idx in raw_rows(db, "PRAGMA index_list(profiles)") if idx["unique"]
    ]
    assert sorted(unique_indexes) == [["scenario_id", "distance"], ["scenario_id", "name"]]


def test_migration_to_scenarios_drops_orphans_and_never_reuses_their_ids(tmp_path, caplog):
    db_path = tmp_path / "pre_scenario.db"
    _create_pre_scenario_db(db_path)

    with caplog.at_level(logging.WARNING):
        db = DatabaseManager(db_path=db_path)

    remaining = {r["id"] for r in raw_rows(db, "SELECT id FROM profiles")}
    assert remaining == {2, 4, 5}
    assert "orphelin" in caplog.text and "test 3" in caplog.text
    assert raw_rows(db, "PRAGMA foreign_key_check") == []

    # L'id 7 (orphelin écarté) était le dernier attribué : il ne doit pas être réutilisé.
    new_id = db.create_or_get_profile(db.get_scenarios(1)[0]["id"], "Nouveau", 50.0)
    assert new_id == 8


def test_migration_to_scenarios_is_idempotent(tmp_path):
    db_path = tmp_path / "pre_scenario.db"
    _create_pre_scenario_db(db_path)

    DatabaseManager(db_path=db_path)
    first = DatabaseManager(db_path=db_path).get_all_projects()
    second = DatabaseManager(db_path=db_path).get_all_projects()

    assert first == second
    assert len(raw_rows(DatabaseManager(db_path=db_path), "SELECT id FROM scenarios")) == 3


def test_fresh_database_schema_has_expected_tables(tmp_path):
    db = make_db(tmp_path)

    tables = {r["name"] for r in raw_rows(db, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"projects", "scenarios", "profiles", "drafts"} <= tables
    profile_columns = {r["name"] for r in raw_rows(db, "PRAGMA table_info(profiles)")}
    assert "scenario_id" in profile_columns and "project_id" not in profile_columns


# --- Archivage des projets ---

def test_archived_project_leaves_the_tree_and_is_listed_in_archives(tmp_path):
    db = make_db(tmp_path)
    kept = db.create_project("A garder")
    archived = db.create_project("A ranger")
    scenario_id = db.create_scenario(archived, "S")
    db.create_or_get_profile(scenario_id, "PK 0", 0.0)
    db.create_or_get_profile(scenario_id, "PK 100", 100.0)
    db.create_scenario(archived, "S2")

    db.set_project_archived(archived, True)

    assert [p["id"] for p in db.get_all_projects()] == [kept]
    assert db.get_archived_projects() == [
        {"id": archived, "name": "A ranger", "scenario_count": 2, "profile_count": 2}
    ]


def test_restoring_an_archived_project_gives_back_its_full_content(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    scenario_id = db.create_scenario(project_id, "S")
    profile_id = db.create_or_get_profile(scenario_id, "PK 0", 0.0)
    db.save_profile_state(profile_id, [{"X (m)": 0.0, "Z (m NGF)": 5.0}], {"anchor_z": 4.5})
    before = db.get_all_projects()

    db.set_project_archived(project_id, True)
    db.set_project_archived(project_id, False)

    assert db.get_all_projects() == before
    assert db.get_archived_projects() == []
    assert db.load_profile_state(profile_id) == ([{"X (m)": 0.0, "Z (m NGF)": 5.0}], {"anchor_z": 4.5})


def test_set_project_archived_rejects_an_unknown_project(tmp_path):
    db = make_db(tmp_path)

    with pytest.raises(ValueError, match="introuvable"):
        db.set_project_archived(999, True)


def test_archived_project_keeps_its_name_reserved_and_the_error_says_so(tmp_path):
    db = make_db(tmp_path)
    archived = db.create_project("Rivière")
    other = db.create_project("Autre")
    db.set_project_archived(archived, True)

    with pytest.raises(ValueError, match="dans les archives"):
        db.create_project("Rivière")
    with pytest.raises(ValueError, match="dans les archives"):
        db.rename_project(other, "Rivière")
    with pytest.raises(ValueError, match="dans les archives"):
        db.duplicate_project(other, "Rivière")
    # Un doublon avec un projet actif garde son message habituel.
    with pytest.raises(ValueError) as excinfo:
        db.create_project("Autre")
    assert str(excinfo.value) == "Le projet 'Autre' existe déjà."


def test_import_project_renames_on_collision_with_an_archived_project(tmp_path):
    db = make_db(tmp_path)
    archived = db.create_project("Rivière")
    db.set_project_archived(archived, True)

    new_id = db.import_project({"type": "project", "version": 1, "name": "Rivière", "scenarios": []})

    assert [p["name"] for p in db.get_all_projects()] == ["Rivière - importé"]
    assert new_id != archived


def test_deleting_an_archived_project_removes_all_its_content(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    scenario_id = db.create_scenario(project_id, "S")
    db.create_or_get_profile(scenario_id, "PK 0", 0.0)
    db.set_project_archived(project_id, True)

    db.delete_project(project_id)

    assert db.get_archived_projects() == []
    assert raw_rows(db, "SELECT id FROM scenarios") == []
    assert raw_rows(db, "SELECT id FROM profiles") == []


def test_migration_adds_archived_column_and_keeps_every_project_active(tmp_path):
    db_path = tmp_path / "pre_archive.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
            hard_point_upstream_name TEXT, hard_point_upstream_x REAL, hard_point_upstream_z REAL,
            hard_point_downstream_name TEXT, hard_point_downstream_x REAL, hard_point_downstream_z REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO projects (id, name, hard_point_upstream_name, hard_point_upstream_x, hard_point_upstream_z)
            VALUES (3, 'Ancien', 'Seuil', 12.5, 101.25), (8, 'Autre', NULL, NULL, NULL);
    """)
    conn.commit()
    conn.close()

    db = DatabaseManager(db_path=db_path)

    assert [(p["id"], p["name"]) for p in db.get_all_projects()] == [(3, "Ancien"), (8, "Autre")]
    assert db.get_archived_projects() == []
    assert hard_points(db, 3) == [{"name": "Seuil", "pk": 12.5, "z": 101.25}]
    # Idempotent : rouvrir la base ne rajoute pas la colonne une seconde fois.
    DatabaseManager(db_path=db_path)
    columns = [r["name"] for r in raw_rows(db, "PRAGMA table_info(projects)")]
    assert columns.count("archived") == 1


def test_longitudinal_data_carries_the_profile_names(tmp_path):
    db = make_db(tmp_path)
    scenario_id = make_scenario(db)
    db.create_or_get_profile(scenario_id, "Aval", 200.0)
    db.create_or_get_profile(scenario_id, "Amont", 0.0)

    rows = db.get_longitudinal_data(scenario_id)

    assert [(r[0], r[3]) for r in rows] == [(0.0, "Amont"), (200.0, "Aval")]

