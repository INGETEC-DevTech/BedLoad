"""
Construction des graphiques Plotly à partir d'un ou plusieurs CrossSection.

Ces fonctions ne dépendent pas de Streamlit : elles retournent un objet
plotly.graph_objects.Figure, que la couche UI se charge d'afficher.
"""

from typing import List, Optional, Tuple

import plotly.graph_objects as go

from core.models import CrossSection
from core.longitudinal import LongitudinalProfile

EXISTING_COLOR = "#2ca02c"   # vert : profil existant
PROJECT_COLOR = "#9467bd"    # violet : profil projet
HARD_POINT_COLOR = "#d62728" # rouge : points durs (repères de terrain fixes)
CALC_BOUND_COLOR = "#6c757d" # gris : limites du lit de calcul hydraulique


def _apply_common_layout(fig: go.Figure, title: str) -> go.Figure:
    """Mise en page épurée et institutionnelle du graphique Plotly."""
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color="#495057")),
        xaxis_title=dict(text="Distance (m)", font=dict(size=12, color="#6c757d")),
        yaxis_title=dict(text="Altitude (m NGF)", font=dict(size=12, color="#6c757d")),
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff", # Se fond parfaitement avec les onglets blancs
        autosize=True,
        margin=dict(l=50, r=20, t=60, b=50),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
            font=dict(size=11, color="#495057")
        ),
        hovermode="x unified",
        uirevision="keep_state",
        # Grille subtile et moderne
        xaxis=dict(showgrid=True, gridwidth=1, gridcolor="#f1f3f5", zeroline=False),
        yaxis=dict(showgrid=True, gridwidth=1, gridcolor="#f1f3f5", zeroline=False),
    )
    # Axes orthonormés : 1 m écran en X = 1 m écran en Z.
    fig.update_yaxes(scaleanchor="x", scaleratio=1)
    return fig


def _add_water(fig: go.Figure, water_level: Optional[float],
               water_intervals: Optional[List[Tuple[float, float]]],
               calc_bounds: Optional[Tuple[float, float]]) -> None:
    """Ligne d'eau : un trait par lit mouillé (interrompu là où le terrain émerge, au lieu
    d'un trait continu qui traverserait un merlon ou une berge entre deux lits), en une
    seule trace (segments séparés par None) pour une seule entrée de légende. Les limites
    du lit de calcul, si définies, sont tracées en tirets verticaux."""
    if water_level is not None and water_intervals:
        xs, ys = [], []
        for x_left, x_right in water_intervals:
            if xs:
                xs.append(None)
                ys.append(None)
            xs += [x_left, x_right]
            ys += [water_level, water_level]
        fig.add_trace(
            go.Scatter(
                x=xs, y=ys,
                mode="lines",
                name="Ligne d'eau",
                line=dict(color="blue", width=2),
                connectgaps=False,
            )
        )

    if calc_bounds is not None:
        for x in calc_bounds:
            fig.add_vline(x=x, line=dict(color=CALC_BOUND_COLOR, width=1, dash="dash"))


def plot_single_profile(
    section: CrossSection,
    color: str = PROJECT_COLOR,
    water_level: float = None,
    water_intervals: Optional[List[Tuple[float, float]]] = None,
    calc_bounds: Optional[Tuple[float, float]] = None,
) -> go.Figure:
    """Graphique d'un seul profil (existant seul, ou projet seul) avec ligne d'eau optionnelle."""
    xs, zs = section.to_arrays()
    fig = go.Figure()
    
    # Trace du profil de fond
    fig.add_trace(
        go.Scatter(
            x=xs, y=zs,
            mode="lines+markers",
            name=section.name,
            line=dict(color=color, width=2),
            marker=dict(size=6),
        )
    )
    
    _add_water(fig, water_level, water_intervals, calc_bounds)

    fig = _apply_common_layout(fig, section.name)
        
    # On applique la même logique de cadre strict (+ 1 mètre de marge)
    fig.update_xaxes(range=[min(xs) - 1, max(xs) + 1])
    fig.update_yaxes(range=[min(zs) - 1, max(zs) + 1])
    
    return fig


