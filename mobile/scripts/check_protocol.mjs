// Used by tests/test_phone_link.py: runs the app's own protocol code (src/lib/protocol.ts)
// in Node and prints what it computes, so Python can compare it with engine/phone_link.py.
//   node --experimental-strip-types mobile/scripts/check_protocol.mjs '<json>'
import { signingKey, sign, signedHeaders, parsePairingCode, hex, sha256, utf8 } from "../src/lib/protocol.ts";

const input = JSON.parse(process.argv[2] || "{}");
const key = signingKey(input.token);
const out = {
  key,
  sig: sign(key, input.method, input.path, input.stamp, input.body),
  sig_nonce: sign(key, input.method, input.path, input.stamp, input.body, "nonce-1"),
  headers: signedHeaders("abc123abc123", key, "GET", "/phone/status", "", 1800000000123),
  headers2: signedHeaders("abc123abc123", key, "GET", "/phone/status", "", 1800000000123),
  sha_empty: hex(sha256(utf8(""))),
  sha_unicode: hex(sha256(utf8("LOKI é中😀"))),
  pairing: parsePairingCode(input.code),
};
try {
  parsePairingCode("loki-phone:" + "eyJ2IjoxfQ");
  out.incomplete_refused = false;
} catch {
  out.incomplete_refused = true;
}
console.log(JSON.stringify(out));
