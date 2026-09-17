import sqlite3
import json
import dataclasses
from pathlib import Path
from typing import List, Dict, Optional, Tuple

DB_PATH = Path("data/hydrotopo.db")

class DatabaseManager:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialise le schéma de la base de données si nécessaire."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Table des projets
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Table des profils (PK) rattachés aux projets
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    pk_name TEXT NOT NULL,
                    existing_data TEXT, -- JSON des points du profil existant
                    project_params TEXT, -- JSON des paramètres du profil projet
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
                    UNIQUE (project_id, pk_name)
                )
            """)
            conn.commit()

    # --- GESTION DES PROJETS ---

    def get_all_projects(self) -> List[Dict]:
        """Récupère l'arborescence complète (Projets et leurs Profils)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM projects ORDER BY name")
            projects = [dict(row) for row in cursor.fetchall()]
            
            for project in projects:
                cursor.execute(
                    "SELECT id, pk_name FROM profiles WHERE project_id = ? ORDER BY pk_name", 
                    (project["id"],)
                )
                project["profiles"] = [dict(row) for row in cursor.fetchall()]
                
            return projects

    def create_project(self, name: str) -> int:
        """Crée un nouveau projet et retourne son ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO projects (name) VALUES (?)", (name,))
                conn.commit()
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                raise ValueError(f"Le projet '{name}' existe déjà.")

    # --- GESTION DES PROFILS ET AUTO-SAVE ---

    def create_or_get_profile(self, project_id: int, pk_name: str) -> int:
        """Crée un profil s'il n'existe pas, ou retourne son ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM profiles WHERE project_id = ? AND pk_name = ?", 
                (project_id, pk_name)
            )
            row = cursor.fetchone()
            if row:
                return row["id"]
            
            cursor.execute(
                "INSERT INTO profiles (project_id, pk_name, existing_data, project_params) VALUES (?, ?, '{}', '{}')",
                (project_id, pk_name)
            )
            conn.commit()
            return cursor.lastrowid

    def save_profile_state(self, profile_id: int, existing_data: List[Dict], project_params: Dict) -> None:
        """Auto-save : Met à jour les données d'un profil spécifique (sérialisation JSON)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE profiles 
                SET existing_data = ?, project_params = ?, last_updated = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (json.dumps(existing_data), json.dumps(project_params), profile_id))
            conn.commit()

    def load_profile_state(self, profile_id: int) -> Tuple[List[Dict], Dict]:
        """Charge l'état d'un profil (Points existants et Paramètres projet)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT existing_data, project_params FROM profiles WHERE id = ?", 
                (profile_id,)
            )
            row = cursor.fetchone()
            
            if row:
                existing_data = json.loads(row["existing_data"]) if row["existing_data"] else []
                project_params = json.loads(row["project_params"]) if row["project_params"] else {}
                return existing_data, project_params
            return [], {}

    def delete_project(self, project_id: int) -> None:
        """Supprime un projet et tous ses profils associés (grâce au CASCADE)."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()

    def delete_profile(self, profile_id: int) -> None:
        """Supprime un profil spécifique."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
            conn.commit()