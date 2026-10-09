import pytest

from core.controller import ProfileController
from viz.figures import build_longitudinal_figure
from core.earthworks import compute_earthworks
from core.geometry import build_project_cross_section
from core.longitudinal import build_longitudinal_profile, LongitudinalProfile
from core.models import CrossSection as _Section, Point as _Point
from viz.plots import plot_longitudinal_profile, CUT_COLOR, HARD_POINT_COLOR, PROJECT_HARD_POINT_COLOR

POINTS = [
    {"name": "A", "pk": 1000.0, "z": 50.0},
    {"name": "B", "pk": 1200.0, "z": 46.0},
    {"name": "C", "pk": 1400.0, "z": 45.0},
]


def _trace(fig, name):
    return next((t for t in fig.data if t.name == name), None)


def test_plot_longitudinal_profile_without_hard_points_has_no_hard_point_trace():
    fig = plot_longitudinal_profile(LongitudinalProfile(pk_existing=[0.0], z_existing=[10.0]))

    for kind in ("existants", "projet"):
        assert _trace(fig, f"Points durs {kind}") is None
        assert _trace(fig, f"Tronçons entre points durs {kind}") is None
    assert not fig.layout.annotations


def test_plot_longitudinal_profile_draws_every_hard_point_and_segment_slopes_in_m_per_m():
    fig = plot_longitudinal_profile(build_longitudinal_profile([(100.0, 48.0, 47.5)], POINTS))

    points = _trace(fig, "Points durs existants")
    assert list(points.x) == [0.0, 200.0, 400.0] and list(points.y) == [50.0, 46.0, 45.0]
    assert list(points.text) == ["A", "B", "C"]
    assert points.marker.color == HARD_POINT_COLOR
    assert list(_trace(fig, "Tronçons entre points durs existants").x) == [0.0, 200.0, 400.0]
    slopes = [a for a in fig.layout.annotations if a.text.startswith("I = ")]
    assert [a.text for a in slopes] == ["I = 0.0200 m/m", "I = 0.0050 m/m"]
    assert [a.x for a in slopes] == [100.0, 300.0]


def test_single_hard_point_is_drawn_without_segment():
    fig = plot_longitudinal_profile(build_longitudinal_profile([], POINTS[:1]))

    assert list(_trace(fig, "Points durs existants").x) == [0.0]
    assert _trace(fig, "Tronçons entre points durs existants") is None
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



def test_every_chart_pans_by_default_and_has_a_minor_grid():
    """Glisser déplace la vue (pas de zoom au cadre par défaut), et une grille secondaire
    s'ajoute à la principale, sur les profils en travers comme sur le profil en long."""
    from core.models import CrossSection, Point
    from viz.plots import plot_single_profile
    cross = plot_single_profile(CrossSection("s", [Point(x=0, z=1), Point(x=1, z=0)]))
    longitudinal = plot_longitudinal_profile(LongitudinalProfile(pk_existing=[0.0], z_existing=[10.0]))

    for fig in (cross, longitudinal):
        assert fig.layout.dragmode == "pan"
        for axis in (fig.layout.xaxis, fig.layout.yaxis):
            assert axis.showgrid and axis.minor.showgrid
            assert axis.minor.nticks == 2  # une seule ligne fine entre deux principales


# --- Déblai / remblai de chaque profil sur le profil en long ---

EXISTING = [{"X (m)": x, "Z (m NGF)": z} for x, z in [(-5, 52), (0, 49), (5, 48), (10, 49), (20, 52)]]


def _states():
    return [
        {"name": "Amont", "distance": 0.0, "existing_data": EXISTING, "project_params": {"anchor_z": 48.5}},
        {"name": "Milieu", "distance": 50.0, "existing_data": EXISTING, "project_params": {"anchor_z": 47.0}},
        {"name": "Aval", "distance": 100.0, "existing_data": EXISTING, "project_params": {}},
    ]


def test_station_earthworks_match_the_cross_section_computation():
    controller = ProfileController()
    stations = controller.station_earthworks(_states())

    existing = _Section("Existant", [_Point(x=p["X (m)"], z=p["Z (m NGF)"]) for p in EXISTING])
    for station, anchor_z in zip(stations[:2], (48.5, 47.0)):
        params = controller.to_project_parameters({**controller.default_project_params(), "anchor_z": anchor_z})
        expected = compute_earthworks(existing, build_project_cross_section(params, name="Projet"))
        assert station.computed
        assert station.cut == pytest.approx(expected.cut_total)
        assert station.fill == pytest.approx(expected.fill_total)
    assert not stations[2].computed and stations[2].note == "profil projet non renseigné"


