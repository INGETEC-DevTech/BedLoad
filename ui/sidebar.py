# ui/sidebar.py
from html import escape
from typing import List, Optional, Tuple

from PyQt6.QtWidgets import (QTreeView, QVBoxLayout, QWidget, QPushButton,
                             QInputDialog, QMessageBox, QMenu, QApplication, QStyle,
                             QStyledItemDelegate, QDialog, QFileDialog)
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QFont, QColor, QPainter, QBrush, QPen
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QRectF
from database.db_manager import DatabaseManager, DEFAULT_SCENARIO_NAME
from core.hard_points import SlopeReport
from ui.dialogs.archives_dialog import ArchivesDialog
from ui.dialogs.hard_points_dialog import HardPointsDialog
from ui.dialogs.scenario_dialog import ScenarioDialog
from ui import theme

# Bornes/format des saisies de "distance au premier point dur" (nouveau profil, renommage,
# duplication) quand le projet n'a pas encore de zone couverte par ses points durs ; sinon,
# la saisie est bornée par cette zone (cf. Sidebar._prompt_distance).
_DISTANCE_MIN = -1_000_000.0
_DISTANCE_MAX = 1_000_000.0
_DISTANCE_DECIMALS = 3

# Types de nœuds de l'arborescence. Deux zones au premier niveau : les projets
# (Projet → Scénario → Profil) et la zone Draft (Draft → Brouillon), sans aucun lien
# entre elles.
PROJECT = "project"
SCENARIO = "scenario"
PROFILE = "profile"
DRAFT_ROOT = "draft_root"
DRAFT = "draft"
_EXPANDABLE_TYPES = (PROJECT, SCENARIO, DRAFT_ROOT)
# Nœuds qui ouvrent le formulaire complet (profil existant / projet / hydraulique).
_EDITABLE_TYPES = (PROFILE, DRAFT)
_DRAFT_ZONE_LABEL = "Draft"
_ARCHIVES_LABEL = "Archives"

# Valeur sentinelle choisie dans le sélecteur de destination d'un import/copie de profil
# (cf. _prompt_scenario_or_draft), pour la distinguer d'un id de scénario (entier).
_DRAFT_DESTINATION = "__draft__"
_DRAFT_DESTINATION_LABEL = "Draft (brouillons)"

# Libellés des trois formes de fichier d'export, pour les messages d'erreur d'import
# (cf. Sidebar._pick_import_file).
_TYPE_LABELS = {"profile": "profil", "scenario": "scénario", "project": "projet"}


def _key(data: dict) -> tuple:
    """Identifiant d'un nœud, stable d'un refresh_tree() à l'autre. Le type en fait
    partie car les ids des différentes tables (profils, brouillons...) se recoupent."""
    return (data["type"], data.get("id"))


