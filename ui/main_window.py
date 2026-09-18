# ui/main_window.py
from PyQt6.QtWidgets import QMainWindow, QSplitter, QWidget, QVBoxLayout, QTabWidget, QCheckBox
from PyQt6.QtCore import Qt

from database.db_manager import DatabaseManager
from ui.sidebar import Sidebar
from ui.forms.existing_form import ExistingProfileForm
from ui.forms.project_form import ProjectProfileForm
from ui.views.plot_view import PlotView

from core.controller import ProfileController, ViewMode

class MainWindow(QMainWindow):
    # Correspondance entre l'index du QTabWidget (ordre de création des onglets,
    # ligne 45-46 ci-dessous) et le mode métier attendu par le contrôleur.
    TAB_MODES = [ViewMode.EXISTING, ViewMode.PROJECT]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("HydroTopo - V2 (PyQt6)")
        self.resize(1400, 800)
        self.db_manager = DatabaseManager()
        self.controller = ProfileController()
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
            project_data = self.controller.default_project_params()
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
        if self.current_profile_id is None:
            return

        # 1. Transmission des données brutes au contrôleur
        existing_data = self.form_existing.get_data()
        project_data = self.form_project.get_data()
        mode = self.TAB_MODES[self.tabs.currentIndex()]

        fig = self.controller.build_figure(
            existing_data,
            project_data,
            mode,
            show_overlay=self.chk_overlay.isChecked(),
        )

        # 2. Affichage de ce que le contrôleur a produit
        self.plot_view.update_plot(fig)