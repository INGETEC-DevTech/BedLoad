# core/utils.py
import logging
import sys
from pathlib import Path

def get_base_dir() -> Path:
    """Retourne le dossier racine de l'application, qu'elle soit en script ou en .exe."""
    if getattr(sys, 'frozen', False):
        # Mode exécutable (PyInstaller) : on pointe sur le dossier contenant le .exe
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

def setup_logger():
    """Configure le journal d'événements de l'application."""
    log_file = get_base_dir() / "hydrotopo.log"
    
    # Configuration pour écrire dans le fichier avec un format clair
    handlers = [logging.FileHandler(log_file, encoding='utf-8')]
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers
    )

