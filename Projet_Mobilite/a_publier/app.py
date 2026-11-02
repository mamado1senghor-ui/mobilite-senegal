import base64
import io
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from secrets import token_hex

import streamlit as st
from PIL import Image, ImageOps

st.set_page_config(page_title="Mobilité Sénégal", layout="wide")

BASE_DIR = Path(__file__).parent
FICHIER_DB = BASE_DIR / "reservations.db"
TAILLE_PHOTO = (800, 600)

# Code d'accès des chauffeurs : CHANGE-LE avant toute utilisation réelle
try:
    CODE_CHAUFFEUR = str(st.secrets["CODE_CHAUFFEUR"])
except Exception:
    CODE_CHAUFFEUR = ""

STATUTS = {"En attente": "⏳", "Acceptée": "✅", "Terminée": "🏁"}

# ---------------- Données ----------------
ACCUEIL = [
    {
        "cle": "voiture",
        "nom": "Voiture",
        "image": "images/voiture.jpg",
        "icone": "🚗",
        "couleur": "#0b7a3e",
        "fond": "#e3f3ea",
        "description": "Confort et sécurité pour vos déplacements en ville et entre les régions.",
        "prix": 1500,
    },
    {
        "cle": "moto",
        "nom": "Moto",
        "image": "images/moto.jpg",
        "icone": "🏍️",
        "couleur": "#1769e0",
        "fond": "#e3edfc",
        "description": "Rapide et économique pour vos trajets urbains et courts.",
        "prix": 1000,
    },
    {
        "cle": "marchandises",
        "nom": "Transport de marchandises",
        "image": "images/tricycle.jpg",
        "icone": "🚚",
        "couleur": "#e59a0b",
        "fond": "#fdf1d6",
        "description": "Moto tricyclette ou voiture porte-bagages : l'alternative moderne à la charrette.",
        "prix": None,
        "pastille": "2 véhicules au choix",
    },
]

MARCHANDISES = [
    {
        "cle": "tricycle",
        "nom": "Moto tricyclette",
        "image": "images/tricycle.jpg",
        "description": "Charges moyennes en ville, une alternative à la charrette",
        "prix": 1500,
    },
    {
        "cle": "voiture_bagages",
        "nom": "Voiture porte-bagages",
        "image": "images/voiture_bagages.jpg",
        "description": "Grands bagages, courses et charges plus lourdes",
        "prix": 2500,
    },
]

NOMS_MARCHANDISES = [s["nom"] for s in MARCHANDISES]
POIDS = ["Moins de 20 kg", "20 à 100 kg", "100 à 300 kg", "Plus de 300 kg"]

# ---------------- Base de données (SQLite) ----------------
COLONNES = [
    "reference", "date_demande", "service", "nom", "telephone",
    "depart", "arrivee", "date_prise_en_charge", "passagers",
    "marchandise", "poids", "aide_chargement", "remarques",
    "statut", "chauffeur", "chauffeur_tel", "prix_estime",
    "lat", "lon", "position_exacte", "pour_autrui", "contact_nom", "contact_tel",
    "chauffeur_lat", "chauffeur_lon", "position_maj",
]


def _connexion():
    conn = sqlite3.connect(FICHIER_DB)
    conn.row_factory = sqlite3.Row
    return conn


def db_init():
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


def db_ajouter(reservation):
    valeurs = {c: reservation.get(c, "") for c in COLONNES}
    if not valeurs["statut"]:
        valeurs["statut"] = "En attente"
    colonnes = ", ".join(COLONNES)
    marques = ", ".join(":" + c for c in COLONNES)
    with closing(_connexion()) as conn, conn:
        conn.execute(
            f"INSERT INTO reservations ({colonnes}) VALUES ({marques})", valeurs
        )


def db_lister(statut=None, chauffeur_tel=None, ordre="ASC"):
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


def db_trouver(reference, telephone):
    with closing(_connexion()) as conn:
        ligne = conn.execute(
            "SELECT * FROM reservations WHERE reference = ? AND telephone = ?",
            (reference, telephone),
        ).fetchone()
    return dict(ligne) if ligne else None


def db_accepter(reference, nom_chauffeur, tel_chauffeur):
    """True si la course était encore libre, False si un autre chauffeur l'a prise."""
    with closing(_connexion()) as conn, conn:
        curseur = conn.execute(
            "UPDATE reservations SET statut = 'Acceptée', chauffeur = ?, chauffeur_tel = ? "
            "WHERE reference = ? AND statut = 'En attente'",
            (nom_chauffeur, tel_chauffeur, reference),
        )
        return curseur.rowcount == 1


def db_terminer(reference, tel_chauffeur):
    with closing(_connexion()) as conn, conn:
        curseur = conn.execute(
            "UPDATE reservations SET statut = 'Terminée' "
            "WHERE reference = ? AND chauffeur_tel = ? AND statut = 'Acceptée'",
            (reference, tel_chauffeur),
        )
        return curseur.rowcount == 1


def db_remettre_en_attente(reference, tel_chauffeur):
    with closing(_connexion()) as conn, conn:
        curseur = conn.execute(
            "UPDATE reservations SET statut = 'En attente', chauffeur = '', chauffeur_tel = '' "
            "WHERE reference = ? AND chauffeur_tel = ? AND statut = 'Acceptée'",
            (reference, tel_chauffeur),
        )
        return curseur.rowcount == 1


import math

# ---------------- Estimation du prix ----------------
# Tarifs d'exemple a adapter : (prix de base, prix par km, prix minimum) en FCFA
TARIFS = {
    "Voiture": (500, 350, 1500),
    "Moto": (300, 150, 1000),
    "Moto tricyclette": (500, 250, 1500),
    "Voiture porte-bagages": (1000, 400, 2500),
}
SUPPLEMENTS_POIDS = [0, 500, 1500, 3000]  # dans l'ordre de la liste POIDS
SUPPLEMENT_AIDE = 500
FACTEUR_ROUTE = 1.3  # la route est plus longue que la ligne droite

AUTRE = "Autre lieu"

