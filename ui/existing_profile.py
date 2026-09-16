import pandas as pd
import streamlit as st
from core.models import CrossSection, dataframe_to_points
from viz.plots import plot_single_profile, EXISTING_COLOR

def render() -> None:
    st.header("Profil en travers existant")
    st.caption(
        "Renseignez les points topographiques (X = distance cumulée, "
        "Z = altitude) du profil existant ligne par ligne."
    )

    st.session_state.existing_profile_name = st.text_input(
        "Nom du profil", value=st.session_state.existing_profile_name
    )

    st.session_state.existing_profile_df = st.data_editor(
        st.session_state.existing_profile_df,
        num_rows="dynamic",
        width='stretch',
        key="existing_profile_editor",
    )

    points = dataframe_to_points(st.session_state.existing_profile_df)

    if len(points) < 2:
        st.info("Ajoutez au moins deux points pour afficher le profil.")
        return

    section = CrossSection(name=st.session_state.existing_profile_name, points=points)
    st.plotly_chart(plot_single_profile(section, color=EXISTING_COLOR), width='stretch')