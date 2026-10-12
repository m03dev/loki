# Loki signing key

`loki_public.pem` is the trusted RSA-2048 public key used to verify signed Loki
release artifacts.

    Fingerprint (SHA256): k7mnIAntVdK6HNIKTPLtOuN6Ps5kfLTzSPkmJ5oqCNs

- The **private** key never lives in this repo. Keep it offline and point
  `LOKI_SIGNING_KEY` at it (or pass `--key`) when signing.
- Signatures are detached RSA-2048 / SHA-256 (`openssl dgst -sha256`), stored as
  `<file>.sig` next to the artifact.
- Verify against the bundled key:

      python tools/loki_sign.py verify <file>          # or: verify-all <dir>
      python tools/loki_sign.py fingerprint            # the value to pin

Trust model: this lets anyone confirm a Loki artifact was signed by the holder of
the private key. Verification is only as strong as the fingerprint you pin, so
publish that fingerprint out-of-band (release notes, README). To rotate, replace
`loki_public.pem` and update the pin.
