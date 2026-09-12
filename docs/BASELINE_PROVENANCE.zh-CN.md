# v1 基线来源与恢复

[English (primary)](BASELINE_PROVENANCE.md) · [简体中文](BASELINE_PROVENANCE.zh-CN.md) · [文档导航](README.zh-CN.md)

本记录采集于 v2 实施开始之前。

- 基线提交：`db8e714eceb73e88496f0f705a56cd8c571e0278`
- 基线分支：`improve-inference-reliability`
- Origin：`git@github.com:liu-xiaoran/AI-auto-lrc.git`
- 恢复 bundle：`/Users/liu-haixiao/ai_code/AI-auto-lrc-pre-v2-db8e714.bundle`
- 恢复 bundle SHA-256：`6b51c9e10c69958ec31b27a2395f36f21fe3f632f691b7bb7777b41d4f4ad30a`
- Bundle 验证：完整 Git 历史、8 个 ref、SHA-1 仓库格式
- Git LFS：`git-lfs/3.8.0`；重构前 `git lfs fsck` 通过

## 资产哈希

| 资产 | SHA-256 |
|---|---|
| `checkpoints/checkpoint_Baseline` | `b420ea97032691b3f51e271c0b688a85e168d7b7ee89baf6725f601ccd07bb45` |
| `checkpoints/checkpoint_MTL` | `826559e7e810bf8f90223d8fd5c66525c01ad4dd9cdc19d019f39f784e7ed3c1` |
| `checkpoints/checkpoint_BDR` | `a3955b290311bec16f04253eac328147d444f275f263315490ec5faf1a668fc9` |
| `lid.176.ftz` | `8f3472cfe8738a7b6099e8e999c3cbfae0dcd15696aac7d7738a8039db603e83` |
| `demofile/original_track.mp3` | `e5d68541c999bec2a6ff7f4eeba0ad893c56895e8509855abb5ca9e292c980b8` |
| `demofile/original_txt.txt` | `f15162581177f5f5383cb4921c71c929ecdc93281c19468357fcb57ed0f1361c` |

Git bundle 不能替代 Git LFS 对象留存。恢复仓库 bundle 及匹配的 LFS 对象，然后验证上述哈希。

## 恢复检查

```bash
git bundle verify /Users/liu-haixiao/ai_code/AI-auto-lrc-pre-v2-db8e714.bundle
git clone /Users/liu-haixiao/ai_code/AI-auto-lrc-pre-v2-db8e714.bundle restored-ai-auto-lrc
cd restored-ai-auto-lrc
git checkout db8e714eceb73e88496f0f705a56cd8c571e0278
git lfs pull
git lfs fsck
```

v2 仓库获得经验证的远端备份与发行产物之前，不要删除或覆盖此 bundle。
