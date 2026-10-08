import math
from dataclasses import asdict, replace

import pandas as pd
import pytest

from core.hydraulics import (
    suggest_arm_split,
    clip_to_bounds,
    compute_hydraulic_params,
    find_water_level_for_discharge,
    get_wet_beds,
    overflow_level,
    resolve_hydraulic_result,
    subsection_dividers,
)


def get_water_intersections(section, water_z, bounds=None):
    """Bornes extrêmes (x gauche, x droite) de la zone mouillée, ou (None, None)."""
    beds = get_wet_beds(section, water_z, bounds)
    if not beds:
        return None, None
    return beds[0][0].x, beds[-1][-1].x
from core.models import CrossSection, Point, dataframe_to_points
from core.controller import format_discharge
from core.geometry import build_project_cross_section
from core.models import ProjectParameters


@pytest.fixture
def trapezoidal_section() -> CrossSection:
    """Canal trapézoïdal symétrique : fond plat de x=1 à x=4 (z=0), berges de pente 1:2
    (1 m horizontal pour 2 m vertical) remontant jusqu'à z=2 en x=0 et x=5."""
    return CrossSection(
        name="test",
        points=[
            Point(x=0, z=2),
            Point(x=1, z=0),
            Point(x=4, z=0),
            Point(x=5, z=2),
        ],
    )


def test_get_water_intersections_mid_bank(trapezoidal_section):
    """Pour une cote d'eau de 1 m, l'eau doit couper chaque berge à mi-hauteur (x=0.5 et x=4.5)."""
    x_left, x_right = get_water_intersections(trapezoidal_section, water_z=1.0)
    assert x_left == pytest.approx(0.5)
    assert x_right == pytest.approx(4.5)


def test_get_water_intersections_below_bed_returns_none(trapezoidal_section):
    """Une cote d'eau sous le fond du lit ne doit trouver aucune intersection."""
    x_left, x_right = get_water_intersections(trapezoidal_section, water_z=-1.0)
    assert x_left is None
    assert x_right is None


def test_get_water_intersections_above_banks_returns_none(trapezoidal_section):
    """Une cote d'eau au-dessus du sommet des berges ne doit trouver aucune intersection
    (la fonction ne gère pas le débordement, cf. audit)."""
    x_left, x_right = get_water_intersections(trapezoidal_section, water_z=3.0)
    assert x_left is None
    assert x_right is None


def test_compute_hydraulic_params_matches_hand_calculation(trapezoidal_section):
    """Vérifie S, P, Rh contre un calcul géométrique manuel pour une cote d'eau de 1 m :
    S = aire du trapèze (largeur fond 3 m, largeur miroir 4 m, hauteur 1 m) = 3.5 m².
    P = 2 * sqrt(0.5^2 + 1^2) + 3 = somme des longueurs mouillées des 2 berges + du fond.
    """
    res = compute_hydraulic_params(trapezoidal_section, water_z=1.0, slope=0.001, ks=30.0)

    expected_s = 3.5
    expected_p = 2 * math.sqrt(0.5**2 + 1.0**2) + 3.0
    expected_rh = expected_s / expected_p
    expected_v = 30.0 * expected_rh ** (2 / 3) * math.sqrt(0.001)
    expected_q = expected_v * expected_s

    assert res["S"] == pytest.approx(expected_s)
    assert res["P"] == pytest.approx(expected_p)
    assert res["Rh"] == pytest.approx(expected_rh)
    assert res["V"] == pytest.approx(expected_v)
    assert res["Q"] == pytest.approx(expected_q)
    assert res["x_left"] == pytest.approx(0.5)
    assert res["x_right"] == pytest.approx(4.5)


@pytest.mark.parametrize("slope,ks", [(0.0, 30.0), (-0.001, 30.0), (0.001, 0.0), (0.001, -5.0)])
def test_compute_hydraulic_params_invalid_slope_or_ks_returns_zeros(trapezoidal_section, slope, ks):
    """Une pente ou un coefficient de Strickler nul ou négatif doit renvoyer un résultat neutre,
    et ne jamais lever d'exception (division par zéro potentielle sinon). Seule la ligne
    d'eau (water_intervals) reste fournie : la cote d'eau, elle, est connue."""
    res = compute_hydraulic_params(trapezoidal_section, water_z=1.0, slope=slope, ks=ks)

    assert res == {
        "S": 0, "P": 0, "Rh": 0, "V": 0, "Q": 0,
        "water_z": 1.0, "x_left": None, "x_right": None, "wet_intervals": [], "bed_discharges": [],
        "subsections": [], "overflow_sides": [], "water_intervals": [(0.5, 4.5)],
    }


def test_compute_hydraulic_params_no_intersection_returns_zeros(trapezoidal_section):
    """Si la cote d'eau ne coupe pas le profil (ex: sous le fond du lit), le résultat doit rester neutre."""
    res = compute_hydraulic_params(trapezoidal_section, water_z=-1.0, slope=0.001, ks=30.0)
    assert res["S"] == 0
    assert res["Q"] == 0


def test_find_water_level_for_discharge_converges_to_known_level(trapezoidal_section):
    """En injectant le débit calculé pour z=1 m, la dichotomie doit retrouver une cote d'eau proche de 1 m."""
    target = compute_hydraulic_params(trapezoidal_section, water_z=1.0, slope=0.001, ks=30.0)["Q"]

    res = find_water_level_for_discharge(trapezoidal_section, target_q=target, slope=0.001, ks=30.0)

    assert res["water_z"] == pytest.approx(1.0, abs=1e-3)
    assert res["Q"] == pytest.approx(target, rel=1e-3)


def test_find_water_level_for_discharge_unreachable_target_stops_at_bank_top(trapezoidal_section):
    """Documente le comportement actuel (cf. audit) : si le débit cible dépasse la capacité du profil,
    la fonction s'arrête silencieusement à la cote la plus haute du profil (z=2) sans avertir l'appelant.
    Le débit à cette cote doit rester celui, non nul, du plein bord (cf. fix de l'intervalle fermé
    dans get_water_intersections : ce n'est plus 0 par simple effet de bord de comparaison stricte)."""
    res = find_water_level_for_discharge(trapezoidal_section, target_q=1e9, slope=0.001, ks=30.0)

    z_max = max(p.z for p in trapezoidal_section.points)
    assert res["water_z"] == pytest.approx(z_max)
    assert res["Q"] < 1e9
    assert res["Q"] > 0


def test_get_water_intersections_exact_top_of_profile_is_valid():
    """Cf. audit : quand le niveau d'eau testé est exactement égal au point le plus haut du
    profil, la comparaison stricte ("<" au lieu de "<=") faisait perdre l'intersection côté
    du sommet atteint, et le débit retombait à 0 alors qu'un débit de plein bord est
    calculable à ce niveau."""
    section = CrossSection(
        name="test",
        points=[Point(x=0, z=2), Point(x=1, z=0), Point(x=4, z=0), Point(x=5, z=2)],
    )

    x_left, x_right = get_water_intersections(section, water_z=2.0)

    assert x_left == pytest.approx(0.0)
    assert x_right == pytest.approx(5.0)


