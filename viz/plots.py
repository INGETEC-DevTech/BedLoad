"""
Construction des graphiques Plotly à partir d'un ou plusieurs CrossSection.

Ces fonctions ne dépendent pas de Streamlit : elles retournent un objet
plotly.graph_objects.Figure, que la couche UI se charge d'afficher.
"""

import math
from typing import List, Optional, Tuple

import plotly.graph_objects as go

from core.earthworks import CUT, EarthworksResult
from core.hard_points import format_slope
from core.models import CrossSection
from core.longitudinal import LongitudinalProfile

EXISTING_COLOR = "#2ca02c"   # vert : profil existant
PROJECT_COLOR = "#9467bd"    # violet : profil projet
HARD_POINT_COLOR = "#d62728" # rouge : points durs (repères de terrain fixes)
CALC_BOUND_COLOR = "#6c757d" # gris : limites du lit de calcul hydraulique
STATION_COLOR = "#ced4da"       # gris clair : position des profils en travers (profil en long)
STATION_LABEL_COLOR = "#495057" # gris foncé : nom de ces profils
CUT_COLOR = "#d62728"        # rouge : déblai (terrain existant à enlever)
FILL_COLOR = "#ff7f0e"       # orange : remblai (matériaux à ajouter)
# Surface en dessous de laquelle une zone n'est pas étiquetée sur le graphique (elle reste
# identifiable au survol) : évite d'empiler des étiquettes sur de minuscules zones.
_MIN_LABELLED_AREA = 0.01


def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


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
               calc_bounds: Optional[Tuple[float, float]],
               x_extent: Tuple[float, float]) -> None:
    """Ligne d'eau : un trait par lit mouillé (interrompu là où le terrain émerge, au lieu
    d'un trait continu qui traverserait un merlon ou une berge entre deux lits), en une
    seule trace (segments séparés par None) pour une seule entrée de légende.

    Les limites de la zone d'écoulement, si définies, sont tracées en tirets verticaux, et
    le terrain exclu du calcul (ex. l'autre bras) est grisé jusqu'au bord du graphique
    (`x_extent` : abscisses extrêmes des profils tracés). Une limite infinie (bras seul :
    ce côté n'est borné que par l'extrémité du profil) n'est ni tracée ni grisée."""
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
        x_min, x_max = x_extent[0] - 1, x_extent[1] + 1  # même marge que le cadrage des axes
        left, right = calc_bounds
        excluded = []
        if math.isfinite(left):
            fig.add_vline(x=left, line=dict(color=CALC_BOUND_COLOR, width=1, dash="dash"))
            if left > x_min:
                excluded.append((x_min, left))
        if math.isfinite(right):
            fig.add_vline(x=right, line=dict(color=CALC_BOUND_COLOR, width=1, dash="dash"))
            if right < x_max:
                excluded.append((right, x_max))
        for x0, x1 in excluded:
            fig.add_vrect(
                x0=x0, x1=x1, fillcolor=CALC_BOUND_COLOR, opacity=0.08, line_width=0, layer="below",
                annotation_text="Hors calcul", annotation_position="bottom left" if x0 == x_min else "bottom right",
                annotation_font=dict(size=10, color=CALC_BOUND_COLOR),
            )


def _centroid(xs: List[float], zs: List[float]) -> Tuple[float, float]:
    """Centre de gravité d'un polygone fermé (formule de l'aire signée), pour placer
    l'étiquette d'une zone à l'intérieur de celle-ci ; moyenne des sommets en repli si le
    polygone est dégénéré."""
    area = cx = cz = 0.0
    for (x0, z0), (x1, z1) in zip(zip(xs, zs), zip(xs[1:], zs[1:])):
        cross = x0 * z1 - x1 * z0
        area += cross
        cx += (x0 + x1) * cross
        cz += (z0 + z1) * cross
    if abs(area) < 1e-12:
        return sum(xs) / len(xs), sum(zs) / len(zs)
    return cx / (3 * area), cz / (3 * area)


