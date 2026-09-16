import streamlit as st
from core.geometry import build_project_cross_section
from core.models import points_to_dataframe, dataframe_to_points, CrossSection
from viz.plots import plot_single_profile, plot_overlay, PROJECT_COLOR

# Liste des débits caractéristiques à afficher
_DISCHARGE_REMINDERS = [
    "QMNA5", "QMOD", "2QMOD", "3QMOD",
    "Q2", "Q5", "Q10", "Q20", "Q50", "Q100", "QMAX",
]

def render() -> None:
    st.header("Dimensionnement du profil projet")
    st.caption(
        "Ajustez les paramètres du lit projeté. Le profil est reconstruit "
        "automatiquement à chaque changement."
    )

    p = st.session_state.project_params

    # Création des colonnes asymétriques : 1/3 pour les réglages, 2/3 pour le graphique
    col_left, col_right = st.columns([1, 2])

    with col_left:
        # Le conteneur à hauteur fixe permet de scroller uniquement cette zone
        with st.container(height=700):
            tab_geo, tab_hydro = st.tabs(["Géométrie", "Hydraulique"])
            
            # --- ONGLET GÉOMÉTRIE ---
            with tab_geo:

                st.markdown("**Ancrage sur le terrain**")
                p.anchor_x = st.number_input("X du bord gauche du fond du lit (m)", value=p.anchor_x, step=0.1)
                p.anchor_z = st.number_input("Z du fond du lit (m NGF)", value=p.anchor_z, step=0.01)
                
                st.markdown("**Lit trapézoïdal**")
                p.bed_width = st.number_input("Largeur fond du lit (m)", min_value=0.0, value=p.bed_width, step=0.1)
                p.bed_depth = st.number_input("Profondeur du fond du lit (m)", min_value=0.0, value=p.bed_depth, step=0.01)
                p.bed_side_slope = st.number_input("Pente des bords du lit d'étiage (H/V)", min_value=0.01, value=p.bed_side_slope, step=0.1)
                
                st.markdown("**Banquettes**")
                p.berm_width_left = st.number_input("Largeur BANQ RG (m)", min_value=0.0, value=p.berm_width_left, step=0.1)
                p.berm_width_right = st.number_input("Largeur BANQ RD (m)", min_value=0.0, value=p.berm_width_right, step=0.1)
                
                st.markdown("**Berge gauche**")
                p.bank_slope_left = st.number_input("Pente BG (H/V)", min_value=0.01, value=p.bank_slope_left, step=0.1)
                p.bank_width_left = st.number_input("Largeur BG (m)", min_value=0.0, value=p.bank_width_left, step=0.1)

                st.markdown("**Berge droite**")
                p.bank_slope_right = st.number_input("Pente BD (H/V)", min_value=0.01, value=p.bank_slope_right, step=0.1)
                p.bank_width_right = st.number_input("Largeur BD (m)", min_value=0.0, value=p.bank_width_right, step=0.1)

                # st.caption(
                #    "Masqué pour l'instant (non branché à la géométrie dans cette V1, "
                #    "conformément à l'Excel de référence) : suppression de points, "
                #    "lit majeur, interruption de terrassements, D50, conservation de "
                #    "la pente existante."
                # )

            # --- ONGLET HYDRAULIQUE ---
            with tab_hydro:
                st.markdown("**Ligne d'eau**")
                
                # Paramètre conservé : hauteur d'eau (sert pour l'altitude Z de la ligne)
                p.h_eau = st.number_input("h_eau (m)", min_value=0.0, value=p.h_eau, step=0.01, format="%.4f")
                
                # Nouveaux paramètres manuels pour encadrer la ligne bleue sur l'axe X
                # (On initialise avec les valeurs du fond du lit par défaut)
                p.x_eau_gauche = st.number_input("X de l'eau (gauche)", value=p.anchor_x, step=0.1)
                p.x_eau_droite = st.number_input("X de l'eau (droite)", value=p.anchor_x + p.bed_width, step=0.1)

                # --- TOUT LE RESTE EST MASQUÉ (NON AFFICHÉ SUR LE GRAPHIQUE) ---
                
                # p.calc_mode = st.radio(
                #     "Calculs sur l'existant ou sur le projet ?",
                #     options=["Existant", "Projet"],
                #     index=0 if p.calc_mode == "Existant" else 1,
                #     horizontal=True,
                # )
                
                # p.ks_pro = st.number_input("Ks_pro", min_value=0.0, value=p.ks_pro, step=1.0)
                
                # st.metric("Q_dim", "À calculer")
                # st.caption("Le calcul de Q_dim (Manning-Strickler) sera branché dans une prochaine itération.")
                
                # st.markdown("**Rappels des débits caractéristiques**")
                # st.caption("Emplacements réservés pour un futur écran Hydrologie.")
                
                # reminder_cols = st.columns(3)
                # for i, label in enumerate(_DISCHARGE_REMINDERS):
                #     with reminder_cols[i % 3]:
                #         st.metric(label, "-")

    # Mise à jour des paramètres en session
    st.session_state.project_params = p

    # --- AFFICHAGE DU GRAPHIQUE (COLONNE DE DROITE) ---
    with col_right:
        st.session_state.project_profile_name = st.text_input(
            "Nom du profil", value=st.session_state.project_profile_name
        )
        
        # Ajout de la case à cocher
        show_existing = st.checkbox("Afficher le profil existant en fond (gris)", value=False)
        
        # Génération de la géométrie projet
        section = build_project_cross_section(p, name=st.session_state.project_profile_name)
        
        # Choix du graphique selon la case à cocher
        if show_existing:
            # On récupère les points de l'existant depuis la session
            existing_points = dataframe_to_points(st.session_state.existing_profile_df)
            existing_section = CrossSection(name=st.session_state.existing_profile_name, points=existing_points)
            
            # On dessine le graphique superposé
            fig = plot_overlay(
                existing=existing_section, 
                project=section,
                water_level=p.anchor_z + p.h_eau,
                water_x_left=p.x_eau_gauche,
                water_x_right=p.x_eau_droite
            )
        else:
            # On dessine le graphique normal (projet seul)
            fig = plot_single_profile(
                section, 
                color=PROJECT_COLOR,
                water_level=p.anchor_z + p.h_eau,
                water_x_left=p.x_eau_gauche,
                water_x_right=p.x_eau_droite
            )
            
        # Affichage du graphique choisi
        st.plotly_chart(fig, use_container_width=True)
        
        with st.expander("Table des points générés"):
            st.dataframe(points_to_dataframe(section.points), use_container_width=True)