# Zones : coordonnees approximatives du centre de chaque zone
ZONES = {
    "Plateau (centre-ville)": (14.6708, -17.4380),
    "M\u00e9dina": (14.6785, -17.4500),
    "Grand Yoff": (14.7270, -17.4560),
    "HLM / Libert\u00e9": (14.7110, -17.4440),
    "Mermoz / Sacr\u00e9-C\u0153ur": (14.7103, -17.4739),
    "Ouakam": (14.7167, -17.4930),
    "Almadies / Ngor": (14.7442, -17.5160),
    "Yoff": (14.7500, -17.4700),
    "Parcelles Assainies": (14.7600, -17.4400),
    "Pikine": (14.7550, -17.3900),
    "Gu\u00e9diawaye": (14.7750, -17.3900),
    "Thiaroye": (14.7600, -17.3600),
    "Keur Massar": (14.7800, -17.3100),
    "Rufisque": (14.7160, -17.2730),
    "Diamniadio": (14.7200, -17.1800),
    "A\u00e9roport AIBD": (14.6700, -17.0730),
}
ZONES_NOMS = list(ZONES.keys()) + [AUTRE]


def distance_km(lat1, lon1, lat2, lon2):
    rayon = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * rayon * math.asin(math.sqrt(a))


def format_prix(valeur):
    return f"{valeur:,}".replace(",", " ")


def avec_zone(adresse, zone):
    return adresse if zone == AUTRE else adresse + " (" + zone + ")"


def estimer_prix(service, zone_depart, zone_arrivee, distance_manuelle, poids="", aide=False):
    if service not in TARIFS:
        return None, None, "Service inconnu."
    if AUTRE in (zone_depart, zone_arrivee):
        if distance_manuelle <= 0:
            return None, None, "Indiquez la distance en km (obligatoire si vous choisissez \u00ab Autre lieu \u00bb)."
        distance = float(distance_manuelle)
    else:
        a = ZONES[zone_depart]
        b = ZONES[zone_arrivee]
        distance = max(1.0, distance_km(a[0], a[1], b[0], b[1]) * FACTEUR_ROUTE)
    base, par_km, minimum = TARIFS[service]
    prix = base + par_km * distance
    if poids in POIDS:
        prix += SUPPLEMENTS_POIDS[POIDS.index(poids)]
    if aide:
        prix += SUPPLEMENT_AIDE
    prix = max(prix, minimum)
    prix = int(round(prix / 50.0)) * 50
    return prix, distance, None


def db_migrer():
    with closing(_connexion()) as conn, conn:
        existantes = [ligne[1] for ligne in conn.execute("PRAGMA table_info(reservations)")]
        if "prix_estime" not in existantes:
            conn.execute("ALTER TABLE reservations ADD COLUMN prix_estime TEXT DEFAULT ''")


import pandas as pd
from urllib.parse import quote

try:
    from streamlit_geolocation import streamlit_geolocation
except ImportError:
    streamlit_geolocation = None

# ---------------- Geolocalisation ----------------
VITESSE_MOYENNE_KMH = 25  # vitesse moyenne en ville, pour estimer le temps d'arrivee


def en_float(valeur):
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


def lire_position(loc):
    if not loc:
        return None, None
    try:
        lat = en_float(loc.get("latitude"))
        lon = en_float(loc.get("longitude"))
    except AttributeError:
        return None, None
    if lat is None or lon is None:
        return None, None
    return lat, lon


def zone_proche(lat, lon):
    return min(ZONES, key=lambda nom: distance_km(lat, lon, ZONES[nom][0], ZONES[nom][1]))