def test_compute_hydraulic_params_at_exact_top_returns_nonzero_discharge(trapezoidal_section):
    z_max = max(p.z for p in trapezoidal_section.points)

    res = compute_hydraulic_params(trapezoidal_section, water_z=z_max, slope=0.001, ks=30.0)

    assert res["S"] == pytest.approx(8.0)  # trapèze : (largeur fond 3 + largeur miroir 5) / 2 * hauteur 2
    assert res["Q"] > 0


def test_get_water_intersections_handles_horizontal_shelf_at_water_level():
    """Un profil avec un palier horizontal exactement à la cote d'eau testée (plusieurs
    sommets à la même altitude, de part et d'autre d'un creux) ne doit ni planter (division
    par zéro sur le segment horizontal) ni élargir la largeur mouillée au-delà des bords
    réels du creux. Le palier lui-même (profondeur nulle) n'est pas mouillé : le lit
    commence à x=2, là où le terrain passe sous l'eau."""
    section = CrossSection(
        name="test",
        points=[
            Point(x=0, z=2),
            Point(x=1, z=1),
            Point(x=2, z=1),  # palier horizontal à z=1
            Point(x=3, z=0),
            Point(x=4, z=1),  # symétrique côté droit
            Point(x=5, z=2),
        ],
    )

    x_left, x_right = get_water_intersections(section, water_z=1.0)

    assert x_left == pytest.approx(2.0)
    assert x_right == pytest.approx(4.0)


# --- Plusieurs lits dans le même profil ---

@pytest.fixture
def two_beds_section() -> CrossSection:
    """Deux lits trapézoïdaux identiques séparés par un merlon : lit A de x=0 à x=5, merlon
    culminant à z=3 en x=6, lit B de x=7 à x=12. Les berges extérieures montent à z=2."""
    return CrossSection(
        name="test",
        points=[
            Point(x=0, z=2), Point(x=1, z=0), Point(x=4, z=0), Point(x=5, z=2),
            Point(x=6, z=3),
            Point(x=7, z=2), Point(x=8, z=0), Point(x=11, z=0), Point(x=12, z=2),
        ],
    )


def test_water_line_stops_at_the_emerging_bank_and_restarts_in_the_second_bed(two_beds_section):
    res = compute_hydraulic_params(two_beds_section, water_z=1.0, slope=0.001, ks=30.0)

    assert res["wet_intervals"] == [pytest.approx((0.5, 4.5)), pytest.approx((7.5, 11.5))]
    assert (res["x_left"], res["x_right"]) == pytest.approx((0.5, 11.5))


def test_two_identical_beds_carry_twice_the_flow_of_one(two_beds_section, trapezoidal_section):
    """Le merlon émergé n'entre ni dans la surface ni dans le périmètre : chaque lit garde
    son propre rayon hydraulique, donc deux lits identiques = exactement deux fois un lit."""
    one = compute_hydraulic_params(trapezoidal_section, water_z=1.0, slope=0.001, ks=30.0)
    two = compute_hydraulic_params(two_beds_section, water_z=1.0, slope=0.001, ks=30.0)

    assert two["S"] == pytest.approx(2 * one["S"])
    assert two["P"] == pytest.approx(2 * one["P"])
    assert two["Q"] == pytest.approx(2 * one["Q"])
    assert two["V"] == pytest.approx(one["V"])


def test_bounds_restrict_the_calculation_to_one_bed(two_beds_section, trapezoidal_section):
    one = compute_hydraulic_params(trapezoidal_section, water_z=1.0, slope=0.001, ks=30.0)

    res = compute_hydraulic_params(two_beds_section, water_z=1.0, slope=0.001, ks=30.0, bounds=(6.0, 20.0))

    assert res["wet_intervals"] == [pytest.approx((7.5, 11.5))]
    assert res["Q"] == pytest.approx(one["Q"])


def test_bound_inside_the_water_acts_as_a_wall_not_counted_in_perimeter(trapezoidal_section):
    """Limite droite au milieu du fond (x=2.5) : l'eau s'arrête sur la paroi fictive. La
    surface est la moitié gauche du trapèze, le périmètre ne compte que le terrain mouillé."""
    res = compute_hydraulic_params(trapezoidal_section, water_z=1.0, slope=0.001, ks=30.0, bounds=(-10.0, 2.5))

    assert res["wet_intervals"] == [pytest.approx((0.5, 2.5))]
    assert res["S"] == pytest.approx(3.5 / 2)
    assert res["P"] == pytest.approx(math.sqrt(0.5**2 + 1.0**2) + 1.5)


def test_bounds_outside_the_profile_change_nothing(two_beds_section):
    free = compute_hydraulic_params(two_beds_section, water_z=1.0, slope=0.001, ks=30.0)
    wide = compute_hydraulic_params(two_beds_section, water_z=1.0, slope=0.001, ks=30.0, bounds=(-100.0, 100.0))

    assert wide == free


def test_bounds_not_overlapping_the_profile_give_no_water(two_beds_section):
    res = compute_hydraulic_params(two_beds_section, water_z=1.0, slope=0.001, ks=30.0, bounds=(50.0, 60.0))

    assert res["Q"] == 0 and res["wet_intervals"] == []
    assert find_water_level_for_discharge(two_beds_section, 5.0, 0.001, 30.0, bounds=(50.0, 60.0))["Q"] == 0


def test_clip_to_bounds_interpolates_the_terrain_on_each_bound(trapezoidal_section):
    points, wall_left, wall_right = clip_to_bounds(trapezoidal_section.points, (0.5, 4.0))

    assert (wall_left, wall_right) == (True, True)
    assert [(p.x, p.z) for p in points] == [(0.5, 1.0), (1, 0), (4, 0)]


def test_find_water_level_with_bounds_solves_in_the_chosen_bed_only(two_beds_section, trapezoidal_section):
    target = compute_hydraulic_params(trapezoidal_section, water_z=1.0, slope=0.001, ks=30.0)["Q"]

    res = find_water_level_for_discharge(two_beds_section, target, 0.001, 30.0, bounds=(6.0, 20.0))

    assert res["water_z"] == pytest.approx(1.0, abs=1e-3)
    assert res["Q"] == pytest.approx(target, rel=1e-3)
    assert res["wet_intervals"] == [pytest.approx((7.5, 11.5), abs=1e-3)]


# --- Lit rectangulaire à berges verticales ---

# Lit de 2 m de large et 1 m de profondeur : fond à z=10 de x=0 à x=2, chaque berge
# verticale étant saisie comme deux points de même X (haut puis bas à gauche, bas puis haut
# à droite).
RECTANGULAR_BED_ROWS = [(0, 11), (0, 10), (2, 10), (2, 11)]


@pytest.mark.parametrize("rows", [
    [(-2, 11)] + RECTANGULAR_BED_ROWS + [(4, 11)],
    # Lit saisi d'abord, plateaux ajoutés en fin de tableau : le tri par X doit déplacer des
    # lignes, et l'ancien tri non stable retournait la berge droite (S = 0.5 m²).
    RECTANGULAR_BED_ROWS + [(4, 11), (-2, 11), (-4, 11), (6, 11)],
    # Profil levé de droite à gauche : retourné avant le tri, sinon chaque berge le serait.
    [(4, 11)] + RECTANGULAR_BED_ROWS[::-1] + [(-2, 11)],
    # Saisi de gauche à droite malgré un dernier X plus petit que le premier : le sens se
    # lit sur l'ensemble des lignes, pas sur leurs extrémités.
    RECTANGULAR_BED_ROWS + [(4, 11), (-2, 11)],
], ids=["saisie_de_gauche_a_droite", "plateaux_ajoutes_en_fin", "saisie_de_droite_a_gauche",
        "plateau_gauche_ajoute_en_fin"])