def test_station_without_existing_points_is_not_computed():
    station, = ProfileController().station_earthworks(
        [{"name": None, "distance": 30.0, "existing_data": [], "project_params": {"anchor_z": 1.0}}])
    assert not station.computed and station.note == "profil existant incomplet"
    assert station.name == "30 m"


def _earthworks_traces(fig):
    return [t for t in fig.data if t.legendgroup == "earthworks"]


def test_longitudinal_shows_each_profile_earthworks_on_hover_and_the_scenario_sum_in_the_legend():
    controller = ProfileController()
    stations = controller.station_earthworks(_states())
    rows = [(0.0, 48.0, 48.5, "Amont"), (50.0, 48.0, 47.0, "Milieu"), (100.0, 48.0, None, "Aval")]

    fig = build_longitudinal_figure(rows, None, stations)

    hover, cut_entry, fill_entry, balance_entry = _earthworks_traces(fig)
    # Info-bulles : marqueurs invisibles, hors légende.
    assert list(hover.x) == [0.0, 50.0, 100.0]
    assert hover.marker.opacity == 0 and hover.showlegend is False
    assert f"déblai {stations[1].cut:.2f} m²" in hover.text[1]
    assert "non calculé (profil projet non renseigné)" in hover.text[2]

    # Légende : un groupe titré, une entrée par grandeur.
    cut = stations[0].cut + stations[1].cut
    fill = stations[0].fill + stations[1].fill
    title = cut_entry.legendgrouptitle.text
    assert "Déblais / remblais du scénario" in title and "2 profils calculés sur 3" in title
    assert cut_entry.name == f"Déblai : <b>{cut:.2f} m²</b>"
    assert cut_entry.marker.color == CUT_COLOR
    assert fill_entry.name == f"Remblai : <b>{fill:.2f} m²</b>"
    assert balance_entry.name.startswith(f"Bilan : <b>{cut - fill:+.2f} m²</b>")


def test_longitudinal_legend_sits_on_the_chart_top_right_over_a_see_through_background():
    """Posée sur la zone de tracé (coordonnées entre 0 et 1), coin supérieur droit, au lieu
    d'occuper une bande à droite ; encadrée, sur un fond blanc semi-transparent."""
    legend = plot_longitudinal_profile(LongitudinalProfile(pk_existing=[0.0], z_existing=[10.0])).layout.legend
    assert legend.orientation == "v" and legend.borderwidth == 1
    assert 0 < legend.x <= 1 and legend.xanchor == "right"
    assert 0 < legend.y <= 1 and legend.yanchor == "top"
    alpha = float(legend.bgcolor.rstrip(")").split(",")[-1])
    assert legend.bgcolor.startswith("rgba(255, 255, 255,") and 0 < alpha < 1


def test_longitudinal_without_earthworks_has_no_earthworks_trace():
    fig = plot_longitudinal_profile(LongitudinalProfile(pk_existing=[0.0], z_existing=[10.0]))
    assert not _earthworks_traces(fig)


def test_both_hard_point_families_are_drawn_distinctly_with_their_own_distance_zero():
    """Lit projet plus long (PK 2000 → 2500 pour PK 1000 → 1400) : chaque famille à sa
    propre distance 0, couleur, symbole et trait différents, avec ses pentes."""
    points = ([{**p, "family": "existing"} for p in POINTS]
              + [{"name": "A'", "pk": 2000.0, "z": 50.0, "family": "project"},
                 {"name": "C'", "pk": 2500.0, "z": 45.0, "family": "project"}])
    fig = plot_longitudinal_profile(build_longitudinal_profile([(100.0, 48.0, 47.5, "PK", 150.0)], points))

    existing, project = _trace(fig, "Points durs existants"), _trace(fig, "Points durs projet")
    assert list(project.x) == [0.0, 500.0] and list(project.text) == ["A'", "C'"]
    assert project.marker.color == PROJECT_HARD_POINT_COLOR != existing.marker.color
    assert project.marker.symbol != existing.marker.symbol
    assert (_trace(fig, "Tronçons entre points durs projet").line.dash
            != _trace(fig, "Tronçons entre points durs existants").line.dash)
    project_slopes = [a.text for a in fig.layout.annotations
                      if a.text.startswith("I = ") and a.font.color == PROJECT_HARD_POINT_COLOR]
    assert project_slopes == ["I = 0.0100 m/m"]
    # Terrain existant à la distance existante, fond projet à la distance projet.
    assert list(_trace(fig, "TN existant (thalweg)").x) == [100.0]
    assert list(_trace(fig, "Projet (fond de lit)").x) == [150.0]
