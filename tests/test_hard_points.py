import pytest

from core.hard_points import (HardPoint, computed_slope, distance_zone, format_slope, reference_pk,
                              segment_for_distance, validate_hard_points)


def hp(name, pk, z, id=None):
    return HardPoint(name=name, pk=pk, z=z, id=id)


# Trois points : A (PK 100, Z 50) -> B (PK 300, Z 46) -> C (PK 500, Z 45)
POINTS = [hp("C", 500.0, 45.0, 3), hp("A", 100.0, 50.0, 1), hp("B", 300.0, 46.0, 2)]


def test_zone_and_reference_follow_the_complete_points_sorted_by_pk():
    assert reference_pk(POINTS) == 100.0
    assert distance_zone(POINTS) == (0.0, 400.0)


def test_incomplete_points_are_ignored_and_less_than_two_means_no_zone():
    assert distance_zone([hp("A", 0.0, 50.0), hp("B", None, 45.0)]) is None
    assert reference_pk([hp("A", None, 50.0), hp("B", 10.0, 45.0)]) == 10.0


@pytest.mark.parametrize("distance,expected", [
    (0.0, ("A", "B")),      # sur le premier point : tronçon aval
    (150.0, ("A", "B")),
    (200.0, ("B", "C")),    # pile sur B : tronçon aval
    (399.999, ("B", "C")),
    (400.0, ("B", "C")),    # sur le dernier point : dernier tronçon
])
def test_segment_for_distance(distance, expected):
    segment = segment_for_distance(POINTS, distance)
    assert (segment.upstream.name, segment.downstream.name) == expected


def test_slope_of_each_segment():
    assert computed_slope(POINTS, 50.0)[0] == pytest.approx(4.0 / 200.0)
    assert computed_slope(POINTS, 250.0)[0] == pytest.approx(1.0 / 200.0)


def test_no_slope_outside_the_zone_or_without_zone():
    slope, segment, reason = computed_slope(POINTS, 450.0)
    assert slope is None and segment is None and "hors de la zone" in reason
    slope, _, reason = computed_slope([hp("A", 0.0, 50.0)], 0.0)
    assert slope is None and "au moins deux points durs" in reason


def test_slopes_are_formatted_in_m_per_m():
    assert format_slope(0.02) == "0.0200 m/m"


def test_valid_list_has_no_error():
    assert validate_hard_points(POINTS, reference_id=1, profile_pks={"P1": 100.0, "P2": 500.0}) == []


def test_counter_slope_and_flat_slope_are_refused():
    errors = validate_hard_points([hp("A", 0.0, 50.0), hp("B", 100.0, 51.0), hp("C", 200.0, 51.0)])
    assert any("Contre-pente" in e and "« A »" in e and "« B »" in e for e in errors)
    assert any("Pente nulle" in e and "« B »" in e and "« C »" in e for e in errors)


def test_same_pk_is_refused():
    errors = validate_hard_points([hp("A", 0.0, 50.0), hp("B", 0.0, 49.0)])
    assert any("même PK" in e for e in errors)


def test_no_point_upstream_of_the_first_one():
    points = POINTS + [hp("Nouveau", 50.0, 51.0)]
    errors = validate_hard_points(points, reference_id=1)
    assert any("Nouveau" in e and "amont du premier" in e for e in errors)
    # Déplacer le premier point lui-même reste possible (s'il reste en tête)
    moved = [hp("A", 80.0, 50.0, 1), hp("B", 300.0, 46.0, 2), hp("C", 500.0, 45.0, 3)]
    assert validate_hard_points(moved, reference_id=1) == []


def test_profiles_must_stay_inside_the_zone():
    shrunk = [hp("A", 100.0, 50.0, 1), hp("B", 300.0, 46.0, 2)]
    errors = validate_hard_points(shrunk, reference_id=1, profile_pks={"PK 450": 450.0, "PK 200": 200.0})
    assert len(errors) == 1 and "« PK 450 » (PK 450)" in errors[0] and "PK 200" not in errors[0]


def test_pk_and_z_are_required_except_for_an_untouched_legacy_incomplete_point():
    legacy = hp("Ancien", None, 48.0, 7)
    original = {7: ("Ancien", None, 48.0)}
    assert validate_hard_points([hp("A", 0.0, 50.0), legacy], original_incomplete=original) == []
    edited = hp("Ancien modifié", None, 48.0, 7)
    assert any("obligatoires" in e for e in validate_hard_points([edited], original_incomplete=original))
    assert any("obligatoires" in e for e in validate_hard_points([hp("Nouveau", 10.0, None)]))