def test_rectangular_bed_with_vertical_banks_keeps_the_entry_order_at_equal_x(rows):
    """Les points sont triés par X mais, à X égal, gardent l'ordre de saisie du tableau, lu
    dans le sens du levé (de gauche à droite ou de droite à gauche). Pour 0.5 m d'eau :
    S = 2 × 0.5 = 1 m², P = fond 2 m + deux berges de 0.5 m = 3 m."""
    table = pd.DataFrame([{"X (m)": x, "Z (m NGF)": z} for x, z in rows])
    section = CrossSection(name="test", points=dataframe_to_points(table))

    res = compute_hydraulic_params(section, water_z=10.5, slope=0.001, ks=30.0)

    assert [(p.x, p.z) for p in section.points if p.x in (0, 2)] == RECTANGULAR_BED_ROWS
    expected_v = 30.0 * (1.0 / 3.0) ** (2 / 3) * math.sqrt(0.001)
    assert res["wet_intervals"] == [pytest.approx((0.0, 2.0))]
    assert res["S"] == pytest.approx(1.0)
    assert res["P"] == pytest.approx(3.0)
    assert res["Q"] == pytest.approx(expected_v * 1.0)


# --- Précision de la recherche de cote ("Imposer Q") ---

# Même canal que trapezoidal_section (fond de 3 m, 2 m de haut).
SMALL_CHANNEL = [Point(x=0, z=2), Point(x=1, z=0), Point(x=4, z=0), Point(x=5, z=2)]
# Grande rivière (fond de 60 m, 6 m de haut). À 5 m d'eau, 1 mm de cote ne change le débit
# que de 0.03 % : la précision sur le débit seule laisserait la cote à 3 mm près.
LARGE_RIVER = [Point(x=0, z=6), Point(x=10, z=0), Point(x=70, z=0), Point(x=80, z=6)]


@pytest.mark.parametrize("points, water_z", [
    (SMALL_CHANNEL, 0.016),
    (SMALL_CHANNEL, 0.065),
    (SMALL_CHANNEL, 1.0),
    (LARGE_RIVER, 1.0),
    (LARGE_RIVER, 5.0),
], ids=["Q=0.003", "Q=0.03", "Q=2.5", "Q=57", "Q=860"])
def test_imposed_q_finds_the_level_within_0_1_percent_of_q_and_1_mm(points, water_z):
    """En injectant le débit d'une cote connue, la dichotomie retrouve cette cote à 1 mm
    près et le débit à 0.1 % près, quel que soit le débit (l'ancienne tolérance absolue de
    0.01 m³/s donnait -8 % d'erreur à 0.03 m³/s et +190 % à 0.003 m³/s)."""
    section = CrossSection(name="test", points=points)
    target = compute_hydraulic_params(section, water_z, slope=0.001, ks=30.0)["Q"]

    res = find_water_level_for_discharge(section, target, slope=0.001, ks=30.0)

    assert res["Q"] == pytest.approx(target, rel=1e-3)
    assert res["water_z"] == pytest.approx(water_z, abs=1e-3)


def test_imposed_zero_discharge_gives_no_water(trapezoidal_section):
    res = find_water_level_for_discharge(trapezoidal_section, 0.0, slope=0.001, ks=30.0)

    assert res["water_z"] == 0 and res["Q"] == 0 and res["S"] == 0


# --- Profil projet : calcul par lits séparés ---

# Lit emboîté simple, calculable à la main : fond de 2 m à z=0, talus 1/1 jusqu'aux
# banquettes (z=0.5, X = -0.5 et 2.5), banquettes de 1 m, berges 1/1 jusqu'aux hauts de
# berge (z=1.5, X = -2.5 et 4.5), lits majeurs de 2 m montant de 0.25 m/m (z=2 au bout).
HAND_PARAMS = ProjectParameters(
    bed_width=2.0, bed_depth=0.5, bed_side_slope=1.0,
    berm_width_left=1.0, berm_width_right=1.0, berm_slope_left=0.0, berm_slope_right=0.0,
    bank_slope_left=1.0, bank_width_left=1.0, bank_slope_right=1.0, bank_width_right=1.0,
    floodplain_width_left=2.0, floodplain_width_right=2.0,
    floodplain_slope_left=0.25, floodplain_slope_right=0.25,
    anchor_x=0.0, anchor_z=0.0,
)

# Banquettes de 0.5 m à z=100.3, berges de 2 m de haut (hauts de berge à z=102.3), lits
# majeurs de 5 m en pente douce (bouts à z=102.55, niveau maximal sans débordement).
COMPOUND_PARAMS = ProjectParameters(
    bed_width=2.0, bed_depth=0.3, bed_side_slope=1.5,
    berm_width_left=0.5, berm_width_right=0.5, berm_slope_left=0.0, berm_slope_right=0.0,
    bank_slope_left=1.0, bank_width_left=2.0, bank_slope_right=1.0, bank_width_right=2.0,
    floodplain_width_left=5.0, floodplain_width_right=5.0,
    floodplain_slope_left=0.05, floodplain_slope_right=0.05,
    anchor_x=0.0, anchor_z=100.0,
)


def _strickler(area, perimeter, ks=30.0, slope=0.001):
    return ks * area * (area / perimeter) ** (2 / 3) * math.sqrt(slope)


def test_project_section_is_computed_part_by_part_as_by_hand():
    """Eau à z=1.75 (0.25 m au-dessus des hauts de berge) : les 5 parties sont mouillées.
    Chacune a sa surface et son périmètre, sans les verticales de découpage :
    - lit majeur : triangle de 1 m sur 0.25 m, S = 0.125 m², P = √(1² + 0.25²) ;
    - banquette + berge : banquette 1 m × 1.25 m + berge 1 m × (1.25 + 0.25) / 2, S = 2 m²,
      P = 1 + √2 ;
    - lit d'étiage : trapèze (2 + 3) / 2 × 0.5 + rectangle 3 × 1.25, S = 5 m², P = 2 + √2."""
    section = build_project_cross_section(HAND_PARAMS)

    res = compute_hydraulic_params(section, water_z=1.75, slope=0.001, ks=30.0)

    floodplain, bank, main = (0.125, math.sqrt(1 + 0.25 ** 2)), (2.0, 1 + math.sqrt(2)), (5.0, 2 + math.sqrt(2))
    expected = [("Lit majeur G", *floodplain), ("Banquette + berge G", *bank), ("Lit d'étiage", *main),
                ("Banquette + berge D", *bank), ("Lit majeur D", *floodplain)]
    assert [part["name"] for part in res["subsections"]] == [name for name, _, _ in expected]
    for part, (_, area, perimeter) in zip(res["subsections"], expected):
        assert part["S"] == pytest.approx(area)
        assert part["P"] == pytest.approx(perimeter)
        assert part["Q"] == pytest.approx(_strickler(area, perimeter))
        assert part["V"] == pytest.approx(_strickler(area, perimeter) / area)
    assert res["S"] == pytest.approx(9.25)
    assert res["Q"] == pytest.approx(sum(_strickler(area, perimeter) for _, area, perimeter in expected))