class _TreeItemDelegate(QStyledItemDelegate):
    """Dessine les projets et la zone Draft comme des lignes de section discrètes
    (transparentes au repos, avec une barre bleue quand la section est "active"), les
    scénarios comme des sous-sections repliables, et les profils/brouillons comme des
    lignes imbriquées plus discrètes avec une puce colorée."""

    SECTION_ROW_HEIGHT = 38   # projet, zone Draft
    SCENARIO_ROW_HEIGHT = 32
    LEAF_ROW_HEIGHT = 30      # profil, brouillon

    # Zone cliquable du chevron (partagée avec _ProjectTreeView.mousePressEvent pour que
    # le hit-test corresponde exactement à ce qui est dessiné). L'indentation native est
    # désactivée : c'est ce décalage qui matérialise le niveau de chaque nœud repliable.
    CHEVRON_X_OFFSETS = {PROJECT: 10, DRAFT_ROOT: 10, SCENARIO: 26}
    CHEVRON_ZONE_WIDTH = 20
    # Position de la puce des feuilles, alignée sous le texte de leur parent.
    LEAF_DOT_X_OFFSETS = {PROFILE: 52, DRAFT: 36}

    def __init__(self, parent, sidebar):
        super().__init__(parent)
        self.sidebar = sidebar

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        node_type = (index.data(Qt.ItemDataRole.UserRole) or {}).get("type")
        if node_type in (PROJECT, DRAFT_ROOT):
            height = self.SECTION_ROW_HEIGHT
        elif node_type == SCENARIO:
            height = self.SCENARIO_ROW_HEIGHT
        else:
            height = self.LEAF_ROW_HEIGHT
        return QSize(size.width(), height)

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        data = index.data(Qt.ItemDataRole.UserRole) or {}
        node_type = data.get("type")
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        rect = option.rect
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""

        if node_type in (PROJECT, DRAFT_ROOT):
            self._paint_section_row(painter, rect, text, index, data, hovered)
        elif node_type == SCENARIO:
            self._paint_scenario_row(painter, rect, text, index, data, selected, hovered)
        else:
            self._paint_leaf_row(painter, rect, text, node_type, selected, hovered)

        painter.restore()

    def _paint_chevron(self, painter, rect, index, node_type) -> float:
        """Chevron d'expand/collapse. Seul un clic dans cette zone plie/déplie (cf.
        _ProjectTreeView.mousePressEvent) : cliquer ailleurs sur la ligne se contente de
        sélectionner le nœud. Retourne l'abscisse disponible juste après le chevron."""
        expanded = self.sidebar.tree_view.isExpanded(index)
        chevron_font = painter.font()
        chevron_font.setPointSize(12)
        chevron_font.setBold(True)
        painter.setFont(chevron_font)
        painter.setPen(QPen(QColor(theme.TEXT_SECONDARY)))
        chevron_x = rect.left() + self.CHEVRON_X_OFFSETS[node_type]
        painter.drawText(
            QRectF(chevron_x, rect.top(), self.CHEVRON_ZONE_WIDTH, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "▾" if expanded else "▸",
        )
        return chevron_x + self.CHEVRON_ZONE_WIDTH

    def _paint_section_row(self, painter, rect, text, index, data, hovered):
        """Un projet, ou la zone Draft. Un nœud est "actif" s'il vient d'être cliqué ou
        s'il contient l'élément actuellement sélectionné (cf. Sidebar.is_active)."""
        is_active = self.sidebar.is_active(data)

        # La zone Draft est séparée des projets par un filet : même niveau dans l'arbre,
        # mais un espace à part, sans lien avec eux.
        if data.get("type") == DRAFT_ROOT:
            painter.setPen(QPen(QColor(theme.BORDER)))
            painter.drawLine(rect.left() + 8, rect.top() + 1, rect.right() - 8, rect.top() + 1)

        # Repos : fond transparent, rien à dessiner. Survol : léger fond gris, feedback
        # transitoire seulement. Actif : pas de bandeau plein, juste une fine barre à gauche.
        if hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(theme.HOVER)))
            painter.drawRoundedRect(QRectF(rect.adjusted(4, 3, -4, -3)), 6, 6)

        if is_active:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(theme.PRIMARY)))
            painter.drawRoundedRect(QRectF(rect.left() + 1, rect.top() + 2, 3, rect.height() - 4), 1.5, 1.5)

        text_color = QColor(theme.PRIMARY_TEXT) if is_active else QColor(theme.TEXT_PRIMARY)

        x = self._paint_chevron(painter, rect, index, data["type"])
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon:
            icon_size = 16
            icon.paint(painter, int(x), rect.center().y() - icon_size // 2, icon_size, icon_size)
            x += icon_size + 8

        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(text_color))
        painter.drawText(
            QRectF(x, rect.top(), rect.right() - x - 8, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text,
        )

    def _paint_scenario_row(self, painter, rect, text, index, data, selected, hovered):
        # Niveau intermédiaire : fond léger au survol/sélection comme les profils, mais
        # repliable (chevron) et en texte plein pour se lire comme l'en-tête de ses profils.
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(theme.PRIMARY_LIGHT)))
            painter.drawRoundedRect(QRectF(rect.adjusted(4, 2, -4, -2)), 6, 6)
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(theme.BACKGROUND)))
            painter.drawRoundedRect(QRectF(rect.adjusted(4, 2, -4, -2)), 6, 6)

        is_active = self.sidebar.is_active(data)
        x = self._paint_chevron(painter, rect, index, SCENARIO)

        # Le chevron a grossi la police du painter : on revient à la taille normale, les
        # scénarios devant rester visuellement sous leur projet.
        font = painter.font()
        font.setPointSize(QFont().pointSize())
        font.setBold(is_active)
        painter.setFont(font)
        painter.setPen(QPen(QColor(theme.PRIMARY_TEXT) if is_active else QColor(theme.TEXT_PRIMARY)))
        painter.drawText(
            QRectF(x, rect.top(), rect.right() - x - 8, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text,
        )

    def _paint_leaf_row(self, painter, rect, text, node_type, selected, hovered):
        # Pas de bandeau plein ici : seulement une puce + un fond léger au survol/sélection,
        # pour rester visuellement "sous" le parent plutôt qu'à son niveau.
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(theme.PRIMARY_LIGHT)))
            painter.drawRoundedRect(QRectF(rect.adjusted(4, 2, -4, -2)), 6, 6)
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(theme.BACKGROUND)))
            painter.drawRoundedRect(QRectF(rect.adjusted(4, 2, -4, -2)), 6, 6)

        dot_color = QColor(theme.PRIMARY) if selected else QColor(theme.TEXT_MUTED)
        dot_size = 6
        dot_x = rect.left() + self.LEAF_DOT_X_OFFSETS.get(node_type, 36)
        dot_y = rect.center().y()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(dot_color))
        painter.drawEllipse(QRectF(dot_x - dot_size / 2, dot_y - dot_size / 2, dot_size, dot_size))

        text_color = QColor(theme.PRIMARY_TEXT) if selected else QColor(theme.TEXT_SECONDARY)
        font = painter.font()
        font.setBold(selected)
        painter.setFont(font)
        painter.setPen(QPen(text_color))

        text_x = dot_x + 14
        painter.drawText(
            QRectF(text_x, rect.top(), rect.right() - text_x - 8, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text,
        )


class _ProjectTreeView(QTreeView):
    """QTreeView où seul un clic sur le chevron (dessiné par _TreeItemDelegate) plie/déplie
    un nœud ; cliquer ailleurs sur la ligne se contente de la sélectionner, sans toggle."""

    def mousePressEvent(self, event):
        index = self.indexAt(event.pos())
        if index.isValid():
            node_type = (index.data(Qt.ItemDataRole.UserRole) or {}).get("type")
            offset = _TreeItemDelegate.CHEVRON_X_OFFSETS.get(node_type)
            if offset is not None:
                chevron_left = self.visualRect(index).left() + offset
                chevron_right = chevron_left + _TreeItemDelegate.CHEVRON_ZONE_WIDTH
                if chevron_left <= event.pos().x() <= chevron_right:
                    self.setExpanded(index, not self.isExpanded(index))
                    return

        super().mousePressEvent(event)


class Sidebar(QWidget):
    # Signal émis lorsqu'un profil d'un scénario est sélectionné dans l'arbre
    profile_selected = pyqtSignal(int)
    # Signal émis lorsqu'un scénario est sélectionné (vue : son profil en long)
    scenario_selected = pyqtSignal(int)
    # Signal émis lorsqu'un projet (nœud racine) est sélectionné dans l'arbre
    project_selected = pyqtSignal(int)
    # Signal émis lorsqu'un brouillon de la zone Draft est sélectionné
    draft_selected = pyqtSignal(int)
    # Signal émis lorsque le nœud racine de la zone Draft est sélectionné
    draft_zone_selected = pyqtSignal()
    # L'élément sélectionné n'existe plus (supprimé, lui ou l'un de ses parents)
    selection_cleared = pyqtSignal()
    # Les libellés du bandeau de contexte ont changé (renommage de l'élément ouvert...)
    context_changed = pyqtSignal()
    # Points durs ou distance d'un profil modifiés : pentes calculées et positions des
    # profils de ce projet ont pu changer (MainWindow recharge le profil ouvert).
    project_data_changed = pyqtSignal(int)
    # Arborescence reconstruite (création, renommage, suppression...) : ce qui en résume le
    # contenu (récapitulatif d'un projet) est à recalculer.
    tree_refreshed = pyqtSignal()

    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db_manager
        # Chemin (données des nœuds, de la racine jusqu'à l'élément) de la sélection
        # courante. Les nœuds de ce chemin sont "actifs" (barre bleue du delegate), et il
        # survit à un refresh_tree() : c'est lui qui permet de retrouver la sélection, ou
        # de constater qu'elle a été supprimée.
        self._active_path = []
        # Clés des nœuds explicitement dépliés/repliés par l'utilisateur, pour survivre
        # à un refresh_tree() (ajout/suppression/renommage) sans tout refermer.
        self._expanded_keys = set()
        # Clés déjà vues au moins une fois : un nœud absent de cet ensemble est "nouveau"
        # et sera déplié par défaut lors de son premier affichage.
        self._known_keys = set()
        # Libellés (projet, scénario, profil) ou ("Draft", brouillon) de la sélection
        # courante, pour le bandeau de contexte.
        self._context_labels = None
        # Libellés de tout le chemin du nœud sélectionné, quel que soit son type (ex.
        # (projet, scénario) pour un scénario), ou None.
        self._selection_labels = None

        # 1. Contraste : Fond légèrement grisé pour détacher le panneau
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(theme.qss(
            "Sidebar { background-color: $BACKGROUND; border-right: 1px solid $BORDER; }"
        ))

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(
            theme.SPACE_LG, theme.SPACE_XL, theme.SPACE_LG, theme.SPACE_LG
        )
        self.main_layout.setSpacing(theme.SPACE_MD)

        # 2. Boutons d'action : Primaire et Secondaires
        self.btn_add_project = QPushButton("+ Nouveau Projet")
        self.btn_add_project.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_project.setStyleSheet(theme.qss("""
            QPushButton { background-color: $PRIMARY; color: $SURFACE; border: none; border-radius: ${RADIUS_MD}px; padding: ${SPACE_SM}px ${SPACE_MD}px; font-weight: bold; }
            QPushButton:hover { background-color: $PRIMARY_HOVER; }
            QPushButton:pressed { background-color: $PRIMARY_PRESSED; }
        """))

        secondary_qss = theme.qss("""
            QPushButton { background-color: $SURFACE; color: $TEXT_SECONDARY; border: 1px solid $BORDER_INPUT; border-radius: ${RADIUS_MD}px; padding: ${SPACE_SM}px ${SPACE_MD}px; font-weight: bold; }
            QPushButton:hover { background-color: $BACKGROUND; border-color: $BORDER_HOVER; }
            QPushButton:pressed { background-color: $HOVER; }
        """)
        self.btn_add_scenario = QPushButton("+ Nouveau Scénario")
        self.btn_add_scenario.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_scenario.setStyleSheet(secondary_qss)

        self.btn_add_profile = QPushButton("+ Nouveau Profil")
        self.btn_add_profile.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_profile.setToolTip(
            "Ajoute un profil au scénario sélectionné, ou un brouillon si la zone Draft est sélectionnée."
        )
        self.btn_add_profile.setStyleSheet(secondary_qss)

        self.btn_import = QPushButton("Importer...")
        self.btn_import.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_import.setToolTip(
            "Importe un fichier .json exporté depuis HydroTopo (profil, scénario ou projet)."
        )
        self.btn_import.setStyleSheet(secondary_qss)

        # Le nombre de projets archivés est ajouté au libellé par refresh_tree().
        self.btn_archives = QPushButton(_ARCHIVES_LABEL)
        self.btn_archives.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_archives.setToolTip(
            "Projets archivés : rangés hors de cette liste, à restaurer pour les rouvrir."
        )
        self.btn_archives.setStyleSheet(secondary_qss)

        self.main_layout.addWidget(self.btn_add_project)
        self.main_layout.addWidget(self.btn_add_scenario)
        self.main_layout.addWidget(self.btn_add_profile)
        self.main_layout.addWidget(self.btn_import)
        self.main_layout.addWidget(self.btn_archives)

        # 3. Arborescence épurée
        self.tree_view = _ProjectTreeView()
        self.tree_view.setHeaderHidden(True)
        self.tree_view.setFocusPolicy(Qt.FocusPolicy.NoFocus) # Retire le cadre pointillé au clic
        self.tree_view.setMouseTracking(True)  # nécessaire pour l'état "survol" du delegate
        self.tree_view.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tree_view.setItemDelegate(_TreeItemDelegate(self.tree_view, self))
        # La flèche native d'expand/collapse est désactivée : le thème Windows peint un carré
        # gris plein derrière elle qu'aucune règle QSS ne parvient à neutraliser. Le delegate
        # dessine son propre chevron à la place, et le pliage se déclenche par code
        # (clic sur le chevron, cf. _ProjectTreeView) plutôt que par ce contrôle natif.
        self.tree_view.setRootIsDecorated(False)
        self.tree_view.setIndentation(0)
        self.tree_view.setStyleSheet("""
            QTreeView { border: none; background-color: transparent; outline: none; }
        """)

        self.model = QStandardItemModel()
        self.tree_view.setModel(self.model)
        self.main_layout.addWidget(self.tree_view)

        # Activation du menu contextuel (clic droit)
        self.tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self.open_context_menu)

        # Connexions
        self.btn_add_project.clicked.connect(self.add_project)
        self.btn_add_scenario.clicked.connect(self.add_scenario)
        self.btn_add_profile.clicked.connect(self.add_profile)
        self.btn_import.clicked.connect(self.import_file)
        self.btn_archives.clicked.connect(self.open_archives)
        self.tree_view.clicked.connect(self.on_item_clicked)

        self.refresh_tree()

    # --- Parcours de l'arbre ---

    def _iter_items(self, parent: QStandardItem = None):
        """Tous les items de l'arbre, en profondeur."""
        if parent is None:
            parent = self.model.invisibleRootItem()
        for row in range(parent.rowCount()):
            child = parent.child(row)
            yield child
            yield from self._iter_items(child)

    def _find_item(self, key: tuple) -> Optional[QStandardItem]:
        for item in self._iter_items():
            if _key(item.data(Qt.ItemDataRole.UserRole)) == key:
                return item
        return None

    @staticmethod
    def _chain(item: QStandardItem) -> list:
        """Items de la racine jusqu'à `item` inclus."""
        chain = []
        while item is not None:
            chain.append(item)
            item = item.parent()
        return list(reversed(chain))

    def is_active(self, data: dict) -> bool:
        """Un nœud est "actif" s'il vient d'être cliqué, ou s'il contient l'élément
        actuellement sélectionné. Comme cliquer sur un nœud le met déjà à jour, l'état
        sélectionné natif de Qt et l'état actif coïncident pour l'élément cliqué : seul
        _active_path fait foi, pour lui comme pour ses parents."""
        key = _key(data)
        return any(_key(d) == key for d in self._active_path)

    # --- Construction de l'arbre ---

    def refresh_tree(self):
        """Recharge l'arbre depuis la base de données avec icônes et typographie."""
        # Mémorise l'état plié/déplié courant avant de tout reconstruire (le modèle est
        # entièrement recréé à chaque refresh, il ne peut donc pas porter cette info lui-même).
        for item in self._iter_items():
            data = item.data(Qt.ItemDataRole.UserRole)
            if data["type"] not in _EXPANDABLE_TYPES:
                continue
            if self.tree_view.isExpanded(self.model.indexFromItem(item)):
                self._expanded_keys.add(_key(data))
            else:
                self._expanded_keys.discard(_key(data))

        self.model.clear()

        # Récupération des icônes natives via le thème de l'application
        style = QApplication.style()
        icon_folder = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        icon_file = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        icon_draft = style.standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)

        font_bold = QFont()
        font_bold.setBold(True)

        def make_item(icon, text, data, font=None):
            item = QStandardItem(icon, text) if icon is not None else QStandardItem(text)
            if font is not None:
                item.setFont(font)
            item.setData(data, Qt.ItemDataRole.UserRole)
            item.setEditable(False)
            return item

        for proj in self.db.get_all_projects():
            proj_item = make_item(icon_folder, proj["name"], {"type": PROJECT, "id": proj["id"]}, font_bold)

            for scen in proj["scenarios"]:
                scen_item = make_item(
                    None, scen["name"],
                    {"type": SCENARIO, "id": scen["id"], "project_id": proj["id"]},
                )
                for prof in scen["profiles"]:
                    scen_item.appendRow(make_item(icon_file, prof["name"], {
                        "type": PROFILE,
                        "id": prof["id"],
                        "scenario_id": scen["id"],
                        "project_id": proj["id"],
                        "name": prof["name"],
                        "distance": prof["distance"],
                    }))
                proj_item.appendRow(scen_item)

            self.model.appendRow(proj_item)

        # Zone Draft : toujours présente, au même niveau que les projets, après eux.
        draft_root = make_item(icon_draft, _DRAFT_ZONE_LABEL, {"type": DRAFT_ROOT, "id": None}, font_bold)
        for draft in self.db.get_all_drafts():
            draft_root.appendRow(make_item(
                icon_file, draft["name"], {"type": DRAFT, "id": draft["id"], "name": draft["name"]}
            ))
        self.model.appendRow(draft_root)

        archived_count = len(self.db.get_archived_projects())
        self.btn_archives.setText(f"{_ARCHIVES_LABEL} ({archived_count})" if archived_count else _ARCHIVES_LABEL)

        # Restaure l'état plié/déplié : un nœud jamais vu jusqu'ici est déplié par défaut
        # pour ne pas donner l'impression qu'il est vide.
        for item in self._iter_items():
            data = item.data(Qt.ItemDataRole.UserRole)
            if data["type"] not in _EXPANDABLE_TYPES:
                continue
            key = _key(data)
            is_new = key not in self._known_keys
            self.tree_view.setExpanded(self.model.indexFromItem(item), is_new or key in self._expanded_keys)
            self._known_keys.add(key)

        self._restore_selection()
        self.tree_refreshed.emit()

    def _restore_selection(self):
        """Après reconstruction du modèle, resélectionne l'élément qui l'était. S'il a
        disparu (supprimé, lui ou l'un de ses parents), la sélection est levée et
        selection_cleared émis, pour que la fenêtre principale n'édite plus une ligne qui
        n'existe plus en base."""
        if not self._active_path:
            return

        item = self._find_item(_key(self._active_path[-1]))
        if item is None:
            self._active_path = []
            self._context_labels = None
            self._selection_labels = None
            self.selection_cleared.emit()
            return

        previous_labels = self._context_labels
        self._set_active(item)
        self.tree_view.setCurrentIndex(self.model.indexFromItem(item))
        if self._context_labels != previous_labels:
            self.context_changed.emit()

    def _set_active(self, item: QStandardItem):
        chain = self._chain(item)
        self._active_path = [it.data(Qt.ItemDataRole.UserRole) for it in chain]
        is_editable = self._active_path[-1]["type"] in _EDITABLE_TYPES
        self._selection_labels = tuple(it.text() for it in chain)
        self._context_labels = self._selection_labels if is_editable else None

    def _select(self, key: tuple):
        """Sélectionne dans l'arbre le nœud de clé donnée (typiquement juste après un
        refresh_tree(), pour mettre en avant un élément nouvellement créé), comme si
        l'utilisateur avait cliqué dessus."""
        item = self._find_item(key)
        if item is None:
            return
        index = self.model.indexFromItem(item)
        self.tree_view.setCurrentIndex(index)
        self.on_item_clicked(index)

    # --- Sélection ---

    def current_context(self):
        """Libellés de la sélection courante — (projet, scénario, profil) ou
        ("Draft", brouillon) — ou None si aucun profil/brouillon n'est sélectionné.
        Alimente le bandeau de contexte de la fenêtre principale, qui ne reçoit sinon
        qu'un identifiant numérique via les signaux de sélection."""
        return self._context_labels

    def select_scenario(self, scenario_id: int):
        """Sélectionne un scénario comme si l'utilisateur avait cliqué dessus (ouvre son
        profil en long) — ex. double-clic dans le récapitulatif du projet."""
        self._select((SCENARIO, scenario_id))

    def selection_labels(self):
        """Libellés du chemin du nœud sélectionné, quel que soit son type — ex. (projet,
        scénario) pour un scénario — ou None. Sert à légender l'export du profil en long."""
        return self._selection_labels

    def on_item_clicked(self, index):
        item = self.model.itemFromIndex(index)
        data = item.data(Qt.ItemDataRole.UserRole)
        self._set_active(item)
        # Le pliage/dépliage est géré par _ProjectTreeView.mousePressEvent (chevron
        # uniquement) : un clic ailleurs sur la ligne ne fait que sélectionner le nœud.
        self.tree_view.viewport().update()

        node_type = data["type"]
        if node_type == PROFILE:
            self.profile_selected.emit(data["id"])
        elif node_type == SCENARIO:
            self.scenario_selected.emit(data["id"])
        elif node_type == PROJECT:
            self.project_selected.emit(data["id"])
        elif node_type == DRAFT:
            self.draft_selected.emit(data["id"])
        elif node_type == DRAFT_ROOT:
            self.draft_zone_selected.emit()

    def _selected_project_id(self) -> Optional[int]:
        if self._active_path and self._active_path[0]["type"] == PROJECT:
            return self._active_path[0]["id"]
        return None

    def _prompt_name(self, title: str, label: str, text: str = "") -> Optional[str]:
        """Saisie d'un nom (texte libre), ou None si annulée ou laissée vide."""
        name, ok = QInputDialog.getText(self, title, label, text=text)
        if not ok:
            return None
        return name.strip() or None

    # --- Projets ---

    def add_project(self):
        name = self._prompt_name("Nouveau Projet", "Nom du projet :")
        if name is None:
            return

        try:
            project_id = self.db.create_project(name)
        except ValueError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            return
        # Un projet naît avec un scénario, pour qu'on puisse y ajouter des profils tout de
        # suite (cf. aussi la migration, qui crée ce même scénario pour les projets existants).
        scenario_id = self.db.create_scenario(project_id, DEFAULT_SCENARIO_NAME)

        self.refresh_tree()
        # Les points durs sont optionnels dès la création : annuler ce dialogue laisse
        # simplement les deux points vides, éditables ensuite via le menu contextuel du
        # projet ("Points durs...").
        self._prompt_hard_points(project_id)
        self._select((SCENARIO, scenario_id))

    def _prompt_hard_points(self, project_id: int) -> bool:
        """Ouvre le dialogue des points durs du projet (vérification complète pendant la
        saisie, dont les profils existants qui sortiraient de la zone couverte) et
        enregistre la liste si l'utilisateur valide. Affiche ensuite le bilan des pentes
        recalculées. Retourne True si la liste a été enregistrée."""
        points = self.db.get_hard_points(project_id)
        while True:
            dialog = HardPointsDialog(
                self, points=points, validator=lambda pts: self.db.check_hard_points(project_id, pts)
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return False
            points = dialog.get_points()
            try:
                report = self.db.set_hard_points(project_id, points)
            except ValueError as e:
                # Cas limite (la vérification pendant la saisie aurait dû l'empêcher) : on
                # rouvre le dialogue avec la saisie de l'utilisateur.
                QMessageBox.warning(self, "Points durs refusés", str(e))
                continue
            self._show_slope_report(report)
            self.project_data_changed.emit(project_id)
            return True

    def _show_slope_report(self, report, only_switches: bool = False):
        """Message récapitulatif des pentes recalculées (cf. SlopeReport.message). Avec
        `only_switches`, seulement si des profils sont passés en pente imposée (création,
        import ou copie : une pente calculée attendue ne mérite pas de message)."""
        if only_switches and not report.switched_to_imposed:
            return
        message = report.message()
        if message:
            QMessageBox.information(self, "Pentes hydrauliques", message)

    def edit_hard_points(self, data: dict):
        """Édite les points durs d'un projet déjà existant (menu contextuel). Ils sont
        communs à tous les scénarios du projet."""
        if not self._prompt_hard_points(data["id"]):
            return
        # Les distances des profils ont pu être décalées (nouveau premier point dur).
        self.refresh_tree()
        # Le profil en long d'un scénario de ce projet affiche ces points : on le redessine.
        if self._active_path and self._active_path[-1]["type"] == SCENARIO \
                and self._active_path[0]["id"] == data["id"]:
            self.scenario_selected.emit(self._active_path[-1]["id"])

    def rename_project_item(self, data: dict, current_name: str):
        """Demande un nouveau nom de projet (texte libre) et renomme le projet."""
        new_name = self._prompt_name("Renommer le projet", "Nom du projet :", current_name)
        if new_name is None:
            return

        try:
            self.db.rename_project(data["id"], new_name)
            self.refresh_tree()
        except ValueError as e:
            QMessageBox.warning(self, "Erreur", str(e))

    def duplicate_project(self, data: dict, current_name: str):
        """Demande un nom pour le nouveau projet et duplique le projet source, ses points
        durs, tous ses scénarios et tous leurs profils."""
        new_name = self._prompt_name("Dupliquer le projet", "Nom du projet :", f"{current_name} - copie")
        if new_name is None:
            return

        try:
            self.db.duplicate_project(data["id"], new_name)
            self.refresh_tree()
        except ValueError as e:
            QMessageBox.warning(self, "Erreur", str(e))

    def archive_project_item(self, data: dict):
        """Range le projet dans les Archives : il quitte l'arborescence, sans rien perdre
        (réversible depuis la fenêtre Archives, donc sans confirmation). Si l'élément ouvert
        en faisait partie, refresh_tree() lève la sélection (selection_cleared)."""
        try:
            self.db.set_project_archived(data["id"], True)
        except ValueError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            return
        self.refresh_tree()

    def open_archives(self):
        """Ouvre la fenêtre Archives (restauration / suppression définitive). Elle agit
        directement sur la base : l'arbre est donc rafraîchi à sa fermeture quoi qu'il
        arrive, et le dernier projet restauré est mis en avant."""
        dialog = ArchivesDialog(self.db, self)
        dialog.exec()
        self.refresh_tree()
        if dialog.restored_ids:
            self._select((PROJECT, dialog.restored_ids[-1]))

    # --- Scénarios ---

    def add_scenario(self):
        project_id = self._selected_project_id()
        if project_id is None:
            QMessageBox.warning(self, "Attention", "Sélectionnez d'abord un projet.")
            return
        self.create_scenario(project_id)

    @staticmethod
    def _next_scenario_name(scenarios: list) -> str:
        existing = {s["name"] for s in scenarios}
        n = len(scenarios) + 1
        while f"Scénario {n}" in existing:
            n += 1
        return f"Scénario {n}"

    def create_scenario(self, project_id: int, source_scenario_id: int = None,
                        default_name: str = None, title: str = "Nouveau scénario"):
        """Dialogue de création d'un scénario, avec l'option "Conserver les profils d'un
        scénario existant" (source à choisir parmi les scénarios du même projet)."""
        scenarios = self.db.get_scenarios(project_id)
        dialog = ScenarioDialog(
            self, scenarios=scenarios,
            default_name=default_name or self._next_scenario_name(scenarios),
            source_scenario_id=source_scenario_id, title=title,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        name, source_id = dialog.get_values()
        try:
            new_scenario_id = self.db.create_scenario(project_id, name, source_scenario_id=source_id)
        except ValueError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            return

        self.refresh_tree()
        self._select((SCENARIO, new_scenario_id))

    def rename_scenario(self, data: dict, current_name: str):
        new_name = self._prompt_name("Renommer le scénario", "Nom du scénario :", current_name)
        if new_name is None:
            return

        try:
            self.db.rename_scenario(data["id"], new_name)
            self.refresh_tree()
        except ValueError as e:
            QMessageBox.warning(self, "Erreur", str(e))

    def duplicate_scenario(self, data: dict, current_name: str):
        """Même dialogue que la création, avec ce scénario pré-choisi comme source."""
        self.create_scenario(
            data["project_id"], source_scenario_id=data["id"],
            default_name=f"{current_name} - copie", title="Dupliquer le scénario",
        )

    # --- Profils ---

    def _prompt_distance(self, title: str, project_id: int, current: float = 0.0) -> Optional[float]:
        """Saisie de la distance d'un profil au premier point dur, bornée par la zone
        couverte par les points durs du projet (libre faute de zone). None si annulée."""
        points = [p for p in self.db.get_hard_points(project_id) if p["pk"] is not None and p["z"] is not None]
        zone = self.db.get_distance_zone(project_id)
        reference = f"au premier point dur « {points[0]['name']} »" if points and points[0]["name"] \
            else "au premier point dur"
        if zone is None:
            label = f"Distance {reference} (m) :"
            low, high = _DISTANCE_MIN, _DISTANCE_MAX
        else:
            label = f"Distance {reference} (m), entre {zone[0]:g} et {zone[1]:g} :"
            low, high = zone
        distance, ok = QInputDialog.getDouble(
            self, title, label, min(max(current, low), high), low, high, _DISTANCE_DECIMALS,
        )
        return distance if ok else None

    def add_profile(self):
        """Nouveau profil dans le scénario sélectionné (ou celui du profil sélectionné),
        ou nouveau brouillon si la sélection est dans la zone Draft."""
        if not self._active_path:
            QMessageBox.warning(self, "Attention", "Sélectionnez d'abord un scénario ou la zone Draft.")
            return

        root = self._active_path[0]
        if root["type"] == DRAFT_ROOT:
            self.add_draft()
            return

        project_id = root["id"]
        scenario = next((d for d in self._active_path if d["type"] == SCENARIO), None)
        if scenario is not None:
            scenario_id = scenario["id"]
        else:
            # Projet sélectionné : sans ambiguïté s'il n'a qu'un scénario.
            scenarios = self.db.get_scenarios(project_id)
            if len(scenarios) != 1:
                QMessageBox.warning(
                    self, "Attention",
                    "Ce projet n'a aucun scénario : créez-en un d'abord." if not scenarios
                    else "Sélectionnez d'abord le scénario auquel ajouter le profil."
                )
                return
            scenario_id = scenarios[0]["id"]

        self.add_profile_to_scenario(scenario_id, project_id)

    def add_profile_to_scenario(self, scenario_id: int, project_id: int):
        name = self._prompt_name("Nouveau Profil", "Nom du profil :")
        if name is None:
            return

        distance = self._prompt_distance("Nouveau Profil", project_id)
        if distance is None:
            return

        try:
            profile_id = self.db.create_or_get_profile(scenario_id, name, distance)
        except ValueError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            return
        self.refresh_tree()
        self._select((PROFILE, profile_id))

    def rename_profile(self, data: dict, current_name: str):
        """Demande un nouveau nom (texte libre) et une nouvelle distance au point dur
        amont, et renomme le profil."""
        new_name = self._prompt_name("Renommer le profil", "Nom du profil :", current_name)
        if new_name is None:
            return

        new_distance = self._prompt_distance("Renommer le profil", data["project_id"], data.get("distance", 0.0))
        if new_distance is None:
            return

        try:
            report = self.db.rename_profile(data["id"], new_name, new_distance)
        except ValueError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            return
        self.refresh_tree()
        # Distance modifiée : la pente calculée du profil a pu changer.
        self._show_slope_report(report)
        self.project_data_changed.emit(data["project_id"])

    def duplicate_profile(self, data: dict, current_name: str):
        """Demande un nouveau nom (texte libre) et une nouvelle distance au point dur
        amont, et duplique le profil dans le même scénario, avec ses données existantes."""
        new_name = self._prompt_name("Dupliquer le profil", "Nom du profil :")
        if new_name is None:
            return

        new_distance = self._prompt_distance("Dupliquer le profil", data["project_id"], data.get("distance", 0.0))
        if new_distance is None:
            return

        try:
            new_profile_id = self.db.duplicate_profile(data["id"], new_name, new_distance)
        except ValueError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            return

        self.refresh_tree()
        self._show_slope_report(self.db.last_slope_report, only_switches=True)
        self._select((PROFILE, new_profile_id))

    # --- Zone Draft ---

    def add_draft(self):
        name = self._prompt_name("Nouveau brouillon", "Nom du brouillon :")
        if name is None:
            return

        try:
            draft_id = self.db.create_draft(name)
        except ValueError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            return
        self.refresh_tree()
        self._select((DRAFT, draft_id))

    def rename_draft(self, data: dict, current_name: str):
        new_name = self._prompt_name("Renommer le brouillon", "Nom du brouillon :", current_name)
        if new_name is None:
            return

        try:
            self.db.rename_draft(data["id"], new_name)
            self.refresh_tree()
        except ValueError as e:
            QMessageBox.warning(self, "Erreur", str(e))

    def duplicate_draft(self, data: dict, current_name: str):
        new_name = self._prompt_name("Dupliquer le brouillon", "Nom du brouillon :", f"{current_name} - copie")
        if new_name is None:
            return

        try:
            new_draft_id = self.db.duplicate_draft(data["id"], new_name)
        except ValueError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            return
        self.refresh_tree()
        self._select((DRAFT, new_draft_id))

    # --- Export / Import (JSON) ---

    def _scenario_choices(self) -> List[Tuple[str, int]]:
        """Libellés "Projet › Scénario" de tous les scénarios existants, tous projets
        confondus : alimente les sélecteurs de destination d'un import/copie de profil."""
        return [
            (f"{project['name']} › {scenario['name']}", scenario["id"])
            for project in self.db.get_all_projects() for scenario in project["scenarios"]
        ]

    def _project_choices(self) -> List[Tuple[str, int]]:
        return [(p["name"], p["id"]) for p in self.db.get_all_projects()]

    def _prompt_choice(self, title: str, label: str, choices: List[Tuple[str, object]]):
        """Sélection dans une liste de (libellé, valeur) via une boîte de dialogue.
        Renvoie la valeur choisie, ou None si annulé. Suppose les libellés uniques (vrai
        ici : les noms de projet sont uniques, et "Projet › Scénario" l'est donc aussi)."""
        labels = [c[0] for c in choices]
        chosen, ok = QInputDialog.getItem(self, title, label, labels, 0, False)
        if not ok:
            return None
        return dict(choices)[chosen]

    def _prompt_scenario_destination(self, title: str) -> Optional[int]:
        choices = self._scenario_choices()
        if not choices:
            QMessageBox.warning(self, "Attention", "Aucun scénario : créez d'abord un projet et un scénario.")
            return None
        return self._prompt_choice(title, "Scénario de destination :", choices)

    def _prompt_scenario_or_draft_destination(self, title: str):
        """Comme _prompt_scenario_destination, avec la zone Draft en option
        supplémentaire. Renvoie un id de scénario (int), _DRAFT_DESTINATION, ou None si
        annulé (jamais None faute de choix : la zone Draft est toujours proposée)."""
        choices = self._scenario_choices() + [(_DRAFT_DESTINATION_LABEL, _DRAFT_DESTINATION)]
        return self._prompt_choice(title, "Destination :", choices)

    def _prompt_project_destination(self, title: str) -> Optional[int]:
        choices = self._project_choices()
        if not choices:
            QMessageBox.warning(self, "Attention", "Aucun projet : créez-en un d'abord.")
            return None
        return self._prompt_choice(title, "Projet de destination :", choices)

    def _export_to_file(self, title: str, default_name: str, write_fn):
        """Demande un chemin de sauvegarde et y écrit l'export produit par `write_fn`
        (l'une des méthodes DatabaseManager.export_*_to_file)."""
        path, _ = QFileDialog.getSaveFileName(self, title, f"{default_name}.json", "Fichiers JSON (*.json)")
        if not path:
            return
        try:
            write_fn(path)
        except ValueError as e:
            QMessageBox.warning(self, "Erreur", str(e))

    def export_profile_item(self, data: dict, name: str):
        self._export_to_file(
            "Exporter le profil", name, lambda path: self.db.export_profile_to_file(data["id"], path)
        )

    def export_draft_item(self, data: dict, name: str):
        self._export_to_file(
            "Exporter le brouillon", name, lambda path: self.db.export_draft_to_file(data["id"], path)
        )

    def export_scenario_item(self, data: dict, name: str):
        self._export_to_file(
            "Exporter le scénario", name, lambda path: self.db.export_scenario_to_file(data["id"], path)
        )

    def export_project_item(self, data: dict, name: str):
        self._export_to_file(
            "Exporter le projet", name, lambda path: self.db.export_project_to_file(data["id"], path)
        )

    def copy_draft_to_scenario(self, data: dict, name: str):
        """Copie un brouillon vers un scénario choisi par l'utilisateur, comme nouveau
        profil indépendant : même collecte/insertion qu'un import de fichier profil, mais
        en mémoire. Le brouillon source reste inchangé dans la zone Draft."""
        scenario_id = self._prompt_scenario_destination(f"Copier « {name} » vers…")
        if scenario_id is None:
            return
        try:
            new_profile_id = self.db.copy_draft_to_scenario(data["id"], scenario_id)
        except ValueError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            return
        self.refresh_tree()
        self._show_slope_report(self.db.last_slope_report, only_switches=True)
        self._select((PROFILE, new_profile_id))

    def _pick_import_file(self, expected_type: Optional[str] = None) -> Optional[dict]:
        """Ouvre un sélecteur de fichier .json et lit/valide son contenu (cf.
        DatabaseManager.read_export_file). Si `expected_type` est fourni, vérifie aussi
        que le fichier est bien de ce type ("profile", "scenario" ou "project"). Renvoie
        None si l'utilisateur annule, ou après un message d'erreur si le fichier ne
        convient pas."""
        path, _ = QFileDialog.getOpenFileName(self, "Importer", "", "Fichiers JSON (*.json)")
        if not path:
            return None

        try:
            data = self.db.read_export_file(path)
        except ValueError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            return None

        if expected_type is not None and data["type"] != expected_type:
            QMessageBox.warning(
                self, "Erreur",
                f"Ce fichier n'est pas un export de {_TYPE_LABELS[expected_type]} "
                f"(c'est un export de {_TYPE_LABELS[data['type']]})."
            )
            return None
        return data

    def _run_import(self, action, node_type: str):
        """Exécute un import déjà résolu (fichier lu, destination choisie), rafraîchit
        l'arbre et sélectionne l'élément nouvellement créé."""
        self.db.last_slope_report = SlopeReport()
        try:
            new_id = action()
        except ValueError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            return
        self.refresh_tree()
        # Profils importés en pente calculée mais sans calcul possible dans leur projet.
        self._show_slope_report(self.db.last_slope_report, only_switches=True)
        self._select((node_type, new_id))

    def import_file(self):
        """Bouton "Importer..." : choisit un fichier .json exporté depuis HydroTopo et
        l'importe au bon endroit selon son type — un profil demande un scénario ou la
        zone Draft, un scénario demande un projet, un projet ne demande rien (toujours
        créé comme nouveau projet, cf. DatabaseManager.import_project)."""
        data = self._pick_import_file()
        if data is None:
            return

        kind = data["type"]
        if kind == "project":
            self._run_import(lambda: self.db.import_project(data), PROJECT)
        elif kind == "scenario":
            project_id = self._prompt_project_destination("Importer le scénario dans…")
            if project_id is None:
                return
            self._run_import(lambda: self.db.import_scenario_into_project(project_id, data), SCENARIO)
        else:  # "profile"
            destination = self._prompt_scenario_or_draft_destination("Importer le profil dans…")
            if destination is None:
                return
            if destination == _DRAFT_DESTINATION:
                self._run_import(lambda: self.db.import_profile_into_drafts(data), DRAFT)
            else:
                self._run_import(lambda: self.db.import_profile_into_scenario(destination, data), PROFILE)

    def import_profile_into_scenario_item(self, data: dict):
        """Menu contextuel d'un scénario : importe directement un fichier profil dedans,
        sans redemander la destination."""
        imported = self._pick_import_file(expected_type="profile")
        if imported is None:
            return
        self._run_import(lambda: self.db.import_profile_into_scenario(data["id"], imported), PROFILE)

    def import_scenario_into_project_item(self, data: dict):
        """Menu contextuel d'un projet : importe directement un fichier scénario dedans."""
        imported = self._pick_import_file(expected_type="scenario")
        if imported is None:
            return
        self._run_import(lambda: self.db.import_scenario_into_project(data["id"], imported), SCENARIO)

    def import_profile_into_drafts_item(self):
        """Menu contextuel de la zone Draft : importe directement un fichier profil comme
        nouveau brouillon."""
        imported = self._pick_import_file(expected_type="profile")
        if imported is None:
            return
        self._run_import(lambda: self.db.import_profile_into_drafts(imported), DRAFT)

    # --- Menu contextuel et suppression ---

    def open_context_menu(self, position):
        """Affiche le menu contextuel lors d'un clic droit sur un élément."""
        index = self.tree_view.indexAt(position)
        if not index.isValid():
            return

        item = self.model.itemFromIndex(index)
        data = item.data(Qt.ItemDataRole.UserRole)
        name = item.text()
        node_type = data["type"]

        menu = QMenu()
        handlers = {}

        def add(label, handler):
            handlers[menu.addAction(label)] = handler

        if node_type == PROJECT:
            add("Nouveau scénario...", lambda: self.create_scenario(data["id"]))
            add("Importer un scénario...", lambda: self.import_scenario_into_project_item(data))
            menu.addSeparator()
            add("Renommer", lambda: self.rename_project_item(data, name))
            add("Dupliquer", lambda: self.duplicate_project(data, name))
            add("Points durs...", lambda: self.edit_hard_points(data))
            add("Exporter...", lambda: self.export_project_item(data, name))
            add("Archiver", lambda: self.archive_project_item(data))
        elif node_type == SCENARIO:
            add("Nouveau profil...", lambda: self.add_profile_to_scenario(data["id"], data["project_id"]))
            add("Importer un profil...", lambda: self.import_profile_into_scenario_item(data))
            menu.addSeparator()
            add("Renommer", lambda: self.rename_scenario(data, name))
            add("Dupliquer...", lambda: self.duplicate_scenario(data, name))
            add("Exporter...", lambda: self.export_scenario_item(data, name))
        elif node_type == PROFILE:
            add("Renommer", lambda: self.rename_profile(data, name))
            add("Dupliquer", lambda: self.duplicate_profile(data, name))
            add("Exporter...", lambda: self.export_profile_item(data, name))
        elif node_type == DRAFT_ROOT:
            add("Nouveau brouillon...", self.add_draft)
            add("Importer un profil...", self.import_profile_into_drafts_item)
        elif node_type == DRAFT:
            add("Renommer", lambda: self.rename_draft(data, name))
            add("Dupliquer", lambda: self.duplicate_draft(data, name))
            add("Copier vers un scénario...", lambda: self.copy_draft_to_scenario(data, name))
            add("Exporter...", lambda: self.export_draft_item(data, name))

        if node_type != DRAFT_ROOT:
            add("Supprimer", lambda: self.delete_item(data, name))

        handler = handlers.get(menu.exec(self.tree_view.viewport().mapToGlobal(position)))
        if handler is not None:
            handler()

    def delete_item(self, data: dict, name: str):
        """Demande confirmation et supprime l'élément sélectionné."""
        msg = f"Êtes-vous sûr de vouloir supprimer « {escape(name)} » ?"

        warnings = {
            PROJECT: "cela supprimera également tous ses scénarios et leurs profils.",
            SCENARIO: "cela supprimera également tous les profils de ce scénario.",
        }
        if data["type"] in warnings:
            msg += (
                f'<br><br><b style="color:{theme.DANGER}">Attention :</b> '
                f"{warnings[data['type']]}"
            )

        # La suppression est irréversible : le bouton par défaut reste "Non", pour qu'une
        # validation réflexe (Entrée) n'efface pas un projet entier.
        reply = QMessageBox.question(
            self,
            "Confirmation de suppression",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            delete = {
                PROJECT: self.db.delete_project,
                SCENARIO: self.db.delete_scenario,
                PROFILE: self.db.delete_profile,
                DRAFT: self.db.delete_draft,
            }[data["type"]]
            delete(data["id"])
            self.refresh_tree()
