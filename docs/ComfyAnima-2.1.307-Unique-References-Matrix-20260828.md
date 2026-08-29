---
type: unique-references-matrix
project: astrbot_plugin_comfy_anima
target_version: 2.4.0
date: 2026-08-28
---

# 2.4.0 唯一引用矩阵

每个验收项只出现一次，且唯一绑定一条资产/命令/证据来源。重复引用
在打包验证阶段视为失败。

| ID | 验收项 | 唯一来源 | 唯一资产/命令 |
|---|---|---|---|
| Q1 | 预设组合句 probe MISS 不封存 | S-01 AssetProbeTriState §6 | `/画图 风格006 达妮娅` |
| Q2 | 重绘两段式结构化 | S-03 DirectorTwoStage §7 | `/重绘 构图不变 风格006` |
| Q3 | 画图 --llm 结构化 | S-03 DirectorTwoStage §7 | `/画图 --llm 达妮娅自拍` |
| Q4 | kei 身份 exact 绑定 | S-07 DanbooruIdentityBinding §6 | `/重绘 角色是 kei（blue archive）` |
| Q5 | 双 Manifest 合并 | S-06 ManifestMerge §6 | `merge_preset_manifests` |
| Q6 | 沉浸照片路由 | S-01 AssetProbeTriState §4 / S1 | `我想看娅娅的照片` |
| Q7 | 图片真送达回执 | S-04 ImmersiveDualTrack §4 | `mark_send_attempt` |
| Q8 | 多图/节奏 | S-04 ImmersiveDualTrack §6 | `decide_delivery_pacing` |
| Q9 | unknown 降级无伪成功 | S-04 ImmersiveDualTrack §5 | `present_error("delivery_unknown")` |
| P1.3 | Envelope 归属挂载校验 | S-04 ImmersiveDualTrack §2 | `BundleLedger.attach_bundle` |
| C1 | depth 控制验收 | S-08 ControlNetOptimization §5 | `--mode depth` |
| C2 | pose+depth 控制验收 | S-08 ControlNetOptimization §5 | `--mode pose_depth` |

## 去重规则

- 一个 ID 只能出现在一行；
- 一行只能引用一个主要来源和一个主要资产/命令；
- 新增验收项必须先在本矩阵分配唯一 ID。
