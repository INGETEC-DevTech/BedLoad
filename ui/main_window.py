# ui/main_window.py
import pandas as pd
from PyQt6.QtWidgets import QMainWindow, QSplitter, QWidget, QVBoxLayout, QTabWidget, QCheckBox
from PyQt6.QtCore import Qt

from database.db_manager import DatabaseManager
from ui.sidebar import Sidebar
from ui.forms.existing_form import ExistingProfileForm
from ui.forms.project_form import ProjectProfileForm
from ui.views.plot_view import PlotView

# Importation de ta logique métier existante
from core.models import ProjectParameters, CrossSection, dataframe_to_points
from core.geometry import build_project_cross_section
from viz.plots import plot_single_profile, plot_overlay, PROJECT_COLOR, EXISTING_COLOR

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HydroTopo - V2 (PyQt6)")
        self.resize(1400, 800)
        self.db_manager = DatabaseManager()
        self.current_profile_id = None
        
        # --- LAYOUT PRINCIPAL ---
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(main_splitter)
        
        # 1. Panneau latéral gauche (Arbre)
        self.sidebar = Sidebar(self.db_manager)
        main_splitter.addWidget(self.sidebar)
        
        # 2. Zone de travail (Splitter intérieur : Formulaires à gauche, Graphe à droite)
        work_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(work_splitter)
        
        # 2a. Panneau des formulaires
        forms_widget = QWidget()
        forms_layout = QVBoxLayout(forms_widget)
        self.tabs = QTabWidget()
        
        self.form_existing = ExistingProfileForm()
        self.form_project = ProjectProfileForm()
        
        self.tabs.addTab(self.form_existing, "Profil existant")
        self.tabs.addTab(self.form_project, "Profil projet")
        forms_layout.addWidget(self.tabs)
        
        # Checkbox pour la superposition (comme dans Streamlit)
        self.chk_overlay = QCheckBox("Afficher le profil existant en fond (vert)")
        self.chk_overlay.setChecked(False)
        forms_layout.addWidget(self.chk_overlay)
        
        work_splitter.addWidget(forms_widget)
        
        # 2b. Panneau du graphique
        self.plot_view = PlotView()
        work_splitter.addWidget(self.plot_view)
        
        # Ratios de largeur
        main_splitter.setSizes([250, 1150])
        work_splitter.setSizes([450, 700])
        
        # --- CONNEXIONS ---
        self.sidebar.profile_selected.connect(self.load_profile)
        self.form_existing.data_changed.connect(self.save_and_update_plot)
        self.form_project.data_changed.connect(self.save_and_update_plot)
        self.chk_overlay.stateChanged.connect(self.update_plot)
        self.tabs.currentChanged.connect(self.update_plot)

        # Désactiver les formulaires tant qu'aucun profil n'est sélectionné
        forms_widget.setEnabled(False)
        self.forms_widget = forms_widget

    def load_profile(self, profile_id: int):
        self.current_profile_id = profile_id
        self.forms_widget.setEnabled(True)
        
        existing_data, project_data = self.db_manager.load_profile_state(profile_id)
        
        # Remplissage silencieux (ne déclenche pas d'events)
        self.form_existing.set_data(existing_data)
        
        if not project_data:
            # Valeurs par défaut si le dict est vide
            project_data = vars(ProjectParameters())
        self.form_project.set_data(project_data)
        
        self.update_plot()

    def save_and_update_plot(self, _=None):
        if self.current_profile_id is None: return
        
        # 1. Sauvegarde (Auto-save)
        existing_data = self.form_existing.get_data()
        project_data = self.form_project.get_data()
        self.db_manager.save_profile_state(self.current_profile_id, existing_data, project_data)
        
        # 2. Mise à jour du graphe
        self.update_plot()

    def update_plot(self, _=None):
        if self.current_profile_id is None: return
        
        # Récupération des données brutes
        existing_data = self.form_existing.get_data()
        project_data = self.form_project.get_data()
        
        # Paramètres d'eau
        h_eau = project_data.get('h_eau', 0)
        anchor_z = project_data.get('anchor_z', 0)
        water_level = anchor_z + h_eau
        water_x_left = project_data.get('x_eau_gauche')
        water_x_right = project_data.get('x_eau_droite')

        current_tab_index = self.tabs.currentIndex()
        fig = None

        if current_tab_index == 0:  # Tab "Existant"
            df = pd.DataFrame(existing_data)
            points = dataframe_to_points(df)
            if len(points) >= 2:
                section = CrossSection(name="Existant", points=points)
                fig = plot_single_profile(section, color=EXISTING_COLOR)
                
        elif current_tab_index == 1:  # Tab "Projet"
            # On instancie la dataclass en filtrant les attributs valides
            valid_keys = ProjectParameters.__dataclass_fields__.keys()
            filtered_params = {k: v for k, v in project_data.items() if k in valid_keys}
            p = ProjectParameters(**filtered_params)
            
            section_proj = build_project_cross_section(p, name="Projet")
            
            if self.chk_overlay.isChecked():
                df = pd.DataFrame(existing_data)
                points_ext = dataframe_to_points(df)
                section_ext = CrossSection(name="Existant", points=points_ext)
                fig = plot_overlay(
                    section_ext, section_proj,
                    water_level=water_level,
                    water_x_left=water_x_left, water_x_right=water_x_right
                )
            else:
                fig = plot_single_profile(
                    section_proj, color=PROJECT_COLOR,
                    water_level=water_level,
                    water_x_left=water_x_left, water_x_right=water_x_right
                )
                
        self.plot_view.update_plot(fig)