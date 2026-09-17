# app.py
import sys
from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow

QSS_THEME = """
/* Base de la fenêtre */
QMainWindow, QWidget {
    background-color: #f8f9fa;
    font-family: "Segoe UI", "Helvetica Neue", sans-serif;
    font-size: 13px;
    color: #212529;
}

/* Allègement des cadres (QGroupBox) */
QGroupBox {
    font-weight: bold;
    border: none;
    border-top: 1px solid #dee2e6;
    margin-top: 20px;
    padding-top: 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding-bottom: 5px;
    color: #495057;
}

/* Onglets modernisés */
QTabWidget::pane {
    border: 1px solid #dee2e6;
    background: white;
    border-radius: 4px;
}
QTabBar::tab {
    background: #e9ecef;
    border: 1px solid #dee2e6;
    padding: 8px 20px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}
QTabBar::tab:selected {
    background: white;
    border-bottom-color: white;
    color: #0056b3;
    font-weight: bold;
}

/* Arbre de navigation */
QTreeView {
    background-color: white;
    border: 1px solid #dee2e6;
    border-radius: 4px;
}
QTreeView::item {
    padding: 6px;
}
QTreeView::item:selected {
    background-color: #e6f2ff;
    color: #0056b3;
    font-weight: bold;
}

/* Boutons flat design */
QPushButton {
    background-color: #ffffff;
    border: 1px solid #ced4da;
    border-radius: 4px;
    padding: 6px 12px;
}
QPushButton:hover {
    background-color: #e9ecef;
}
QPushButton:pressed {
    background-color: #dee2e6;
}

/* Champs de saisie */
QLineEdit, QTableWidget {
    border: 1px solid #ced4da;
    border-radius: 3px;
    padding: 4px;
    background: white;
}
QLineEdit:focus, QTableWidget:focus {
    border: 1px solid #80bdff;
}
"""

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Fusion applique une base neutre multi-OS, idéale pour écraser ensuite avec le QSS
    app.setStyle("Fusion") 
    app.setStyleSheet(QSS_THEME)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())