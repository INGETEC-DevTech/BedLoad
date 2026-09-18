"""
Construction des graphiques Plotly à partir d'un ou plusieurs CrossSection.

Ces fonctions ne dépendent pas de Streamlit : elles retournent un objet
plotly.graph_objects.Figure, que la couche UI se charge d'afficher.
"""

import plotly.graph_objects as go

from core.models import CrossSection

EXISTING_COLOR = "#2ca02c"   # vert : profil existant
PROJECT_COLOR = "#9467bd"    # violet : profil projet


def _apply_common_layout(fig: go.Figure, title: str) -> go.Figure:
    """Mise en page épurée et institutionnelle du graphique Plotly."""
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color="#495057")),
        xaxis_title=dict(text="Distance (m)", font=dict(size=12, color="#6c757d")),
        yaxis_title=dict(text="Altitude (m NGF)", font=dict(size=12, color="#6c757d")),
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff", # Se fond parfaitement avec les onglets blancs
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


def plot_single_profile(
    section: CrossSection, 
    color: str = PROJECT_COLOR,
    water_level: float = None,
    water_x_left: float = None,
    water_x_right: float = None
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
    
    # Trace de la ligne d'eau (uniquement si les paramètres sont fournis)
    if water_level is not None and water_x_left is not None and water_x_right is not None:
        fig.add_trace(
            go.Scatter(
                x=[water_x_left, water_x_right],
                y=[water_level, water_level],
                mode="lines",
                name="Ligne d'eau",
                line=dict(color="blue", width=2),
            )
        )
        
    fig = _apply_common_layout(fig, section.name)
        
    # On applique la même logique de cadre strict (+ 1 mètre de marge)
    fig.update_xaxes(range=[min(xs) - 1, max(xs) + 1])
    fig.update_yaxes(range=[min(zs) - 1, max(zs) + 1])
    
    return fig


def plot_overlay(
    existing: CrossSection, 
    project: CrossSection,
    water_level: float = None,
    water_x_left: float = None,
    water_x_right: float = None
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

    # Trace de la ligne d'eau (si paramètres fournis)
    if water_level is not None and water_x_left is not None and water_x_right is not None:
        fig.add_trace(
            go.Scatter(
                x=[water_x_left, water_x_right],
                y=[water_level, water_level],
                mode="lines",
                name="Ligne d'eau",
                line=dict(color="blue", width=2),
            )
        )

    fig = _apply_common_layout(fig, f"{existing.name} vs {project.name}")
    
    # On force le cadre UNIQUEMENT sur le profil PROJET (+ 1 mètre de marge).
    fig.update_xaxes(range=[min(xs_p) - 1, max(xs_p) + 1])
    fig.update_yaxes(range=[min(zs_p) - 1, max(zs_p) + 1])
    
    return fig