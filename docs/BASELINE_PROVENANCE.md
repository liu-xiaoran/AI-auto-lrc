# v1 Baseline Provenance and Recovery

This record was captured before the v2 implementation started.

- Baseline commit: `db8e714eceb73e88496f0f705a56cd8c571e0278`
- Baseline branch: `improve-inference-reliability`
- Origin: `git@github.com:liu-xiaoran/AI-auto-lrc.git`
- Recovery bundle: `/Users/liu-haixiao/ai_code/AI-auto-lrc-pre-v2-db8e714.bundle`
- Recovery bundle SHA-256: `6b51c9e10c69958ec31b27a2395f36f21fe3f632f691b7bb7777b41d4f4ad30a`
- Bundle verification: complete Git history, eight refs, SHA-1 repository format
- Git LFS: `git-lfs/3.8.0`; `git lfs fsck` passed before refactoring

## Asset hashes

| Asset | SHA-256 |
|---|---|
| `checkpoints/checkpoint_Baseline` | `b420ea97032691b3f51e271c0b688a85e168d7b7ee89baf6725f601ccd07bb45` |
| `checkpoints/checkpoint_MTL` | `826559e7e810bf8f90223d8fd5c66525c01ad4dd9cdc19d019f39f784e7ed3c1` |
| `checkpoints/checkpoint_BDR` | `a3955b290311bec16f04253eac328147d444f275f263315490ec5faf1a668fc9` |
| `lid.176.ftz` | `8f3472cfe8738a7b6099e8e999c3cbfae0dcd15696aac7d7738a8039db603e83` |
| `demofile/original_track.mp3` | `e5d68541c999bec2a6ff7f4eeba0ad893c56895e8509855abb5ca9e292c980b8` |
| `demofile/original_txt.txt` | `f15162581177f5f5383cb4921c71c929ecdc93281c19468357fcb57ed0f1361c` |

The Git bundle does not replace Git LFS object retention. Restore both the
repository bundle and the matching LFS objects, then verify the hashes above.

## Recovery check

```bash
git bundle verify /Users/liu-haixiao/ai_code/AI-auto-lrc-pre-v2-db8e714.bundle
git clone /Users/liu-haixiao/ai_code/AI-auto-lrc-pre-v2-db8e714.bundle restored-ai-auto-lrc
cd restored-ai-auto-lrc
git checkout db8e714eceb73e88496f0f705a56cd8c571e0278
git lfs pull
git lfs fsck
```

Do not delete or overwrite the bundle until the v2 repository has a verified
remote backup and release artifact.