def test_project_discharge_always_increases_with_the_water_level():
    """Au pas de 1 mm, du fond jusqu'au niveau maximal sans débordement, y compris au passage
    des banquettes (z=100.3) et des hauts de berge (z=102.3). Calculé d'un seul bloc, le même
    terrain voyait son débit chuter à ces deux passages (périmètre brutalement allongé)."""
    section = build_project_cross_section(COMPOUND_PARAMS)
    levels = [100.0 + k / 1000 for k in range(1, 2550)]

    discharges = [compute_hydraulic_params(section, z, 0.005, 25.0)["Q"] for z in levels]

    assert all(q2 > q1 for q1, q2 in zip(discharges, discharges[1:]))
    one_block = CrossSection("Un seul bloc", section.points)
    q_block = [compute_hydraulic_params(one_block, z, 0.005, 25.0)["Q"] for z in levels]
    drops = [z for z, q1, q2 in zip(levels[1:], q_block, q_block[1:]) if q2 < q1]
    assert drops[0] == pytest.approx(100.301) and drops[1] == pytest.approx(102.301)


def test_imposed_q_finds_the_level_just_below_the_bank_top():
    """Débit de l'eau à 5 cm sous les hauts de berge (z=102.25). Calculé d'un seul bloc, le
    débit retombait sur le lit majeur à cette même valeur : la dichotomie y trouvait une cote
    30 cm trop haute."""
    section = build_project_cross_section(COMPOUND_PARAMS)
    target = compute_hydraulic_params(section, 102.25, 0.005, 25.0)["Q"]

    res = find_water_level_for_discharge(section, target, 0.005, 25.0)

    assert res["water_z"] == pytest.approx(102.25, abs=1e-3)
    assert res["Q"] == pytest.approx(target, rel=1e-3)
    assert [part["name"] for part in res["subsections"]] == [
        "Banquette + berge G", "Lit d'étiage", "Banquette + berge D"]


def test_dry_or_missing_parts_are_ignored():
    """Sans lit majeur, les verticales des hauts de berge tombent aux bouts du profil : elles
    ne séparent rien et ne sont pas tracées. Sous les banquettes, seul le lit d'étiage est
    mouillé."""
    section = build_project_cross_section(replace(HAND_PARAMS, floodplain_width_left=0.0,
                                                  floodplain_width_right=0.0))

    below_berms = compute_hydraulic_params(section, 0.4, 0.001, 30.0)
    above_berms = compute_hydraulic_params(section, 1.0, 0.001, 30.0)

    assert [part["name"] for part in below_berms["subsections"]] == ["Lit d'étiage"]
    assert [part["name"] for part in above_berms["subsections"]] == [
        "Banquette + berge G", "Lit d'étiage", "Banquette + berge D"]
    assert subsection_dividers(section) == [(-0.5, 0.5), (2.5, 0.5)]


def test_division_applies_inside_the_flow_zone():
    """Zone de X = 1 à X = 5 : le lit d'étiage est coupé par la limite gauche, le lit majeur D
    par la limite droite (parois hors périmètre) ; les parties de gauche sont hors zone."""
    section = build_project_cross_section(HAND_PARAMS)

    res = compute_hydraulic_params(section, 1.75, 0.001, 30.0, bounds=(1.0, 5.0))

    main, bank, floodplain = res["subsections"]
    assert (main["name"], bank["name"], floodplain["name"]) == ("Lit d'étiage", "Banquette + berge D", "Lit majeur D")
    # Fond plat de X = 1 à 2 (1.75 m d'eau), puis talus jusqu'à la banquette (1.75 → 1.25 m).
    assert main["S"] == pytest.approx(1.0 * 1.75 + 0.5 * (1.75 + 1.25) / 2)
    assert main["P"] == pytest.approx(1.0 + 0.5 * math.sqrt(2))
    assert bank["S"] == pytest.approx(2.0)
    # Lit majeur de X = 4.5 (0.25 m d'eau) à la paroi X = 5 (0.125 m).
    assert floodplain["S"] == pytest.approx(0.5 * (0.25 + 0.125) / 2)
    assert floodplain["P"] == pytest.approx(math.hypot(0.5, 0.125))
    assert subsection_dividers(section, (1.0, 5.0)) == [(2.5, 0.5), (4.5, 1.5)]


