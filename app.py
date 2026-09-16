"""
HydroTopo — MVP V1

Application locale de saisie et de visualisation de profils en travers
(existant / projet), inspirée de BedloadWeb (interface) et du classeur
Excel hydrotopo (logique de dimensionnement du lit projet).

Périmètre V1 : saisie de données + dessin uniquement, aucun calcul
hydraulique (débit, hauteur d'eau, volumes) pour l'instant.

Lancement : streamlit run app.py
"""

import streamlit as st

from state.session import init_session_state
from ui import comparison, existing_profile, project_profile


def main() -> None:
    st.set_page_config(page_title="HydroTopo — V1", layout="wide")
    init_session_state()

    st.sidebar.title("HydroTopo — V1")
    st.sidebar.caption("Saisie et visualisation de profils en travers")

    page = st.sidebar.radio(
        "Navigation",
        ["Profil existant", "Profil projet", "Comparaison"],
    )

    if page == "Profil existant":
        existing_profile.render()
    elif page == "Profil projet":
        project_profile.render()
    elif page == "Comparaison":
        comparison.render()


if __name__ == "__main__":
    main()
