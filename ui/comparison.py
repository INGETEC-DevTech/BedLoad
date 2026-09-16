"""
Page "Comparaison" : le grand graphique avec l'existant et le projet
superposés sur le même repère.
"""

import streamlit as st

from core.geometry import build_project_cross_section
from core.models import CrossSection, dataframe_to_points
from viz.plots import plot_overlay


def render() -> None:
    st.header("Comparaison existant / projet")

    existing_points = dataframe_to_points(st.session_state.existing_profile_df)
    if len(existing_points) < 2:
        st.warning(
            "Le profil existant n'a pas assez de points. "
            "Complétez-le dans l'onglet \"Profil existant\"."
        )
        return

    existing = CrossSection(name=st.session_state.existing_profile_name, points=existing_points)
    project = build_project_cross_section(
        st.session_state.project_params, name=st.session_state.project_profile_name
    )

    st.plotly_chart(plot_overlay(existing, project), width='stretch')
