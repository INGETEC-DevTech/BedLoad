# ui/main_window.py
from PyQt6.QtWidgets import QMainWindow, QSplitter, QWidget, QVBoxLayout, QTabWidget, QCheckBox, QStackedWidget, QLabel
from PyQt6.QtCore import Qt

from database.db_manager import DatabaseManager
from ui.sidebar import Sidebar
from ui.forms.existing_form import ExistingProfileForm
from ui.forms.project_form import ProjectProfileForm
from ui.views.plot_view import PlotView
from ui import theme

from core.controller import ProfileController, ViewMode

class MainWindow(QMainWindow):
    TAB_MODES = [ViewMode.EXISTING, ViewMode.PROJECT]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("HydroTopo - V2 (PyQt6)")
        self.resize(1400, 800)
        self.db_manager = DatabaseManager()
        self.controller = ProfileController()
        self.current_profile_id = None
        
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(main_splitter)
        
        # 1. Panneau latéral gauche
        self.sidebar = Sidebar(self.db_manager)
        main_splitter.addWidget(self.sidebar)
        
        # 2. Zone de travail (Le splitter est affiché dès le départ)
        work_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(work_splitter)
        
        # 2a. Panneau des formulaires (Caché au démarrage via StackedWidget)
        self.forms_stack = QStackedWidget()
        
        # Index 0 : Message d'accueil (prend la place des formulaires vides)
        welcome_widget = QWidget()
        welcome_layout = QVBoxLayout(welcome_widget)
        lbl_welcome = QLabel("👈 Sélectionnez un projet ou un\nprofil dans l'arborescence")
        lbl_welcome.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_welcome.setStyleSheet(theme.qss(
            "color: $TEXT_MUTED; font-size: ${FONT_SIZE_VALUE}px; font-weight: bold;"
        ))
        welcome_layout.addWidget(lbl_welcome)
        self.forms_stack.addWidget(welcome_widget)
        
        # Index 1 : Les vrais formulaires
        forms_widget = QWidget()
        forms_layout = QVBoxLayout(forms_widget)
        self.tabs = QTabWidget()
        
        self.form_existing = ExistingProfileForm()
        self.form_project = ProjectProfileForm()
        
        self.tabs.addTab(self.form_existing, "Profil existant")
        self.tabs.addTab(self.form_project, "Profil projet")
        forms_layout.addWidget(self.tabs)
        
        self.chk_overlay = QCheckBox("Afficher le profil existant en fond (vert)")
        self.chk_overlay.setVisible(False)
        forms_layout.addWidget(self.chk_overlay)
        
        self.forms_stack.addWidget(forms_widget)

        work_splitter.addWidget(self.forms_stack)

        # 2b. Panneau du graphique (Toujours visible pour éviter le clignotement OpenGL)
        self.plot_view = PlotView()
        work_splitter.addWidget(self.plot_view)

        self._work_splitter = work_splitter

        # On impose la répartition de l'espace
        main_splitter.setSizes([250, 1150])
        work_splitter.setSizes([450, 700])

        # Poignées non redimensionnables à la souris (juste visibles) : les proportions
        # ci-dessus restent la seule base de calcul, y compris au redimensionnement fenêtre.
        main_splitter.handle(1).setEnabled(False)
        work_splitter.handle(1).setEnabled(False)

        # Connexions
        self.sidebar.profile_selected.connect(self.load_profile)
        self.sidebar.project_selected.connect(self.load_project_longitudinal)
        self.form_existing.data_changed.connect(self.save_and_update_plot)
        self.form_project.data_changed.connect(self.save_and_update_plot)
        self.chk_overlay.stateChanged.connect(self.update_plot)
        self.tabs.currentChanged.connect(self.on_tab_changed)

    def on_tab_changed(self, index: int):
        self.chk_overlay.setVisible(index == 1)
        self.update_plot()

    def load_profile(self, profile_id: int):
        self.current_profile_id = profile_id

        # Dès qu'on clique sur un profil, on révèle les formulaires à côté du graphique
        self.forms_stack.show()
        self.forms_stack.setCurrentIndex(1)
        self._work_splitter.setSizes([450, 700])
        self.plot_view.lbl_title.setText("Visualisation de la coupe transversale")

        existing_data, project_data = self.db_manager.load_profile_state(profile_id)

        self.form_existing.set_data(existing_data)
        if not project_data:
            project_data = self.controller.default_project_params()
        self.form_project.set_data(project_data)

        self.update_plot()

    def load_project_longitudinal(self, project_id: int):
        """Clic sur le nœud projet : bascule la vue centrale vers le profil en long agrégé
        (vue de contrôle en lecture seule, sans formulaire ni recalcul). Le panneau de
        formulaires est entièrement masqué : le graphique occupe alors toute la largeur
        disponible et il n'y a plus de poignée de scission à faire glisser pour le cacher."""
        self.current_profile_id = None
        self.forms_stack.hide()
        self.plot_view.lbl_title.setText("Profil en long du projet")

        rows = self.db_manager.get_longitudinal_data(project_id)
        fig = self.controller.build_longitudinal_figure(rows)
        self.plot_view.update_plot(fig)

    def save_and_update_plot(self, _=None):
        if self.current_profile_id is None: return
        existing_data = self.form_existing.get_data()
        project_data = self.form_project.get_data()
        self.db_manager.save_profile_state(self.current_profile_id, existing_data, project_data)
        self.update_plot()

    def update_plot(self, _=None):
        if self.current_profile_id is None: return
        existing_data = self.form_existing.get_data()
        project_data = self.form_project.get_data()
        mode = self.TAB_MODES[self.tabs.currentIndex()]
        fig = self.controller.build_figure(
            existing_data, project_data, mode, show_overlay=self.chk_overlay.isChecked()
        )
        self.plot_view.update_plot(fig)