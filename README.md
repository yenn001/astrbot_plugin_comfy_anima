# AstrBot Comfy Anima

> 当前版本：v2.0.2

面向 AstrBot、NapCat / OneBot v11 与 ComfyUI 的 Anima 绘图插件。它提供自然语言分镜、直接 Tags、图片反推、多人语义换角、整图改图、底图控制、RTX 放大、遮罩重绘、LoRA 管理、Danbooru 本地索引、任务中心和两套管理页面。

## v2.0.2 命令能力与角色变体修复

- `remielle_dan` 一类基础角色 canonical 会与同根活动/服装变体正确归并；提示词中唯一 Copyright exact 会参与角色声明解析，不再误报“多个身份”。
- `/底图控制` 与 `/控制画图` 可同时使用 `--m p/d/l/r` 和 `--mode preserve/balanced/free`；控制通道与内容自由度不再冲突。
- `/反推画图` 支持相同内容模式。无控制通道时按 `preserve=0.35`、`balanced=0.55`、`free=0.8` 设置默认 img2img denoise；显式 `--denoise` 仍优先。
- `/重绘` 会在同一入口准确区分整图模式与 `quick/lanpaint` 局部模式；`/改图`、`/重绘`、`/反推画图` 都会先剥离选项再识别自然语言换角，避免选项进入角色名。
- `/方案`、`/anima draw`、`/换角色` 和 `/放大` 不再静默丢弃或误报选项：支持的字段被消费，不支持的字段返回命令专属错误。

## v2.0.1 个人图片任务队列

- 同一用户已有图片任务时，新指令会进入插件 FIFO 队列，不再要求任务结束后重新发送。
- 默认每位用户可等待 3 个任务，可在两套 WebUI 用“每用户等待队列”调整为 0–10；设为 0 可恢复旧的直接拒绝行为。
- 入队时立即回复等待位置，前序任务结束后自动通知并执行。普通生图、反推、反推画图、换角、改图、底图控制、放大和重绘共用同一队列。
- `/anima status` 同时显示运行项和等待数；`/anima cancel current|queue|all` 可分别取消当前任务、等待项或全部图片任务。任务中心也可取消单个排队任务。
- 队列不持久化原图、提示词或消息对象。插件重启后无法安全恢复的 queued 图片任务会标记为 interrupted，不会永久显示排队中。

- 项目地址：<https://github.com/yenn001/astrbot_plugin_comfy_anima>
- 更新记录：[CHANGELOG.md](CHANGELOG.md)
- 完整配置：[_conf_schema.json](_conf_schema.json)

## v2.0.0 核心变化

1. **多人换角**：最多观察六个角色槽位，用自然语言指定来源角色；其他角色的特征和 LoRA 会被保护。
2. **LoRA 三层身份**：LoRA 文件、激活词、Danbooru 角色/作品 canonical 独立保存，不能互相冒充授权。
3. **统一换角入口**：`/画图 --llm cc`、Ultra 模式和 `/反推画图` 共用同一套确定性选择与最终校验。
4. **Schema v3 语义档案**：支持共享激活词、多角色逐项绑定、SHA-256 内容跟随和旧档案安全迁移。
5. **Prompt Contract v3.0**：LLM 负责创作与候选发现，本地代码负责文件存在性、角色 exact、作品一致性和最终提交。

典型异名现在可以正确共存：

```text
LoRA 文件：black deniav1-2.safetensors
激活词：black_denia
角色身份：denia_(wuthering_waves)
作品身份：wuthering_waves
```

文件名和激活词不会再被送去冒充 Danbooru Character；最终提示词可以同时包含正确 canonical 与文件绑定的一个或多个激活词。

## 工作流能力

