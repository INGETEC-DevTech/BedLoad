import sqlite3

import pytest

from database.db_manager import DatabaseManager


def make_db(tmp_path) -> DatabaseManager:
    return DatabaseManager(db_path=tmp_path / "test.db")


def test_create_project_and_profile_round_trip(tmp_path):
    db = make_db(tmp_path)

    project_id = db.create_project("Rivière Test")
    profile_id = db.create_or_get_profile(project_id, "Pont de la Gare", 125.4)

    projects = db.get_all_projects()
    assert projects == [
        {"id": project_id, "name": "Rivière Test",
         "profiles": [{"id": profile_id, "name": "Pont de la Gare", "distance": 125.4}]}
    ]


def test_create_or_get_profile_returns_existing_id_by_name(tmp_path):
    """Une deuxième création avec le même nom ne recrée pas de profil : elle renvoie
    l'existant sans toucher à sa distance."""
    db = make_db(tmp_path)
    project_id = db.create_project("P")

    first_id = db.create_or_get_profile(project_id, "Amont", 0.0)
    second_id = db.create_or_get_profile(project_id, "Amont", 999.0)

    assert first_id == second_id
    profiles = db.get_all_projects()[0]["profiles"]
    assert profiles == [{"id": first_id, "name": "Amont", "distance": 0.0}]


def test_profile_name_must_be_unique_per_project(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    profile_id = db.create_or_get_profile(project_id, "Amont", 0.0)

    with pytest.raises(ValueError):
        db.rename_profile(
            db.create_or_get_profile(project_id, "Aval", 100.0),
            "Amont", 200.0,
        )


def test_profile_distance_must_be_unique_per_project(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    db.create_or_get_profile(project_id, "Amont", 0.0)

    with pytest.raises(ValueError):
        db.create_or_get_profile(project_id, "Autre nom", 0.0)


def test_same_name_or_distance_allowed_across_different_projects(tmp_path):
    """L'unicité (nom, distance) est par projet, pas globale."""
    db = make_db(tmp_path)
    project_a = db.create_project("A")
    project_b = db.create_project("B")

    db.create_or_get_profile(project_a, "Amont", 0.0)
    # Même nom ET même distance, mais dans un autre projet : doit passer.
    db.create_or_get_profile(project_b, "Amont", 0.0)

    assert len(db.get_all_projects()[0]["profiles"]) == 1
    assert len(db.get_all_projects()[1]["profiles"]) == 1


def test_profiles_sorted_by_distance_not_creation_order(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    db.create_or_get_profile(project_id, "C", 300.0)
    db.create_or_get_profile(project_id, "A", 100.0)
    db.create_or_get_profile(project_id, "B", 200.0)

    names = [p["name"] for p in db.get_all_projects()[0]["profiles"]]
    assert names == ["A", "B", "C"]


def test_hard_points_default_to_none_then_round_trip(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("P")

    assert db.get_hard_points(project_id) == {
        "upstream": {"name": None, "x": None, "z": None},
        "downstream": {"name": None, "x": None, "z": None},
    }

    db.set_hard_points(project_id, "Pont Amont", 0.0, 100.0, "Pont Aval", 500.0, 90.0)

    assert db.get_hard_points(project_id) == {
        "upstream": {"name": "Pont Amont", "x": 0.0, "z": 100.0},
        "downstream": {"name": "Pont Aval", "x": 500.0, "z": 90.0},
    }


def test_duplicate_project_copies_hard_points_and_profiles(tmp_path):
    db = make_db(tmp_path)
    project_id = db.create_project("Original")
    db.set_hard_points(project_id, "Pont Amont", 0.0, 100.0, "Pont Aval", 500.0, 90.0)
    db.create_or_get_profile(project_id, "Amont", 0.0)

    new_project_id = db.duplicate_project(project_id, "Copie")

    assert db.get_hard_points(new_project_id) == db.get_hard_points(project_id)
    new_profiles = [p["name"] for p in db.get_all_projects()[1]["profiles"]]
    assert new_profiles == ["Amont"]


def test_get_longitudinal_data_uses_distance_and_ignores_nothing(tmp_path):
    """Contrairement à l'ancien pk_name (texte, parfois non numérique et alors ignoré),
    `distance` est une colonne numérique NOT NULL : aucun profil n'est écarté."""
    db = make_db(tmp_path)
    project_id = db.create_project("P")
    db.create_or_get_profile(project_id, "Nom quelconque", 200.0)
    db.create_or_get_profile(project_id, "Autre nom", 100.0)

    rows = db.get_longitudinal_data(project_id)

    assert [r[0] for r in rows] == [100.0, 200.0]


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
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path)

    db = DatabaseManager(db_path=db_path)

    profiles = {p["id"]: p for p in db.get_all_projects()[0]["profiles"]}
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
    new_id = db.create_or_get_profile(1, "Nouveau", 50.0)

    assert new_id > 9


def test_migration_adds_hard_point_columns_to_existing_projects_table(tmp_path):
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path)

    db = DatabaseManager(db_path=db_path)

    assert db.get_hard_points(1) == {
        "upstream": {"name": None, "x": None, "z": None},
        "downstream": {"name": None, "x": None, "z": None},
    }
