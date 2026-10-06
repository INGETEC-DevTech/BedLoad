# core/utils.py
import logging
import sys
import tempfile
from pathlib import Path
from typing import Optional

def get_base_dir() -> Path:
    """Retourne le dossier racine de l'application, qu'elle soit en script ou en .exe."""
    if getattr(sys, 'frozen', False):
        # Mode exécutable (PyInstaller) : on pointe sur le dossier contenant le .exe
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

# Fichiers écrits par l'application à côté de l'exe (appli portable).
DATA_DIR_NAME = "data"
DB_FILE_NAME = "hydrotopo.db"
LOG_FILE_NAME = "hydrotopo.log"


def _write_problem(directory: Path) -> Optional[str]:
    """Essaie réellement d'écrire dans `directory` (le créant au besoin) : sous Windows,
    l'attribut "lecture seule" d'un dossier ne dit rien de ses droits réels (Program Files,
    partage réseau...). Retourne la cause de l'échec, ou None si l'écriture fonctionne."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=directory):
            pass
    except OSError as e:
        return e.strerror or str(e)
    return None


def _file_write_problem(path: Path) -> Optional[str]:
    """Cause de l'impossibilité de modifier un fichier existant, ou None (fichier absent :
    il sera créé dans un dossier dont l'écriture a déjà été vérifiée)."""
    if not path.exists():
        return None
    try:
        with open(path, "r+b"):
            pass
    except OSError as e:
        return e.strerror or str(e)
    return None


def find_storage_problem(base_dir: Path) -> Optional[str]:
    """Vérifie, avant toute écriture, que l'application pourra enregistrer sa base de
    données (data/hydrotopo.db) et son journal (hydrotopo.log) à côté de l'exe. Retourne
    un message clair pour l'utilisateur si ce n'est pas le cas, ou None."""
    data_dir = base_dir / DATA_DIR_NAME
    # Dans l'ordre, et on s'arrête au premier problème (inutile de tester data/ si le
    # dossier de l'exe lui-même n'est pas modifiable).
    checks = (
        (base_dir, _write_problem),
        (data_dir, _write_problem),
        (data_dir / DB_FILE_NAME, _file_write_problem),
        (base_dir / LOG_FILE_NAME, _file_write_problem),
    )
    for path, check in checks:
        problem = check(path)
        if problem is not None:
            return (
                "HydroTopo enregistre sa base de données et son journal dans son propre "
                f"dossier :\n{base_dir}\n\n"
                f"Impossible d'y écrire ({path} : {problem}). C'est le cas notamment dans "
                "« Program Files » ou sur un partage réseau en lecture seule.\n\n"
                "Déplacez HydroTopo (l'exe, avec son dossier « data » s'il existe) dans un "
                "dossier où vous pouvez écrire, par exemple dans vos Documents, puis "
                "relancez-le."
            )
    return None


def setup_logger():
    """Configure le journal d'événements de l'application."""
    log_file = get_base_dir() / LOG_FILE_NAME
    
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