class TestResolveHydraulicResult:
    """resolve_hydraulic_result est le point d'entrée unique utilisé par
    core.controller.ProfileController pour l'onglet Hydraulique. Ces tests vérifient qu'il
    n'a AUCUN état interne : le résultat ne dépend que des arguments reçus à CET appel, donc
    changer de mode, de profil ou de valeur imposée ne peut jamais laisser filtrer le
    résultat d'un appel précédent (cf. bug rapporté : tirant d'eau/vitesse périmés affichés
    en mode "Imposer Q")."""

    @staticmethod
    def _reproduction_section():
        """Géométrie du cas de reproduction rapporté : bed_width=0.80, bed_depth=0.38,
        bed_side_slope=1.60, berges 2.20/1.30, largeurs 2.40/1.50."""
        params = ProjectParameters(
            bed_width=0.80, bed_depth=0.38, bed_side_slope=1.60,
            berm_width_left=0.0, berm_width_right=0.0,
            berm_slope_left=0.0, berm_slope_right=0.0,
            bank_slope_left=2.20, bank_width_left=2.40,
            bank_slope_right=1.30, bank_width_right=1.50,
            anchor_x=6.49, anchor_z=81.97,
        )
        return build_project_cross_section(params), params.anchor_z

    def test_reported_reproduction_case_gives_correct_depth_not_stale_h_eau(self):
        """Cas de reproduction exact du rapport de bug : cible Q=8.00 m³/s doit donner un
        tirant d'eau proche de 0.87 m — jamais 0.54 m (l'ancien h_eau d'un précédent passage
        en mode "Imposer H"). L'eau dépasse le haut du lit d'étiage : calculée en lits séparés
        (lit d'étiage et berges), la section débite plus qu'en un seul bloc (0.93 m avant)."""
        section, anchor_z = self._reproduction_section()

        res = resolve_hydraulic_result(
            section, calc_mode='H_FROM_Q',
            q_target=8.00, h_eau=0.54,  # h_eau volontairement laissé à une valeur périmée
            z_ref=anchor_z, slope=0.058, ks=25.0,
        )

        h = res["water_z"] - anchor_z
        assert h == pytest.approx(0.87, abs=0.02)
        assert h != pytest.approx(0.54, abs=0.05)
        assert res["V"] == pytest.approx(4.12, abs=0.05)
        assert res["S"] == pytest.approx(1.94, abs=0.05)
        assert res["Q"] == pytest.approx(8.00, rel=1e-3)

    def test_switching_calc_mode_recomputes_from_scratch(self):
        """Basculer de "Imposer H" à "Imposer Q" (même section) doit changer le résultat en
        conséquence, pas répéter l'ancien tirant d'eau saisi."""
        section, anchor_z = self._reproduction_section()

        res_impose_h = resolve_hydraulic_result(
            section, calc_mode='Q_FROM_H',
            q_target=999.0, h_eau=0.54,  # q_target ignoré dans ce mode : ne doit rien changer
            z_ref=anchor_z, slope=0.058, ks=25.0,
        )
        res_impose_q = resolve_hydraulic_result(
            section, calc_mode='H_FROM_Q',
            q_target=8.00, h_eau=0.54,
            z_ref=anchor_z, slope=0.058, ks=25.0,
        )

        assert res_impose_h["water_z"] - anchor_z == pytest.approx(0.54)
        assert res_impose_q["water_z"] - anchor_z == pytest.approx(0.87, abs=0.02)
        assert res_impose_h["water_z"] != res_impose_q["water_z"]

    def test_changing_q_target_alone_recomputes_result(self):
        """Changer uniquement le débit cible (sans changer de mode ni de profil) doit
        redéclencher un vrai recalcul du tirant d'eau — pas de valeur figée."""
        section, anchor_z = self._reproduction_section()

        res_q8 = resolve_hydraulic_result(
            section, calc_mode='H_FROM_Q', q_target=8.00, h_eau=0.0,
            z_ref=anchor_z, slope=0.058, ks=25.0,
        )
        res_q12 = resolve_hydraulic_result(
            section, calc_mode='H_FROM_Q', q_target=12.00, h_eau=0.0,
            z_ref=anchor_z, slope=0.058, ks=25.0,
        )

        assert res_q8["water_z"] != res_q12["water_z"]
        assert res_q12["water_z"] > res_q8["water_z"]  # plus de débit -> tirant d'eau plus grand
        assert res_q8["Q"] == pytest.approx(8.00, rel=1e-3)
        assert res_q12["Q"] == pytest.approx(12.00, rel=1e-3)

    def test_changing_profile_geometry_recomputes_result(self):
        """Changer de profil (section différente), en restant dans le même mode et avec le
        même débit cible, doit donner un tirant d'eau propre à la NOUVELLE géométrie."""
        section_a, anchor_z_a = self._reproduction_section()
        params_b = ProjectParameters(
            bed_width=2.40, bed_depth=1.00, bed_side_slope=2.00,
            anchor_x=3.78, anchor_z=47.40,
        )
        section_b = build_project_cross_section(params_b)

        res_a = resolve_hydraulic_result(
            section_a, calc_mode='H_FROM_Q', q_target=8.00, h_eau=0.0,
            z_ref=anchor_z_a, slope=0.058, ks=25.0,
        )
        res_b = resolve_hydraulic_result(
            section_b, calc_mode='H_FROM_Q', q_target=8.00, h_eau=0.0,
            z_ref=params_b.anchor_z, slope=0.058, ks=25.0,
        )

        assert (res_a["water_z"] - anchor_z_a) != pytest.approx(res_b["water_z"] - params_b.anchor_z)


# --- Onglet Hydraulique (contrôleur + graphique) ---

TWO_BEDS_POINTS = [
    {"X (m)": x, "Z (m NGF)": z}
    for x, z in [(0, 2), (1, 0), (4, 0), (5, 2), (6, 3), (7, 2), (8, 0), (11, 0), (12, 2)]
]


def _hydraulics_figure(**hydro):
    from core.controller import ProfileController, ViewMode
    data = {"hydro_source": "existing", "calc_mode": "Q_FROM_H", "h_eau": 1.0,
            "slope": 0.001, "ks_pro": 30.0, **hydro}
    return ProfileController().build_figure(TWO_BEDS_POINTS, data, ViewMode.HYDRAULICS)


def _results_text(fig):
    """Texte de l'encadré "Résultats hydrauliques" (les autres annotations : zones grisées)."""
    return next(a.text for a in fig.layout.annotations if "Résultats hydrauliques" in a.text)


def _water_trace(fig):
    return next(t for t in fig.data if t.name == "Ligne d'eau")


def test_hydraulics_figure_draws_one_water_segment_per_bed():
    trace = _water_trace(_hydraulics_figure())

    # Le None coupe le trait au-dessus du merlon émergé, entre les deux lits.
    assert list(trace.x[:2]) == pytest.approx([0.5, 4.5])
    assert trace.x[2] is None
    assert list(trace.x[3:]) == pytest.approx([7.5, 11.5])


def _dashed_lines_x(fig):
    """Limites de la zone d'écoulement (tirets)."""
    return sorted(sh.x0 for sh in fig.layout.shapes if sh.type == "line" and sh.line.dash == "dash")


def _dotted_lines_x(fig):
    """Verticales de découpage de la section en lits (pointillés)."""
    return sorted(sh.x0 for sh in fig.layout.shapes if sh.type == "line" and sh.line.dash == "dot")


def _greyed_out(fig):
    return sorted((sh.x0, sh.x1) for sh in fig.layout.shapes if sh.type == "rect")


def _project_figure(params, **hydro):
    from core.controller import ProfileController, ViewMode
    data = {**asdict(params), "hydro_source": "project", "slope": 0.001, "ks_pro": 30.0, **hydro}
    return ProfileController().build_figure([], data, ViewMode.HYDRAULICS)


def test_project_hydraulics_draws_the_dividers_and_details_each_wet_part():
    """Eau à 1.75 m au-dessus du fond (cf. HAND_PARAMS) : les 4 verticales sont tracées en
    pointillés, du terrain jusqu'au haut du profil (z=2, bouts des lits majeurs), et
    l'encadré donne le débit et la vitesse de chacune des 5 parties."""
    fig = _project_figure(HAND_PARAMS, calc_mode="Q_FROM_H", h_eau=1.75)

    dotted = sorted((sh.x0, sh.y0, sh.y1) for sh in fig.layout.shapes if sh.line.dash == "dot")
    assert dotted == [(-2.5, 1.5, 2.0), (-0.5, 0.5, 2.0), (2.5, 0.5, 2.0), (4.5, 1.5, 2.0)]
    results = _results_text(fig)
    assert "<b>Détail par partie mouillée :</b>" in results
    res = compute_hydraulic_params(build_project_cross_section(HAND_PARAMS), 1.75, 0.001, 30.0)
    for part in res["subsections"]:
        share = 100 * part["Q"] / res["Q"]
        assert (f"• {part['name']} : {format_discharge(part['Q'])} m³/s ({share:.0f} %), "
                f"V = {part['V']:.2f} m/s") in results


def test_project_hydraulics_draws_only_the_dividers_inside_the_flow_zone():
    fig = _project_figure(HAND_PARAMS, calc_mode="Q_FROM_H", h_eau=1.75,
                          hydro_zone="custom", hydro_x_left=1.0, hydro_x_right=5.0)

    assert _dotted_lines_x(fig) == [2.5, 4.5]
    assert _dashed_lines_x(fig) == [1.0, 5.0]


