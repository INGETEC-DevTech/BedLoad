import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Tuple
import logging
from core.utils import get_base_dir

# Construction du chemin absolu dynamique
DB_PATH = get_base_dir() / "data" / "hydrotopo.db"

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
                    """SELECT id, pk_name FROM profiles WHERE project_id = ?
                       ORDER BY CAST(REPLACE(pk_name, ',', '.') AS REAL)""",
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
            """Auto-save : Met à jour les données d'un profil spécifique."""
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE profiles 
                    SET existing_data = ?, project_params = ?, last_updated = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (json.dumps(existing_data), json.dumps(project_params), profile_id))
                conn.commit()
                
            logging.info(f"Auto-save réussi pour le profil ID {profile_id}.")

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

    def rename_profile(self, profile_id: int, new_pk_name: str) -> None:
        """Renomme un profil (PK) existant."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "UPDATE profiles SET pk_name = ? WHERE id = ?",
                    (new_pk_name, profile_id)
                )
                conn.commit()
            except sqlite3.IntegrityError:
                raise ValueError(f"Le PK '{new_pk_name}' existe déjà dans ce projet.")

    def duplicate_profile(self, profile_id: int, new_pk_name: str) -> int:
        """Duplique un profil (PK) dans le même projet, sous un nouveau nom."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT project_id FROM profiles WHERE id = ?", (profile_id,))
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"Le profil source (ID {profile_id}) est introuvable.")
            project_id = row["project_id"]

            cursor.execute(
                "SELECT id FROM profiles WHERE project_id = ? AND pk_name = ?",
                (project_id, new_pk_name)
            )
            if cursor.fetchone() is not None:
                raise ValueError(f"Le PK '{new_pk_name}' existe déjà dans ce projet.")

        existing_data, project_params = self.load_profile_state(profile_id)
        new_profile_id = self.create_or_get_profile(project_id, new_pk_name)
        self.save_profile_state(new_profile_id, existing_data, project_params)
        return new_profile_id

    def duplicate_project(self, project_id: int, new_name: str) -> int:
        """Duplique un projet et tous ses profils (PK) dans un nouveau projet."""
        new_project_id = self.create_project(new_name)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, pk_name FROM profiles WHERE project_id = ?",
                (project_id,)
            )
            profiles = [dict(row) for row in cursor.fetchall()]

        for profile in profiles:
            existing_data, project_params = self.load_profile_state(profile["id"])
            new_profile_id = self.create_or_get_profile(new_project_id, profile["pk_name"])
            self.save_profile_state(new_profile_id, existing_data, project_params)

        return new_project_id

    def get_longitudinal_data(self, project_id: int) -> List[Tuple[float, float, float]]:
        """Pour le profil en long : un triplet (pk, altitude mini du TN existant, anchor_z du
        projet) par profil du projet, trié par PK numérique croissant. Les profils dont le nom
        de PK n'est pas numérique (ancien nom type 'test 2') sont ignorés. Les profils sans
        points existants, ou sans paramètres projet enregistrés, renvoient None sur la valeur
        manquante plutôt que d'être exclus entièrement."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT pk_name, existing_data, project_params FROM profiles WHERE project_id = ?",
                (project_id,)
            )
            rows = cursor.fetchall()

        result = []
        for row in rows:
            try:
                pk = float(row["pk_name"].replace(',', '.'))
            except (TypeError, ValueError):
                continue

            existing_data = json.loads(row["existing_data"]) if row["existing_data"] else []
            z_values = [pt["Z (m NGF)"] for pt in existing_data if "Z (m NGF)" in pt]
            min_z_existing = min(z_values) if z_values else None

            project_params = json.loads(row["project_params"]) if row["project_params"] else {}
            anchor_z_project = project_params.get("anchor_z")

            result.append((pk, min_z_existing, anchor_z_project))

        result.sort(key=lambda t: t[0])
        return result

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