def _add_earthwork_zones(fig: go.Figure, earthworks: EarthworksResult) -> None:
    """Une surface colorée par zone de déblai/remblai, nommée (D1, R1...) au survol et, si
    elle n'est pas minuscule, par une étiquette en son centre. Une seule entrée de légende
    par type de zone."""
    shown_in_legend = set()
    for zone in earthworks.zones:
        is_cut = zone.kind == CUT
        color = CUT_COLOR if is_cut else FILL_COLOR
        label = "Déblai (à enlever)" if is_cut else "Remblai (à ajouter)"
        fig.add_trace(
            go.Scatter(
                x=zone.outline_x, y=zone.outline_z,
                mode="lines", fill="toself",
                fillcolor=_rgba(color, 0.3), line=dict(width=0, color=color),
                name=label, legendgroup=zone.kind,
                showlegend=zone.kind not in shown_in_legend,
                hoveron="fills", hoverinfo="text",
                text=f"{zone.name} : {label.split(' ')[0]} {zone.area:.2f} m²",
            )
        )
        shown_in_legend.add(zone.kind)

        if zone.area >= _MIN_LABELLED_AREA:
            label_x, label_z = _centroid(zone.outline_x, zone.outline_z)
            fig.add_annotation(
                x=label_x, y=label_z,
                text=f"<b>{zone.name}</b><br>{zone.area:.2f} m²",
                showarrow=False, font=dict(size=10, color=color),
                bgcolor="rgba(255, 255, 255, 0.7)",
            )


def _add_earthwork_summary(fig: go.Figure, earthworks: EarthworksResult) -> None:
    """Encadré des totaux (en haut à gauche, comme les résultats hydrauliques)."""
    if earthworks.extent is None:
        text = "<b>Terrassements</b><br><br>Les deux profils n'ont pas d'emprise commune."
    else:
        n_cut = sum(1 for z in earthworks.zones if z.kind == CUT)
        n_fill = len(earthworks.zones) - n_cut
        x0, x1 = earthworks.extent
        text = (
            "<b>Terrassements (surface en coupe)</b><br><br>"
            f'<span style="color:{CUT_COLOR}"><b>Déblai (à enlever) :</b> '
            f"{earthworks.cut_total:.2f} m²</span> ({n_cut} zone{'s' if n_cut > 1 else ''})<br>"
            f'<span style="color:{FILL_COLOR}"><b>Remblai (à ajouter) :</b> '
            f"{earthworks.fill_total:.2f} m²</span> ({n_fill} zone{'s' if n_fill > 1 else ''})<br>"
            f"<b>Bilan (déblai − remblai) :</b> {earthworks.balance:+.2f} m²<br>"
            f"<i>Emprise commune : X = {x0:.2f} → {x1:.2f} m</i>"
        )
    fig.add_annotation(
        text=text, align="left", showarrow=False,
        xref="paper", yref="paper", x=0.02, y=0.96, xanchor="left", yanchor="top",
        bgcolor="rgba(255, 255, 255, 0.95)", bordercolor="#dee2e6",
        borderwidth=1, borderpad=10, font=dict(size=12, color="#495057"),
    )


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
    
    _add_water(fig, water_level, water_intervals, calc_bounds, (min(xs), max(xs)))

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
    earthworks: Optional[EarthworksResult] = None,
    frame_all: bool = False,
) -> go.Figure:
    """Graphique de comparaison : les deux profils superposés, avec ligne d'eau optionnelle
    et, si `earthworks` est fourni, les zones de déblai/remblai entre les deux.

    Cadrage par défaut : sur le seul profil projet (onglet Profil projet, où le projet est
    l'objet de la saisie), ou, avec `frame_all`, sur les deux profils en entier et la ligne
    d'eau (onglet Hydraulique, où rien ne doit sortir du cadre)."""
    xs_e, zs_e = existing.to_arrays()
    xs_p, zs_p = project.to_arrays()
    fig = go.Figure()

    # Zones tracées en premier : les deux profils restent lisibles par-dessus.
    if earthworks is not None:
        _add_earthwork_zones(fig, earthworks)
    
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

    all_xs = list(xs_e) + list(xs_p)
    _add_water(fig, water_level, water_intervals, calc_bounds, (min(all_xs), max(all_xs)))

    fig = _apply_common_layout(fig, f"{existing.name} vs {project.name}")
    if earthworks is not None:
        _add_earthwork_summary(fig, earthworks)
    
    # Cadre explicite (+ 1 mètre de marge), sur le profil projet seul ou sur tout le contenu.
    if frame_all:
        frame_xs = all_xs
        frame_zs = list(zs_e) + list(zs_p)
        if water_level is not None and water_intervals:
            frame_zs.append(water_level)
    else:
        frame_xs, frame_zs = xs_p, zs_p
    fig.update_xaxes(range=[min(frame_xs) - 1, max(frame_xs) + 1])
    fig.update_yaxes(range=[min(frame_zs) - 1, max(frame_zs) + 1])

    return fig


