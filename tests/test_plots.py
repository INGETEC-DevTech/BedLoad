from core.longitudinal import build_longitudinal_profile, LongitudinalProfile
from viz.plots import plot_longitudinal_profile, HARD_POINT_COLOR

POINTS = [
    {"name": "A", "pk": 1000.0, "z": 50.0},
    {"name": "B", "pk": 1200.0, "z": 46.0},
    {"name": "C", "pk": 1400.0, "z": 45.0},
]


def _trace(fig, name):
    return next((t for t in fig.data if t.name == name), None)


def test_plot_longitudinal_profile_without_hard_points_has_no_hard_point_trace():
    fig = plot_longitudinal_profile(LongitudinalProfile(pk_existing=[0.0], z_existing=[10.0]))

    assert _trace(fig, "Points durs") is None and _trace(fig, "Tronçons entre points durs") is None
    assert not fig.layout.annotations


def test_plot_longitudinal_profile_draws_every_hard_point_and_segment_slopes_in_m_per_m():
    fig = plot_longitudinal_profile(build_longitudinal_profile([(100.0, 48.0, 47.5)], POINTS))

    points = _trace(fig, "Points durs")
    assert list(points.x) == [0.0, 200.0, 400.0] and list(points.y) == [50.0, 46.0, 45.0]
    assert list(points.text) == ["A", "B", "C"]
    assert points.marker.color == HARD_POINT_COLOR
    assert list(_trace(fig, "Tronçons entre points durs").x) == [0.0, 200.0, 400.0]
    slopes = [a for a in fig.layout.annotations if a.text.startswith("I = ")]
    assert [a.text for a in slopes] == ["I = 0.0200 m/m", "I = 0.0050 m/m"]
    assert [a.x for a in slopes] == [100.0, 300.0]


def test_single_hard_point_is_drawn_without_segment():
    fig = plot_longitudinal_profile(build_longitudinal_profile([], POINTS[:1]))

    assert list(_trace(fig, "Points durs").x) == [0.0]
    assert _trace(fig, "Tronçons entre points durs") is None
    assert not [a for a in fig.layout.annotations if a.text.startswith("I = ")]


def test_cross_section_names_are_shown_at_their_distance():
    rows = [(100.0, 48.0, 47.5, "PK 1100"), (250.0, None, 46.0, "Seuil aval"), (300.0, None, None, "Vide")]

    fig = plot_longitudinal_profile(build_longitudinal_profile(rows, POINTS))

    names = [(a.x, a.text) for a in fig.layout.annotations if a.textangle == -90]
    assert names == [(100.0, "PK 1100"), (250.0, "Seuil aval"), (300.0, "Vide")]
    assert sorted(sh.x0 for sh in fig.layout.shapes if sh.type == "line") == [100.0, 250.0, 300.0]
    # Au survol, chaque point porte le nom de son profil.
    assert list(_trace(fig, "TN existant (thalweg)").text) == ["PK 1100"]
    assert list(_trace(fig, "Projet (fond de lit)").text) == ["PK 1100", "Seuil aval"]