def test_dividers_stand_out_from_the_grid_but_stay_lighter_than_the_profile_and_water_line():
    """Pointillés tracés par-dessus la grille mais sous les courbes, plus foncés que la
    grille et plus fins que le profil et la ligne d'eau."""
    from viz.plots import GRID_COLOR
    fig = _project_figure(HAND_PARAMS, calc_mode="Q_FROM_H", h_eau=1.75)
    profile = next(t for t in fig.data if t.name == "Projet")
    water = _water_trace(fig)

    def luminance(hex_color):
        return sum(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))

    dividers = [sh for sh in fig.layout.shapes if sh.type == "line" and sh.line.dash == "dot"]
    assert len(dividers) == 4
    for divider in dividers:
        assert divider.layer == "between"
        assert luminance(divider.line.color) < luminance(GRID_COLOR)
        assert divider.line.width < min(profile.line.width, water.line.width)


@pytest.mark.parametrize("hydro", [
    dict(),
    dict(hydro_zone="custom", hydro_x_left=1.0, hydro_x_right=5.0),
])
def test_shapes_between_grid_and_traces_are_tied_to_the_axes(hydro):
    """Plotly.js 4.1 ne sait pas dessiner une forme "between" rattachée au domaine ou au
    papier (ex. add_vline, yref "y domain") : il n'en trouve pas le calque et tout le
    graphique échoue ("Cannot read properties of undefined (reading 'append')")."""
    fig = _project_figure(HAND_PARAMS, calc_mode="Q_FROM_H", h_eau=1.75, **hydro)

    between = [sh for sh in fig.layout.shapes if sh.layer == "between"]
    assert between
    for shape in between:
        assert (shape.xref, shape.yref) == ("x", "y")


def test_project_overflow_is_still_reported_without_part_detail():
    """Sans lit majeur, l'eau au-dessus des hauts de berge (z=1.5) déborde hors du profil :
    signalé, débit non calculé, comme avant le découpage."""
    params = replace(HAND_PARAMS, floodplain_width_left=0.0, floodplain_width_right=0.0)

    fig = _project_figure(params, calc_mode="Q_FROM_H", h_eau=1.75)

    assert "Débordement" in _overflow_warning_text(fig)
    results = _results_text(fig)
    assert "Débit (Q) : non calculable (débordement)" in results
    assert "Détail par partie" not in results


def test_existing_profile_is_not_divided():
    fig = _hydraulics_figure()

    assert _dotted_lines_x(fig) == []
    assert "Détail par partie" not in _results_text(fig)


def test_hydraulics_figure_between_two_x_draws_only_that_zone_and_greys_the_rest():
    fig = _hydraulics_figure(hydro_zone="custom", hydro_x_left=6.0, hydro_x_right=10.0)

    assert list(_water_trace(fig).x) == pytest.approx([7.5, 10.0])
    assert _dashed_lines_x(fig) == [6.0, 10.0]
    # Grisé de part et d'autre, jusqu'au bord du graphique (profil de 0 à 12, marge de 1 m).
    assert _greyed_out(fig) == [(-1.0, 6.0), (10.0, 13.0)]
    assert "Zone d'écoulement" in _results_text(fig)


def test_legacy_bounds_checkbox_is_read_as_between_two_x():
    """Profil enregistré avec l'ancienne case "Lit de calcul" (avant le choix du bras)."""
    fig = _hydraulics_figure(hydro_bounds_enabled=True, hydro_x_left=6.0, hydro_x_right=13.0)

    assert list(_water_trace(fig).x) == pytest.approx([7.5, 11.5])
    assert "X = 6.00 → 13.00 m" in _results_text(fig)


def test_hydraulics_bounds_disabled_are_ignored_even_if_inconsistent():
    fig = _hydraulics_figure(hydro_bounds_enabled=False, hydro_x_left=5.0, hydro_x_right=1.0)

    assert len(_water_trace(fig).x) == 5
    assert not fig.layout.shapes


def test_hydraulics_inconsistent_bounds_raise_a_readable_error():
    with pytest.raises(ValueError, match="X gauche"):
        _hydraulics_figure(hydro_bounds_enabled=True, hydro_x_left=5.0, hydro_x_right=5.0)


def test_existing_source_depth_is_measured_from_the_bottom_of_the_chosen_bed():
    """Lit de droite relevé de 0.5 m : avec les limites sur ce lit, "h = 1 m" doit donner une
    cote d'eau à 1.5 (fond du lit choisi + 1), pas 1.0 (fond de l'autre lit + 1)."""
    from core.controller import ProfileController, ViewMode
    points = [{"X (m)": p["X (m)"], "Z (m NGF)": p["Z (m NGF)"] + (0.5 if p["X (m)"] >= 7 else 0)}
              for p in TWO_BEDS_POINTS]
    data = {"hydro_source": "existing", "calc_mode": "Q_FROM_H", "h_eau": 1.0, "slope": 0.001,
            "ks_pro": 30.0, "hydro_bounds_enabled": True, "hydro_x_left": 6.0, "hydro_x_right": 13.0}

    fig = ProfileController().build_figure(points, data, ViewMode.HYDRAULICS)

    assert list(_water_trace(fig).y) == pytest.approx([1.5, 1.5])


# --- Deux bras : eau dans les deux, ou dans un seul ---

def test_suggest_arm_split_finds_the_crest_between_two_arms(two_beds_section, trapezoidal_section):
    assert suggest_arm_split(two_beds_section.points) == Point(x=6, z=3)
    # Un seul creux : aucun séparateur (les berges extérieures ne séparent rien).
    assert suggest_arm_split(trapezoidal_section.points) is None


def test_discharge_is_split_between_the_wet_arms(two_beds_section):
    res = compute_hydraulic_params(two_beds_section, water_z=1.0, slope=0.001, ks=30.0)

    assert res["bed_discharges"] == [pytest.approx(res["Q"] / 2), pytest.approx(res["Q"] / 2)]


@pytest.mark.parametrize("zone,expected", [("left_arm", [0.5, 4.5]), ("right_arm", [7.5, 11.5])])
def test_single_arm_puts_the_water_only_in_the_chosen_arm(zone, expected):
    fig = _hydraulics_figure(hydro_zone=zone, hydro_arm_split_x=6.0)

    assert list(_water_trace(fig).x) == pytest.approx(expected)
    assert _dashed_lines_x(fig) == [6.0]
    excluded = (6.0, 13.0) if zone == "left_arm" else (-1.0, 6.0)
    assert _greyed_out(fig) == [excluded]
    side = "gauche" if zone == "left_arm" else "droit"
    assert f"bras {side} seul" in _results_text(fig)
    assert "Répartition du débit" not in _results_text(fig)


def test_single_arm_imposed_q_puts_the_whole_flow_in_that_arm():
    """Même débit imposé : avec les deux bras il se partage, avec un seul bras il passe tout
    entier dans ce bras, d'où une cote d'eau plus haute."""
    both = _hydraulics_figure(calc_mode="H_FROM_Q", q_target=1.0)
    one = _hydraulics_figure(calc_mode="H_FROM_Q", q_target=1.0, hydro_zone="left_arm", hydro_arm_split_x=6.0)

    assert _water_trace(one).y[0] > _water_trace(both).y[0]
    assert "Répartition du débit" in _results_text(both)