def depuis(horodatage):
    try:
        ecart = datetime.now() - datetime.strptime(horodatage, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return "r\u00e9cemment"
    minutes = int(ecart.total_seconds() // 60)
    if minutes < 1:
        return "\u00e0 l'instant"
    return "il y a " + str(minutes) + " min"


def position_depart(r):
    lat = en_float(r.get("lat"))
    lon = en_float(r.get("lon"))
    if lat is None or lon is None:
        return None
    return lat, lon


def lien_itineraire(r):
    pos = position_depart(r)
    if pos is not None and r.get("position_exacte") == "oui":
        destination = str(pos[0]) + "," + str(pos[1])
    else:
        destination = r["depart"] + ", S\u00e9n\u00e9gal"
    return "https://www.google.com/maps/dir/?api=1&destination=" + quote(destination)


def prix_pour_distance(service, distance, poids="", aide=False):
    base, par_km, minimum = TARIFS[service]
    prix = base + par_km * distance
    if poids in POIDS:
        prix += SUPPLEMENTS_POIDS[POIDS.index(poids)]
    if aide:
        prix += SUPPLEMENT_AIDE
    prix = max(prix, minimum)
    return int(round(prix / 50.0)) * 50


def estimer_prix_gps(service, position, zone_depart, zone_arrivee, distance_manuelle, poids="", aide=False):
    if position is not None and zone_arrivee != AUTRE and service in TARIFS:
        a = ZONES[zone_arrivee]
        distance = max(1.0, distance_km(position[0], position[1], a[0], a[1]) * FACTEUR_ROUTE)
        return prix_pour_distance(service, distance, poids, aide), distance, None
    return estimer_prix(service, zone_depart, zone_arrivee, distance_manuelle, poids, aide)


def db_migrer_geo():
    nouvelles = [
        "lat", "lon", "position_exacte", "pour_autrui", "contact_nom", "contact_tel",
        "chauffeur_lat", "chauffeur_lon", "position_maj",
    ]
    with closing(_connexion()) as conn, conn:
        existantes = [ligne[1] for ligne in conn.execute("PRAGMA table_info(reservations)")]
        for nom in nouvelles:
            if nom not in existantes:
                conn.execute("ALTER TABLE reservations ADD COLUMN " + nom + " TEXT DEFAULT ''")


def db_maj_position(tel_chauffeur, lat, lon):
    maintenant = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with closing(_connexion()) as conn, conn:
        curseur = conn.execute(
            "UPDATE reservations SET chauffeur_lat = ?, chauffeur_lon = ?, position_maj = ? "
            "WHERE chauffeur_tel = ? AND statut = 'Accept\u00e9e'",
            (str(lat), str(lon), maintenant, tel_chauffeur),
        )
        return curseur.rowcount


def afficher_localisation(r, carte=True, lien=True):
    if r.get("pour_autrui") == "oui":
        st.markdown(
            "\U0001F465 Commande pour une autre personne : " + md(r.get("contact_nom") or "")
            + " \u00b7 " + md(r.get("contact_tel") or "")
        )
        if lien and r.get("contact_tel"):
            st.markdown("[\U0001F4DE Appeler la personne sur place](tel:+221" + r["contact_tel"] + ")")
    pos = position_depart(r)
    if r.get("position_exacte") == "oui":
        st.markdown("\U0001F4CD Position GPS exacte partag\u00e9e par le client")
        if carte and pos is not None:
            st.map(pd.DataFrame({"lat": [pos[0]], "lon": [pos[1]]}), zoom=15)
    else:
        st.markdown("\U0001F4CD Adresse indiqu\u00e9e par le client (position approximative)")
    if lien:
        st.link_button("\U0001F9ED Itin\u00e9raire (Google Maps)", lien_itineraire(r))


def afficher_suivi_chauffeur(r):
    pos_client = position_depart(r)
    if pos_client is None or r.get("position_exacte") != "oui":
        st.info("Le suivi sur la carte n'est disponible que pour une position GPS exacte. Le chauffeur vous appellera.")
        return
    lat_c = en_float(r.get("chauffeur_lat"))
    lon_c = en_float(r.get("chauffeur_lon"))
    if lat_c is None or lon_c is None:
        st.info("Le chauffeur n'a pas encore partag\u00e9 sa position.")
        st.map(pd.DataFrame({"lat": [pos_client[0]], "lon": [pos_client[1]]}), zoom=13)
        return
    km = distance_km(lat_c, lon_c, pos_client[0], pos_client[1]) * FACTEUR_ROUTE
    minutes = max(1, int(round(km / VITESSE_MOYENNE_KMH * 60)))
    m1, m2 = st.columns(2)
    m1.metric("Distance du chauffeur", str(round(km, 1)).replace(".", ",") + " km")
    m2.metric("Arriv\u00e9e estim\u00e9e", "environ " + str(minutes) + " min")
    st.caption("Position du chauffeur mise \u00e0 jour " + depuis(r.get("position_maj")) + ". Estimation indicative.")
    df = pd.DataFrame({
        "lat": [lat_c, pos_client[0]],
        "lon": [lon_c, pos_client[1]],
        "couleur": ["#e31b23", "#0b7a3e"],
    })
    st.map(df, latitude="lat", longitude="lon", color="couleur", zoom=13)
    st.caption("Rouge : chauffeur. Vert : point de prise en charge.")


import streamlit.components.v1 as components

# ---------------- Suivi automatique ----------------
HTML_GPS = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body { font-family: Arial, sans-serif; margin: 0; padding: 4px 0; font-size: 14px; color: #0a5a33; }
</style>
</head>
<body>
<div id="etat">Recherche de votre position...</div>
<script>
function envoyer(type, data) {
  window.parent.postMessage(Object.assign({isStreamlitMessage: true, type: type}, data), "*");
}
envoyer("streamlit:componentReady", {apiVersion: 1});
envoyer("streamlit:setFrameHeight", {height: 36});

var etat = document.getElementById("etat");
var courante = null;
var derniere = null;
var dernierEnvoi = 0;

function metres(a, b) {
  var R = 6371000;
  var rad = Math.PI / 180;
  var dLat = (b.lat - a.lat) * rad;
  var dLon = (b.lon - a.lon) * rad;
  var x = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
          Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
  return 2 * R * Math.asin(Math.sqrt(x));
}

function publier(pos) {
  derniere = pos;
  dernierEnvoi = Date.now();
  envoyer("streamlit:setComponentValue", {
    value: {lat: pos.lat, lon: pos.lon, precision: pos.precision, t: dernierEnvoi},
    dataType: "json"
  });
}

function surPosition(p) {
  courante = {lat: p.coords.latitude, lon: p.coords.longitude, precision: p.coords.accuracy};
  etat.textContent = "Position partag\u00e9e en direct (pr\u00e9cision " + Math.round(courante.precision) + " m)";
  if (derniere === null || (metres(derniere, courante) > 15 && Date.now() - dernierEnvoi > 5000)) {
    publier(courante);
  }
}

function surErreur(e) {
  etat.textContent = "Position indisponible. Autorisez la localisation dans votre navigateur.";
}

setInterval(function () {
  if (courante !== null && Date.now() - dernierEnvoi > 15000) {
    publier(courante);
  }
}, 5000);

if (navigator.geolocation) {
  navigator.geolocation.watchPosition(surPosition, surErreur,
    {enableHighAccuracy: true, maximumAge: 5000, timeout: 20000});
} else {
  etat.textContent = "La g\u00e9olocalisation n'est pas disponible sur cet appareil.";
}
</script>
</body>
</html>
"""


@st.cache_resource
def declarer_composant_gps():
    dossier = BASE_DIR / "composant_gps"
    dossier.mkdir(exist_ok=True)
    (dossier / "index.html").write_text(HTML_GPS, encoding="utf-8")
    return components.declare_component("suivi_gps", path=str(dossier))


def composant_gps(key):
    return declarer_composant_gps()(key=key, default=None)


@st.fragment
def suivi_gps_chauffeur(tel):
    position = composant_gps("gps_" + tel)
    if position:
        lat = en_float(position.get("lat"))
        lon = en_float(position.get("lon"))
        if lat is not None and lon is not None:
            db_maj_position(tel, lat, lon)
            st.caption("Vos clients voient votre position en direct. Gardez cette page ouverte et l'\u00e9cran allum\u00e9.")


@st.fragment(run_every=6)
def panneau_suivi(reference, tel):
    r = db_trouver(reference, tel)
    if r is None:
        st.warning("Aucune demande trouv\u00e9e avec ces informations.")
        return
    st.markdown("### " + STATUTS.get(r["statut"], "") + " " + r["statut"])
    if r["statut"] == "En attente":
        st.info("Votre demande est en attente d'un chauffeur. Cette page se met \u00e0 jour toute seule.")
    elif r["statut"] == "Accept\u00e9e":
        st.success(
            "Un chauffeur a accept\u00e9 votre demande : " + md(r["chauffeur"])
            + ", t\u00e9l. " + md(r["chauffeur_tel"]) + "."
        )
        afficher_suivi_chauffeur(r)
    elif r["statut"] == "Termin\u00e9e":
        st.success("Course termin\u00e9e. Merci d'avoir utilis\u00e9 Mobilit\u00e9 S\u00e9n\u00e9gal !")
    with st.container(border=True):
        afficher_demande(r)


# ---------------- Style ----------------
CSS = """
<style>
header[data-testid="stHeader"], [data-testid="stToolbar"] {display:none;}
.stApp {background:#f6faf7; overflow-x:hidden;}
.block-container, [data-testid="stMainBlockContainer"] {padding:0 !important; max-width:100% !important;}
.st-key-contenu {padding:24px 8vw 10px;}
.st-key-rangee_cartes {margin-top:-90px; position:relative; z-index:3;}

.topbar {display:flex; align-items:center; justify-content:space-between; gap:20px; flex-wrap:wrap;
  background:white; padding:14px 8vw; box-shadow:0 2px 10px rgba(0,0,0,.06);}
.brand {display:flex; align-items:center; gap:14px;}
.logo {width:54px; height:54px; border-radius:50%; display:flex; align-items:center; justify-content:center;
  font-size:26px; color:white; text-shadow:0 0 3px rgba(0,0,0,.5);
  background:linear-gradient(90deg,#00853f 0 33.3%,#fdef42 33.3% 66.6%,#e31b23 66.6% 100%);}
.brand-name {font-size:32px; font-weight:800; color:#0a3d2a; line-height:1.1;}
.brand-name span {color:#0b9444;}
.brand-tag {font-size:14px; font-style:italic; color:#333;}
.nav {display:flex; gap:30px; font-size:15px; color:#33443b;}
.nav span {padding:8px 0;}
.nav .actif {color:#0b7a3e; font-weight:600; border-bottom:3px solid #0b7a3e;}
.connexion {background:#0b7a3e; color:white; padding:12px 26px; border-radius:30px; font-weight:600;}

.hero {position:relative; min-height:270px; padding:34px 8vw 100px;
  background:linear-gradient(112deg, rgba(8,64,86,.97) 0%, rgba(8,64,86,.93) 38%, rgba(8,64,86,0) 38.3%),
             var(--photo) center 40% / cover;
  background-color:#0b4a5c;}
.hero-text {max-width:36%; min-width:280px;}
.hero-text * {color:white !important;}
.hero-titre {font-size:clamp(26px,3vw,44px); font-weight:800; line-height:1.15; margin-bottom:14px;}
.hero-sous {font-size:17px; line-height:1.5; margin-bottom:16px;}
.tricolore {width:120px; height:5px; border-radius:3px;
  background:linear-gradient(90deg,#00853f 33.3%,#fdef42 33.3% 66.6%,#e31b23 66.6%);}
.hero-slogan {position:absolute; right:6vw; top:34px; transform:rotate(-12deg); color:white !important;
  font-style:italic; font-weight:700; font-size:clamp(18px,2.4vw,32px); line-height:1.15;
  text-shadow:0 2px 8px rgba(0,0,0,.55);}

[class*="st-key-carte_"] {background:white; border-radius:20px; padding:10px 10px 18px;
  box-shadow:0 6px 22px rgba(10,74,44,.12); border:1px solid #e3ebe6;}
.c-top {position:relative; margin-bottom:36px;}
.c-top img {width:100%; height:200px; object-fit:cover; border-radius:14px; display:block;}
.c-ph {height:200px; display:flex; align-items:center; justify-content:center; background:#e6ece8;
  border-radius:14px; color:#6b7a72; font-size:14px;}
.c-icon {position:absolute; left:18px; bottom:-30px; width:64px; height:64px; border-radius:50%;
  display:flex; align-items:center; justify-content:center; font-size:30px; border:4px solid white;}
.c-body {padding:0 12px;}
.c-title {font-size:26px; font-weight:800; color:#0a2f20; margin-bottom:6px;}
.c-desc {font-size:15px; color:#6b7a72; line-height:1.5; margin-bottom:12px; min-height:46px;}
.c-pill {display:inline-block; padding:6px 14px; border-radius:10px; font-size:14px; font-weight:600; margin-bottom:16px;}
[class*="st-key-carte_"] [data-testid="stButton"], [class*="st-key-carte_"] .stButton {padding:0 12px;}
[class*="st-key-carte_"] button {width:100%; border:none !important; border-radius:12px; height:48px; font-weight:600;}
[class*="st-key-carte_"] button:hover {filter:brightness(1.08);}
__BOUTONS__

.features {display:grid; grid-template-columns:repeat(4,1fr); gap:10px; background:#e9f4ee;
  border-radius:18px; padding:20px 14px; margin:28px 0 10px;}
.f {display:flex; align-items:center; gap:12px; padding:0 10px; border-right:1px solid #cfe2d6;}
.f:last-child {border-right:none;}
.f-ico {font-size:30px;}
.f b {display:block; color:#0a5a33; font-size:15px;}
.f span {color:#6b7a72; font-size:13px;}

.pied {display:flex; justify-content:space-between; flex-wrap:wrap; gap:10px; background:#0a4a2c;
  color:white; padding:20px 8vw; font-size:14px;}
.pied .sep {display:inline-block; width:1px; height:16px; background:#6fa58a; margin:0 14px; vertical-align:middle;}

@media (max-width:800px) {
  .nav {display:none;}
  .hero {background:linear-gradient(rgba(8,64,86,.85),rgba(8,64,86,.85)), var(--photo) center / cover;
    background-color:#0b4a5c;}
  .hero-text {max-width:100%;}
  .hero-slogan {display:none;}
  .features {grid-template-columns:1fr 1fr;}
  .f {border-right:none;}
  .st-key-contenu {padding:24px 4vw 10px;}
}
</style>
"""

ENTETE = """
<div class="topbar">
<div class="brand">
<div class="logo">★</div>
<div><div class="brand-name">Mobilité <span>Sénégal</span></div>
<div class="brand-tag">Plus proche de vous, partout au Sénégal</div></div>
</div>
<div class="nav"><span class="actif">🏠 Accueil</span><span>📅 Mes réservations</span><span>❓ Aide</span></div>
<div class="connexion">👤 Connexion</div>
</div>
"""

HERO = """
<div class="hero" style="--photo:__FOND__">
<div class="hero-text">
<div class="hero-titre">Déplacez-vous facilement<br>au Sénégal</div>
<div class="hero-sous">Moto, voiture et transport de marchandises : choisissez votre moyen de transport
et partez à la découverte de toutes les régions du Sénégal.</div>
<div class="tricolore"></div>
</div>
<div class="hero-slogan">Le Sénégal<br>se déplace<br>ensemble</div>
</div>
"""

FEATURES = """
<div class="features">
<div class="f"><div class="f-ico">🛡️</div><div><b>Sécurité</b><span>Des trajets plus sûrs pour tous.</span></div></div>
<div class="f"><div class="f-ico">🍃</div><div><b>Accessibilité</b><span>Des solutions pour tous les budgets.</span></div></div>
<div class="f"><div class="f-ico">📍</div><div><b>Couverture nationale</b><span>Des villes aux régions, partout au Sénégal.</span></div></div>
<div class="f"><div class="f-ico">👥</div><div><b>Solidarité</b><span>Une mobilité qui rassemble tout le monde.</span></div></div>
</div>
"""

PIED = """
<div class="pied">
<div><b>Mobilité Sénégal</b><span class="sep"></span>Ensemble pour une mobilité durable et inclusive.</div>
<div>© 2026 Mobilité Sénégal · Prototype</div>
</div>
"""

# ---------------- Fonctions utiles ----------------
db_init()
db_migrer()
db_migrer_geo()

if "page" not in st.session_state:
    st.session_state.page = "accueil"


def aller_a(page):
    st.session_state.page = page


def commander(nom_service):
    st.session_state.service = nom_service
    st.session_state.page = "formulaire"


def html(contenu):
    st.markdown(re.sub(r"\s*\n\s*", " ", contenu), unsafe_allow_html=True)


def md(texte):
    """Neutralise le markdown dans les textes saisis par les utilisateurs."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~$:])", r"\\\1", str(texte))


@st.cache_data
def image_base64(chemin_relatif, largeur, hauteur=None):
    chemin = BASE_DIR / chemin_relatif
    if not chemin.exists():
        return None
    img = Image.open(chemin).convert("RGB")
    if hauteur:
        img = ImageOps.fit(img, (largeur, hauteur))
    else:
        img.thumbnail((largeur, largeur))
    tampon = io.BytesIO()
    img.save(tampon, format="JPEG", quality=80)
    return base64.b64encode(tampon.getvalue()).decode()


def afficher_photo(chemin_relatif):
    chemin = BASE_DIR / chemin_relatif
    if chemin.exists():
        img = Image.open(chemin).convert("RGB")
        img = ImageOps.fit(img, TAILLE_PHOTO)
        st.image(img, use_container_width=True)
    else:
        st.caption(f"Photo introuvable : {chemin_relatif}")


def carte(service, bouton, action, args, cle_bouton):
    afficher_photo(service["image"])
    st.subheader(service["nom"])
    st.write(service["description"])
    if service["prix"]:
        st.markdown(f"**À partir de {service['prix']} FCFA**")
    st.button(bouton, key=cle_bouton, on_click=action, args=args)


def carte_html(s):
    photo = image_base64(s["image"], 800, 480)
    if photo:
        image = f'<img src="data:image/jpeg;base64,{photo}">'
    else:
        image = f'<div class="c-ph">Photo introuvable : {s["image"]}</div>'
    if s["prix"]:
        prix = f"{s['prix']:,}".replace(",", "&nbsp;")
        pastille = f"À partir de {prix} FCFA"
    else:
        pastille = s["pastille"]
    return (
        f'<div class="c-top">{image}'
        f'<div class="c-icon" style="background:{s["couleur"]}">{s["icone"]}</div></div>'
        f'<div class="c-body"><div class="c-title">{s["nom"]}</div>'
        f'<div class="c-desc">{s["description"]}</div>'
        f'<span class="c-pill" style="color:{s["couleur"]};background:{s["fond"]}">{pastille}</span></div>'
    )


def telephone_valide(numero):
    numero = re.sub(r"[\s.\-]", "", numero)
    return re.fullmatch(r"(\+?221)?7[05678]\d{7}", numero) is not None


def normaliser_telephone(numero):
    numero = re.sub(r"[\s.\-]", "", numero)
    return re.sub(r"^\+?221", "", numero)


def afficher_message():
    msg = st.session_state.pop("message", None)
    if msg:
        niveau, texte = msg
        getattr(st, niveau)(texte)


def afficher_demande(r):
    st.markdown(f"**{md(r['service'])}** · `{r['reference']}`")
    st.markdown(f"📍 {md(r['depart'])} → {md(r['arrivee'])}")
    st.markdown(f"🕒 {md(r['date_prise_en_charge'])}")
    st.markdown(f"👤 {md(r['nom'])} · 📞 {md(r['telephone'])}")
    if r["marchandise"]:
        aide = " · aide au chargement demandée" if r["aide_chargement"] == "oui" else ""
        st.markdown(f"📦 {md(r['marchandise'])} ({md(r['poids'])}){aide}")
    elif r["passagers"]:
        st.markdown(f"🧍 Passagers : {md(r['passagers'])}")
    if r.get("prix_estime"):
        st.markdown("\U0001F4B0 Prix estim\u00e9 : " + md(r["prix_estime"]) + " FCFA")
    if r["remarques"]:
        st.markdown(f"💬 {md(r['remarques'])}")


def afficher_entete(page):
    css_boutons = ""
    for s in ACCUEIL:
        sel = ".st-key-btn_" + s["cle"]
        css_boutons += sel + " button{background:" + s["couleur"] + " !important; color:white !important;}"
        css_boutons += sel + " button p{color:white !important;}"
    contenu = CSS.replace("__BOUTONS__", css_boutons) + ENTETE
    if page == "accueil":
        photo = image_base64("images/fond_renaissance.jpg", 1600)
        fond = f"url('data:image/jpeg;base64,{photo}')" if photo else "none"
        contenu += HERO.replace("__FOND__", fond)
    html(contenu)


# ---------------- Actions chauffeur ----------------
def accepter_course(reference):
    ch = st.session_state.chauffeur
    if db_accepter(reference, ch["nom"], ch["tel"]):
        st.session_state.message = ("success", f"Course {reference} acceptée.")
    else:
        st.session_state.message = ("warning", "Cette course a déjà été prise par un autre chauffeur.")


def terminer_course(reference):
    ch = st.session_state.chauffeur
    if db_terminer(reference, ch["tel"]):
        st.session_state.message = ("success", f"Course {reference} terminée.")


def liberer_course(reference):
    ch = st.session_state.chauffeur
    if db_remettre_en_attente(reference, ch["tel"]):
        st.session_state.message = ("info", f"Course {reference} remise en attente.")


def deconnecter_chauffeur():
    st.session_state.pop("chauffeur", None)


# ---------------- Pages ----------------
def page_accueil():
    with st.container(key="rangee_cartes"):
        cols = st.columns(3, gap="large")
        for col, s in zip(cols, ACCUEIL):
            with col:
                with st.container(key=f"carte_{s['cle']}"):
                    html(carte_html(s))
                    if s["cle"] == "marchandises":
                        st.button("Choisir ce transport  →", key="btn_marchandises",
                                  on_click=aller_a, args=("marchandises",))
                    else:
                        st.button("Choisir ce transport  →", key=f"btn_{s['cle']}",
                                  on_click=commander, args=(s["nom"],))
    html(FEATURES)
    c1, c2, _ = st.columns([1, 1, 2])
    c1.button("📅 Suivre ma demande", on_click=aller_a, args=("suivi",))
    c2.button("🚖 Espace chauffeur", on_click=aller_a, args=("chauffeur",))


def page_marchandises():
    st.subheader("Transport de marchandises : choisissez votre véhicule")
    st.button("← Retour", on_click=aller_a, args=("accueil",))
    cols = st.columns(2)
    for col, s in zip(cols, MARCHANDISES):
        with col:
            carte(s, f"Commander : {s['nom']}", commander, (s["nom"],), f"btn_{s['cle']}")


def adresse_complete(repere, zone):
    repere = repere.strip()
    if repere:
        return avec_zone(repere, zone)
    return zone


def page_formulaire():
    service = st.session_state.get("service", "")
    est_marchandise = service in NOMS_MARCHANDISES
    retour = "marchandises" if est_marchandise else "accueil"

    st.button("\u2190 Retour", on_click=aller_a, args=(retour,))
    st.subheader("Commande : " + service)

    MODE_MOI = "Pour moi, \u00e0 ma position"
    MODE_AUTRE = "Pour quelqu'un d'autre ou \u00e0 une autre adresse"
    mode = st.radio("Pour qui est cette commande ?", [MODE_MOI, MODE_AUTRE], horizontal=True, key="mode_commande")
    pour_moi = mode == MODE_MOI

    zone_depart = ZONES_NOMS[0]
    position = None
    repere_depart = ""
    contact_nom = ""
    contact_tel = ""

    if pour_moi:
        if streamlit_geolocation is None:
            st.warning(
                "Le module de g\u00e9olocalisation n'est pas install\u00e9. Choisissez \u00ab autre adresse \u00bb "
                "ou installez-le : python -m pip install streamlit-geolocation"
            )
        else:
            st.write("Appuyez sur le bouton ci-dessous pour partager votre position :")
            lat, lon = lire_position(streamlit_geolocation())
            if lat is not None:
                position = (lat, lon)
        if position is not None:
            zone_depart = zone_proche(position[0], position[1])
            st.success("Position d\u00e9tect\u00e9e, pr\u00e8s de : " + zone_depart)
            st.map(pd.DataFrame({"lat": [position[0]], "lon": [position[1]]}), zoom=15)
        else:
            st.info("En attente de votre position. Si le bouton ne fonctionne pas, choisissez \u00ab autre adresse \u00bb.")
    else:
        a1, a2 = st.columns(2)
        with a1:
            zone_depart = st.selectbox("Zone de d\u00e9part *", ZONES_NOMS, key="zone_depart")
        with a2:
            repere_depart = st.text_input(
                "Adresse exacte de d\u00e9part *",
                placeholder="Ex : Villa 12, rue 5, pr\u00e8s de la mosqu\u00e9e",
                key="repere_depart",
            )
        a3, a4 = st.columns(2)
        with a3:
            contact_nom = st.text_input("Nom de la personne sur place *", key="contact_nom")
        with a4:
            contact_tel = st.text_input(
                "T\u00e9l\u00e9phone de la personne sur place *", placeholder="77 123 45 67", key="contact_tel"
            )

    zone_arrivee = st.selectbox("Arriv\u00e9e *", ZONES_NOMS, index=1, key="zone_arrivee")

    distance_manuelle = 0.0
    if AUTRE in (zone_depart, zone_arrivee):
        distance_manuelle = st.number_input(
            "Distance approximative en km *",
            min_value=0.0, max_value=1000.0, value=0.0, step=1.0, key="distance_manuelle",
        )

    poids = ""
    if est_marchandise:
        poids = st.selectbox("Poids approximatif de la marchandise", POIDS, key="poids")

    zone_prix = st.container()

    telephone = st.text_input("Votre t\u00e9l\u00e9phone *", placeholder="77 123 45 67", key="telephone")

    with st.expander("Plus de d\u00e9tails (facultatif)"):
        nom = st.text_input("Votre nom", key="nom")
        if pour_moi:
            repere_depart = st.text_input(
                "Pr\u00e9cision sur votre position (facultatif)", placeholder="Ex : devant la boutique bleue",
                key="precision_position",
            )
        repere_arrivee = st.text_input("Rep\u00e8re d'arriv\u00e9e", key="repere_arrivee")
        quand = st.radio("Quand ?", ["D\u00e8s que possible", "Plus tard"], horizontal=True, key="quand")
        date_pec = datetime.now().date()
        heure_pec = datetime.now().time().replace(second=0, microsecond=0)
        if quand == "Plus tard":
            d1, d2 = st.columns(2)
            with d1:
                date_pec = st.date_input("Date", value=date_pec, key="date_pec")
            with d2:
                heure_pec = st.time_input("Heure", value=heure_pec, key="heure_pec")
        passagers = ""
        marchandise = ""
        aide = False
        if est_marchandise:
            marchandise = st.text_input(
                "Nature de la marchandise",
                placeholder="Ex : sacs de riz, meubles, l\u00e9gumes",
                key="marchandise",
            )
            aide = st.checkbox("J'ai besoin d'aide pour le chargement / d\u00e9chargement", key="aide")
        else:
            maximum = 2 if service == "Moto" else 4
            passagers = st.number_input(
                "Nombre de passagers", min_value=1, max_value=maximum, value=1, key="passagers"
            )
        remarques = st.text_area("Remarques pour le chauffeur", key="remarques")

    prix, distance, erreur_prix = estimer_prix_gps(
        service, position, zone_depart, zone_arrivee, distance_manuelle, poids, aide
    )
    attente_position = pour_moi and position is None
    with zone_prix:
        if attente_position:
            st.info("Le prix s'affichera apr\u00e8s le partage de votre position.")
        elif erreur_prix:
            st.info("Indiquez la distance pour afficher le prix.")
        else:
            st.metric("Prix estim\u00e9", format_prix(prix) + " FCFA")
            st.caption(
                "Distance d'environ " + str(round(distance, 1)).replace(".", ",")
                + " km. Estimation indicative : le prix final est confirm\u00e9 avec le chauffeur."
            )

    if st.button("Envoyer la demande", type="primary"):
        erreurs = []
        if not telephone_valide(telephone):
            erreurs.append("Votre num\u00e9ro de t\u00e9l\u00e9phone n'est pas valide (ex : 77 123 45 67).")
        if attente_position:
            erreurs.append("Partagez votre position avec le bouton, ou choisissez \u00ab autre adresse \u00bb.")
        if not pour_moi:
            if not repere_depart.strip():
                erreurs.append("L'adresse exacte de d\u00e9part est obligatoire.")
            if not contact_nom.strip():
                erreurs.append("Indiquez le nom de la personne sur place.")
            if not telephone_valide(contact_tel):
                erreurs.append("Le t\u00e9l\u00e9phone de la personne sur place n'est pas valide.")
        if zone_arrivee == AUTRE and not repere_arrivee.strip():
            erreurs.append("Pr\u00e9cisez le lieu d'arriv\u00e9e dans \u00ab Plus de d\u00e9tails \u00bb.")
        if erreur_prix and not attente_position:
            erreurs.append(erreur_prix)

        if erreurs:
            for e in erreurs:
                st.error(e)
        else:
            maintenant = datetime.now()
            if quand == "Plus tard":
                prise_en_charge = str(date_pec) + " " + heure_pec.strftime("%H:%M")
            else:
                prise_en_charge = "D\u00e8s que possible"
            nature = (marchandise.strip() or "Non pr\u00e9cis\u00e9e") if est_marchandise else ""

            if pour_moi:
                lat_dep, lon_dep = position
                exacte = "oui"
                depart_txt = "Position GPS (pr\u00e8s de " + zone_depart + ")"
                if repere_depart.strip():
                    depart_txt += " - " + repere_depart.strip()
            else:
                exacte = "non"
                if zone_depart != AUTRE:
                    lat_dep, lon_dep = ZONES[zone_depart]
                else:
                    lat_dep, lon_dep = "", ""
                depart_txt = adresse_complete(repere_depart, zone_depart)

            reservation = {
                "reference": "VTC-" + maintenant.strftime("%Y%m%d-%H%M%S") + "-" + token_hex(2).upper(),
                "date_demande": maintenant.strftime("%Y-%m-%d %H:%M"),
                "service": service,
                "nom": nom.strip() or "Client",
                "telephone": normaliser_telephone(telephone),
                "depart": depart_txt,
                "arrivee": adresse_complete(repere_arrivee, zone_arrivee),
                "date_prise_en_charge": prise_en_charge,
                "passagers": passagers,
                "marchandise": nature,
                "poids": poids,
                "aide_chargement": "oui" if aide else "non",
                "remarques": remarques.strip(),
                "statut": "En attente",
                "chauffeur": "",
                "chauffeur_tel": "",
                "prix_estime": format_prix(prix),
                "lat": str(lat_dep),
                "lon": str(lon_dep),
                "position_exacte": exacte,
                "pour_autrui": "non" if pour_moi else "oui",
                "contact_nom": contact_nom.strip(),
                "contact_tel": normaliser_telephone(contact_tel) if contact_tel.strip() else "",
            }
            try:
                db_ajouter(reservation)
            except Exception as erreur:
                st.error("Erreur d'enregistrement : " + str(erreur))
            else:
                st.session_state.derniere_reservation = reservation
                st.session_state.page = "confirmation"
                st.rerun()


def page_confirmation():
    r = st.session_state.get("derniere_reservation")
    if r:
        st.success(f"Demande envoyée. Référence : {r['reference']}")
        st.info("Conservez cette référence : elle vous permet de suivre votre demande.")
        st.markdown(
            f"""
**Service :** {md(r['service'])}  
**Nom :** {md(r['nom'])}  
**Téléphone :** {md(r['telephone'])}  
**Départ :** {md(r['depart'])}  
**Arrivée :** {md(r['arrivee'])}  
**Prise en charge :** {md(r['date_prise_en_charge'])}
"""
        )
        if r.get("prix_estime"):
            st.markdown("**Prix estim\u00e9 :** " + md(r["prix_estime"]) + " FCFA")
        if r["marchandise"]:
            st.markdown(f"**Marchandise :** {md(r['marchandise'])} ({md(r['poids'])})")
    c1, c2, _ = st.columns([1, 1, 2])
    c1.button("← Nouvelle commande", on_click=aller_a, args=("accueil",))
    c2.button("📅 Suivre ma demande", on_click=aller_a, args=("suivi",))


def page_suivi():
    st.button("\u2190 Retour", on_click=aller_a, args=("accueil",))
    st.subheader("Suivre ma demande")

    if "suivi" not in st.session_state and st.session_state.get("derniere_reservation"):
        dr = st.session_state.derniere_reservation
        st.session_state.suivi = {"reference": dr["reference"], "tel": dr["telephone"]}

    courant = st.session_state.get("suivi") or {}
    with st.form("formulaire_suivi"):
        reference = st.text_input(
            "R\u00e9f\u00e9rence de la demande *", value=courant.get("reference", ""),
            placeholder="VTC-20261029-153012-A3F9",
        )
        telephone = st.text_input(
            "T\u00e9l\u00e9phone utilis\u00e9 pour la commande *", value=courant.get("tel", ""),
            placeholder="77 123 45 67",
        )
        voir = st.form_submit_button("Voir le statut")

    if voir:
        if not reference.strip() or not telephone_valide(telephone):
            st.error("Indiquez la r\u00e9f\u00e9rence et un num\u00e9ro de t\u00e9l\u00e9phone valide.")
            return
        st.session_state.suivi = {
            "reference": reference.strip().upper(),
            "tel": normaliser_telephone(telephone),
        }

    suivi = st.session_state.get("suivi")
    if not suivi:
        return
    st.caption("Le suivi se met \u00e0 jour automatiquement.")
    panneau_suivi(suivi["reference"], suivi["tel"])


def page_chauffeur():
    st.button("\u2190 Retour", on_click=aller_a, args=("accueil",))
    st.subheader("Espace chauffeur")

    ch = st.session_state.get("chauffeur")
    if not ch:
        with st.form("connexion_chauffeur"):
            nom = st.text_input("Votre nom *")
            tel = st.text_input("Votre t\u00e9l\u00e9phone *", placeholder="77 123 45 67")
            code = st.text_input("Code d'acc\u00e8s *", type="password")
            ok = st.form_submit_button("Se connecter")
        if ok:
            if not nom.strip():
                st.error("Le nom est obligatoire.")
            elif not telephone_valide(tel):
                st.error("Le num\u00e9ro de t\u00e9l\u00e9phone n'est pas valide.")
            elif not CODE_CHAUFFEUR or code != CODE_CHAUFFEUR:
                st.error("Code d'acc\u00e8s incorrect.")
            else:
                st.session_state.chauffeur = {"nom": nom.strip(), "tel": normaliser_telephone(tel)}
                st.rerun()
        return

    afficher_message()
    c1, c2, _ = st.columns([2, 1, 1])
    c1.write("Connect\u00e9 : **" + md(ch["nom"]) + "**")
    c2.button("Se d\u00e9connecter", on_click=deconnecter_chauffeur)
    st.button("\U0001F504 Actualiser")

    en_attente = db_lister(statut="En attente")
    mes_courses = db_lister(statut="Accept\u00e9e", chauffeur_tel=ch["tel"])
    terminees = db_lister(statut="Termin\u00e9e", chauffeur_tel=ch["tel"], ordre="DESC")

    onglet1, onglet2 = st.tabs([
        "Demandes en attente (" + str(len(en_attente)) + ")",
        "Mes courses (" + str(len(mes_courses)) + ")",
    ])

    with onglet1:
        if not en_attente:
            st.info("Aucune demande en attente pour le moment.")
        for r in en_attente:
            with st.container(border=True):
                afficher_demande(r)
                afficher_localisation(r, carte=False, lien=False)
                st.button("Accepter cette course", key="acc_" + r["reference"],
                          on_click=accepter_course, args=(r["reference"],))

    with onglet2:
        if mes_courses:
            partage = st.toggle("\U0001F4E1 Partager ma position automatiquement", key="partage_auto")
            if partage:
                suivi_gps_chauffeur(ch["tel"])
            else:
                st.caption("Activez le partage pour que vos clients vous voient arriver en direct.")
        else:
            st.info("Vous n'avez aucune course en cours.")
        for r in mes_courses:
            with st.container(border=True):
                afficher_demande(r)
                afficher_localisation(r)
                st.markdown(
                    "[\U0001F4DE Appeler le client](tel:+221" + r["telephone"] + ") \u00b7 "
                    "[\U0001F4AC WhatsApp](https://wa.me/221" + r["telephone"] + ")"
                )
                b1, b2, _ = st.columns([1, 1, 2])
                b1.button("Terminer", key="fin_" + r["reference"],
                          on_click=terminer_course, args=(r["reference"],))
                b2.button("Remettre en attente", key="rel_" + r["reference"],
                          on_click=liberer_course, args=(r["reference"],))
        with st.expander("Courses termin\u00e9es (" + str(len(terminees)) + ")"):
            for r in terminees:
                st.markdown(
                    "\U0001F3C1 `" + r["reference"] + "` \u00b7 " + md(r["service"]) + " \u00b7 "
                    + md(r["depart"]) + " \u2192 " + md(r["arrivee"])
                )


# ---------------- Affichage ----------------
page = st.session_state.page
afficher_entete(page)

with st.container(key="contenu"):
    if page == "accueil":
        page_accueil()
    elif page == "marchandises":
        page_marchandises()
    elif page == "formulaire":
        page_formulaire()
    elif page == "confirmation":
        page_confirmation()
    elif page == "suivi":
        page_suivi()
    elif page == "chauffeur":
        page_chauffeur()

html(PIED)
