"""
Gestion centralisée de l'état de session Streamlit.

Toutes les pages lisent/écrivent leurs données via st.session_state. Ce
module regroupe l'initialisation à un seul endroit pour éviter d'avoir des
"if X not in st.session_state" dispersés dans chaque page.
"""

import streamlit as st

from core.models import ProjectParameters, points_to_dataframe, Point

# Profil de démonstration = points réels de la coupe CT1 du classeur hydrotopo,
# pour que l'application ne s'ouvre pas sur un écran vide.
_DEMO_EXISTING_POINTS = [
    Point(0.00, 49.44),
    Point(3.78, 47.40),
    Point(5.78, 47.40),
    Point(6.08, 47.67),
    Point(7.08, 47.67),
    Point(11.55, 49.44),
]


def init_session_state() -> None:
    """À appeler une seule fois, en tout début de app.py."""

    if "existing_profile_df" not in st.session_state:
        st.session_state.existing_profile_df = points_to_dataframe(_DEMO_EXISTING_POINTS)

    if "existing_profile_name" not in st.session_state:
        st.session_state.existing_profile_name = "Profil existant"

    if "project_params" not in st.session_state:
        # Paramètres par défaut = mêmes valeurs que la coupe CT1 de l'Excel,
        # ancrés sur le fond du lit existant pour un premier affichage cohérent.
        st.session_state.project_params = ProjectParameters(
            bed_width=2.0,
            bed_depth=0.27,
            bed_side_slope=2.0,
            berm_width_left=0.0,
            berm_width_right=0.0,
            bank_slope_left=1.8,
            bank_width_left=3.0,
            bank_slope_right=2.5,
            bank_width_right=3.0,
            anchor_x=3.78,
            anchor_z=47.40,
        )

    if "project_profile_name" not in st.session_state:
        st.session_state.project_profile_name = "Profil projet"
