from core.longitudinal import build_longitudinal_profile


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
