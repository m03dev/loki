# Contribution prepared for receptron/laya

A prepared upstream change to **`https://github.com/receptron/laya`** (MIT, the
open-source Jev-compatible System-1 decision model that Loki uses as its local-first
decision provider). Patch: `0001-systemone-offline-tests.patch`.

## The problem

`Laya.systemOne` shapes the model's raw logits into the three answer types (`choice`,
`score`, `noul`) - the temperature buckets, softmax, confidence, 4-decimal rounding and
usage accounting. That code was covered **only** by `test/test_model.ts`, which runs
**only when the 1.7 GB ONNX bundle is on disk**. `src/sequence.ts` is already fully
tested offline; the shaping step was not. On CI (and any fresh checkout) that logic ran
untested.

## The change

- **`src/laya.ts`** - a `static fromParts(session, tokenizer, config, ids, modelDir)`
  factory. It calls the private constructor, so the public surface is unchanged and
  ordinary callers still use `Laya.load()`. It exists so the shaping can be driven by a
  stub session instead of the weights.
- **`test/test_systemone.ts`** - offline tests that answer with a known logit pattern,
  located through `marker_mask` so a batched call with different option counts lines up.
  They assert each answer type, the 4-decimal rounding, a tie's zero confidence, usage
  accounting, and that a single-question call equals the same question inside a batch.
- **`package.json`** - adds the new test file to `yarn test`.

## Verified in a clean checkout

```
yarn install
yarn test        # 13 pass, 1 skipped (the model test), 0 fail
yarn typecheck   # clean
yarn lint        # no errors
```

## How to apply

```sh
git clone https://github.com/receptron/laya
cd laya
git am /path/to/0001-systemone-offline-tests.patch
yarn install && yarn test
```

## How to submit

Not submitted automatically - opening a fork and a pull request on a third-party
repository is an externally visible action that was not authorized. To submit it:

```sh
gh repo fork receptron/laya --clone=false
git remote add fork https://github.com/<you>/laya.git
git push fork HEAD:systemone-offline-tests
gh pr create --repo receptron/laya --head <you>:systemone-offline-tests
```