def plot_longitudinal_profile(profile: LongitudinalProfile) -> go.Figure:
    """Profil en long d'un projet : TN existant (thalweg relevé) et fond de lit projet
    (anchor_z), chacun tracé en fonction de la distance au premier point dur. Contrairement
    aux coupes transversales, les axes ne sont volontairement PAS orthonormés (cette
    distance s'étend typiquement sur des centaines de mètres pour quelques mètres
    d'altitude)."""
    fig = go.Figure()

    # Profils en travers : un trait vertical discret à la position de chacun, et son nom
    # écrit verticalement en bas de la zone de tracé (le haut est déjà occupé par les noms
    # des points durs et la légende).
    for distance, name in profile.stations:
        fig.add_vline(x=distance, line=dict(color=STATION_COLOR, width=1, dash="dot"), layer="below")
        fig.add_annotation(
            x=distance, y=0, xref="x", yref="paper", yanchor="bottom", yshift=4,
            text=name, textangle=-90, showarrow=False,
            font=dict(size=10, color=STATION_LABEL_COLOR), bgcolor="rgba(255, 255, 255, 0.8)",
        )

    # Survol : le nom du profil en plus de sa distance et de son altitude.
    hover = "<b>%{text}</b> : %{y:.2f} m NGF<extra>%{fullData.name}</extra>"
    fig.add_trace(
        go.Scatter(
            x=profile.pk_existing, y=profile.z_existing,
            mode="lines+markers",
            name="TN existant (thalweg)",
            line=dict(color=EXISTING_COLOR, width=2),
            marker=dict(size=6),
            text=profile.names_existing, hovertemplate=hover,
        )
    )

    fig.add_trace(
        go.Scatter(
            x=profile.pk_project, y=profile.z_project,
            mode="lines+markers",
            name="Projet (fond de lit)",
            line=dict(color=PROJECT_COLOR, width=2),
            marker=dict(size=6),
            text=profile.names_project, hovertemplate=hover,
        )
    )

    # Points durs (repères de terrain fixes) : reliés par un trait pointillé qui matérialise
    # les tronçons de pente (pente affichée en m/m, comme dans l'onglet Hydraulique), et
    # chacun identifié par son nom au-dessus de son marqueur.
    if profile.segments:
        fig.add_trace(
            go.Scatter(
                x=[m.distance for m in profile.hard_points], y=[m.z for m in profile.hard_points],
                mode="lines", name="Tronçons entre points durs",
                line=dict(color=HARD_POINT_COLOR, width=1.5, dash="dot"),
                hoverinfo="skip",
            )
        )
        for segment in profile.segments:
            fig.add_annotation(
                x=(segment.start.distance + segment.end.distance) / 2,
                y=(segment.start.z + segment.end.z) / 2,
                text=f"I = {format_slope(segment.slope)}",
                showarrow=False, yshift=12,
                font=dict(size=11, color=HARD_POINT_COLOR),
                bgcolor="rgba(255, 255, 255, 0.85)",
            )
    if profile.hard_points:
        fig.add_trace(
            go.Scatter(
                x=[m.distance for m in profile.hard_points], y=[m.z for m in profile.hard_points],
                mode="markers+text", name="Points durs",
                text=[m.name for m in profile.hard_points],
                textposition="top center",
                textfont=dict(size=11, color=HARD_POINT_COLOR),
                marker=dict(size=13, symbol="diamond", color=HARD_POINT_COLOR,
                            line=dict(width=1, color="#ffffff")),
            )
        )

    fig = _apply_common_layout(fig, "Profil en long")
    fig.update_layout(xaxis_title=dict(
        text="Distance au premier point dur (m)", font=dict(size=12, color="#6c757d")
    ))
    # On annule l'échelle orthonormée héritée de _apply_common_layout : non pertinente ici.
    fig.update_yaxes(scaleanchor=None, scaleratio=None)

    return fig