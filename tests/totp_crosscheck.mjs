// Standalone JS reference, copied verbatim from operator_console.html, so a CI
// run can prove the browser TOTP matches src/aurora/totp.py byte-for-byte.
const STEP = 60, TOKEN_LEN = 8;
const B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

function base32(bytes) {
  let bits = 0, value = 0, out = "";
  for (let i = 0; i < bytes.length; i++) {
    value = (value << 8) | bytes[i]; bits += 8;
    while (bits >= 5) { out += B32[(value >>> (bits - 5)) & 31]; bits -= 5; }
  }
  if (bits > 0) out += B32[(value << (5 - bits)) & 31];
  return out;
}

async function tokenForCounter(secret, counter) {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const buf = new ArrayBuffer(8);
  new DataView(buf).setBigUint64(0, BigInt(counter), false);
  const sig = await crypto.subtle.sign("HMAC", key, buf);
  return base32(new Uint8Array(sig)).slice(0, TOKEN_LEN).toUpperCase();
}

// (secret, counter) pairs read from argv as JSON; print token per line.
const pairs = JSON.parse(process.argv[2]);
const out = [];
for (const [secret, counter] of pairs) out.push(await tokenForCounter(secret, counter));
process.stdout.write(out.join("\n"));
