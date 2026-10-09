import pytest

from core.earthworks import CUT, FILL, compute_earthworks
from core.models import CrossSection, Point


def section(*xz):
    return CrossSection(name="s", points=[Point(x=x, z=z) for x, z in xz])


def test_flat_ground_and_trapezoidal_bed_gives_one_cut_zone():
    """Terrain plat à z=2, lit trapézoïdal creusé de 2 m (fond de x=1 à x=4, talus 1/2) :
    une seule zone de déblai, le trapèze (3 + 5) / 2 * 2 = 8 m²."""
    existing = section((0, 2), (5, 2))
    project = section((0, 2), (1, 0), (4, 0), (5, 2))

    res = compute_earthworks(existing, project)

    assert [(z.kind, z.name) for z in res.zones] == [(CUT, "D1")]
    assert res.zones[0].area == pytest.approx(8.0)
    assert (res.zones[0].x_start, res.zones[0].x_end) == pytest.approx((0.0, 5.0))
    assert res.cut_total == pytest.approx(8.0) and res.fill_total == 0
    assert res.balance == pytest.approx(8.0)


def test_crossing_profiles_split_into_cut_and_fill_zones_at_the_intersection():
    """Terrain incliné de z=1 à z=-1 sur 4 m, projet plat à z=0 : déblai triangulaire à
    gauche (1 m²), remblai triangulaire à droite (1 m²), séparés au croisement x=2."""
    existing = section((0, 1), (4, -1))
    project = section((0, 0), (4, 0))

    res = compute_earthworks(existing, project)

    assert [(z.name, z.kind) for z in res.zones] == [("D1", CUT), ("R1", FILL)]
    assert [z.area for z in res.zones] == [pytest.approx(1.0), pytest.approx(1.0)]
    assert res.zones[0].x_end == pytest.approx(2.0) and res.zones[1].x_start == pytest.approx(2.0)
    assert res.balance == pytest.approx(0.0)


def test_zones_are_numbered_left_to_right_per_kind():
    """Terrain en dents de scie autour d'un projet plat : D1, R1, D2, R2."""
    existing = section((0, 1), (1, -1), (2, 1), (3, -1))
    project = section((0, 0), (3, 0))

    res = compute_earthworks(existing, project)

    assert [z.name for z in res.zones] == ["D1", "R1", "D2", "R2"]
    # Chaque dent : deux triangles de base 0.5 et hauteur 1 de part et d'autre du croisement.
    assert res.cut_total == pytest.approx(0.25 + 0.5)
    assert res.fill_total == pytest.approx(0.5 + 0.25)


def test_only_the_common_extent_is_counted():
    """Projet plus large que le terrain levé : seule l'emprise commune [2, 6] est calculée."""
    existing = section((2, 1), (6, 1))
    project = section((0, 0), (10, 0))

    res = compute_earthworks(existing, project)

    assert res.extent == pytest.approx((2.0, 6.0))
    assert res.cut_total == pytest.approx(4.0)


def test_vertical_step_in_a_profile_switches_zone_without_a_crossing():
    """Le projet saute verticalement de z=-1 à z=1 en x=2 (deux points de même X) :
    déblai de 2 m² à gauche, remblai de 2 m² à droite, sans croisement des courbes."""
    existing = section((0, 0), (4, 0))
    project = section((0, -1), (2, -1), (2, 1), (4, 1))

    res = compute_earthworks(existing, project)

    assert [(z.name, round(z.area, 9)) for z in res.zones] == [("D1", 2.0), ("R1", 2.0)]


def test_identical_profiles_and_disjoint_profiles_give_no_zone():
    same = section((0, 0), (1, 1), (2, 0))
    assert compute_earthworks(same, section((0, 0), (1, 1), (2, 0))).zones == []

    disjoint = compute_earthworks(section((0, 0), (1, 0)), section((5, 0), (6, 0)))
    assert disjoint.zones == [] and disjoint.extent is None


def test_zone_outline_is_closed_and_follows_both_profiles():
    existing = section((0, 2), (5, 2))
    project = section((0, 2), (1, 0), (4, 0), (5, 2))

    zone = compute_earthworks(existing, project).zones[0]

    assert (zone.outline_x[0], zone.outline_z[0]) == (zone.outline_x[-1], zone.outline_z[-1])
    assert set(zip(zone.outline_x, zone.outline_z)) >= {(0, 2), (1, 0), (4, 0), (5, 2)}


# --- Graphique de l'onglet Profil projet ---

def _project_figure(existing_points, show_overlay=True):
    from viz.figures import ViewMode, build_figure
    from core.models import ProjectParameters
    params = vars(ProjectParameters(anchor_x=4.0, anchor_z=10.0, bed_width=2.0, bed_depth=0.5))
    return build_figure(existing_points, params, ViewMode.PROJECT, show_overlay=show_overlay)


FLAT_GROUND = [{"X (m)": -5.0, "Z (m NGF)": 11.0}, {"X (m)": 20.0, "Z (m NGF)": 11.0}]


def test_overlay_figure_shows_zones_and_totals():
    fig = _project_figure(FLAT_GROUND)

    # Lit creusé sous le terrain (déblai), hauts de berge du projet au-dessus (remblais).
    fills = [t for t in fig.data if t.fill == "toself"]
    assert {t.legendgroup for t in fills} == {CUT, FILL}
    assert sorted(t.legendgroup for t in fills if t.showlegend) == sorted([CUT, FILL])  # une entrée par type
    # Les zones sont tracées sous les deux profils.
    assert all(t.fill == "toself" for t in fig.data[:len(fills)])
    summary = fig.layout.annotations[-1].text
    assert "Déblai (à enlever)" in summary and "Bilan" in summary
    assert any("D1" in a.text for a in fig.layout.annotations)


def test_no_earthworks_without_overlay_or_without_existing_points():
    no_overlay = _project_figure(FLAT_GROUND, show_overlay=False)
    no_existing = _project_figure([])

    for fig in (no_overlay, no_existing):
        assert not [t for t in fig.data if t.fill == "toself"]
        assert not any("Terrassements" in (a.text or "") for a in fig.layout.annotations)
