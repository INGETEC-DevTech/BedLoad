# ui/sidebar.py
from PyQt6.QtWidgets import QTreeView, QVBoxLayout, QWidget, QPushButton, QInputDialog, QMessageBox, QMenu
from PyQt6.QtGui import QStandardItemModel, QStandardItem
from PyQt6.QtCore import pyqtSignal, Qt
from database.db_manager import DatabaseManager

class Sidebar(QWidget):
    # Signal émis lorsqu'un profil est sélectionné dans l'arbre
    profile_selected = pyqtSignal(int) 

    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db_manager
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        
        # Boutons d'action
        self.btn_add_project = QPushButton("Nouveau Projet")
        self.btn_add_profile = QPushButton("Nouveau Profil (PK)")
        self.layout.addWidget(self.btn_add_project)
        self.layout.addWidget(self.btn_add_profile)
        
        # Arborescence
        self.tree_view = QTreeView()
        self.tree_view.setHeaderHidden(True)
        self.model = QStandardItemModel()
        self.tree_view.setModel(self.model)
        self.layout.addWidget(self.tree_view)

        # Activation du menu contextuel (clic droit)
        self.tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self.open_context_menu)
        
        # Connexions
        self.btn_add_project.clicked.connect(self.add_project)
        self.btn_add_profile.clicked.connect(self.add_profile)
        self.tree_view.clicked.connect(self.on_item_clicked)
        
        self.refresh_tree()

    def refresh_tree(self):
        """Recharge l'arbre depuis la base de données."""
        self.model.clear()
        projects = self.db.get_all_projects()
        
        for proj in projects:
            proj_item = QStandardItem(proj["name"])
            proj_item.setData({"type": "project", "id": proj["id"]}, Qt.ItemDataRole.UserRole)
            proj_item.setEditable(False)
            
            for prof in proj["profiles"]:
                prof_item = QStandardItem(prof["pk_name"])
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
        
        # Création du menu
        menu = QMenu()
        delete_action = menu.addAction("Supprimer")
        
        # Affichage du menu à la position de la souris
        action = menu.exec(self.tree_view.viewport().mapToGlobal(position))
        
        if action == delete_action:
            self.delete_item(data, item.text())

    def delete_item(self, data: dict, name: str):
        """Demande confirmation et supprime l'élément sélectionné."""
        msg = f"Êtes-vous sûr de vouloir supprimer '{name}' ?"
        
        # Avertissement supplémentaire si c'est un projet entier
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