| 能力 | API 工作流 | 入口 |
| --- | --- | --- |
| Anima 原图 | `workflow/anima_base_api.json` | `--pipeline base` |
| Anima + RTX | `workflow/anima_rtx_api.json` | `--pipeline rtx` |
| Anima + 迭代放大 | `workflow/anima_iterative_api.json` | `--pipeline iterative` |
| 底图控制 | `workflow/anima_control_api.json` | `/底图控制` |
| 整图 img2img | `workflow/anima_img2img_api.json` | `/改图`、无控制模式的 `/反推画图` |
| RTX 独立放大 | `workflow/rtx_upscale_api.json` | `/放大` |
| Quick 遮罩重绘 | `workflow/anima_inpaint_crop_api.json` | `/重绘 --mode quick` |
| LanPaint 重绘 | `workflow/anima_lanpaint_api.json` | `/重绘 --mode lanpaint` |

WebUI 的“默认生图工作流”只列出 `base`、`rtx` 和 `iterative`。其余五项是按指令调用的工具工作流，不会进入 `/comfy_use` 的默认文生图列表。

## 环境要求

### AstrBot

- AstrBot 需要能访问 ComfyUI 的 `/prompt`、`/history`、`/view`、`/queue`、`/system_stats`、`/upload/image` 和 `/object_info`。
- Docker 内的 `127.0.0.1` 指向 AstrBot 容器自身。请使用宿主机地址、ComfyUI 服务名或可访问的局域网地址。
- 原生 `plugin-page` 依赖 AstrBot Plugins Page 与官方 Bridge。缺少该能力时可使用独立端口 WebUI。

### Python

```text
aiohttp>=3.9.0,<4.0.0
Pillow>=10.0.0,<13.0.0
```

AstrBot 未自动安装时执行：

```bash
python -m pip install -r requirements.txt
```

### ComfyUI

内置工作流当前使用：

| 类型 | 默认文件名 |
| --- | --- |
| UNET | `miaomiaoHarem_anima8Step10.safetensors` |
| CLIP | `qwen_3_06b_base.safetensors` |
| VAE | `qwen_image_vae.safetensors` |

主要自定义节点：

| 能力 | 节点类 |
| --- | --- |
| 动态 LoRA | `Lora Loader (LoraManager)` |
| RTX 放大 | `RTXVideoSuperResolution` |
| 迭代放大 | `PixelKSampleUpscalerProvider`、`IterativeImageUpscale`、`ColorMatch` |
| Quick 重绘 | `InpaintCropImproved`、`InpaintStitchImproved` |
| LanPaint | `LanPaint_KSampler`、`LanPaint_MaskBlend` |
| 底图控制 | `AnimaLLLiteApply`、`OpenposePreprocessor`、`DepthAnythingV2Preprocessor`、`LineArtPreprocessor` |

插件**不会自动下载或安装** ComfyUI 自定义节点、模型、LoRA 或控制权重。可把 [docs/workflows/导入Comfy工作流用下载插件用.json](docs/workflows/导入Comfy工作流用下载插件用.json) 导入 ComfyUI Manager 做基础依赖检查，再以插件管理页显示的缺失节点/模型为最终依据。

## 安装

1. 通过 AstrBot 插件管理器安装，或克隆到 AstrBot 插件目录：

   ```bash
   git clone https://github.com/yenn001/astrbot_plugin_comfy_anima.git
   ```

2. 安装 `requirements.txt`。
3. 在 ComfyUI 中准备模型和缺失节点。
4. 重载 AstrBot 插件。
5. 设置 `comfyui_url`、绘图思考 Provider 和反推多模态 Provider。
6. 执行 `/anima ping`，再运行工作流依赖检查。
7. 用低成本请求验收：

   ```text
   /画图no 1girl, white hair, blue eyes, portrait --pipeline base --size 512x512 --steps 4
   ```

建议保持 `strict_lora_validation=true`。启用 LoRA Manager 时，每次独立 LoRA 操作都会先刷新 Manager 与 ComfyUI 实际可加载清单；提交前仍会再次强制复核。

连续提交任务时无需等待上一张完成：

```text
/anima status
/anima cancel current
/anima cancel queue
/anima cancel all
```

## 常用绘图

### 直接 Tags

```text
/画图no 1girl, solo, beach, sunset --pipeline base
/画图 1girl, solo, school uniform, selfie
```