def test_single_arm_above_the_crest_keeps_the_water_in_that_arm():
    """Berges extérieures à z=5, île à z=3, eau à z=3.5 : sans choix, l'île est submergée et
    les deux bras ne forment plus qu'une seule nappe ; avec "bras gauche seul", la
    séparation fait paroi et l'eau reste dans le bras gauche."""
    from core.controller import ProfileController, ViewMode
    points = [{"X (m)": x, "Z (m NGF)": z}
              for x, z in [(0, 5), (1, 0), (4, 0), (5, 2), (6, 3), (7, 2), (8, 0), (11, 0), (12, 5)]]
    data = {"hydro_source": "existing", "calc_mode": "Q_FROM_H", "h_eau": 3.5, "slope": 0.001, "ks_pro": 30.0}

    merged = ProfileController().build_figure(points, data, ViewMode.HYDRAULICS)
    left = ProfileController().build_figure(
        points, {**data, "hydro_zone": "left_arm", "hydro_arm_split_x": 6.0}, ViewMode.HYDRAULICS)

    assert list(_water_trace(merged).x) == pytest.approx([0.3, 11.7])
    assert list(_water_trace(left).x) == pytest.approx([0.3, 6.0])


def test_arm_split_outside_the_profile_raises_a_readable_error():
    with pytest.raises(ValueError, match="Séparation des bras"):
        _hydraulics_figure(hydro_zone="right_arm", hydro_arm_split_x=50.0)


def test_single_arm_depth_is_measured_from_the_bottom_of_that_arm():
    """Bras droit relevé de 0.5 m : en "bras droit seul", h = 1 m donne une cote d'eau à 1.5."""
    from core.controller import ProfileController, ViewMode
    points = [{"X (m)": p["X (m)"], "Z (m NGF)": p["Z (m NGF)"] + (0.5 if p["X (m)"] >= 7 else 0)}
              for p in TWO_BEDS_POINTS]
    data = {"hydro_source": "existing", "calc_mode": "Q_FROM_H", "h_eau": 1.0, "slope": 0.001,
            "ks_pro": 30.0, "hydro_zone": "right_arm", "hydro_arm_split_x": 6.0}

    fig = ProfileController().build_figure(points, data, ViewMode.HYDRAULICS)

    assert list(_water_trace(fig).y) == pytest.approx([1.5, 1.5])


# --- Débordement hors du profil : non modélisé, mais signalé ---

def _overflow_warning_text(fig):
    return next((a.text for a in fig.layout.annotations if "⚠" in (a.text or "")), None)


def test_overflow_sides_flag_the_free_end_exceeded(trapezoidal_section):
    """Berges à z=2 aux deux extrémités : en dessous, rien ; au-dessus, les deux côtés."""
    assert compute_hydraulic_params(trapezoidal_section, 1.0, 0.001, 30.0)["overflow_sides"] == []
    assert compute_hydraulic_params(trapezoidal_section, 2.0, 0.001, 30.0)["overflow_sides"] == []
    res = compute_hydraulic_params(trapezoidal_section, 2.5, 0.001, 30.0)
    assert res["overflow_sides"] == ["left", "right"] and res["Q"] == 0


def test_a_wall_side_never_overflows(trapezoidal_section):
    res = compute_hydraulic_params(trapezoidal_section, 2.5, 0.001, 30.0, bounds=(-10.0, 2.5))
    assert res["overflow_sides"] == ["left"]


LOW_RIGHT_END = [{"X (m)": x, "Z (m NGF)": z} for x, z in [(0, 3), (1, 0), (4, 0), (5, 1.5)]]


def _figure(points, **hydro):
    from core.controller import ProfileController, ViewMode
    data = {"hydro_source": "existing", "slope": 0.001, "ks_pro": 30.0, **hydro}
    return ProfileController().build_figure(points, data, ViewMode.HYDRAULICS)


def test_imposed_h_above_a_profile_end_shows_an_overflow_warning():
    """Extrémité droite à z=1.5 : avec h = 2 m l'eau déborderait à droite. Le débit n'est
    pas calculable, un avertissement l'explique, avec la capacité sans débordement."""
    fig = _figure(LOW_RIGHT_END, calc_mode="Q_FROM_H", h_eau=2.0)

    warning = _overflow_warning_text(fig)
    assert warning is not None
    assert "Débordement" in warning and "droite (Z = 1.50 m NGF)" in warning
    assert "Capacité maximale sans débordement" in warning and "Z = 1.50 m NGF" in warning
    assert "débit non calculable" in warning


def _results_text(fig):
    return next((a.text for a in fig.layout.annotations if "Résultats hydrauliques" in (a.text or "")), None)


def test_imposed_h_overflow_keeps_the_water_line_up_to_the_profile_end():
    """Le trait ne disparaît plus : il va du point où l'eau coupe la berge gauche (z = 3 en
    X = 0 → z = 2 en X = 1/3) jusqu'à l'extrémité droite du profil, à la cote saisie, et le
    cadre l'inclut. Les résultats restent affichés, débit "non calculable"."""
    fig = _figure(LOW_RIGHT_END, calc_mode="Q_FROM_H", h_eau=2.0)

    water = _water_trace(fig)
    assert list(water.x) == pytest.approx([1 / 3, 5.0])
    assert list(water.y) == pytest.approx([2.0, 2.0])
    results = _results_text(fig)
    assert "Débit (Q) : non calculable (débordement)" in results
    assert "Tirant d'eau (h) :</b> 2.00 m" in results
    assert "Répartition du débit" not in results


def test_imposed_h_above_the_whole_profile_spans_it_entirely_and_is_framed():
    fig = _figure(LOW_RIGHT_END, calc_mode="Q_FROM_H", h_eau=5.0)

    assert list(_water_trace(fig).x) == pytest.approx([0.0, 5.0])
    assert fig.layout.yaxis.range[1] >= 5.0 + 1 - 1e-9


def test_imposed_q_beyond_capacity_leaves_the_water_at_the_maximum_level():
    """Débit trop fort : l'eau reste au niveau maximal sans débordement (extrémité droite,
    z = 1.5), avec la capacité correspondante, au lieu de retomber à Q = 0 sans trait."""
    from core.hydraulics import compute_hydraulic_params as compute
    from core.models import CrossSection, Point
    section = CrossSection("s", [Point(x=p["X (m)"], z=p["Z (m NGF)"]) for p in LOW_RIGHT_END])
    capacity = compute(section, 1.5, 0.001, 30.0)["Q"]

    fig = _figure(LOW_RIGHT_END, calc_mode="H_FROM_Q", q_target=capacity * 3)

    water = _water_trace(fig)
    assert list(water.y) == pytest.approx([1.5, 1.5])
    assert water.x[-1] == pytest.approx(5.0)
    results = _results_text(fig)
    assert f"{capacity:.2f} m³/s (cible {capacity * 3:.2f} m³/s non atteinte)" in results


def test_imposed_q_beyond_capacity_shows_a_warning():
    from core.hydraulics import compute_hydraulic_params as compute
    from core.models import CrossSection, Point
    section = CrossSection("s", [Point(x=p["X (m)"], z=p["Z (m NGF)"]) for p in LOW_RIGHT_END])
    capacity = compute(section, 1.5, 0.001, 30.0)["Q"]

    fig = _figure(LOW_RIGHT_END, calc_mode="H_FROM_Q", q_target=capacity * 3)

    warning = _overflow_warning_text(fig)
    assert warning is not None and "Débit cible non atteint" in warning
    assert f"{capacity:.2f} m³/s" in warning


