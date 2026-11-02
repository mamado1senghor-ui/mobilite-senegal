import sqlite3
from contextlib import closing
from pathlib import Path

FICHIER_DB = Path(__file__).parent / "reservations.db"

COLONNES = [
    "reference", "date_demande", "service", "nom", "telephone",
    "depart", "arrivee", "date_prise_en_charge", "passagers",
    "marchandise", "poids", "aide_chargement", "remarques",
    "statut", "chauffeur", "chauffeur_tel",
]


def _connexion():
    conn = sqlite3.connect(FICHIER_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(_connexion()) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reservations (
                reference TEXT PRIMARY KEY,
                date_demande TEXT,
                service TEXT,
                nom TEXT,
                telephone TEXT,
                depart TEXT,
                arrivee TEXT,
                date_prise_en_charge TEXT,
                passagers TEXT,
                marchandise TEXT,
                poids TEXT,
                aide_chargement TEXT,
                remarques TEXT,
                statut TEXT DEFAULT 'En attente',
                chauffeur TEXT DEFAULT '',
                chauffeur_tel TEXT DEFAULT ''
            )
            """
        )


def ajouter(reservation):
    valeurs = {c: reservation.get(c, "") for c in COLONNES}
    if not valeurs["statut"]:
        valeurs["statut"] = "En attente"
    colonnes = ", ".join(COLONNES)
    marques = ", ".join(":" + c for c in COLONNES)
    with closing(_connexion()) as conn, conn:
        conn.execute(
            f"INSERT INTO reservations ({colonnes}) VALUES ({marques})", valeurs
        )


def lister(statut=None, chauffeur_tel=None, ordre="ASC"):
    ordre = "DESC" if ordre == "DESC" else "ASC"
    requete = "SELECT * FROM reservations WHERE 1=1"
    parametres = []
    if statut:
        requete += " AND statut = ?"
        parametres.append(statut)
    if chauffeur_tel:
        requete += " AND chauffeur_tel = ?"
        parametres.append(chauffeur_tel)
    requete += f" ORDER BY date_demande {ordre}, rowid {ordre}"
    with closing(_connexion()) as conn:
        return [dict(ligne) for ligne in conn.execute(requete, parametres).fetchall()]


def trouver(reference, telephone):
    with closing(_connexion()) as conn:
        ligne = conn.execute(
            "SELECT * FROM reservations WHERE reference = ? AND telephone = ?",
            (reference, telephone),
        ).fetchone()
    return dict(ligne) if ligne else None


def accepter(reference, nom_chauffeur, tel_chauffeur):
    """Renvoie True si la course était encore libre, False si un autre chauffeur l'a prise."""
    with closing(_connexion()) as conn, conn:
        curseur = conn.execute(
            "UPDATE reservations SET statut = 'Acceptée', chauffeur = ?, chauffeur_tel = ? "
            "WHERE reference = ? AND statut = 'En attente'",
            (nom_chauffeur, tel_chauffeur, reference),
        )
        return curseur.rowcount == 1


def terminer(reference, tel_chauffeur):
    with closing(_connexion()) as conn, conn:
        curseur = conn.execute(
            "UPDATE reservations SET statut = 'Terminée' "
            "WHERE reference = ? AND chauffeur_tel = ? AND statut = 'Acceptée'",
            (reference, tel_chauffeur),
        )
        return curseur.rowcount == 1


def remettre_en_attente(reference, tel_chauffeur):
    with closing(_connexion()) as conn, conn:
        curseur = conn.execute(
            "UPDATE reservations SET statut = 'En attente', chauffeur = '', chauffeur_tel = '' "
            "WHERE reference = ? AND chauffeur_tel = ? AND statut = 'Acceptée'",
            (reference, tel_chauffeur),
        )
        return curseur.rowcount == 1