# Serveur de la tablette

Dans Termux : `~/energie/` contient `energie.py`, `index.html` (copie du site), `config.json`, `.env` (jamais dans git).

`.env` :
```
PRM=14chiffres
TOKEN=jeton_conso_api
```
`config.json` : `{"hp":0.27,"hc":0.2068,"abo":15.65,"plagesHC":"22:00-06:00"}`

Démarrage au boot : `~/.termux/boot/start-energie`. Relance : `sh ~/energie/relancer.sh`.
Adresse : `http://<nom-tailscale-tablette>:8090` (réseau Tailscale uniquement).
