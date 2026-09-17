# app.py
import sys
from PyQt6.QtWidgets import QApplication, QMessageBox
from ui.main_window import MainWindow
import traceback
import logging
from core.utils import setup_logger

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
QPushButton:disabled {
    background-color: #f8f9fa;
    color: #adb5bd;
    border: 1px solid #e9ecef;
}

/* Champs de saisie */
QLineEdit, QTableWidget, QDoubleSpinBox {
    border: 1px solid #ced4da;
    border-radius: 3px;
    padding: 4px;
    background: white;
}
QLineEdit:focus, QTableWidget:focus, QDoubleSpinBox:focus {
    border: 1px solid #80bdff;
}
QLineEdit:disabled, QTableWidget:disabled, QDoubleSpinBox:disabled {
    background-color: #f1f3f5;
    color: #adb5bd;
}

/* Cases à cocher */
QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #ced4da;
    border-radius: 3px;
    background: white;
}
QCheckBox::indicator:checked {
    background-color: #0056b3;
    border: 1px solid #0056b3;
}
QCheckBox:disabled {
    color: #adb5bd;
}

/* Groupes et onglets désactivés (formulaires grisés tant qu'aucun profil n'est sélectionné) */
QGroupBox:disabled, QTabWidget:disabled {
    color: #adb5bd;
}
"""

def global_exception_handler(exc_type, exc_value, exc_tb):
    """Intercepte les erreurs critiques pour éviter la fermeture silencieuse."""
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

    # Enregistrement silencieux du crash
    logging.critical(f"Crash inattendu : {exc_value}\n{error_msg}")

    msg_box = QMessageBox()
    msg_box.setIcon(QMessageBox.Icon.Critical)
    msg_box.setWindowTitle("Erreur critique")
    msg_box.setText("Le logiciel a rencontré une erreur inattendue.")
    msg_box.setInformativeText(str(exc_value))
    msg_box.setDetailedText(error_msg)
    msg_box.exec()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    setup_logger()
    logging.info("=== Démarrage d'HydroTopo V2 ===")
    
    # Interception de toutes les erreurs globales
    sys.excepthook = global_exception_handler
    
    app.setStyle("Fusion") 
    app.setStyleSheet(QSS_THEME)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())