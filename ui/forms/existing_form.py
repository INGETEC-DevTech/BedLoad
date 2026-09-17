# ui/forms/existing_form.py
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, 
                               QPushButton, QLabel, QHeaderView)
from PyQt6.QtCore import pyqtSignal

class ExistingProfileForm(QWidget):
    # Signal émis vers MainWindow quand les données changent (auto-save + maj graphique)
    data_changed = pyqtSignal(list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)
        
        label = QLabel("<b>Profil en travers existant</b><br><i>Renseignez les points (X = distance, Z = altitude).</i>")
        self.main_layout.addWidget(label)
        
        # Tableau de saisie
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["X (m)", "Z (m NGF)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.main_layout.addWidget(self.table)
        
        self.btn_add_row = QPushButton("Ajouter un point")
        self.main_layout.addWidget(self.btn_add_row)
        
        # Connexions
        self.btn_add_row.clicked.connect(self.add_row)
        self.table.itemChanged.connect(self.on_item_changed)
        
        # Verrou pour éviter les signaux multiples lors du chargement initial
        self._is_loading = False
        
    def add_row(self):
        row = self.table.rowCount()
        self._is_loading = True
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem("0.0"))
        self.table.setItem(row, 1, QTableWidgetItem("0.0"))
        self._is_loading = False
        self.on_item_changed()
        
    def get_data(self) -> list:
        """Extrait les données de la table sous forme de liste de dictionnaires."""
        data = []
        for row in range(self.table.rowCount()):
            # Sécurisation : on vérifie que les cellules existent bien
            item_x = self.table.item(row, 0)
            item_z = self.table.item(row, 1)
            
            if not item_x or not item_z:
                continue
                
            # Nettoyage des espaces et remplacement de la virgule française
            str_x = item_x.text().strip().replace(',', '.')
            str_z = item_z.text().strip().replace(',', '.')
            
            # On ignore les lignes en cours de saisie (vides)
            if not str_x or not str_z:
                continue
                
            try:
                x = float(str_x)
                z = float(str_z)
                data.append({"X (m)": x, "Z (m NGF)": z})
            except ValueError:
                # TODO UX : Mettre la cellule en rouge si la valeur n'est pas un nombre valide
                continue
                
        return data
        
    def set_data(self, data: list):
        """Peuple la table à partir des données chargées depuis la base SQLite."""
        self._is_loading = True
        self.table.setRowCount(0)
        for i, point in enumerate(data):
            self.table.insertRow(i)
            self.table.setItem(i, 0, QTableWidgetItem(str(point.get("X (m)", 0.0))))
            self.table.setItem(i, 1, QTableWidgetItem(str(point.get("Z (m NGF)", 0.0))))
        self._is_loading = False
        
    def on_item_changed(self, item=None):
        if not self._is_loading:
            self.data_changed.emit(self.get_data())