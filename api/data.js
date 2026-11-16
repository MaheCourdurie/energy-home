// Relevés Linky : appelle Conso API à la demande (jeton et PRM dans les variables d'environnement Vercel).
const { autorise } = require('./_lib');
const config = require('../config.json');

const API = 'https://conso.boris.sh/api/courbe_de_charge_consommation';
const UA = 'energy-home (github.com/MaheCourdurie/energy-home)';
const JOURS = 60;
const TTL = 6 * 3600 * 1000;
let memo = null;                                        // cache de l'instance, jamais servi sans authentification

const iso = d => d.toISOString().slice(0, 10);
const ajoute = (s, n) => { const d = new Date(s + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return iso(d); };
const aujourdhui = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Paris' }).format(new Date());

function plages(txt) {
  return txt.split(',').map(p => {
    const [a, b] = p.trim().split('-').map(x => { const [h, m] = x.split(':'); return +h * 60 + +m; });
    return [a, b];
  });
}
const estHC = (min, pl) => pl.some(([a, b]) => a < b ? (min >= a && min < b) : (min >= a || min < b));

function agreger(rep, pl) {
  const mr = rep.meter_reading || rep;
  const il = String((mr.reading_type || {}).interval_length || '');
  const pas = /^PT(\d+)M$/.test(il) ? +il.match(/^PT(\d+)M$/)[1] : 30;
  const jours = {};
  for (const p of mr.interval_reading || []) {
    const m = String(p.date).replace('T', ' ').match(/^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2})/);
    const w = parseFloat(p.value);
    if (!m || isNaN(w)) continue;
    let t = +m[2] * 60 + +m[3] - pas, jour = m[1];     // horodatage = fin de l'intervalle
    if (t < 0) { t += 1440; jour = ajoute(jour, -1); }
    const kwh = w * pas / 60 / 1000;
    const j = jours[jour] || (jours[jour] = { hp: 0, hc: 0 });
    j[estHC(t, pl) ? 'hc' : 'hp'] += kwh;
  }
  return jours;
}

async function fenetre(prm, token, debut, fin) {
  const q = new URLSearchParams({ pointId: prm, dateDebut: debut, dateFin: fin });
  const r = await fetch(`${API}?${q}`, { headers: { Authorization: 'Bearer ' + token, 'User-Agent': UA } });
  if (!r.ok) throw new Error(`Conso API ${r.status}`);
  return r.json();
}

module.exports = async (req, res) => {
  res.setHeader('Cache-Control', 'private, no-store');
  if (!autorise(req)) return res.status(401).json({ erreur: 'Code d\'accès requis.' });
  const { PRM, TOKEN } = process.env;
  if (!PRM || !TOKEN) return res.status(200).json({ demo: true, days: {}, config });
  if (memo && Date.now() - memo.t < TTL) return res.status(200).json(memo.v);

  const pl = plages(config.plagesHC);
  const fin = aujourdhui();
  const fenetres = [];
  for (let d = ajoute(fin, -JOURS); d < fin; d = ajoute(d, 7)) {
    const f = ajoute(d, 7); fenetres.push([d, f < fin ? f : fin]);
  }
  const days = {}; const erreurs = [];
  for (let i = 0; i < fenetres.length; i += 3) {        // 3 appels en parallèle, bien sous le quota
    await Promise.all(fenetres.slice(i, i + 3).map(async ([d, f]) => {
      try { Object.assign(days, agreger(await fenetre(PRM, TOKEN, d, f), pl)); }
      catch (e) { erreurs.push(`${d}: ${e.message}`); }
    }));
  }
  for (const k in days) { days[k].hp = +days[k].hp.toFixed(3); days[k].hc = +days[k].hc.toFixed(3); }
  if (!Object.keys(days).length) return res.status(502).json({ erreur: 'Aucune donnée reçue de Conso API.', details: erreurs.slice(0, 3) });
  const v = { demo: false, days, config, updated: new Date().toISOString(), partiel: erreurs.length > 0 };
  if (!erreurs.length) memo = { t: Date.now(), v };
  res.status(200).json(v);
};
