const crypto = require('crypto');
const { cookieValeur } = require('./_lib');

module.exports = async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') return res.status(405).json({ erreur: 'POST seulement' });
  const code = (req.body && req.body.code) || '';
  const attendu = process.env.ACCESS_CODE || '';
  const a = crypto.createHash('sha256').update(String(code)).digest();
  const b = crypto.createHash('sha256').update(attendu).digest();
  if (!attendu || !crypto.timingSafeEqual(a, b)) {
    await new Promise(r => setTimeout(r, 800));          // freine les essais en rafale
    return res.status(401).json({ erreur: 'Code incorrect.' });
  }
  res.setHeader('Set-Cookie', `eh=${cookieValeur()}; Path=/; Max-Age=31536000; HttpOnly; Secure; SameSite=Strict`);
  res.status(200).json({ ok: true });
};