def plot_overlay(
    existing: CrossSection, 
    project: CrossSection,
    water_level: float = None,
    water_intervals: Optional[List[Tuple[float, float]]] = None,
    calc_bounds: Optional[Tuple[float, float]] = None,
) -> go.Figure:
    """Graphique de comparaison : les deux profils superposés, avec ligne d'eau optionnelle."""
    xs_e, zs_e = existing.to_arrays()
    xs_p, zs_p = project.to_arrays()
    fig = go.Figure()
    
    # Trace du profil existant (vert)
    fig.add_trace(
        go.Scatter(
            x=xs_e, y=zs_e,
            mode="lines+markers",
            name=existing.name,
            line=dict(color=EXISTING_COLOR, width=2),
            marker=dict(size=6),
        )
    )
    
    # Trace du profil projet (violet) - CORRIGÉ pour correspondre au profil simple
    fig.add_trace(
        go.Scatter(
            x=xs_p, y=zs_p,
            mode="lines+markers",
            name=project.name,
            line=dict(color=PROJECT_COLOR, width=2), # Repassé à 2 (au lieu de 3)
            marker=dict(size=6),                     # Retrait du symbol="diamond" et repassé à 6
        )
    )

    _add_water(fig, water_level, water_intervals, calc_bounds)

    fig = _apply_common_layout(fig, f"{existing.name} vs {project.name}")
    
    # On force le cadre UNIQUEMENT sur le profil PROJET (+ 1 mètre de marge).
    fig.update_xaxes(range=[min(xs_p) - 1, max(xs_p) + 1])
    fig.update_yaxes(range=[min(zs_p) - 1, max(zs_p) + 1])

    return fig


def plot_longitudinal_profile(profile: LongitudinalProfile) -> go.Figure:
    """Profil en long d'un projet : TN existant (thalweg relevé) et fond de lit projet
    (anchor_z), chacun tracé en fonction de la distance au point dur amont. Contrairement
    aux coupes transversales, les axes ne sont volontairement PAS orthonormés (cette
    distance s'étend typiquement sur des centaines de mètres pour quelques mètres
    d'altitude)."""
    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=profile.pk_existing, y=profile.z_existing,
            mode="lines+markers",
            name="TN existant (thalweg)",
            line=dict(color=EXISTING_COLOR, width=2),
            marker=dict(size=6),
        )
    )

    fig.add_trace(
        go.Scatter(
            x=profile.pk_project, y=profile.z_project,
            mode="lines+markers",
            name="Projet (fond de lit)",
            line=dict(color=PROJECT_COLOR, width=2),
            marker=dict(size=6),
        )
    )

    # Points durs (repères de terrain fixes) : un marqueur ponctuel par point, sans
    # ligne (ce ne sont pas des courbes), identifié par son propre nom dans la légende
    # et l'étiquette affichée au-dessus du marqueur. Absents du graphique tant que leurs
    # coordonnées ne sont pas toutes renseignées (cf. build_longitudinal_profile).
    for hard_point in (profile.hard_point_upstream, profile.hard_point_downstream):
        if hard_point is None:
            continue
        fig.add_trace(
            go.Scatter(
                x=[hard_point.distance], y=[hard_point.z],
                mode="markers+text",
                name=hard_point.name,
                text=[hard_point.name],
                textposition="top center",
                textfont=dict(size=11, color=HARD_POINT_COLOR),
                marker=dict(
                    size=13, symbol="diamond", color=HARD_POINT_COLOR,
                    line=dict(width=1, color="#ffffff"),
                ),
            )
        )

    fig = _apply_common_layout(fig, "Profil en long")
    fig.update_layout(xaxis_title=dict(
        text="Distance au point dur amont (m)", font=dict(size=12, color="#6c757d")
    ))
    # On annule l'échelle orthonormée héritée de _apply_common_layout : non pertinente ici.
    fig.update_yaxes(scaleanchor=None, scaleratio=None)

    return fig