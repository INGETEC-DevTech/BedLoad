# ui/sidebar.py
from PyQt6.QtWidgets import (QTreeView, QVBoxLayout, QWidget, QPushButton, 
                             QInputDialog, QMessageBox, QMenu, QApplication, QStyle)
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QFont
from PyQt6.QtCore import pyqtSignal, Qt
from database.db_manager import DatabaseManager

class Sidebar(QWidget):
    # Signal émis lorsqu'un profil est sélectionné dans l'arbre
    profile_selected = pyqtSignal(int)

    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db_manager
        
        # 1. Contraste : Fond légèrement grisé pour détacher le panneau
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("Sidebar { background-color: #f8f9fa; border-right: 1px solid #dee2e6; }")
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(15, 20, 15, 15) # Plus de respiration
        self.main_layout.setSpacing(12)
        
        # 2. Boutons d'action : Primaire et Secondaire
        self.btn_add_project = QPushButton("+ Nouveau Projet")
        self.btn_add_project.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_project.setStyleSheet("""
            QPushButton { background-color: #0d6efd; color: white; border: none; border-radius: 6px; padding: 8px 12px; font-weight: bold; }
            QPushButton:hover { background-color: #0b5ed7; }
            QPushButton:pressed { background-color: #0a58ca; }
        """)
        
        self.btn_add_profile = QPushButton("+ Nouveau Profil (PK)")
        self.btn_add_profile.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_profile.setStyleSheet("""
            QPushButton { background-color: #ffffff; color: #495057; border: 1px solid #ced4da; border-radius: 6px; padding: 8px 12px; font-weight: bold; }
            QPushButton:hover { background-color: #f8f9fa; border-color: #b6bec5; }
            QPushButton:pressed { background-color: #e9ecef; }
        """)
        
        self.main_layout.addWidget(self.btn_add_project)
        self.main_layout.addWidget(self.btn_add_profile)
        
        # 3. Arborescence épurée
        self.tree_view = QTreeView()
        self.tree_view.setHeaderHidden(True)
        self.tree_view.setFocusPolicy(Qt.FocusPolicy.NoFocus) # Retire le cadre pointillé au clic
        self.tree_view.setStyleSheet("""
            QTreeView { border: none; background-color: transparent; outline: none; }
            QTreeView::item { padding: 6px; border-radius: 4px; margin-bottom: 2px; }
            QTreeView::item:hover { background-color: #e9ecef; }
            QTreeView::item:selected { background-color: #e6f2ff; color: #0d6efd; font-weight: bold; }
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
            
        self.tree_view.expandAll()

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
        if ok and name:
            self.db.create_or_get_profile(data["id"], name)
            self.refresh_tree()

    def on_item_clicked(self, index):
        item = self.model.itemFromIndex(index)
        data = item.data(Qt.ItemDataRole.UserRole)
        if data["type"] == "profile":
            self.profile_selected.emit(data["id"])

    def open_context_menu(self, position):
        """Affiche le menu contextuel lors d'un clic droit sur un élément."""
        index = self.tree_view.indexAt(position)
        if not index.isValid():
            return
            
        item = self.model.itemFromIndex(index)
        data = item.data(Qt.ItemDataRole.UserRole)
        
        menu = QMenu()
        delete_action = menu.addAction("Supprimer")
        action = menu.exec(self.tree_view.viewport().mapToGlobal(position))
        
        if action == delete_action:
            self.delete_item(data, item.text())

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