const crypto = require('crypto');

function cookieValeur() {
  return crypto.createHmac('sha256', process.env.ACCESS_CODE || '').update('energy-home').digest('hex');
}
function autorise(req) {
  if (!process.env.ACCESS_CODE) return false;           // sans code d'accès, jamais de données réelles
  const m = (req.headers.cookie || '').match(/(?:^|;\s*)eh=([0-9a-f]+)/);
  if (!m) return false;
  const a = Buffer.from(m[1]), b = Buffer.from(cookieValeur());
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}
module.exports = { cookieValeur, autorise };
