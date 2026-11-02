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
CODE_CHAUFFEUR = "chauffeur2026"

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
    "statut", "chauffeur", "chauffeur_tel",
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


def page_formulaire():
    service = st.session_state.get("service", "")
    est_marchandise = service in NOMS_MARCHANDISES
    retour = "marchandises" if est_marchandise else "accueil"

    st.button("← Retour", on_click=aller_a, args=(retour,))
    st.subheader(f"Commande : {service}")

    with st.form("formulaire_commande"):
        col1, col2 = st.columns(2)
        with col1:
            nom = st.text_input("Nom complet *")
        with col2:
            telephone = st.text_input("Téléphone *", placeholder="77 123 45 67")

        depart = st.text_input("Adresse de départ *", placeholder="Ex : Yoff, près de la mosquée")
        arrivee = st.text_input("Adresse d'arrivée *", placeholder="Ex : Plateau, Place de l'Indépendance")

        col3, col4 = st.columns(2)
        with col3:
            date_pec = st.date_input("Date de prise en charge", value=datetime.now().date())
        with col4:
            heure_pec = st.time_input(
                "Heure de prise en charge",
                value=datetime.now().time().replace(second=0, microsecond=0),
            )

        passagers = ""
        marchandise = ""
        poids = ""
        aide = False

        if est_marchandise:
            marchandise = st.text_input("Nature de la marchandise *", placeholder="Ex : sacs de riz, meubles, légumes")
            poids = st.selectbox("Poids approximatif", POIDS)
            aide = st.checkbox("J'ai besoin d'aide pour le chargement / déchargement")
        else:
            maximum = 2 if service == "Moto" else 4
            passagers = st.number_input("Nombre de passagers", min_value=1, max_value=maximum, value=1)

        remarques = st.text_area("Remarques (facultatif)", placeholder="Précisions pour le chauffeur")

        envoyer = st.form_submit_button("Envoyer la demande")

    if envoyer:
        erreurs = []
        if not nom.strip():
            erreurs.append("Le nom est obligatoire.")
        if not telephone_valide(telephone):
            erreurs.append("Le numéro de téléphone n'est pas valide (ex : 77 123 45 67).")
        if not depart.strip():
            erreurs.append("L'adresse de départ est obligatoire.")
        if not arrivee.strip():
            erreurs.append("L'adresse d'arrivée est obligatoire.")
        if est_marchandise and not marchandise.strip():
            erreurs.append("Indiquez la nature de la marchandise.")

        if erreurs:
            for e in erreurs:
                st.error(e)
        else:
            maintenant = datetime.now()
            reservation = {
                "reference": "VTC-" + maintenant.strftime("%Y%m%d-%H%M%S") + "-" + token_hex(2).upper(),
                "date_demande": maintenant.strftime("%Y-%m-%d %H:%M"),
                "service": service,
                "nom": nom.strip(),
                "telephone": normaliser_telephone(telephone),
                "depart": depart.strip(),
                "arrivee": arrivee.strip(),
                "date_prise_en_charge": f"{date_pec} {heure_pec.strftime('%H:%M')}",
                "passagers": passagers,
                "marchandise": marchandise.strip(),
                "poids": poids,
                "aide_chargement": "oui" if aide else "non",
                "remarques": remarques.strip(),
                "statut": "En attente",
                "chauffeur": "",
                "chauffeur_tel": "",
            }
            try:
                db_ajouter(reservation)
            except Exception as e:
                st.error(f"Erreur d'enregistrement : {e}")
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
        if r["marchandise"]:
            st.markdown(f"**Marchandise :** {md(r['marchandise'])} ({md(r['poids'])})")
    c1, c2, _ = st.columns([1, 1, 2])
    c1.button("← Nouvelle commande", on_click=aller_a, args=("accueil",))
    c2.button("📅 Suivre ma demande", on_click=aller_a, args=("suivi",))


