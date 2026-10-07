# ui/main_window.py
import re
from html import escape

from PyQt6.QtWidgets import (QMainWindow, QSplitter, QWidget, QVBoxLayout, QTabWidget, QStackedWidget,
                             QLabel, QFileDialog, QMessageBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut

from core.excel_export import export_project_profile
from core.utils import LOGO_FILE_NAME, get_assets_dir
from database.db_manager import DatabaseManager
from ui.sidebar import Sidebar
from ui.forms.existing_form import ExistingProfileForm
from ui.forms.project_form import ProjectProfileForm
from ui.forms.hydraulics_form import HydraulicsForm
from ui.views.plot_view import PlotView
from ui.views.home_view import RECENT_PROJECTS_COUNT, HomeView
from ui.views.project_summary_view import ProjectSummaryView
from ui import theme

from core.controller import ProfileController, ViewMode

class MainWindow(QMainWindow):
    TAB_MODES = [ViewMode.EXISTING, ViewMode.PROJECT, ViewMode.HYDRAULICS]

    # Textes (titre, aide) affichés à la place des formulaires quand la zone Draft est
    # sélectionnée. Quand rien n'est sélectionné, c'est la page d'accueil (HomeView).
    WELCOME_DRAFT_ZONE = (
        "Zone Draft",
        "Brouillons de test, sans lien avec les projets.\n"
        "Choisissez un brouillon, ou créez-en un avec « + Nouveau Profil ».",
    )

    def __init__(self):
        super().__init__()
        self.setWindowTitle("HydroTopo — Profils en travers")
        self.resize(1400, 800)
        self.db_manager = DatabaseManager()
        self.controller = ProfileController()
        # Élément ouvert dans le formulaire : ("profile", id) pour un profil de scénario,
        # ("draft", id) pour un brouillon de la zone Draft, ou None. Le type est
        # indispensable : les ids des deux tables se recoupent, et un brouillon ne doit
        # jamais être enregistré dans la table des profils (ni l'inverse).
        self._current_target = None
        
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(main_splitter)
        
        # 1. Panneau latéral gauche
        self.sidebar = Sidebar(self.db_manager)
        main_splitter.addWidget(self.sidebar)
        
        # 2. Zone de travail. Elle alterne avec le récapitulatif du projet, affiché à sa
        # place quand on clique sur un projet, et avec la page d'accueil, affichée quand rien
        # n'est sélectionné (au lancement notamment).
        self.work_stack = QStackedWidget()
        main_splitter.addWidget(self.work_stack)
        work_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.work_stack.addWidget(work_splitter)
        self.summary_view = ProjectSummaryView()
        self.work_stack.addWidget(self.summary_view)
        self.home_view = HomeView(get_assets_dir() / LOGO_FILE_NAME)
        self.work_stack.addWidget(self.home_view)
        # Projet dont le récapitulatif est affiché, ou None.
        self._summary_project_id = None
        
        # 2a. Panneau des formulaires (Caché au démarrage via StackedWidget)
        self.forms_stack = QStackedWidget()
        
        # Index 0 : Message (zone Draft sélectionnée) à la place des formulaires vides
        welcome_widget = QWidget()
        welcome_layout = QVBoxLayout(welcome_widget)
        welcome_layout.setContentsMargins(
            theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG
        )
        # Les deux libellés doivent se lire comme un seul bloc centré verticalement :
        # sans ces étirements, le layout les répartirait sur toute la hauteur.
        welcome_layout.setSpacing(theme.SPACE_SM)
        welcome_layout.addStretch()
        self.lbl_welcome = QLabel()
        self.lbl_welcome.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_welcome.setStyleSheet(theme.qss(
            "color: $TEXT_SECONDARY; font-size: ${FONT_SIZE_TITLE}px; font-weight: bold;"
        ))
        welcome_layout.addWidget(self.lbl_welcome)

        self.lbl_welcome_hint = QLabel()
        self.lbl_welcome_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_welcome_hint.setStyleSheet(theme.qss(
            "color: $TEXT_MUTED; font-size: ${FONT_SIZE_BASE}px;"
        ))
        welcome_layout.addWidget(self.lbl_welcome_hint)
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

        # Largeur minimum : sous ce seuil, les colonnes Gauche/Droite du profil projet
        # (Banquette/Berges/Lit majeur) et les boutons de raccord ne tiennent plus et se
        # retrouvent coupés (la zone de formulaires n'a pas de barre de défilement
        # horizontale, elle se contente de rétrécir son contenu).
        self.forms_stack.setMinimumWidth(650)
        work_splitter.addWidget(self.forms_stack)

        # 2b. Panneau du graphique (Toujours visible pour éviter le clignotement OpenGL)
        self.plot_view = PlotView()
        # Largeur minimum : le graphique ne doit jamais devenir illisible si la fenêtre
        # ou le panneau de gauche prennent trop de place.
        self.plot_view.setMinimumWidth(500)
        work_splitter.addWidget(self.plot_view)

        self._main_splitter = main_splitter
        self._work_splitter = work_splitter

        # Graphique agrandi (bouton "Agrandir") : barre latérale et formulaires masqués.
        # On retient ce qui était affiché pour le rétablir tel quel (au profil en long, les
        # formulaires sont déjà masqués et doivent le rester). Échap ramène à l'affichage
        # normal ; le raccourci n'est actif que pendant l'agrandissement, pour ne rien
        # intercepter le reste du temps.
        self._plot_expanded = False
        self._layout_before_expand = None
        self._exit_expanded_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._exit_expanded_shortcut.setEnabled(False)
        self._exit_expanded_shortcut.activated.connect(self.toggle_plot_expanded)

        # On impose la répartition de l'espace au démarrage : le panneau de formulaires
        # est élargi pour que ses deux colonnes Gauche/Droite tiennent entièrement, au
        # prix d'une largeur réduite (mais toujours lisible, cf. setMinimumWidth ci-dessus)
        # pour le graphique.
        main_splitter.setSizes([250, 1150])
        work_splitter.setSizes([650, 500])

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
        self.sidebar.draft_selected.connect(self.load_draft)
        self.sidebar.scenario_selected.connect(self.load_scenario_longitudinal)
        self.sidebar.project_selected.connect(self.show_project_summary)
        self.summary_view.scenario_activated.connect(self.sidebar.select_scenario)
        self.sidebar.tree_refreshed.connect(self._refresh_project_summary)
        self.sidebar.tree_refreshed.connect(self._refresh_home)
        self.sidebar.draft_zone_selected.connect(lambda: self.show_placeholder(*self.WELCOME_DRAFT_ZONE))
        self.sidebar.selection_cleared.connect(self.show_home)
        # Actions rapides de la page d'accueil : exactement celles de la barre latérale.
        self.home_view.new_project_requested.connect(self.sidebar.add_project)
        self.home_view.import_requested.connect(self.sidebar.import_file)
        self.home_view.project_activated.connect(self.sidebar.select_project)
        self.sidebar.project_data_changed.connect(self._on_project_data_changed)
        self.sidebar.context_changed.connect(
            lambda: self._update_context_bar(self.sidebar.current_context())
        )
        self.form_existing.data_changed.connect(self.save_and_update_plot)
        self.form_project.data_changed.connect(self.save_and_update_plot)
        self.form_hydraulics.data_changed.connect(self.save_and_update_plot)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.form_project.export_excel_requested.connect(self.export_project_excel)
        self.plot_view.expand_toggled.connect(self.toggle_plot_expanded)

        # Rien n'est sélectionné au lancement.
        self.show_home()

    def toggle_plot_expanded(self):
        """Bouton "Agrandir" / "Réduire" (ou Échap) : le graphique occupe toute la fenêtre,
        ou retrouve sa place. Le graphique note d'abord la vue affichée, pour garder le
        zoom en cours malgré le changement de taille (cf. PlotView.prepare_layout_change)."""
        expand = not self._plot_expanded
        self.plot_view.prepare_layout_change(lambda: self._set_plot_expanded(expand))

    def _set_plot_expanded(self, expanded: bool):
        if expanded == self._plot_expanded:
            return
        if expanded:
            self._layout_before_expand = (
                not self.sidebar.isHidden(), not self.forms_stack.isHidden(),
                self._main_splitter.sizes(), self._work_splitter.sizes(),
            )
            self.sidebar.hide()
            self.forms_stack.hide()
        else:
            sidebar_shown, forms_shown, main_sizes, work_sizes = self._layout_before_expand
            self.sidebar.setVisible(sidebar_shown)
            self.forms_stack.setVisible(forms_shown)
            self._main_splitter.setSizes(main_sizes)
            self._work_splitter.setSizes(work_sizes)
        self._plot_expanded = expanded
        self.plot_view.set_expanded(expanded)
        self._exit_expanded_shortcut.setEnabled(expanded)

    def export_project_excel(self):
        """Exporte le profil projet ouvert (points + paramètres) dans un classeur Excel
        choisi par l'utilisateur. Le nom proposé reprend celui du profil."""
        if self._current_target is None:
            return
        context = self.sidebar.current_context()
        base_name = re.sub(r'[\\/:*?"<>|]', "_", context[-1]) if context else "profil"
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter le profil projet", f"{base_name} - profil projet.xlsx",
            "Classeur Excel (*.xlsx)",
        )
        if not path:
            return
        try:
            export_project_profile(path, self.form_project.get_data(), context)
        except ValueError as e:
            QMessageBox.warning(self, "Export impossible", str(e))
        except OSError as e:
            QMessageBox.warning(
                self, "Export impossible",
                f"Impossible d'écrire le fichier (est-il ouvert dans Excel ?)\n\n{e}",
            )

    def _on_project_data_changed(self, project_id: int):
        """Points durs ou distance modifiés : la pente calculée (et la distance) du profil
        ouvert a pu changer en base ; on le recharge pour l'afficher à jour. Idem pour le
        récapitulatif du projet s'il est affiché."""
        if self._current_target is not None and self._current_target[0] == "profile":
            self._open_editor(self._current_target)
        elif self._summary_project_id == project_id:
            self.show_project_summary(project_id)

    def show_project_summary(self, project_id: int):
        """Clic sur un projet : récapitulatif de ses scénarios à la place des formulaires et
        du graphique (cf. ProjectSummaryView), recalculé à chaque affichage depuis les
        profils enregistrés."""
        self._current_target = None
        self._update_context_bar(None)
        labels = self.sidebar.selection_labels()
        name = labels[0] if labels else ""
        scenarios = [
            (s["id"], s["name"], self.db_manager.get_scenario_profile_states(s["id"]))
            for s in self.db_manager.get_scenarios(project_id)
        ]
        summary = self.controller.project_summary(
            name, self.db_manager.get_hard_points(project_id), scenarios
        )
        self.summary_view.set_summary(summary)
        self._summary_project_id = project_id
        self.work_stack.setCurrentWidget(self.summary_view)

    def _refresh_project_summary(self):
        """Scénario créé, renommé ou supprimé (ou projet renommé) pendant que le
        récapitulatif est affiché : il est recalculé."""
        if self._summary_project_id is not None:
            self.show_project_summary(self._summary_project_id)

    def show_home(self):
        """Rien de sélectionné (lancement, élément ouvert supprimé ou archivé) : page
        d'accueil à la place de toute la zone de travail, projets récents à jour."""
        self._current_target = None
        self._summary_project_id = None
        self._update_context_bar(None)
        self.work_stack.setCurrentWidget(self.home_view)
        self._refresh_home()

    def _refresh_home(self):
        """Relit en base les projets récents de la page d'accueil si elle est affichée
        (projet créé, renommé, supprimé, archivé ou restauré depuis la barre latérale)."""
        if self.work_stack.currentWidget() is not self.home_view:
            return
        self.home_view.set_recent_projects(
            self.db_manager.get_recent_projects(RECENT_PROJECTS_COUNT),
            archived_count=len(self.db_manager.get_archived_projects()),
        )

    def _show_work_area(self):
        """Formulaires et graphique à la place du récapitulatif de projet."""
        self._summary_project_id = None
        self.work_stack.setCurrentWidget(self._work_splitter)

    def show_startup_messages(self):
        """Bilan de la migration vers les points durs multiples, affiché une seule fois
        (au premier lancement après la mise à jour)."""
        message = self.db_manager.startup_slope_report.message()
        if message:
            QMessageBox.information(self, "Mise à jour des pentes hydrauliques", message)

    def on_tab_changed(self, index: int):
        self.update_plot()

    def _update_context_bar(self, context):
        """Affiche "<projet> › <scénario> › <nom du profil>" (ou "Draft › <brouillon>")
        au-dessus des onglets, ou masque le bandeau si aucun profil n'est sélectionné. Les
        libellés viennent de la saisie utilisateur, d'où l'échappement HTML avant de les
        injecter dans le texte enrichi du QLabel."""
        if not context:
            self.lbl_context.setVisible(False)
            return

        *parents, leaf = (escape(part) for part in context)
        separator = f'<span style="color:{theme.TEXT_MUTED}"> &rsaquo; </span>'
        parts = [f'<span style="color:{theme.TEXT_SECONDARY}">{name}</span>' for name in parents]
        parts.append(f'<span style="color:{theme.TEXT_PRIMARY}; font-weight:bold">{leaf}</span>')
        self.lbl_context.setText(separator.join(parts))
        self.lbl_context.setVisible(True)

    def _set_welcome_text(self, title: str, hint: str):
        self.lbl_welcome.setText(title)
        self.lbl_welcome_hint.setText(hint)

    def show_placeholder(self, title: str, hint: str):
        """Rien à éditer ni à tracer (zone Draft sélectionnée) : message à la place des
        formulaires, graphique vidé."""
        self._current_target = None
        self._show_work_area()
        self._update_context_bar(None)
        self._set_welcome_text(title, hint)
        self.forms_stack.show()
        self.forms_stack.setCurrentIndex(0)
        self._work_splitter.setSizes([650, 500])
        self.plot_view.lbl_title.setText("Visualisation de la coupe transversale")
        self.plot_view.update_plot(None, error_message=title)

    def load_profile(self, profile_id: int):
        self._open_editor(("profile", profile_id))

    def load_draft(self, draft_id: int):
        """Un brouillon s'édite avec exactement le même formulaire qu'un profil ; seule la
        table de stockage change (cf. _load_state / _save_state)."""
        self._open_editor(("draft", draft_id))

    def _load_state(self, target):
        kind, row_id = target
        if kind == "draft":
            return self.db_manager.load_draft_state(row_id)
        return self.db_manager.load_profile_state(row_id)

    def _save_state(self, target, existing_data, project_data):
        kind, row_id = target
        if kind == "draft":
            self.db_manager.save_draft_state(row_id, existing_data, project_data)
        else:
            self.db_manager.save_profile_state(row_id, existing_data, project_data)

    def _open_editor(self, target):
        self._current_target = target
        self._show_work_area()

        # Dès qu'on clique sur un profil, on révèle les formulaires à côté du graphique
        self.forms_stack.show()
        self.forms_stack.setCurrentIndex(1)
        self._work_splitter.setSizes([650, 500])
        self.plot_view.lbl_title.setText("Visualisation de la coupe transversale")
        self._update_context_bar(self.sidebar.current_context())

        existing_data, project_data = self._load_state(target)

        self.form_existing.set_data(existing_data)
        self.form_project.set_existing_points(existing_data)
        self.form_hydraulics.set_existing_points(existing_data)
        # Valeurs par défaut complétées par celles enregistrées : un profil jamais ouvert
        # peut n'avoir que quelques clés en base (ex. son mode de pente), et les formulaires
        # ne doivent pas garder pour les autres les valeurs du profil précédent.
        project_data = {**self.controller.default_project_params(), **(project_data or {})}
        self.form_project.set_data(project_data)
        self.form_hydraulics.set_data(project_data)
        kind, row_id = target
        if kind == "profile":
            self.form_hydraulics.set_slope_info(self.db_manager.profile_slope_info(row_id))
        else:
            self.form_hydraulics.set_slope_info(None, is_draft=True)

        self.update_plot()

    def load_scenario_longitudinal(self, scenario_id: int):
        """Clic sur un scénario : bascule la vue centrale vers le profil en long agrégé de
        ses profils (vue de contrôle en lecture seule, sans formulaire ni recalcul), avec
        les points durs de son projet (communs à tous les scénarios). Le panneau de
        formulaires est entièrement masqué : le graphique occupe alors toute la largeur
        disponible et il n'y a plus de poignée de scission à faire glisser pour le cacher."""
        self._current_target = None
        self._show_work_area()
        self.forms_stack.hide()
        self._update_context_bar(None)
        self.plot_view.lbl_title.setText("Profil en long du scénario")
        labels = self.sidebar.selection_labels()
        self.plot_view.export_name = f"{labels[-1]} - Profil en long" if labels else "Profil en long"
        self.plot_view.export_caption = (
            " › ".join(labels) + " — Profil en long" if labels else "Profil en long"
        )

        rows = self.db_manager.get_longitudinal_data(scenario_id)
        project_id = self.db_manager.get_scenario_project_id(scenario_id)
        hard_points = self.db_manager.get_hard_points(project_id) if project_id is not None else []
        earthworks = self.controller.station_earthworks(
            self.db_manager.get_scenario_profile_states(scenario_id)
        )
        fig = self.controller.build_longitudinal_figure(rows, hard_points, earthworks)
        # Un zoom mémorisé par scénario, retrouvé au retour (cf. update_plot).
        self.plot_view.update_plot(fig, view_key=f"scenario:{scenario_id}:longitudinal")

    def save_and_update_plot(self, _=None):
        if self._current_target is None: return
        existing_data = self.form_existing.get_data()
        self.form_project.set_existing_points(existing_data)
        self.form_hydraulics.set_existing_points(existing_data)
        # Un seul blob project_params en base : les champs hydrauliques (slope, ks_pro,
        # calc_mode, q_target, h_eau, hydro_source...) y sont fusionnés. Les deux formulaires
        # ne doivent donc jamais partager une clé : la case "profil en fond" a la sienne dans
        # chaque onglet (show_overlay_project / show_overlay_hydraulics), sinon celle de
        # l'onglet Hydraulique écrasait celle du Profil projet à chaque enregistrement.
        project_data = {**self.form_project.get_data(), **self.form_hydraulics.get_data()}
        self._save_state(self._current_target, existing_data, project_data)
        self.update_plot()

    def update_plot(self, _=None):
        if self._current_target is None: return
        existing_data = self.form_existing.get_data()
        project_data = {**self.form_project.get_data(), **self.form_hydraulics.get_data()}
        mode = self.TAB_MODES[self.tabs.currentIndex()]

        if mode is ViewMode.PROJECT:
            show_overlay = self.form_project.get_data()['show_overlay_project']
        elif mode is ViewMode.HYDRAULICS:
            show_overlay = self.form_hydraulics.get_data()['show_overlay_hydraulics']
        else:
            show_overlay = False

        try:
            fig = self.controller.build_figure(
                existing_data, project_data, mode, show_overlay=show_overlay
            )
        except ValueError as e:
            self.plot_view.update_plot(None, error_message=str(e))
            return

        # Une vue par (profil ou brouillon, onglet) : son zoom est mémorisé par le graphique
        # et retrouvé au retour (ex. après un passage par le profil en long).
        kind, row_id = self._current_target
        context = self.sidebar.current_context()
        tab_label = self.tabs.tabText(self.tabs.currentIndex())
        self.plot_view.export_name = f"{context[-1]} - {tab_label}" if context else tab_label
        self.plot_view.export_caption = (
            " › ".join(context) + f" — {tab_label}" if context else tab_label
        )
        self.plot_view.update_plot(fig, view_key=f"{kind}:{row_id}:{mode.value}")