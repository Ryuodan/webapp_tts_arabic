# Best Fine-Tuned OmniVoice Checkpoint

Best available checkpoint:

```text
omnivoice/checkpoints/saudi_hq_ft/checkpoint-2500
```

Local alias:

```text
omnivoice/checkpoints/best_finetuned
```

Selection basis: lowest `eval/loss` among checkpoint directories still present
under `omnivoice/checkpoints/saudi_hq_ft`.

| Step | Eval loss | Status |
| ---: | ---: | --- |
| 1250 | 4.3344 | best logged loss, but checkpoint was pruned |
| 2500 | 4.4111 | best available checkpoint |
| 3500 | 4.4453 | available |
| 2000 | 4.4492 | available, previous best |
| 1750 | 4.4537 | available |
| 3750 | 4.4896 | available |
| 3250 | 4.5091 | available |
| 2750 | 4.5428 | available |
| 3000 | 4.5491 | available |
| 4000 | 4.5669 | available |
| 2250 | 4.5789 | available |

The raw checkpoint files remain ignored by Git because they are large model
artifacts. `checkpoint-2500/model.safetensors` is 2,450,344,144 bytes with
SHA-256:

```text
5f2b8938ccdcebe95038caef452dd945bbada1e0c3ac34b2956ed2ed293a7e3f
```

The checkpoint-progression source data is in:

```text
outputs/abeer_compare/omni_ckpts/losses.json
```