def page_suivi():
    st.button("← Retour", on_click=aller_a, args=("accueil",))
    st.subheader("Suivre ma demande")

    with st.form("formulaire_suivi"):
        reference = st.text_input("Référence de la demande *", placeholder="VTC-20261029-153012-A3F9")
        telephone = st.text_input("Téléphone utilisé pour la commande *", placeholder="77 123 45 67")
        voir = st.form_submit_button("Voir le statut")

    if voir:
        if not reference.strip() or not telephone_valide(telephone):
            st.error("Indiquez la référence et un numéro de téléphone valide.")
            return
        r = db_trouver(reference.strip().upper(), normaliser_telephone(telephone))
        if r is None:
            st.warning("Aucune demande trouvée avec ces informations.")
            return
        st.markdown(f"### {STATUTS.get(r['statut'], '')} {r['statut']}")
        if r["statut"] == "En attente":
            st.info("Votre demande est en attente d'un chauffeur. Revenez vérifier dans quelques instants.")
        elif r["statut"] == "Acceptée":
            st.success(f"Un chauffeur a accepté votre demande : {r['chauffeur']}, tél. {r['chauffeur_tel']}.")
        elif r["statut"] == "Terminée":
            st.success("Course terminée. Merci d'avoir utilisé Mobilité Sénégal !")
        with st.container(border=True):
            afficher_demande(r)


def page_chauffeur():
    st.button("← Retour", on_click=aller_a, args=("accueil",))
    st.subheader("Espace chauffeur")

    ch = st.session_state.get("chauffeur")
    if not ch:
        with st.form("connexion_chauffeur"):
            nom = st.text_input("Votre nom *")
            tel = st.text_input("Votre téléphone *", placeholder="77 123 45 67")
            code = st.text_input("Code d'accès *", type="password")
            ok = st.form_submit_button("Se connecter")
        if ok:
            if not nom.strip():
                st.error("Le nom est obligatoire.")
            elif not telephone_valide(tel):
                st.error("Le numéro de téléphone n'est pas valide.")
            elif code != CODE_CHAUFFEUR:
                st.error("Code d'accès incorrect.")
            else:
                st.session_state.chauffeur = {"nom": nom.strip(), "tel": normaliser_telephone(tel)}
                st.rerun()
        return

    afficher_message()
    c1, c2, _ = st.columns([2, 1, 1])
    c1.write(f"Connecté : **{md(ch['nom'])}**")
    c2.button("Se déconnecter", on_click=deconnecter_chauffeur)
    st.button("🔄 Actualiser")

    en_attente = db_lister(statut="En attente")
    mes_courses = db_lister(statut="Acceptée", chauffeur_tel=ch["tel"])
    terminees = db_lister(statut="Terminée", chauffeur_tel=ch["tel"], ordre="DESC")

    onglet1, onglet2 = st.tabs([
        f"Demandes en attente ({len(en_attente)})",
        f"Mes courses ({len(mes_courses)})",
    ])

    with onglet1:
        if not en_attente:
            st.info("Aucune demande en attente pour le moment.")
        for r in en_attente:
            with st.container(border=True):
                afficher_demande(r)
                st.button("Accepter cette course", key=f"acc_{r['reference']}",
                          on_click=accepter_course, args=(r["reference"],))

    with onglet2:
        if not mes_courses:
            st.info("Vous n'avez aucune course en cours.")
        for r in mes_courses:
            with st.container(border=True):
                afficher_demande(r)
                b1, b2, _ = st.columns([1, 1, 2])
                b1.button("Terminer", key=f"fin_{r['reference']}",
                          on_click=terminer_course, args=(r["reference"],))
                b2.button("Remettre en attente", key=f"rel_{r['reference']}",
                          on_click=liberer_course, args=(r["reference"],))
        with st.expander(f"Courses termin\u00e9es ({len(terminees)})"):
            for r in terminees:
                st.markdown(f"\U0001F3C1 `{r['reference']}` \u00b7 {md(r['service'])} \u00b7 {md(r['depart'])} \u2192 {md(r['arrivee'])}")


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