未显式使用 `--llm` 时，`/画图` 与 `/画图no` 保持直接 Tags 路径。

### LLM 分镜

```text
/画图 《Blue Archive》的 Kei，女仆装，自拍 --llm
/画图 雨夜和风庭院中的单人全身像 --llm u
```

- Standard：`--llm`、`--l`
- Ultra：`--llm u`、`--llm ultra`、`--l u`

LLM 只提供创作计划、角色查询提示和候选 LoRA。插件会在本地重新确认 Danbooru exact、LoRA 文件和最终提示词。

### 图片反推与改图

```text
/反推
/反推画图 构图不变，换成雨夜场景
/改图 把外套换成白色礼服，构图不变
/放大 --scale 2
```

在同一条消息发送图片，或回复一张图片后发送指令。`/改图` 是无蒙版整图重生成，不保证像素级保持；局部像素控制请使用 `/重绘` 和蒙版。

### 底图控制

```text
/底图控制 姿势不变 --m p
/底图控制 构图和姿势不变 --m p d
/底图控制 按线稿重新上色 --m l
/底图控制 参考整体外观和配色 --m r
```

`p / d / l / r` 分别代表 Pose、Depth、Lineart、Reference。Reference 不会因普通“构图不变”自动命中。

## 多人语义换角

### 文字 Tags

```text
/画图 2girls, yellow hair, red hair, school uniform, outdoors，\
把黄色头发的角色换成目标角色:BlueArchive日鞠(himari) --l cc
```

```text
/画图 1girl, old_character_\(old_work\), beach，\
把角色换成目标角色:denia_(wuthering_waves) --llm cc u --preview
```

### 反推图片

```text
/反推画图 把黄色头发的角色换成目标角色:BlueArchive日鞠(himari) --l cc u
```

选择顺序固定为：

1. 明确来源身份
2. 唯一性别
3. 唯一外观组合
4. 衣装、动作等组合
5. 左右、前后等位置，仅在同特征角色无法区分时兜底

不支持“猜一个最像的角色”。选择不唯一时会停止并要求补充自然语言描述。`--preview` 只展示选择、移除、保护和新增项，绝不提交 ComfyUI。

换角常用选项：

| 选项 | 作用 |
| --- | --- |
| `--llm cc` / `--llmcc` / `--lcc` | 启用文字换角 |
| 追加 `u` | 使用 Ultra 外貌证据预算 |
| `--preview` / `--v` | 仅预览，不生成 |
| `--no-character-lora` / `--no-lora` / `--nl` | 不加载目标角色 LoRA |
| `--weight` / `--w` | 目标角色 LoRA 权重 |
| `--mode keep-outfit` / `--m k` | 保留源衣装 |
| `--mode target-outfit` / `--m t` | 使用目标衣装策略 |

## LoRA 身份绑定

v2.0.0 的 LoRA 语义档案使用 Schema v3：

```text
activation_terms[]
identity_bindings[]
  character_canonical
  copyright_canonical
  activation_terms[]
```

在 WebUI 的 LoRA 详情中可以编辑：

- **共享激活词**：对该 LoRA 所有身份生效。
- **Danbooru exact 身份绑定**：每行一个角色、作品和该角色专用激活词。

格式：

```text
denia_(wuthering_waves) | wuthering_waves | black_denia
```

保存时会实时执行 Character/Copyright exact，并拒绝角色与作品不一致的绑定。规则如下：

- 文件名、标题、别名、描述、Civitai Tags 和激活词只帮助发现，不授权身份。
- 有 SHA-256 时，绑定跟随文件内容；Manager 元数据更新不会清空绑定。
- 文件 SHA-256 改变后，旧绑定立即失效。
- 无 SHA-256 时使用语义指纹，元数据变化会使绑定失效。
- 多角色 LoRA 可分别保存每个 canonical 的专用激活词。
- LLM 不允许写入 `identity_bindings`。

## Danbooru 本地索引

