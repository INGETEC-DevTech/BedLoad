from core.longitudinal import build_longitudinal_profile, HardPointMarker


def test_build_longitudinal_profile_splits_both_series():
    rows = [
        (0.0, 10.0, 9.5),
        (100.0, 8.0, 7.6),
        (200.0, 6.0, 5.9),
    ]

    profile = build_longitudinal_profile(rows)

    assert profile.pk_existing == [0.0, 100.0, 200.0]
    assert profile.z_existing == [10.0, 8.0, 6.0]
    assert profile.pk_project == [0.0, 100.0, 200.0]
    assert profile.z_project == [9.5, 7.6, 5.9]


def test_build_longitudinal_profile_skips_missing_values_independently():
    """Un profil sans points existants ou sans paramètres projet enregistrés ne doit
    manquer que dans la série concernée, pas disparaître des deux (vue de contrôle,
    pas de source de vérité unique entre les deux séries)."""
    rows = [
        (0.0, 10.0, None),   # pas encore de paramètres projet
        (50.0, None, 8.0),   # pas encore de points existants
        (100.0, 6.0, 5.5),
    ]

    profile = build_longitudinal_profile(rows)

    assert profile.pk_existing == [0.0, 100.0]
    assert profile.z_existing == [10.0, 6.0]
    assert profile.pk_project == [50.0, 100.0]
    assert profile.z_project == [8.0, 5.5]


def test_build_longitudinal_profile_empty_rows_returns_empty_series():
    profile = build_longitudinal_profile([])

    assert profile.pk_existing == []
    assert profile.z_existing == []
    assert profile.pk_project == []
    assert profile.z_project == []
    assert profile.hard_point_upstream is None
    assert profile.hard_point_downstream is None


def test_hard_points_absent_by_default():
    """Sans argument hard_points (ou avec None), le comportement est inchangé : aucun
    point dur positionné."""
    profile = build_longitudinal_profile([(0.0, 1.0, 1.0)], hard_points=None)

    assert profile.hard_point_upstream is None
    assert profile.hard_point_downstream is None


def test_hard_points_fully_specified_are_positioned_correctly():
    """Amont toujours à distance 0 ; aval à (X_aval - X_amont), chacun à son propre Z."""
    hard_points = {
        "upstream": {"name": "Pont Amont", "x": 10.0, "z": 100.0},
        "downstream": {"name": "Pont Aval", "x": 510.0, "z": 90.0},
    }

    profile = build_longitudinal_profile([], hard_points=hard_points)

    assert profile.hard_point_upstream == HardPointMarker(distance=0.0, z=100.0, name="Pont Amont")
    assert profile.hard_point_downstream == HardPointMarker(distance=500.0, z=90.0, name="Pont Aval")


def test_hard_point_missing_name_falls_back_to_generic_label():
    hard_points = {
        "upstream": {"name": None, "x": 0.0, "z": 100.0},
        "downstream": {"name": None, "x": 500.0, "z": 90.0},
    }

    profile = build_longitudinal_profile([], hard_points=hard_points)

    assert profile.hard_point_upstream.name == "Point dur amont"
    assert profile.hard_point_downstream.name == "Point dur aval"


def test_hard_point_downstream_missing_upstream_x_is_not_positioned():
    """Le point dur aval a besoin des DEUX X (amont et aval) pour être positionné : si
    l'un des deux manque, on ne le place pas à une position arbitraire."""
    hard_points = {
        "upstream": {"name": "Amont", "x": None, "z": 100.0},
        "downstream": {"name": "Aval", "x": 500.0, "z": 90.0},
    }

    profile = build_longitudinal_profile([], hard_points=hard_points)

    # L'amont ne dépend que de son propre Z : il reste positionnable.
    assert profile.hard_point_upstream == HardPointMarker(distance=0.0, z=100.0, name="Amont")
    assert profile.hard_point_downstream is None


def test_hard_point_upstream_missing_z_is_not_positioned_but_downstream_can_be():
    """Le point dur amont a besoin de son propre Z ; le point dur aval n'en dépend pas
    (seulement des deux X et de son propre Z), les deux absences sont indépendantes."""
    hard_points = {
        "upstream": {"name": "Amont", "x": 10.0, "z": None},
        "downstream": {"name": "Aval", "x": 510.0, "z": 90.0},
    }

    profile = build_longitudinal_profile([], hard_points=hard_points)

    assert profile.hard_point_upstream is None
    assert profile.hard_point_downstream == HardPointMarker(distance=500.0, z=90.0, name="Aval")


def test_hard_points_empty_dict_values_treated_as_absent():
    """Format renvoyé par DatabaseManager.get_hard_points pour un projet sans aucun point
    dur renseigné : toutes les valeurs sont None, donc rien n'est positionné."""
    hard_points = {
        "upstream": {"name": None, "x": None, "z": None},
        "downstream": {"name": None, "x": None, "z": None},
    }

    profile = build_longitudinal_profile([], hard_points=hard_points)

    assert profile.hard_point_upstream is None
    assert profile.hard_point_downstream is None
