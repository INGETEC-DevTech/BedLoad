import pytest

from core.longitudinal import build_longitudinal_profile, longitudinal_table, HardPointMarker


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
    assert profile.hard_points == [] and profile.segments == []


def test_hard_points_absent_by_default():
    profile = build_longitudinal_profile([(0.0, 1.0, 1.0)], hard_points=None)

    assert profile.hard_points == [] and profile.segments == []


def test_all_hard_points_are_positioned_from_the_first_one_with_segment_slopes():
    hard_points = [
        {"name": "C", "pk": 1400.0, "z": 45.0},
        {"name": "A", "pk": 1000.0, "z": 50.0},
        {"name": "B", "pk": 1200.0, "z": 46.0},
    ]

    profile = build_longitudinal_profile([], hard_points=hard_points)

    assert [(m.name, m.distance, m.z) for m in profile.hard_points] == [
        ("A", 0.0, 50.0), ("B", 200.0, 46.0), ("C", 400.0, 45.0)
    ]
    assert [(s.start.name, s.end.name) for s in profile.segments] == [("A", "B"), ("B", "C")]
    assert [s.slope for s in profile.segments] == [pytest.approx(0.02), pytest.approx(0.005)]


def test_incomplete_hard_points_are_not_positioned():
    hard_points = [
        {"name": "A", "pk": 0.0, "z": 50.0},
        {"name": "Sans PK", "pk": None, "z": 48.0},
        {"name": "Sans Z", "pk": 50.0, "z": None},
        {"name": "B", "pk": 100.0, "z": 49.0},
    ]

    profile = build_longitudinal_profile([], hard_points=hard_points)

    assert [m.name for m in profile.hard_points] == ["A", "B"]
    assert len(profile.segments) == 1


def test_hard_point_without_name_gets_a_generic_label():
    profile = build_longitudinal_profile([], hard_points=[{"name": None, "pk": 0.0, "z": 50.0}])

    assert profile.hard_points[0].name == "Point dur 1"
    assert profile.segments == []


def test_stations_keep_every_profile_name_even_without_values():
    rows = [(0.0, 10.0, None, "Amont"), (50.0, None, None, "Vide"), (100.0, 9.0, 8.5, None)]

    profile = build_longitudinal_profile(rows)

    assert profile.stations == [(0.0, "Amont"), (50.0, "Vide"), (100.0, "100 m")]
    assert profile.names_existing == ["Amont", "100 m"]
    assert profile.names_project == ["100 m"]


# --- Tableau du profil en long (export Excel) ---

TABLE_HARD_POINTS = [{"name": "Pont", "pk": 1000.0, "z": 50.0}, {"name": "Seuil", "pk": 1150.0, "z": 48.0},
                     {"name": None, "pk": 1300.0, "z": 46.5}]
TABLE_ROWS = [(150.0, 47.9, 47.6, "PK 150"), (0.0, 49.8, None, "Amont"),
              (80.0, None, 48.4, "PK 80"), (300.0, None, None, "Aval")]


def test_table_interleaves_profiles_and_hard_points_by_distance():
    """Une ligne par profil et par point dur, triées par distance ; à distance égale, le
    point dur d'abord ; une cote absente vaut None."""
    table = longitudinal_table(build_longitudinal_profile(TABLE_ROWS, TABLE_HARD_POINTS))

    assert [(r.name, r.distance, r.z_existing, r.z_project, r.z_hard_point) for r in table] == [
        ("Pont", 0.0, None, None, 50.0),
        ("Amont", 0.0, 49.8, None, None),
        ("PK 80", 80.0, None, 48.4, None),
        ("Seuil", 150.0, None, None, 48.0),
        ("PK 150", 150.0, 47.9, 47.6, None),
        ("Point dur 3", 300.0, None, None, 46.5),
        ("Aval", 300.0, None, None, None),
    ]


def test_table_values_are_exactly_those_of_the_chart():
    from viz.plots import plot_longitudinal_profile
    profile = build_longitudinal_profile(TABLE_ROWS, TABLE_HARD_POINTS)
    traces = {t.name: t for t in plot_longitudinal_profile(profile).data}
    table = longitudinal_table(profile)

    def plotted(column):
        return sorted((r.distance, getattr(r, column)) for r in table if getattr(r, column) is not None)

    for column, trace in (("z_existing", "TN existant (thalweg)"), ("z_project", "Projet (fond de lit)"),
                          ("z_hard_point", "Points durs")):
        assert plotted(column) == sorted(zip(traces[trace].x, traces[trace].y))
