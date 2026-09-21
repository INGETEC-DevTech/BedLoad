# ui/sidebar.py
from PyQt6.QtWidgets import (QTreeView, QVBoxLayout, QWidget, QPushButton,
                             QInputDialog, QMessageBox, QMenu, QApplication, QStyle,
                             QStyledItemDelegate)
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QFont, QColor, QPainter, QBrush, QPen
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QRectF
from database.db_manager import DatabaseManager
from ui import theme


class _TreeItemDelegate(QStyledItemDelegate):
    """Dessine les projets comme des lignes de section discrètes (transparentes au repos,
    avec une barre bleue quand le projet est "actif") et les profils comme des lignes
    imbriquées plus discrètes avec une puce colorée."""

    PROJECT_ROW_HEIGHT = 38
    PROFILE_ROW_HEIGHT = 30

    # Zone cliquable du chevron (partagée avec _ProjectTreeView.mousePressEvent pour que
    # le hit-test corresponde exactement à ce qui est dessiné).
    CHEVRON_X_OFFSET = 10
    CHEVRON_ZONE_WIDTH = 20

    def __init__(self, parent, sidebar):
        super().__init__(parent)
        self.sidebar = sidebar

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        height = self.PROJECT_ROW_HEIGHT if not index.parent().isValid() else self.PROFILE_ROW_HEIGHT
        return QSize(size.width(), height)

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_project = not index.parent().isValid()
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        rect = option.rect
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""

        if is_project:
            self._paint_project_row(painter, rect, text, index, hovered)
        else:
            selected = bool(option.state & QStyle.StateFlag.State_Selected)
            self._paint_profile_row(painter, rect, text, selected, hovered)

        painter.restore()

    def _is_project_active(self, index) -> bool:
        """Un projet est "actif" s'il vient d'être cliqué, ou s'il contient le profil
        actuellement sélectionné. Comme cliquer sur un projet le met déjà à jour, l'état
        sélectionné natif de Qt et l'état actif sont la même chose ici : pas besoin de les
        distinguer, un seul indicateur (sidebar._active_project_id) suffit pour les deux cas."""
        data = index.data(Qt.ItemDataRole.UserRole) or {}
        return self.sidebar._active_project_id == data.get("id")

    def _paint_project_row(self, painter, rect, text, index, hovered):
        is_active = self._is_project_active(index)

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

        # Chevron d'expand/collapse, dessiné avant l'icône dossier. Seul un clic dans cette
        # zone plie/déplie (cf. _ProjectTreeView.mousePressEvent) : cliquer ailleurs sur la
        # ligne se contente de sélectionner le projet.
        expanded = self.sidebar.tree_view.isExpanded(index)
        chevron_font = painter.font()
        chevron_font.setPointSize(12)
        chevron_font.setBold(True)
        painter.setFont(chevron_font)
        painter.setPen(QPen(QColor(theme.TEXT_SECONDARY)))
        chevron_x = rect.left() + self.CHEVRON_X_OFFSET
        painter.drawText(
            QRectF(chevron_x, rect.top(), self.CHEVRON_ZONE_WIDTH, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "▾" if expanded else "▸",
        )

        x = chevron_x + self.CHEVRON_ZONE_WIDTH
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon:
            icon_size = 16
            icon.paint(painter, x, rect.center().y() - icon_size // 2, icon_size, icon_size)
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

    def _paint_profile_row(self, painter, rect, text, selected, hovered):
        # Pas de bandeau plein ici : seulement une puce + un fond léger au survol/sélection,
        # pour rester visuellement "sous" le projet plutôt qu'à son niveau.
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
        dot_x = rect.left() + 36
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
    un projet ; cliquer ailleurs sur la ligne se contente de la sélectionner, sans toggle."""

    def mousePressEvent(self, event):
        index = self.indexAt(event.pos())
        is_project = index.isValid() and not index.parent().isValid()

        if is_project:
            rect = self.visualRect(index)
            chevron_left = rect.left() + _TreeItemDelegate.CHEVRON_X_OFFSET
            chevron_right = chevron_left + _TreeItemDelegate.CHEVRON_ZONE_WIDTH
            if chevron_left <= event.pos().x() <= chevron_right:
                self.setExpanded(index, not self.isExpanded(index))
                return

        super().mousePressEvent(event)


class Sidebar(QWidget):
    # Signal émis lorsqu'un profil est sélectionné dans l'arbre
    profile_selected = pyqtSignal(int)
    # Signal émis lorsqu'un projet (nœud parent) est sélectionné dans l'arbre
    project_selected = pyqtSignal(int)

    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db_manager
        # Id du projet "actif" (celui qui vient d'être cliqué, ou qui contient le profil
        # actuellement sélectionné) : c'est ce qui pilote la barre bleue du delegate.
        self._active_project_id = None
        # Ids des projets explicitement dépliés/repliés par l'utilisateur, pour survivre
        # à un refresh_tree() (ajout/suppression/renommage) sans tout refermer.
        self._expanded_project_ids = set()
        # Ids déjà vus au moins une fois : un projet absent de cet ensemble est "nouveau"
        # et sera déplié par défaut lors de son premier affichage.
        self._known_project_ids = set()

        # 1. Contraste : Fond légèrement grisé pour détacher le panneau
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(theme.qss(
            "Sidebar { background-color: $BACKGROUND; border-right: 1px solid $BORDER; }"
        ))
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(15, 20, 15, 15) # Plus de respiration
        self.main_layout.setSpacing(12)
        
        # 2. Boutons d'action : Primaire et Secondaire
        self.btn_add_project = QPushButton("+ Nouveau Projet")
        self.btn_add_project.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_project.setStyleSheet(theme.qss("""
            QPushButton { background-color: $PRIMARY; color: $SURFACE; border: none; border-radius: ${RADIUS_MD}px; padding: 8px 12px; font-weight: bold; }
            QPushButton:hover { background-color: $PRIMARY_HOVER; }
            QPushButton:pressed { background-color: $PRIMARY_PRESSED; }
        """))
        
        self.btn_add_profile = QPushButton("+ Nouveau Profil (PK)")
        self.btn_add_profile.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_profile.setStyleSheet(theme.qss("""
            QPushButton { background-color: $SURFACE; color: $TEXT_SECONDARY; border: 1px solid $BORDER_INPUT; border-radius: ${RADIUS_MD}px; padding: 8px 12px; font-weight: bold; }
            QPushButton:hover { background-color: $BACKGROUND; border-color: $BORDER_HOVER; }
            QPushButton:pressed { background-color: $HOVER; }
        """))
        
        self.main_layout.addWidget(self.btn_add_project)
        self.main_layout.addWidget(self.btn_add_profile)
        
        # 3. Arborescence épurée
        self.tree_view = _ProjectTreeView()
        self.tree_view.setHeaderHidden(True)
        self.tree_view.setFocusPolicy(Qt.FocusPolicy.NoFocus) # Retire le cadre pointillé au clic
        self.tree_view.setMouseTracking(True)  # nécessaire pour l'état "survol" du delegate
        self.tree_view.setItemDelegate(_TreeItemDelegate(self.tree_view, self))
        # La flèche native d'expand/collapse est désactivée : le thème Windows peint un carré
        # gris plein derrière elle qu'aucune règle QSS ne parvient à neutraliser. Le delegate
        # dessine son propre chevron à la place, et le pliage se déclenche par code
        # (clic n'importe où sur la ligne, cf. on_item_clicked) plutôt que par ce contrôle natif.
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
        self.btn_add_profile.clicked.connect(self.add_profile)
        self.tree_view.clicked.connect(self.on_item_clicked)
        
        self.refresh_tree()

    def refresh_tree(self):
        """Recharge l'arbre depuis la base de données avec icônes et typographie."""
        # Mémorise l'état plié/déplié courant avant de tout reconstruire (le modèle est
        # entièrement recréé à chaque refresh, il ne peut donc pas porter cette info lui-même).
        for row in range(self.model.rowCount()):
            proj_item = self.model.item(row)
            proj_id = proj_item.data(Qt.ItemDataRole.UserRole)["id"]
            proj_index = self.model.indexFromItem(proj_item)
            if self.tree_view.isExpanded(proj_index):
                self._expanded_project_ids.add(proj_id)
            else:
                self._expanded_project_ids.discard(proj_id)

        self.model.clear()
        projects = self.db.get_all_projects()

        # Récupération des icônes natives via le thème de l'application
        style = QApplication.style()
        icon_folder = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        icon_file = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)

        font_bold = QFont()
        font_bold.setBold(True)

        for proj in projects:
            # Création de l'item Projet (Dossier + Gras)
            proj_item = QStandardItem(icon_folder, proj["name"])
            proj_item.setFont(font_bold)
            proj_item.setData({"type": "project", "id": proj["id"]}, Qt.ItemDataRole.UserRole)
            proj_item.setEditable(False)

            for prof in proj["profiles"]:
                # Création de l'item Profil (Fichier)
                prof_item = QStandardItem(icon_file, prof["pk_name"])
                prof_item.setData({"type": "profile", "id": prof["id"]}, Qt.ItemDataRole.UserRole)
                prof_item.setEditable(False)
                proj_item.appendRow(prof_item)

            self.model.appendRow(proj_item)

        # Restaure l'état plié/déplié : un projet jamais vu jusqu'ici est déplié par défaut
        # pour ne pas donner l'impression qu'il est vide.
        for row in range(self.model.rowCount()):
            proj_item = self.model.item(row)
            proj_id = proj_item.data(Qt.ItemDataRole.UserRole)["id"]
            proj_index = self.model.indexFromItem(proj_item)
            is_new = proj_id not in self._known_project_ids
            self.tree_view.setExpanded(proj_index, is_new or proj_id in self._expanded_project_ids)
            self._known_project_ids.add(proj_id)

    def add_project(self):
        name, ok = QInputDialog.getText(self, "Nouveau Projet", "Nom du projet :")
        if ok and name:
            try:
                self.db.create_project(name)
                self.refresh_tree()
            except ValueError as e:
                QMessageBox.warning(self, "Erreur", str(e))

    def add_profile(self):
        selected = self.tree_view.currentIndex()
        if not selected.isValid():
            QMessageBox.warning(self, "Attention", "Sélectionnez d'abord un projet.")
            return
            
        item = self.model.itemFromIndex(selected)
        data = item.data(Qt.ItemDataRole.UserRole)
        
        # Si on a cliqué sur un profil, on remonte au projet parent
        if data["type"] == "profile":
            item = item.parent()
            data = item.data(Qt.ItemDataRole.UserRole)
            
        name, ok = QInputDialog.getText(self, "Nouveau Profil", "Nom du PK :")
        if not ok or not name:
            return

        name = name.strip()
        try:
            float(name.replace(',', '.'))
        except ValueError:
            QMessageBox.warning(self, "Erreur", "Le nom du PK doit être une valeur numérique (ex : 125.4).")
            return

        self.db.create_or_get_profile(data["id"], name)
        self.refresh_tree()

    def on_item_clicked(self, index):
        item = self.model.itemFromIndex(index)
        data = item.data(Qt.ItemDataRole.UserRole)
        if data["type"] == "profile":
            parent_data = item.parent().data(Qt.ItemDataRole.UserRole)
            self._active_project_id = parent_data["id"]
            self.tree_view.viewport().update()
            self.profile_selected.emit(data["id"])
        elif data["type"] == "project":
            self._active_project_id = data["id"]
            # Le pliage/dépliage est géré par _ProjectTreeView.mousePressEvent (chevron
            # uniquement) : un clic ailleurs sur la ligne ne fait que sélectionner le projet.
            self.tree_view.viewport().update()
            self.project_selected.emit(data["id"])

    def open_context_menu(self, position):
        """Affiche le menu contextuel lors d'un clic droit sur un élément."""
        index = self.tree_view.indexAt(position)
        if not index.isValid():
            return
            
        item = self.model.itemFromIndex(index)
        data = item.data(Qt.ItemDataRole.UserRole)
        
        menu = QMenu()
        rename_action = menu.addAction("Renommer") if data["type"] == "profile" else None
        delete_action = menu.addAction("Supprimer")
        action = menu.exec(self.tree_view.viewport().mapToGlobal(position))

        if action == delete_action:
            self.delete_item(data, item.text())
        elif rename_action is not None and action == rename_action:
            self.rename_profile(data, item.text())

    def rename_profile(self, data: dict, current_name: str):
        """Demande un nouveau nom de PK (obligatoirement numérique) et renomme le profil."""
        new_name, ok = QInputDialog.getText(self, "Renommer le profil", "Nom du PK :", text=current_name)
        if not ok or not new_name:
            return

        new_name = new_name.strip()
        try:
            float(new_name.replace(',', '.'))
        except ValueError:
            QMessageBox.warning(self, "Erreur", "Le nom du PK doit être une valeur numérique (ex : 125.4).")
            return

        try:
            self.db.rename_profile(data["id"], new_name)
            self.refresh_tree()
        except ValueError as e:
            QMessageBox.warning(self, "Erreur", str(e))

    def delete_item(self, data: dict, name: str):
        """Demande confirmation et supprime l'élément sélectionné."""
        msg = f"Êtes-vous sûr de vouloir supprimer '{name}' ?"
        
        if data["type"] == "project":
            msg += "\n\nATTENTION : Cela supprimera également tous les profils (PK) associés de la base de données."
            
        reply = QMessageBox.question(
            self, 
            "Confirmation de suppression", 
            msg, 
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            if data["type"] == "project":
                self.db.delete_project(data["id"])
            else:
                self.db.delete_profile(data["id"])
                
            self.refresh_tree()