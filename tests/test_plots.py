from core.longitudinal import LongitudinalProfile, HardPointMarker
from viz.plots import plot_longitudinal_profile, HARD_POINT_COLOR


def _hard_point_traces(fig):
    """Les traces de points durs sont les seules en mode marqueur+texte : les courbes
    TN existant / projet sont toujours en mode lignes+marqueurs."""
    return [trace for trace in fig.data if trace.mode == "markers+text"]


def test_plot_longitudinal_profile_without_hard_points_has_no_marker_trace():
    profile = LongitudinalProfile(pk_existing=[0.0], z_existing=[10.0])

    fig = plot_longitudinal_profile(profile)

    assert _hard_point_traces(fig) == []


def test_plot_longitudinal_profile_draws_both_hard_points():
    profile = LongitudinalProfile(
        hard_point_upstream=HardPointMarker(distance=0.0, z=100.0, name="Pont Amont"),
        hard_point_downstream=HardPointMarker(distance=500.0, z=90.0, name="Pont Aval"),
    )

    fig = plot_longitudinal_profile(profile)
    traces = _hard_point_traces(fig)

    assert len(traces) == 2
    names = {trace.name for trace in traces}
    assert names == {"Pont Amont", "Pont Aval"}

    by_name = {trace.name: trace for trace in traces}
    upstream_trace = by_name["Pont Amont"]
    assert list(upstream_trace.x) == [0.0]
    assert list(upstream_trace.y) == [100.0]
    assert upstream_trace.marker.color == HARD_POINT_COLOR

    downstream_trace = by_name["Pont Aval"]
    assert list(downstream_trace.x) == [500.0]
    assert list(downstream_trace.y) == [90.0]


def test_plot_longitudinal_profile_draws_only_the_hard_point_that_is_positioned():
    """Un seul des deux points durs positionnable (l'autre reste None, cf.
    core.longitudinal) : une seule trace de marqueur ajoutée."""
    profile = LongitudinalProfile(
        hard_point_upstream=HardPointMarker(distance=0.0, z=100.0, name="Amont"),
        hard_point_downstream=None,
    )

    fig = plot_longitudinal_profile(profile)
    traces = _hard_point_traces(fig)

    assert len(traces) == 1
    assert traces[0].name == "Amont"