插件可导入已有 JSON/CSV，也可从 Danbooru 官方 API 或兼容镜像生成 Schema v2 索引。索引采用 SQLite exact/category/prefix 先缩小候选；Embedding 和 Rerank 只对小候选集排序，绝不读取全部 Tag 给 LLM，也不能授权身份。

- `identity`：完整 Character、Copyright、Artist，按阈值保留 General/Meta。
- `full`：抓取五类 Tag。
- 定期更新默认关闭；启用后默认每 168 小时执行。
- 更新使用高水位、ID 游标、检查点、有界重试、内容哈希和原子替换；失败保留旧库。

服务器无法访问 Danbooru 时，请配置可信 API 镜像或无凭据 HTTP 代理。不要在公开配置档案中保存敏感代理凭据。

## 管理页面

- **AstrBot plugin-page**：推荐，复用 AstrBot 管理权限和官方 Bridge。
- **独立端口 WebUI**：默认关闭；启用后必须设置强密码，并限制监听地址或防火墙来源。

两套页面提供配置档案、工作流依赖、Provider、模型、LoRA、身份绑定、Civitai 元数据、语义建档、Prompt Lab、任务中心和持久控制台日志。

## 管理命令

```text
/comfy_ls
/comfy_use <编号>
/comfy_lock
/模型列表
/模型切换 <编号或名称>
/lora刷新
/lora组合列表
/lora组合保存
/lora组合删除
/lora下载 <Civitai URL>
/方案列表
/方案 <ID>
/comfy帮助
```

`/comfy_use` 只能切换文生图工作流，不能把 `rtx_upscale_api.json` 设为默认生图入口。

## 安全与数据

- API Token、WebUI 密码和其他敏感凭据不会写入配置档案。
- 运行状态、语义档案、任务事件和日志保存在 AstrBot `plugin_data`，不放入可替换的插件目录。
- 控制台和任务时间线保存脱敏阶段、耗时、重试与错误；不保存完整 Prompt、Provider 原始回复、图片路径或隐藏推理。
- 模型与 LoRA 删除仅允许管理员，并使用最新 ComfyUI 清单、允许目录和路径边界复核。
- 最终 LoRA 文件存在性只由 ComfyUI 实际可加载清单授权，Manager 仅补充元数据。

## 常见问题

### LoRA 在 Manager 中但仍不可用

Manager 记录不证明 ComfyUI 能加载文件。先执行 `/lora刷新`，再检查 ComfyUI `object_info` 和工作流 LoRA 节点的真实列表。

### 角色 LoRA 被拒绝

在 LoRA 详情中确认文件 SHA、角色 canonical、作品 canonical 和激活词绑定。不要把 LoRA 文件名或自定义激活词当作 Danbooru 角色名。

### 换角要求补充来源角色

多人场景的来源选择不唯一。补充发色、服装、动作或身份；只有仍无法区分时才补“左边/右边”。

### WebUI 只看到三个工作流

这是预期行为。只有 `base`、`rtx`、`iterative` 是默认文生图管线；控制、改图、独立放大和重绘由各自命令调用。

### RTX 没有执行

检查实际选择的 pipeline、ComfyUI history 中是否存在 `RTXVideoSuperResolution`，以及最终输出节点是否接在 RTX 节点之后。QQ 预览压缩不能证明 RTX 未运行。

### 图片输入无效

同条消息发送图片，或回复包含图片的消息。反推 Provider 必须支持多模态输入。

## 开发验证

```bash
python -m unittest discover -s tests -t .. -q
python -m ruff check .
python -m compileall -q .
node --check web/app.js
node --check pages/control/app.js
git diff --check
```

Linux 发布 ZIP 必须使用 POSIX 路径。正式包应从已经验证的服务器运行目录生成，并与发布提交逐文件比对。

## 许可证

仓库当前未附带明确的 `LICENSE` 文件。在作者发布许可证前，不应默认本项目允许复制、修改、再分发或商用。

ComfyUI、自定义节点、模型、LoRA、Civitai 资源、Danbooru 数据及其他第三方内容分别受其各自许可证和使用条款约束。插件不打包第三方模型、节点、数据索引或预览图。
