# ui/main_window.py
from html import escape

from PyQt6.QtWidgets import QMainWindow, QSplitter, QWidget, QVBoxLayout, QTabWidget, QStackedWidget, QLabel
from PyQt6.QtCore import Qt

from database.db_manager import DatabaseManager
from ui.sidebar import Sidebar
from ui.forms.existing_form import ExistingProfileForm
from ui.forms.project_form import ProjectProfileForm
from ui.forms.hydraulics_form import HydraulicsForm
from ui.views.plot_view import PlotView
from ui import theme

from core.controller import ProfileController, ViewMode

class MainWindow(QMainWindow):
    TAB_MODES = [ViewMode.EXISTING, ViewMode.PROJECT, ViewMode.HYDRAULICS]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("HydroTopo — Profils en travers")
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
        welcome_layout.setContentsMargins(
            theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG
        )
        # Les deux libellés doivent se lire comme un seul bloc centré verticalement :
        # sans ces étirements, le layout les répartirait sur toute la hauteur.
        welcome_layout.setSpacing(theme.SPACE_SM)
        welcome_layout.addStretch()
        lbl_welcome = QLabel("Aucun profil sélectionné")
        lbl_welcome.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_welcome.setStyleSheet(theme.qss(
            "color: $TEXT_SECONDARY; font-size: ${FONT_SIZE_TITLE}px; font-weight: bold;"
        ))
        welcome_layout.addWidget(lbl_welcome)

        lbl_welcome_hint = QLabel(
            "Choisissez un projet pour son profil en long,\n"
            "ou un PK pour éditer son profil en travers."
        )
        lbl_welcome_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_welcome_hint.setStyleSheet(theme.qss(
            "color: $TEXT_MUTED; font-size: ${FONT_SIZE_BASE}px;"
        ))
        welcome_layout.addWidget(lbl_welcome_hint)
        welcome_layout.addStretch()
        self.forms_stack.addWidget(welcome_widget)
        
        # Index 1 : Les vrais formulaires
        forms_widget = QWidget()
        forms_layout = QVBoxLayout(forms_widget)
        # Marge droite réduite : le panneau du graphique apporte déjà la sienne juste après.
        forms_layout.setContentsMargins(
            theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_SM, theme.SPACE_LG
        )
        forms_layout.setSpacing(theme.SPACE_MD)

        # Bandeau de contexte : rappelle en permanence quel profil est en cours d'édition,
        # information qui n'existait jusqu'ici que dans la sélection de l'arborescence.
        self.lbl_context = QLabel()
        self.lbl_context.setVisible(False)
        self.lbl_context.setStyleSheet(theme.qss(
            "font-size: ${FONT_SIZE_TITLE}px; padding-bottom: ${SPACE_SM}px;"
            "border-bottom: 1px solid $BORDER;"
        ))
        forms_layout.addWidget(self.lbl_context)

        self.tabs = QTabWidget()
        
        self.form_existing = ExistingProfileForm()
        self.form_project = ProjectProfileForm()
        self.form_hydraulics = HydraulicsForm()

        self.tabs.addTab(self.form_existing, "Profil existant")
        self.tabs.addTab(self.form_project, "Profil projet")
        self.tabs.addTab(self.form_hydraulics, "Hydraulique")
        forms_layout.addWidget(self.tabs)

        self.forms_stack.addWidget(forms_widget)

        work_splitter.addWidget(self.forms_stack)

        # 2b. Panneau du graphique (Toujours visible pour éviter le clignotement OpenGL)
        self.plot_view = PlotView()
        # Largeur minimum : le graphique ne doit jamais devenir illisible si la fenêtre
        # ou le panneau de gauche prennent trop de place.
        self.plot_view.setMinimumWidth(500)
        work_splitter.addWidget(self.plot_view)

        self._work_splitter = work_splitter

        # On impose la répartition de l'espace au démarrage
        main_splitter.setSizes([250, 1150])
        work_splitter.setSizes([450, 700])

        # Quand la fenêtre est agrandie, tout l'espace en plus va au graphique : la sidebar
        # et le panneau de formulaires gardent leur taille (stretch 0), seul le panneau de
        # travail puis le graphique en son sein ont un stretch non nul. Sans ça, l'espace
        # supplémentaire se répartissait proportionnellement partout, y compris sur des
        # panneaux qui n'en ont pas besoin, laissant le graphique disproportionnellement
        # à l'étroit sur un grand écran.
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        work_splitter.setStretchFactor(0, 0)
        work_splitter.setStretchFactor(1, 1)

        # Poignées non redimensionnables à la souris (juste visibles) : les proportions
        # ci-dessus restent la seule base de calcul pour un redimensionnement manuel.
        main_splitter.handle(1).setEnabled(False)
        work_splitter.handle(1).setEnabled(False)

        # Connexions
        self.sidebar.profile_selected.connect(self.load_profile)
        self.sidebar.project_selected.connect(self.load_project_longitudinal)
        self.form_existing.data_changed.connect(self.save_and_update_plot)
        self.form_project.data_changed.connect(self.save_and_update_plot)
        self.form_hydraulics.data_changed.connect(self.save_and_update_plot)
        self.tabs.currentChanged.connect(self.on_tab_changed)

    def on_tab_changed(self, index: int):
        self.update_plot()

    def _update_context_bar(self, context):
        """Affiche "<projet> › PK <nom>" au-dessus des onglets, ou masque le bandeau si
        aucun profil n'est sélectionné. Les libellés viennent de la saisie utilisateur,
        d'où l'échappement HTML avant de les injecter dans le texte enrichi du QLabel."""
        if not context:
            self.lbl_context.setVisible(False)
            return

        project_name, pk_name = (escape(part) for part in context)
        self.lbl_context.setText(
            f'<span style="color:{theme.TEXT_SECONDARY}">{project_name}</span>'
            f'<span style="color:{theme.TEXT_MUTED}"> &rsaquo; </span>'
            f'<span style="color:{theme.TEXT_PRIMARY}; font-weight:bold">PK {pk_name}</span>'
        )
        self.lbl_context.setVisible(True)

    def load_profile(self, profile_id: int):
        self.current_profile_id = profile_id

        # Dès qu'on clique sur un profil, on révèle les formulaires à côté du graphique
        self.forms_stack.show()
        self.forms_stack.setCurrentIndex(1)
        self._work_splitter.setSizes([450, 700])
        self.plot_view.lbl_title.setText("Visualisation de la coupe transversale")
        self._update_context_bar(self.sidebar.current_context())

        existing_data, project_data = self.db_manager.load_profile_state(profile_id)

        self.form_existing.set_data(existing_data)
        self.form_project.set_existing_points(existing_data)
        if not project_data:
            project_data = self.controller.default_project_params()
        self.form_project.set_data(project_data)
        self.form_hydraulics.set_data(project_data)

        self.update_plot()

    def load_project_longitudinal(self, project_id: int):
        """Clic sur le nœud projet : bascule la vue centrale vers le profil en long agrégé
        (vue de contrôle en lecture seule, sans formulaire ni recalcul). Le panneau de
        formulaires est entièrement masqué : le graphique occupe alors toute la largeur
        disponible et il n'y a plus de poignée de scission à faire glisser pour le cacher."""
        self.current_profile_id = None
        self.forms_stack.hide()
        self._update_context_bar(None)
        self.plot_view.lbl_title.setText("Profil en long du projet")

        rows = self.db_manager.get_longitudinal_data(project_id)
        fig = self.controller.build_longitudinal_figure(rows)
        self.plot_view.update_plot(fig)

    def save_and_update_plot(self, _=None):
        if self.current_profile_id is None: return
        existing_data = self.form_existing.get_data()
        self.form_project.set_existing_points(existing_data)
        # Un seul blob project_params en base : les champs hydrauliques (slope, ks_pro,
        # calc_mode, q_target, h_eau, hydro_source, show_overlay) y sont fusionnés.
        project_data = {**self.form_project.get_data(), **self.form_hydraulics.get_data()}
        self.db_manager.save_profile_state(self.current_profile_id, existing_data, project_data)
        self.update_plot()

    def update_plot(self, _=None):
        if self.current_profile_id is None: return
        existing_data = self.form_existing.get_data()
        project_data = {**self.form_project.get_data(), **self.form_hydraulics.get_data()}
        mode = self.TAB_MODES[self.tabs.currentIndex()]

        if mode is ViewMode.PROJECT:
            show_overlay = self.form_project.get_data()['show_overlay']
        elif mode is ViewMode.HYDRAULICS:
            show_overlay = self.form_hydraulics.get_data()['show_overlay']
        else:
            show_overlay = False

        try:
            fig = self.controller.build_figure(
                existing_data, project_data, mode, show_overlay=show_overlay
            )
        except ValueError as e:
            self.plot_view.update_plot(None, error_message=str(e))
            return

        self.plot_view.update_plot(fig)