@pytest.mark.parametrize("hydro", [
    dict(calc_mode="Q_FROM_H", h_eau=1.0),       # sous l'extrémité la plus basse
    dict(calc_mode="H_FROM_Q", q_target=0.5),    # débit atteignable
])
def test_no_warning_when_the_water_stays_inside_the_profile(hydro):
    assert _overflow_warning_text(_figure(LOW_RIGHT_END, **hydro)) is None


# Débit cible juste au-dessus de la capacité d'un petit fossé (≈ 0.03 m³/s) et d'une grande
# rivière (≈ 1170 m³/s) : le débit "Saisi" et l'avertissement "débit cible non atteint"
# suivent la même règle relative que la recherche de cote (0.1 % du débit cible).
SMALL_DITCH = [{"X (m)": x, "Z (m NGF)": z} for x, z in [(0, 0.4), (0.2, 0), (0.7, 0), (0.9, 0.2)]]
LARGE_RIVER_ROWS = [{"X (m)": p.x, "Z (m NGF)": p.z} for p in LARGE_RIVER]


def _capacity(rows):
    section = CrossSection("s", [Point(x=p["X (m)"], z=p["Z (m NGF)"]) for p in rows])
    return compute_hydraulic_params(section, overflow_level(section), 0.001, 30.0)["Q"]


@pytest.mark.parametrize("rows", [SMALL_DITCH, LARGE_RIVER_ROWS], ids=["petit_debit", "grand_debit"])
def test_target_0_05_percent_above_the_capacity_is_reached(rows):
    """Atteint, même pour un grand débit (l'ancienne tolérance absolue de 0.01 m³/s le
    déclarait non atteint à 1170 m³/s)."""
    fig = _figure(rows, calc_mode="H_FROM_Q", q_target=_capacity(rows) * 1.0005)

    assert "m³/s <i>[Saisi]</i>" in _results_text(fig)
    assert _overflow_warning_text(fig) is None


@pytest.mark.parametrize("rows", [SMALL_DITCH, LARGE_RIVER_ROWS], ids=["petit_debit", "grand_debit"])
def test_target_1_percent_above_the_capacity_is_not_reached(rows):
    """Non atteint, même pour un petit débit (l'ancienne tolérance absolue de 0.01 m³/s le
    déclarait atteint à 0.03 m³/s)."""
    target = _capacity(rows) * 1.01

    fig = _figure(rows, calc_mode="H_FROM_Q", q_target=target)

    assert f"(cible {format_discharge(target)} m³/s non atteinte)" in _results_text(fig)
    assert "Débit cible non atteint" in _overflow_warning_text(fig)


def test_small_discharges_are_shown_with_3_significant_digits():
    """Petit fossé (capacité 0.0315 m³/s), cible 1 % au-dessus : avec 2 décimales, résultats
    et avertissement afficheraient 0.03 m³/s demandés comme calculés."""
    fig = _figure(SMALL_DITCH, calc_mode="H_FROM_Q", q_target=_capacity(SMALL_DITCH) * 1.01)

    assert "0.0315 m³/s (cible 0.0318 m³/s non atteinte)" in _results_text(fig)
    warning = _overflow_warning_text(fig)
    assert "0.0318 m³/s demandés, 0.0315 m³/s calculés" in warning
    assert "Capacité maximale sans débordement : Q = 0.0315 m³/s" in warning


@pytest.mark.parametrize("q, text", [
    (0.001, "0.00100"),
    (0.0318, "0.0318"),
    (0.12345, "0.123"),
    (0.5, "0.500"),
    (0.0, "0.00"),
    (7.943, "7.94"),
    (1171.4, "1171.40"),
])
def test_format_discharge_keeps_3_significant_digits_below_1_m3_per_s(q, text):
    assert format_discharge(q) == text


def test_water_exactly_at_a_profile_end_despite_rounding_is_not_an_overflow():
    """99.4 + 3.4 = 102.80000000000001 en flottant : une eau à ras de l'extrémité droite
    (Z = 102.8) ne doit ni écarter le lit ni déclencher l'avertissement."""
    from core.models import CrossSection, Point
    section = CrossSection("s", [Point(x=0, z=103.0), Point(x=2, z=99.4), Point(x=4, z=102.8)])

    res = compute_hydraulic_params(section, 99.4 + 3.4, 0.001, 30.0)

    assert res["overflow_sides"] == []
    assert res["Q"] > 0 and res["x_right"] == pytest.approx(4.0)


# --- Cadrage par défaut avec l'autre profil en fond ---

WIDE_EXISTING = [{"X (m)": x, "Z (m NGF)": z} for x, z in
                 [(-10, 52), (-4, 50), (0, 48.5), (3, 47.2), (6, 47.0), (9, 47.3), (14, 49), (25, 50.5), (40, 53)]]


def _ranges(fig):
    return tuple(fig.layout.xaxis.range), tuple(fig.layout.yaxis.range)


def test_hydraulics_overlay_frames_both_profiles_and_the_water_line():
    """Projet étroit (X ~ -6 à 14) sur un terrain large (X = -10 à 40) : le cadrage par défaut
    englobe les deux profils en entier et la ligne d'eau, avec 1 m de marge."""
    from core.controller import ProfileController, ViewMode
    ctrl = ProfileController()
    params = {**ctrl.default_project_params(), "anchor_x": 3.0, "anchor_z": 47.0,
              "hydro_source": "project", "calc_mode": "Q_FROM_H", "h_eau": 1.2, "slope": 0.003}

    fig = ctrl.build_figure(WIDE_EXISTING, params, ViewMode.HYDRAULICS, show_overlay=True)

    (x0, x1), (z0, z1) = _ranges(fig)
    every_x = [x for t in fig.data if t.x for x in t.x if x is not None]
    every_z = [z for t in fig.data if t.y for z in t.y if z is not None]
    assert (x0, x1) == pytest.approx((min(every_x) - 1, max(every_x) + 1))
    assert (z0, z1) == pytest.approx((min(every_z) - 1, max(every_z) + 1))
    assert x0 <= -11 and x1 >= 41  # le profil existant entier
    assert z1 >= _water_trace(fig).y[0] + 1


def test_project_tab_overlay_still_frames_the_project_only():
    """Onglet Profil projet : cadrage inchangé, sur le seul profil projet (objet de la saisie)."""
    from core.controller import ProfileController, ViewMode
    from core.geometry import build_project_cross_section
    from core.models import ProjectParameters
    ctrl = ProfileController()
    params = {**ctrl.default_project_params(), "anchor_x": 3.0, "anchor_z": 47.0}
    project = build_project_cross_section(ProjectParameters(**{k: v for k, v in params.items()
                                                               if k in ProjectParameters.__dataclass_fields__}))
    xs, zs = project.to_arrays()

    fig = ctrl.build_figure(WIDE_EXISTING, params, ViewMode.PROJECT, show_overlay=True)

    assert _ranges(fig) == (pytest.approx((min(xs) - 1, max(xs) + 1)), pytest.approx((min(zs) - 1, max(zs) + 1)))
