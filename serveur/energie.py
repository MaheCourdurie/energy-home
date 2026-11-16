"""Energy Home — serveur de la tablette (toujours allumée).

- Sert le dashboard (index.html) et ses données (/api/data) sur le réseau Tailscale uniquement.
- Une fois par jour (entre 8h30 et 9h50, heure choisie au hasard), récupère les relevés J-1 du Linky via Conso API.
- Réglages : config.json (tarifs, heures creuses). Accès Enedis : .env (PRM=..., TOKEN=...), jamais dans git.
- Sans .env : pas de collecte, le dashboard reste en mode démo.
"""
import datetime as dt
import ipaddress
import json
import os
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ICI = os.path.dirname(os.path.abspath(__file__))
PORT = 8090
TAILSCALE = ipaddress.ip_network("100.64.0.0/10")
API = "https://conso.boris.sh/api/courbe_de_charge_consommation"
UA = "energy-home (github.com/MaheCourdurie/energy-home)"
HISTORIQUE_JOURS = 90
verrou = threading.Lock()
etat = {"derniere_tentative": None, "erreur": None}


def chemin(nom):
    return os.path.join(ICI, nom)


def lire_json(nom, defaut):
    try:
        with open(chemin(nom), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defaut


def ecrire_json(nom, valeur):
    tmp = chemin(nom + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(valeur, f, ensure_ascii=False)
    os.replace(tmp, chemin(nom))


def lire_env():
    env = {}
    try:
        with open(chemin(".env"), encoding="utf-8") as f:
            for ligne in f:
                if "=" in ligne and not ligne.strip().startswith("#"):
                    k, v = ligne.split("=", 1)
                    env[k.strip()] = v.strip().strip('"\'')
    except OSError:
        pass
    return env


def plages_hc(texte):
    """'22:30-06:30,12:30-14:00' -> [(1350, 390), (750, 840)] en minutes depuis minuit."""
    res = []
    for p in texte.split(","):
        a, b = p.strip().split("-")
        h1, m1 = a.split(":")
        h2, m2 = b.split(":")
        res.append((int(h1) * 60 + int(m1), int(h2) * 60 + int(m2)))
    return res


def est_hc(minute, plages):
    for a, b in plages:
        if (a <= minute < b) if a < b else (minute >= a or minute < b):
            return True
    return False


def telecharger(prm, token, debut, fin):
    q = urllib.parse.urlencode({"pointId": prm, "dateDebut": debut, "dateFin": fin})
    req = urllib.request.Request(API + "?" + q, headers={"Authorization": "Bearer " + token, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def points(reponse):
    """Extrait [(horodatage 'YYYY-MM-DD HH:MM:SS', valeur W, pas en minutes)] quelle que soit la forme de la réponse."""
    mr = reponse.get("meter_reading", reponse)
    pas = 30
    rt = mr.get("reading_type") or {}
    il = str(rt.get("interval_length", ""))
    if il.startswith("PT") and il.endswith("M"):
        try:
            pas = int(il[2:-1])
        except ValueError:
            pass
    out = []
    for p in mr.get("interval_reading", []):
        try:
            out.append((p["date"].replace("T", " "), float(p["value"]), pas))
        except (KeyError, ValueError):
            continue
    return out


def agreger(pts, plages):
    """Courbe de charge (puissance moyenne en W, horodatage = FIN de l'intervalle) -> kWh HP/HC par jour."""
    jours = {}
    for ts, watts, pas in pts:
        fin = dt.datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
        debut = fin - dt.timedelta(minutes=pas)
        kwh = watts * pas / 60 / 1000
        j = jours.setdefault(debut.strftime("%Y-%m-%d"), {"hp": 0.0, "hc": 0.0})
        j["hc" if est_hc(debut.hour * 60 + debut.minute, plages) else "hp"] += kwh
    return {d: {"hp": round(v["hp"], 3), "hc": round(v["hc"], 3)} for d, v in jours.items()}


def collecter():
    env = lire_env()
    if not env.get("PRM") or not env.get("TOKEN"):
        return "Pas de PRM/TOKEN dans .env : collecte désactivée."
    cfg = lire_json("config.json", {})
    plages = plages_hc(cfg.get("plagesHC", "22:00-06:00"))
    stock = lire_json("data.json", {"days": {}})
    jours = stock["days"]
    aujourdhui = dt.date.today()
    if jours:
        debut = dt.date.fromisoformat(max(jours)) + dt.timedelta(days=1)
    else:
        debut = aujourdhui - dt.timedelta(days=HISTORIQUE_JOURS)
    nouveaux = 0
    while debut < aujourdhui:                       # fenêtres de 7 jours max (limite Enedis), fin exclue
        fin = min(debut + dt.timedelta(days=7), aujourdhui)
        rep = telecharger(env["PRM"], env["TOKEN"], debut.isoformat(), fin.isoformat())
        agr = agreger(points(rep), plages)
        jours.update(agr)
        nouveaux += len(agr)
        debut = fin
        time.sleep(1)
    stock["updated"] = dt.datetime.now().isoformat(timespec="seconds")
    ecrire_json("data.json", stock)
    return f"{nouveaux} jours récupérés."


def tache_collecte():
    while True:
        env = lire_env()
        maintenant = dt.datetime.now()
        cible = maintenant.replace(hour=8, minute=30, second=0, microsecond=0) + dt.timedelta(minutes=random.randint(0, 80))
        stock = lire_json("data.json", {"days": {}})
        hier = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        en_retard = bool(env.get("TOKEN")) and (not stock["days"] or max(stock["days"]) < hier) and maintenant >= cible
        if en_retard or (not stock["days"] and env.get("TOKEN")):
            try:
                with verrou:
                    msg = collecter()
                etat.update(derniere_tentative=dt.datetime.now().isoformat(timespec="seconds"), erreur=None)
                print(dt.datetime.now(), msg, flush=True)
                attente = 3600 * 4 if msg.startswith("0 ") else 3600     # rien de neuf : on retente plus tard dans la journée
            except Exception as e:                                    # réseau, 401, 500... on réessaie plus tard
                etat.update(derniere_tentative=dt.datetime.now().isoformat(timespec="seconds"), erreur=str(e)[:200])
                print(dt.datetime.now(), "Erreur :", e, flush=True)
                attente = 3600
        else:
            attente = 900
        time.sleep(attente)


class Serveur(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def envoyer(self, code, corps, mime):
        if not isinstance(corps, bytes):
            corps = json.dumps(corps, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self):
        ip = ipaddress.ip_address(self.client_address[0].split("%")[0])
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if not (ip.is_loopback or (ip.version == 4 and ip in TAILSCALE)):
            return self.envoyer(403, {"erreur": "Réservé au réseau Tailscale."}, "application/json")
        chem = self.path.split("?")[0]
        if chem == "/api/data":
            stock = lire_json("data.json", {"days": {}})
            cfg = lire_json("config.json", {})
            reel = bool(stock["days"])
            return self.envoyer(200, {"demo": not reel, "days": stock["days"], "updated": stock.get("updated"),
                                      "config": cfg, "collecte": etat}, "application/json; charset=utf-8")
        if chem in ("/", "/index.html"):
            with open(chemin("index.html"), "rb") as f:
                return self.envoyer(200, f.read(), "text/html; charset=utf-8")
        self.envoyer(404, {"erreur": "introuvable"}, "application/json")


if __name__ == "__main__":
    if not os.path.exists(chemin("config.json")):
        ecrire_json("config.json", {"hp": 0.27, "hc": 0.2068, "abo": 15.65, "plagesHC": "22:00-06:00"})
    threading.Thread(target=tache_collecte, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Serveur).serve_forever()
