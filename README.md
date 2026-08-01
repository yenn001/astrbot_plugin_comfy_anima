# AstrBot Comfy Anima

> 当前版本：v1.9.6

面向 AstrBot、aiocqhttp / NapCat QQ 与 ComfyUI 的 Anima 绘图插件。它把自然语言分镜、直接 Tags、生图、图片反推、无蒙版整图改图、单角色语义换角、RTX 放大、遮罩重绘、视觉提示词资产、Prompt Lab 与 LoRA 视觉管理放在同一套受控流程中。

本插件针对仓库内附带的 Anima 工作流与 manifest 设计，不是任意 ComfyUI 工作流的通用适配器。开始部署前，建议先阅读“八项工作流能力”和“依赖”两节。

- 项目地址：<https://github.com/yenn001/astrbot_plugin_comfy_anima>
- 更新记录：[CHANGELOG.md](CHANGELOG.md)
- 配置字段：[\_conf_schema.json](_conf_schema.json)

## 八项工作流能力

插件包含三条可选文生图管线，以及整图 img2img、底图控制、独立放大和两条遮罩重绘工具。只有前三条能设为默认文生图工作流。

| 管线 | 内置 API 工作流 | 用途 | 使用入口 | 可在生图下拉框选择 |
| --- | --- | --- | --- | --- |
| Anima 原图 | `anima_base_api.json` | 只生成 Anima 原图，不做二次放大 | `--pipeline base` | 是 |
| Anima + RTX | `anima_rtx_api.json` | Anima 生图后执行 RTX 放大 | `--pipeline rtx` | 是 |
| Anima + 迭代放大 | `anima_iterative_api.json` | Anima 生图后进行迭代采样和细节重构 | `--pipeline iterative` | 是 |
| Anima 底图控制 | `anima_control_api.json` | 用一张底图控制 Pose、Depth、Lineart 或 Reference；仍可选 base / RTX / iterative 输出 | `/底图控制 [--m p|d|l|r]` | 否 |
| Anima 整图 img2img | `anima_img2img_api.json` | 原图像素经 VAE 编码进入 Anima，支持保守、平衡、自由改图及 base / RTX / iterative 输出 | `/改图`、无 `--m` 的 `/反推画图` | 否 |
| RTX 独立放大 | `rtx_upscale_api.json` | 只放大用户提供的图片，不重新调用 Anima | `/放大` | 否 |
| Quick / LanPaint Fast | `anima_inpaint_crop_api.json` | 裁切遮罩附近区域并用快速 LanPaint 修改 | `/重绘 --mode quick` | 否 |
| LanPaint 精细重绘 | `anima_lanpaint_api.json` | 多步遮罩重绘，适合复杂结构或精细修改 | `/重绘 --mode lanpaint` | 否 |

因此，WebUI 的“当前生图工作流”只出现三个可选项是正常行为。整图 img2img、底图控制、独立 RTX、Quick 和 LanPaint 会显示在工作流依赖检查中，但不会进入生图工作流下拉框，也不会被 `/comfy_use` 设为默认文生图入口。

默认生图管线由 `default_generation_pipeline` 决定，仓库默认值为 `rtx`。单次请求的优先级为：

1. 显式 `--pipeline base|rtx|iterative`。
2. 兼容参数 `--upscale` 或 `--no-upscale`。
3. 绘图导演在用户明确表达时选择的管线。
4. WebUI / 插件配置中的默认管线。

`workflow/anima_v2_api.json` 与 `workflow/anima_api.json` 作为兼容、回滚资产保留，不属于八项正式工作流能力。

## 主要能力

- 自然语言绘图：由 AstrBot 中已配置的聊天 Provider 生成画面意图，再由本地 Prompt Composer v2 整理为“硬控制与 LoRA / 视觉短语 / 英文场景关系句”三层提示词；不增加第二次 LLM 调用。
- 直接 Tags：`/画图` 和 `/画图no` 默认跳过 LLM，直接把用户输入写入工作流；显式 `--llm c` / `--llmcc` / `--lcc` 可对一段完整旧 Tags 执行受控文字换角。
- 图片反推：使用 AstrBot 多模态 Provider 提取结构化 Tags、构图、角色候选和置信度。
- 精确角色检索：换角会先查本地 Danbooru character canonical 与唯一 alias，再让绘图模型提供最多八个同角色罗马字候选并批量 exact；作品限定必须一致。Prefix、keyword、Embedding 与 Rerank 只负责有限候选发现和排序，最终身份必须重新通过本地 exact，多个角色冲突时停止而不猜选。
- 底图控制生成：Pose 锁定人体姿态，Depth 约束空间结构，Lineart 按线稿生成上色成图，Reference 柔和参考外观、配色与画风；支持组合与自然语言。
- 无蒙版整图改图：引用一张图后直接说换衣、换背景、换表情或重新画一张；原图像素接入 img2img，插件按保守、平衡或自由模式控制改动幅度。
- 单角色语义换角：从图片或完整 Tags 中移除原角色身份，保留服装、姿势、构图、背景和风格，再以目标 LoRA 或纯语义 Tags 重建整张图。纯语义模式会把 exact canonical 放入主体区，并可从 ComfyUI 的 Danbooru Gallery 公开安全级帖子中统计最多四项稳定外貌，避免密集场景和强风格 LoRA 压过角色身份；只缓存聚合结果，不保存帖子或图片。
- LoRA 实时刷新：查询、保存组合、换角和提交任务前读取 LoRA Manager 与 ComfyUI 当前实际可加载清单。
- LoRA 管理：搜索、Civitai 元数据、语义建档、中英文别名、人工审核、组合预设、下载、受控删除，以及带文件指纹和本地缩略图的视觉清单。
- 视觉提示词资产库：导入管理员审核过的角色、画师、服装、背景与姿势 JSON/CSV，保留来源并支持搜索、收藏和自定义项。
- 分层编辑与 Prompt Lab：分开处理身份、服装、姿势、镜头、背景、风格、关系句与 LoRA，可固定 Seed、锁定分层并生成多个可复现草稿。
- 模型管理：实时读取并切换 Anima UNET；工作流 manifest 决定实际节点绑定。
- 两套管理页面：AstrBot 原生 `plugin-page` 与可选的独立端口 WebUI，共用同一套后端能力。
- 任务与日志：记录脱敏的阶段、状态、耗时、重试和错误，不把完整提示词、图片路径或 Provider 原始回复写进任务时间线。

## Prompt Composer v2 与本地 Danbooru 索引

Prompt Composer v2 默认开启，只对 LLM 生成或语义编排路径做本地确定性整理，不额外调用模型。`/画图`、`/画图no` 和 `/anima draw` 未显式使用 `--llm` 时仍保持用户原始 Tags 直通；普通聊天 `<pic>`、自然语言绘图、`--llm`、反推画图、底图控制和改图等需要语义编排的入口会复用同一套合成规则。

最终正面提示词按三层组织：

1. **硬控制层**：LoRA 控制、角色 / 作品 / 画师硬 Tags，以及用户或可信元数据给出的确定属性。
2. **视觉短语层**：服装、动作、镜头、光线、材质、环境等可组合的视觉描述。
3. **场景关系句**：位于末尾的一句英文自然语言，用于补足人物接触、空间、衣料和环境关系。

LoRA 控制和其可信触发词会先去重，再插入场景关系句之前；即使触发词是在分镜完成后由实时 LoRA Manager 或保存的风格组合补入，也不会落到英文场景句之后。

绘图导演提供两档自适应视觉扩写：

- **Standard**：`--llm` 或 `--l`。以稳定、清晰和服从度为主，根据景别补足适量面部、手势、服装材质、空间与光影关系。
- **Ultra**：`--llm ultra`、`--llm u`、`--l ultra` 或 `--l u`。允许更高的有效 Tag 密度、更多互相协调的材质、前中后景、环境互动、主光/轮廓光与色彩关系，并可增加不改变角色硬事实的题材化装饰。

Ultra 仍只输出“一行有序 Tags + 一句英文关系句”，不会把三段展示文本、分析小标题或十几个独立加权长句交给 ComfyUI。高质量来自可见关系和构图控制，不会默认堆叠 `8k`、`absurdres`、`masterpiece` 或整段权重。简单肖像不会为了凑数添加不可见脚部、复杂背景或固定 bokeh；多人场景会明确区分每个角色的身份、服装、朝向和空间关系。

`--llm c`、`--llmcc` 与 `--lcc` 不是第三档普通扩写，而是仅限 `/画图`、`/画图no` 的显式文字换角模式；普通聊天不会因为提到“换角色”就自动启用。追加 `u`（例如 `--llm c u`、`--lcc u`）只提高目标身份外观的规划密度，仍遵守同一套身份删除与内容保留规则。

`adaptive_negative_mode` 提供三种本地负面词策略：

- `off`：不自动补充。
- `conservative`：默认值，只在多人接触、手持物、全身、极端透视等实际风险被识别时补充少量确定性负面词。
- `standard`：在保守规则外追加通用质量负面词。

自动负面词不会覆盖用户显式 negative，也不会把正面要求、角色身份或换装后需要保留的特征反向加入 negative。

插件可使用管理员自行提供的离线 Danbooru Tag 索引做硬锚点检查，但**安装包不附带任何第三方标签库或索引数据**。在全局设置填写 `danbooru_index_url` 后，可从“提示词工坊”手动更新 JSON / CSV 数据：HTTPS 可访问可信远端；明文 HTTP 仅允许回环或私有局域网地址。更新采用临时库校验与原子替换，下载、解析或校验失败时保留上一份可用索引。

导入器同时兼容带表头的 JSON/CSV，以及 Anima 常见的无表头 `tag,category,count,aliases` 导出；无表头数据中的超长或无法唯一确认的别名会被丢弃，但 canonical tag 会保留。

- `off`：关闭索引检查。
- `report`：默认且完整可用，只在诊断中报告未知或冲突锚点，不阻止绘图；索引缺失也不会阻止任务。
- `guarded`：为未来结构化角色 / 作品 / 画师 anchor 协议预留。当前生产传输尚不能可靠携带这类分层 anchor，因此普通绘图路径会安全降级为与 `report` 等效，不应把它理解为已启用阻断。

无论选择哪种模式，用户原始 Tags、手工预设触发词和 LoRA Manager 返回的触发词都不会被 Danbooru 校验器删除或拦截。

索引就绪时，普通对话与内部绘图导演的 System Prompt 会收到脱敏后的 `ready / canonical tag 数 / alias 数 / revision`，并可按需调用只读工具 `search_anima_danbooru_tags`：

- `exact`：同时验证 canonical tag 与唯一 alias；只有该模式返回的 `verified=true` 可直接作为已确认标签。
- `prefix` / `keyword`：用于寻找候选，不会把候选伪装成已验证结果；采用前必须再对候选 `canonical_tag` 执行 exact 查询。
- `batch`：使用竖线或换行一次验证最多 12 个 Tag，适合在一个工具回合中确认角色、作品、画师、服装或姿势锚点。

工具输出只包含 canonical tag、适合 ComfyUI 的括号转义形式、分类、热度、匹配类型和少量 alias，不返回索引 URL、文件路径、完整 provenance 或 SHA-256。普通且确定的 general Tags 仍走原有快速分镜路径；只有明确标签检索或可能的角色 / 作品 / 画师身份锚点才进入工具循环，避免每次绘图都增加延迟。

## 视觉资产、分层编辑、LoRA 图库与 Prompt Lab

v1.7.1 在 Prompt Composer 之上增加了一层可视化的“选材与组稿”工作流，并修复了 LoRA Manager 独立预览标识的兼容性，不改变生成时的权威顺序和安全门禁。

### 视觉提示词资产库

- 支持角色、画师、服装、背景和姿势五类资产，可以按名称、别名、Tags、分类和收藏状态检索。
- 管理员可导入 JSON/CSV，记录导入来源、数据集版本/命名空间、导入时间和内容 SHA-256；导入失败不会覆盖上一份可用快照。
- 插件不附带 `Comfyui-Anima-Tools` 或其他第三方项目的大型资产库、预览图或数据索引。导入数据的授权、归属和使用范围由管理员负责确认。
- 本地文件或粘贴 JSON/CSV 可直接导入；URL 导入必须另外开启 `prompt_asset_remote_import_enabled`，且只允许解析到公网地址的 HTTPS，单次远程包最多 16 MiB，同时受 DNS/IP 校验、禁止重定向和记录数上限约束。局域网素材不经过 URL 抓取，请直接粘贴或上传 JSON/CSV。

### 分层编辑器和 Prompt Lab

分层编辑器使用八个明确槽位：角色身份、服装、姿势、镜头/构图、背景、画师/风格、场景关系和 LoRA。编辑与重组仍由本地确定性规则处理，不会因为拖拽、锁定或随机重组而额外触发 LLM。

Prompt Lab 接受固定 Seed、基础分层、可选资产池和锁定层，每批生成 1–6 个可复现候选。候选本身仍是短期草稿：

1. 创建候选时不会提交 ComfyUI，也不携带任意执行能力。
2. 过期、批次不匹配或未选中的草稿不能进入生成。
3. 用户确认一个候选后，管理页会再次核对素材 revision、按最新清单精确复核 LoRA，并交给 Prompt Composer 组合；确认接口仍不会提交 ComfyUI。
4. 开启“保存为 QQ 方案”后，确认结果会原子保存到 AstrBot `plugin_data` 并获得 `P-XXXXXX` 短 ID；插件重载或升级不会清空。
5. 在 QQ 使用 `/方案 P-XXXXXX` 或唯一方案名称即可进入正常生图主链；权限、敏感词、LoRA 实时刷新、提交前复核和工作流校验仍全部执行，Prompt Lab 不提供旁路。

插件内置五套不绑定角色、画师或 LoRA 的通用示例：`EX-001 雨夜霓虹肖像`、`EX-002 海边烟花全身`、`EX-003 和风庭院侧坐`、`EX-004 低角度动作构图`、`EX-005 咖啡馆暖光`。内置示例可以直接用 `/方案 EX-001` 生成，但不能覆盖或删除。

### LoRA 视觉清单

LoRA 图库对当前语义清单生成稳定指纹，展示精确文件、分类、元数据状态、预览状态与缓存状态，并支持分页、筛选、受限预热和缓存裁剪。预览首先查找 `lora_visual_roots` 白名单下与 LoRA 精确同名的本地 companion 图。如果 AstrBot 容器没有挂载 LoRA 目录，后端可代表当前配置的 LoRA Manager 调用同源固定 `/api/lm/previews` 端点，但只允许最新 Manager 清单提供的精确记录和原始 `preview_url`，要求固定接口、单一 `path` 参数、禁止重定向且限制为 4 MB。前端不能提交 URL 或文件路径，后端也不会访问 Civitai 预览或任意远程 URL；所有接收的图片字节都要先解码验证并重编码到内容寻址 WebP 缓存。

**视觉清单只是管理视图，不是生成时的资产权威。** 任何涉及 LoRA 的绘图、换角、预设保存或删除操作，仍必须先刷新 LoRA Manager，并在工作流提交前对最终精确文件再次强制复核。

## 环境与依赖

### AstrBot 与网络

- AstrBot 通过 aiocqhttp 连接 NapCat / OneBot v11。`/画图` 的 QQ 合并转发功能依赖该适配器。
- 原生 `plugin-page` 需要 AstrBot 提供插件 Pages 与官方 Bridge；相关接口曾在 AstrBot 4.26.1 部署环境验证，但这不是仓库声明的严格最低版本。未提供该能力的版本不会出现原生页面，可改用插件配置页或按需开启独立端口 WebUI，并自行验证其余插件接口兼容性。
- AstrBot 必须能访问 ComfyUI 的 `/prompt`、`/history`、`/view`、`/queue`、`/system_stats`、`/upload/image` 和 `/object_info`；启用 `allow_global_interrupt=true` 时还需要 `/interrupt`。
- 如果 AstrBot 在 Docker 中，`127.0.0.1` 指向 AstrBot 容器自身。请改用宿主机地址、ComfyUI 容器服务名或同一容器网络中的可访问地址。

### Python 依赖

仓库的 [requirements.txt](requirements.txt) 目前包含：

```text
aiohttp>=3.9.0,<4.0.0
Pillow>=10.0.0,<13.0.0
```

若 AstrBot 没有自动安装插件依赖，可在 AstrBot 所使用的 Python 环境中执行：

```bash
python -m pip install -r requirements.txt
```

### ComfyUI 模型

八份 API 工作流的当前模板明确引用下列文件名。使用不同 UNET 时，优先通过 `/模型列表` 与 `/模型切换` 写入运行配置；更换 CLIP、VAE 或工作流拓扑时，需要同步检查 API 工作流以及 manifest 中的节点绑定。兼容工作流与 `docs/workflows/` 依赖检查资产可能保留不同的历史模型名，应按各自文件内容单独核对，不能把下表视为整个仓库所有 JSON 的统一模型声明。

| 类型 | 内置文件名 |
| --- | --- |
| UNET | `miaomiaoHarem_anima8Step10.safetensors` |
| CLIP | `qwen_3_06b_base.safetensors` |
| VAE | `qwen_image_vae.safetensors` |

插件不会自动下载缺失的 UNET、CLIP、VAE、LoRA 或自定义节点。控制预处理器可能在 ComfyUI 首次执行时按上游逻辑获取权重；生产环境建议提前缓存并做一次 512×512 验证。

### ComfyUI 自定义节点

八项工作流能力使用的关键非核心节点如下：

| 能力 | 必需节点类 |
| --- | --- |
| Anima 动态 LoRA | `Lora Loader (LoraManager)`，来自 ComfyUI-Lora-Manager |
| RTX 生图后放大 / 独立放大 | `RTXVideoSuperResolution`，工作流记录的节点包标识为 `comfyui_nvidia_rtx_nodes` |
| 迭代放大 | `PixelKSampleUpscalerProvider`、`IterativeImageUpscale`、`ColorMatch` |
| Quick 重绘 | `InpaintCropImproved`、`InpaintStitchImproved` |
| LanPaint | `LanPaint_KSampler`、`LanPaint_MaskBlend` |
| Anima 底图控制 | `AnimaLLLiteApply`、`OpenposePreprocessor`、`DepthAnythingV2Preprocessor`、`LineArtPreprocessor` |

RTX 两条路径还需要满足 NVIDIA RTX 节点上游对显卡、驱动和运行环境的要求；没有该环境时可使用 `base`，或在迭代节点可用时选择 `iterative`。

可先把 [docs/workflows/导入Comfy工作流用下载插件用.json](docs/workflows/导入Comfy工作流用下载插件用.json) 导入 ComfyUI，让 ComfyUI Manager 检查基础 Anima / LoRA Manager / RTX 依赖。迭代放大、底图控制、Quick 与 LanPaint 还应按上表逐项确认节点类是否注册；管理页面的工作流依赖检查和 ComfyUI 报出的缺失 `class_type` 才是当前实例的最终依据。各节点仓库名称可能随上游调整。

`workflow/*.json` 是插件提交给 ComfyUI 的 API Format 工作流；`docs/workflows/` 中的文件主要用于在 ComfyUI 前端检查依赖，不要把两者用途混淆。

## 安装与首次配置

1. 通过 AstrBot 插件管理器安装，或把整个仓库放入当前 AstrBot 的插件目录。手动克隆示例：

   ```bash
   git clone https://github.com/yenn001/astrbot_plugin_comfy_anima.git
   ```

2. 安装 Python 依赖。
3. 在 ComfyUI 中导入依赖检查工作流，安装缺失自定义节点，并准备模型与 LoRA。
4. 在 AstrBot 后台重载插件。
5. 设置 `comfyui_url`。如果反向代理要求 Bearer Token，再填写 `api_token`。
6. 选择“绘图思考模型”；需要 `/反推`、图片换角或 `/反推画图` 时，再选择支持图片输入的多模态 Provider。
7. 使用 ComfyUI-Lora-Manager 时保持 `enable_lora_manager=true`。建议保持 `strict_lora_validation=true`。
8. 先执行 `/anima ping`，再在管理页面点击工作流依赖检查。
9. 最后用一条最小请求验证：

   ```text
   /画图no 1girl, white hair, blue eyes, portrait --pipeline base
   ```

### 建议优先确认的配置

| 配置 | 作用 | 建议 |
| --- | --- | --- |
| `comfyui_url` | ComfyUI 服务地址 | 填写 AstrBot 实际可访问的地址 |
| `prompt_llm_provider_id` | 自然语言分镜、换角分类和语义规划 | 选择稳定的聊天 Provider |
| `reverse_prompt_provider_id` | 图片反推 | 选择支持图片输入的 Provider；留空时按配置回退 |
| `default_generation_pipeline` | 默认文生图管线 | `base`、`rtx` 或 `iterative` |
| `enable_inpaint` | Quick / LanPaint 重绘 | 只有依赖就绪时开启 |
| `strict_lora_validation` | 提交前核对真实 LoRA 文件 | 建议保持开启 |
| `default_style_preset` | 未指定风格时使用的组合 | 默认 `风格001`，请替换为自己的真实 LoRA 栈 |
| `max_concurrent_jobs` | 插件并发任务数 | 按显存和 ComfyUI 使用方式设置 |
| `provider_max_concurrent_jobs` | 反推、分镜、分类的并发准备数 | 默认 4；与 GPU 生成并发分离 |
| `enable_task_lora_snapshot` | 同一任务复用 LoRA 规划快照 | 建议开启；提交前第二次强刷不会被省略 |
| `enable_local_intent_router` | 普通绘图本地优先判断是否需要 LoRA 工具 | 建议开启，减少无意义 Tool Loop |
| `structured_director_mode` | 分镜结构化输出 | 建议 `auto`；优先 Function Calling，兼容 JSON / `<pic>` |
| `enable_prompt_composer_v2` | 本地三层提示词整理 | 建议开启；不会增加 LLM 调用 |
| `adaptive_negative_mode` | 自适应负面词 | 默认 `conservative`；只按检测到的画面风险补词 |
| `danbooru_validation_mode` | 本地硬锚点检查 | 默认 `report`；`guarded` 当前在普通绘图路径安全降级为报告 |
| `enable_prompt_diagnostics` | 提示词工坊内存诊断 | 默认开启；记录有界，重载即清空 |
| `prompt_diagnostics_include_content` | 诊断显示完整分层内容 | 默认关闭；仅在可信管理环境按需开启 |
| `enable_prompt_asset_library` | 视觉提示词资产库 | 默认开启；不附带外部数据 |
| `prompt_asset_remote_import_enabled` / `prompt_asset_max_download_mb` | 资产库 URL 导入开关与大小上限 | 默认关闭；开启后仍仅允许公共 HTTPS，单次最多 16 MiB；局域网数据请粘贴/上传 JSON/CSV |
| `enable_prompt_lab` | 固定 Seed 多候选草稿 | 默认开启；草稿不会自动出图 |
| `prompt_lab_batch_capacity` / `prompt_lab_ttl_seconds` | Prompt Lab 批次容量与有效期 | 默认 32 批、30 分钟 |
| `enable_lora_visual_gallery` | LoRA 指纹化视觉清单 | 默认开启；不取代 LoRA Manager 强制刷新 |
| `lora_visual_roots` | 可读 companion 图的本地根目录白名单 | 默认为空；有挂载时优先本地图，否则使用受控的 Manager 同源预览 |
| `lora_visual_cache_mb` / `lora_visual_preview_max_mb` | 缩略图缓存与单图上限 | 默认 256 MB / 4 MB |
| `enable_web_ui` | 独立端口管理面板 | 默认关闭；需要时再开启并设置强密码 |

完整配置、范围和提示以 [\_conf_schema.json](_conf_schema.json) 为准。

## 绘图用法

### 自然语言绘图

开启 `enable_natural_draw` 并选好绘图思考模型后，可以直接发送普通 QQ 消息：

```text
帮我画一名站在雨夜车站的少女，电影感灯光
用风格001画一名白发角色，分辨率832x1216，只要Anima原图
画一幅山顶日出，使用迭代采样放大
```

插件只在识别到明确绘图意图时接管消息。自然语言中的“不要放大”“RTX 放大”“迭代放大”会用于选择对应生图管线；若同时出现互斥要求，请求会被拒绝而不是猜测。

### 直接 Tags

```text
/画图 1girl, white hair, blue eyes, rain, neon city
/画图no 1girl, black dress, portrait, looking at viewer
/画图no 1girl, white hair, portrait --preset 风格001 --pipeline base
/画图 1girl, red dress, night city --pipeline iterative --size 832x1216
/画图 一名蓝发少女蹲在海边浅水里看烟花 --llm --pipeline rtx
/画图 华丽的双人奇幻海报，金属与薄纱材质，逆光和宏大宫殿 --l u --pipeline rtx
/画图no 用风格001画一名雨夜撑伞的角色 --llm
/画图 1girl, roxy migurdia, blue hair, twin braids, school uniform, standing，把角色换成甘雨，穿JK制服 --lcc u
/画图no 1girl, blue hair, purple eyes, standing，把原角色换成原创角色：黑色长发、金色眼睛、精灵耳、左眼下有美人痣 --llm c
/方案列表
/方案 EX-001 --seed 123 --pipeline rtx
/方案 我的雨夜方案 --size 832x1216
/方案 EX-005 再出个cos给我看看
```

- `/画图` 使用 QQ 合并转发发送结果。
- `/画图no` 直接发送图片。
- 两个命令默认跳过 LLM，输入按可直接用于 Anima 的 Tags 原样执行。
- 显式添加 `--llm`（短写 `--l`）时使用 Standard 绘图导演；追加 `ultra` 或 `u` 使用华丽高密度模式。两种模式都转换为“有序 Tags + 一句英文场景描述”的混合提示词；`--raw` / `--no-llm` 可明确保持原样。
- 显式文字换角使用 `--llm c`、`--llmcc` 或 `--lcc`；Ultra 组合写成 `--llm c u`、`--llmcc u` 或 `--lcc u`。这些开关只对 `/画图` 与 `/画图no` 生效，不属于 `/anima draw` 或普通聊天的自动意图。
- 文字换角正文必须先给出完整旧 Tags，再写 `把角色换成<目标>`；逗号后的内容可覆盖服装等事实。插件会删除旧角色姓名、作品身份以及发型/发色、瞳色/异色瞳、耳角尾、体型、痣等稳定外貌；默认保留服装、动作、表情、视线、构图、背景和风格。
- 目标角色 LoRA 是可选增强：最新清单中只有一个可加载匹配时使用；完全缺失，或同一角色有多个版本但无法唯一选择时，自动改用纯语义身份 Tags。用户明确指定 `.safetensors` 等文件、候选实际属于不同角色或仅有近似名称时会停止，不会猜选。
- 已知角色的纯语义身份以一个合格的 `character_(作品)` canonical Tag 为主锚点；该锚点会使用 ComfyUI 安全括号转义并插入 `1girl/1boy, solo` 后，不再堆到场景尾部。模型不再为了证明身份强行拼出完整脸部/身体清单。若 Danbooru Gallery 可用，插件只从 exact 角色的公开安全级单人帖子中统计最多四项高支持率稳定外貌；衣装、动作、胸围与其他身体猜测不会进入角色档案，原始帖子也不会保存。
- 本地 Danbooru 索引返回 `character` 分类的 exact canonical / unique alias 时，该 canonical Tag 成为已固定的语义主锚点。最终分类会区分 LoRA exact、LoRA metadata、Danbooru exact、Provider 高置信与普通 Provider 受限结果，并按各自证据层级执行对应门槛；prefix、keyword 与 fuzzy 仍只能发现候选，不能固定身份。
- 用户写入“置信度 100%”“confidence=1”等文字不能提高 Provider 或分类器置信度；这些控制语句会从目标与附加要求中移除并记为已忽略，而不是进入提示词。
- `/` 不再单独代表 LoRA 文件路径，因此 `今汐/今夕` 这类角色别名可以正常检索。只有明确的 `lora:` 前缀，或以 `.safetensors`、`.ckpt`、`.pt`、`.bin` 结尾的目标才启用严格文件语义并禁止降级猜选。
- 原创角色可在目标后直接写稳定外貌，例如发色、瞳色、耳型、物种、体型和痣；至少给出三项协调的稳定特征。插件不会把旧角色未指定的外貌继承给原创角色。
- `--preset` 接受 LoRA 组合的稳定序号或精确名称；名称含空格时请加引号。
- `/方案列表` 和 `/方案` 仅管理员可用。仅提供 ID/名称时，`/方案` 使用方案已确认的正面、负面提示词和管线且不调用 LLM；ID/名称后追加自然语言时，绘图导演只调整用户明确要求改变的部分。`--raw` 可把追加内容作为高级 Tags 直接附加；seed、分辨率、步数、CFG、管线与额外 LoRA 预设仍可覆盖。
- 普通对话中明确说“用方案 P-XXXXXX 画图”时，管理员会话的 LLM 可通过只读方案工具先确认真实 ID，再读取方案内容；未查到或名称歧义时必须停止，不能编造方案。

### 高级 `/anima` 命令

```text
/anima draw <剧情或Tags>
/anima prompt <剧情>
/anima status
/anima cancel
/anima ping
/anima help
```

`/anima draw` 常用选项：

| 选项 | 说明 |
| --- | --- |
| `--negative "..."` | 追加负面提示词 |
| `--seed 123456` | 指定随机种子 |
| `--size 832x1216` | 指定画布尺寸 |
| `--steps 30` | 覆盖采样步数 |
| `--cfg 5` | 覆盖 CFG |
| `--pipeline base|rtx|iterative` | 指定三条文生图管线之一 |
| `--denoise 0.35` | 覆盖当前 manifest 声明的采样器 denoise；文生图与重绘均可能受影响 |
| `--upscale` / `--no-upscale` | 兼容参数，分别映射到 RTX / 原图管线 |
| `--llm` / `--l` | 使用 Standard 绘图导演 |
| `--llm ultra` / `--llm u` / `--l ultra` / `--l u` | 使用 Ultra 华丽高质量扩写 |
| `--raw` / `--no-llm` | 直接使用输入 Tags |
| `--preset "风格001"` | 使用一个 LoRA 组合 |

所有长选项保留兼容，并提供精确短写：`--p b|r|i`、`--sz`、`--st`、`--sd`、`--c`、`--n`、`--pr`、`--l`、`--r`。短写按命令上下文解析，不会用单字母模糊匹配模型或 LoRA 文件。

示例：

```text
/anima draw 她在雨夜回头看向镜头 --pipeline rtx --seed 123
/anima draw 1girl, white hair, portrait --raw --pipeline base --preset 风格001
/anima prompt 一名少女站在海边，夕阳逆光
```

### Anima 底图控制

发送或引用一张图后使用：

```text
/底图控制 画成雨夜中的新角色 --m p d --p r
/底图控制 构图和姿势不变，用风格001-1画出来
/底图控制 按线稿完成上色 --m l --p b
/底图控制 参考人物外观和画风，重新设计动作 --m r
```

- `p / pose`：参考人体姿势、动作和骨架。
- `d / depth`：参考空间结构、前后关系与透视布局；不是摄影“景深”。
- `l / lineart`：提取线稿/草图轮廓，生成完整上色结果。
- `r / reference`：柔和参考外观、配色、材质与画风，不保证精确身份或姿势。
- 支持 `--m p d`、`--m p --m d` 和完整名称；显式模式优先于自然语言。
- 在 `/底图控制` 命令中可以省略 `--m`，例如“构图和姿势不变”会选择 Pose + Depth。自然语言示例：“照着这张图的姿势和构图画一个新角色”“按这张线稿上色”“参考这张图的画风和配色画”。
- “用风格001-1”“使用风格2”只选择保存的 LoRA 风格预设，不会启用 Reference；Reference 必须明确表达“参考这张图/原图的画风、配色或外观”。裸“构图漂亮”“景深浅一点”“给衣服上色”也不会误触。

### LLM 回复自动出图

开启 `enable_llm_pic_trigger` 后，普通角色扮演或对话模型可以用控制标签触发图片：

```xml
<pic prompt="1girl, close-up, rain, blue eyes, wet hair, looking at viewer. She looks toward the viewer as rain runs through her wet hair beneath the cold streetlight." pipeline="rtx" negative="text, watermark">
```

明确的遮罩重绘请求可使用：

```xml
<edit prompt="red evening dress, detailed fabric" mode="quick" negative="school uniform">
```

`<pic>` 与 `<edit>` 互斥；`<think>...</think>` 中的标签不会执行。插件还会检查真实图片、遮罩、权限、风控、管线和 LoRA 清单，模型输出并不直接获得任意工作流控制权。

通过这些入口生成的提示词会进入 Prompt Composer v2；直接 Tags 命令只有显式添加 `--llm` 时才进入 Composer。Composer 只做本地分层、去重、冲突检查和确定性负面词补充，不展示或保存模型的思维过程。

## 图片反推与独立 RTX 放大

把图片与命令放在同一条消息中，或回复一张图片后发送：

```text
/反推 重点分析构图和光线
/反推画图 保持构图，改成红色礼服，使用RTX放大
/反推画图 构图和姿势不变，换成雨夜礼服 --m p d --p r
/放大 2
```

- `/反推` 只返回经过结构校验的 Tags、负面词、构图、描述、角色候选和置信度。
- `/反推画图` 先反推可观察事实，再交给绘图导演。追加 `--m p|d|l|r` 时，同一张输入图作为控制图；没有控制模式时，同一张图进入真正的 Anima img2img，默认 denoise 为 `0.55`。
- `/放大` 只执行独立 RTX 工作流，不加载 Anima UNET。倍率范围为 `1` 到 `4`，留空使用 `rtx_scale`。
- 插件只读取用户本条消息或明确引用消息中的图片，不接受命令文本里的任意图片 URL。

## 无蒙版整图改图

发送一张图片，或回复一张图片后使用：

```text
/改图 把衣服换成红色晚礼服，其他内容保持不变 --mode preserve
/改图 改成雨夜街景，保留角色、动作和主要构图 --mode balanced
/改图 参考原图重新画一张电影感版本 --mode free
```

也可以直接使用自然语言：

```text
把这张图里的衣服换成黑色西装，其他保持不变
换个夜景背景
参考这张图重新画一张
```

模式说明：

| 模式 | 行为 |
| --- | --- |
| `preserve` | 除明确修改项外，尽量保留身份、发型、表情、姿势、镜头、构图、背景、光线和画风 |
| `balanced` | 默认模式；保留身份、主体数量、主要动作、构图和场景语义，允许重组次要细节 |
| `free` | 把原图作为内容参考，允许大幅重新设计；仍遵守用户明确要求保留的角色身份 |

插件会从原图宽高比推导约一百万像素、64 倍数的安全画布；显式 `--size` 优先。换衣时，旧服装会从正面 Tags 中移除，只有反推或实时 LoRA 元数据明确证明的冲突衣物词才会少量进入 negative。角色名、脸、发色、瞳色和体型不会因为换衣被放进 negative。

这是像素连接的整图 img2img，不是蒙版局部修改。默认 denoise：`preserve=0.32`、`balanced=0.55`、`free=0.78`；可用 `--denoise 0-1` 显式覆盖。越低越接近原图，越高越允许重画。

## 遮罩局部重绘

```text
/重绘 把遮罩区域的校服换成红色晚礼服 --mode quick
/重绘 修复遮罩内的手部结构并保持其余画面 --mode lanpaint --denoise 0.8
```

支持三种明确输入方式：

1. 回复一张原图，同时发送一张遮罩图。
2. 在同一条消息中按“原图、遮罩”顺序发送两张图片。
3. 只发送一张带透明区域的 PNG；透明区域会转换为重绘遮罩。

遮罩规则：白色或透明区域重绘，黑色区域保留。原图与遮罩尺寸必须完全一致，遮罩必须包含有效的非黑区域。插件不会根据“这里”“那里”或图片内容猜测遮罩，也不会自动缩放尺寸不一致的遮罩。

- `quick`：裁切并重绘遮罩附近区域，通常更快，适合小范围修改。
- `lanpaint`：多步处理和遮罩融合，适合复杂结构或需要更细致重构的区域。

普通“画某角色穿新衣”属于文生图；引用现有图片后的普通换衣、换背景、换表情或重新画一张会进入 `/改图`。为兼容用户习惯，`/重绘` 后如果没有明确提到遮罩、蒙版、白色 / 透明区域、局部区域、inpaint，也没有指定 `--mode quick|lanpaint`，会自动转入无蒙版整图改图；明确局部语义时仍严格要求真实遮罩。

## 单角色语义换角

语义换角会重新生成整张图，只把角色身份从 A 改为 B，并尽量保留衣服、姿势、动作、表情、构图、背景、光线、画风和非角色 LoRA。它不是人脸替换、像素级编辑或局部重绘。

角色和服装可以在同一个请求里修改，例如“把达妮娅换成米浴并穿红色礼服，构图和背景保持不变”。插件会先把新服装写入中间画面 Tags、清理冲突的旧衣服，再执行身份替换；仅写“把泳装换成三点式”不会被识别成换角。

### 图片输入

回复或发送一张单角色图片：

```text
/换角色 达妮娅 -> 卡莲 --preview
/换角色 达妮娅 -> 卡莲 --mode keep-outfit --preset 风格001
```

也可以用明确的自然语言图片请求：

```text
把图片里的达妮娅换成赛马娘的米浴，保持衣服、姿势和背景
```

### 完整 Tags 输入

用 `|` 分隔换角选项和完整 Tags，所有选项必须写在 `|` 之前：

```text
/换角色 达妮娅 -> 卡莲 --preview | <lora:characters/denia:0.8>, 1girl, denia_wuwa, school uniform, standing, rainy street
/换角色 达妮娅 -> 卡莲 --negative "low quality" | 1girl, denia_wuwa, casual hoodie, looking at viewer
```

图片与 Tags 不能同时提供。当前换角只支持单角色；多图、多主体、多个角色 LoRA、歧义角色或无法完整分类的 Tags 会失败关闭。

### 目标角色 LoRA 模式

默认情况下，插件会在强制刷新后的最新 LoRA 清单中唯一解析目标角色：

- 只接受真实可加载文件、明确角色名、可信人工别名或仍有效的高置信语义档案。
- 同名、多版本或多服装候选无法唯一确认时不会猜选。
- 规划后、提交前再次核对文件名、SHA-256 和元数据来源指纹。
- 最终角色 LoRA 栈必须且只能保留目标角色；风格和功能 LoRA 可按规则保留。

`keep-outfit` 是默认模式，只替换身份并保留当前服装。`target-outfit` 会尝试使用目标角色默认服装，但只有 LoRA 当前元数据能明确证明服装触发词时才允许执行。

目标角色 LoRA 权重可用 `--weight` 设置，安全范围为 `0.55` 到 `0.75`。

### 无角色 LoRA / 纯语义 Tags 模式

当最新清单中对普通角色名发生真实未命中时，请求会自动尝试纯语义 Tags。也可以显式禁止加载目标角色 LoRA，即使库中存在对应文件：

```text
/换角色 达妮娅 -> 赛马娘的米浴 --no-character-lora
/换角色 达妮娅 -> 赛马娘的米浴 --no-lora | 1girl, denia_wuwa, school uniform, standing, rainy street
```

`--no-lora` 是 `--no-character-lora` 的兼容别名。自然语言图片请求也会识别“无需 / 不用 / 不使用 / 不要 / 禁止使用角色 LoRA”：

```text
把图片里的达妮娅换成赛马娘的米浴，无需使用角色 LoRA
```

纯语义模式的边界：

- 插件仍会用最新清单核对目标名称；歧义、多候选、近似建议和显式但不存在的文件路径继续失败关闭，不会借纯语义模式绕过角色确认。
- 已知角色以一个 `character_(作品)` canonical Tag 作为主身份锚点；绘图 Provider 最多补充 0–4 项高置信稳定外观，不能确定就留空。原创角色仍要求至少三项协调外貌。
- 若本地 Danbooru 索引以 `character + exact + verified` 证明 canonical Tag，后续分类器会把该身份视为已固定证据，而不是再次凭常识否定；非 exact 查询只提供候选。命中的自然语言风格预设名称会在 LoRA 组合解析后从视觉提示词消费，不能以 `风格006 masterpiece` 等污染项进入 CLIP。
- 用户声明的置信度不会改变任何阈值；带 `/` 的自然别名不是文件路径，严格文件模式只由 `lora:` 或支持的模型文件后缀触发。
- 最终 LoRA 栈禁止出现任何角色 LoRA；画师、风格、画质和功能型 LoRA 仍可保留。
- 只支持 `keep-outfit`，不支持依赖目标 LoRA 元数据的 `target-outfit`。
- 角色还原度通常低于专用 LoRA 模式；Provider 不能给出合格 Tags 时会停止，不会编造文件名继续提交。

建议首次换新角色或处理复杂 weighted Tags 时先加 `--preview`。预览仍会执行必要的图片反推、LoRA 刷新、语义 Tags 规划和分类校验，只跳过最终 ComfyUI 生图提交，并显示移除、保留和新增摘要。

### 换角专用选项

| 选项 | 说明 |
| --- | --- |
| `--mode keep-outfit|target-outfit` | 保留当前衣服，或使用可证明的目标默认服装 |
| `--weight 0.55~0.75` | 目标角色 LoRA 权重；参数始终校验该范围，纯语义模式中不会用于注入，建议省略 |
| `--size 832x1216` | 指定重生成画布 |
| `--negative "..."` | 追加负面提示词 |
| `--preset "..."` | 替换或应用一个画师 / 风格组合 |
| `--no-character-lora` | 强制纯语义 Tags，不使用任何角色 LoRA |
| `--no-lora` | 上一选项的兼容别名 |
| `--preview` | 完成规划与校验，但跳过 ComfyUI 生图提交 |

## LoRA 实时刷新与组合

LoRA Manager 的元数据记录不等同于文件当前可加载。插件将 Manager 返回的数据与 ComfyUI 实际节点清单交叉验证，并在关键操作中强制刷新：

- LLM 调用 `list_anima_loras` 或 `list_anima_lora_presets` 前。
- 管理员执行查询、保存、删除或下载相关命令时。
- 生图、遮罩重绘和语义换角规划前。
- 工作流提交前，对最终精确文件再次复核。

严格模式下，Manager 扫描或 ComfyUI 清单读取失败会停止本次操作，不会拿旧缓存冒充最新文件。删除、改名和同 basename 歧义会在重新解析时被拦截；语义换角还会对规划中记录的 LoRA 校验 SHA-256 与元数据来源指纹，发现内容或身份资料变化时停止提交。

角色 LoRA 与画师 / 风格组合分开管理：风格组合负责画质、美感、画师、皮肤、背景和功能性 LoRA；角色身份由实时查询单独加入。不要把常用角色硬编码进默认风格栈。

可用的管理员命令：

```text
/lora刷新
/lora下载 <Civitai模型页URL>
/lora组合列表 [角色|风格|混合]
/lora组合保存 <角色|风格|混合|auto> <名称|数字|auto> <LoRA串> [--trigger "补充触发词"] [--alias "简称"] [--note "备注"] [--description "说明"]
/保存风格 <名称|数字> <LoRA串> [--trigger "触发词"] [--description "说明"]
/lora组合删除 <序号|名称>
/方案列表
/方案 <ID或唯一名称> [--seed/--size/--steps/--cfg/--pipeline/--preset]
```

- `/lora刷新` 触发 Manager 扫描并立即更新 LLM 可查询清单。
- `/lora下载` 只接受配置允许的 Civitai HTTPS 主机；下载后会尝试补抓元数据并刷新清单。文件下载成功而后处理失败时会报告“部分成功”。
- 组合保存会解析成最新精确文件名并做数量、分类和重复校验。同名保存表示覆盖；WebUI 可编辑并改名，不会残留旧组合。
- 组合支持独立显示名、最多 12 个简称/别名和管理备注。`风格1011 kei` 会安全派生 `风格1011`；`风格GZC` 可用完整名、唯一简称 `GZC`、`用风格GZC` 或 `风格使用gzc` 命中。其他简称可在 WebUI 或 `--alias` 中明确添加，任何别名碰撞仍失败关闭。
- “手动补充触发词”不再屏蔽 Manager 元数据。每次生成仍会强刷 Manager/ComfyUI，风格与功能 LoRA 合并全部最新触发词，角色 LoRA 只采用可验证身份触发词；WebUI 会分别显示手动、Manager 与最终有效结果。
- `/保存风格 001 ...` 会规范为 `风格001`。开启 `auto_reload_after_style_save` 时，画师 / 风格组合持久化成功后会延迟重载插件。
- 管理页面可以为 LoRA 建立带来源和置信度的角色 / 作品 / 风格档案，并允许人工审核别名；人工事实优先于 LLM 推断。
- 可选 Embedding / Rerank 只帮助候选召回和排序，不能替代最终的真实文件确认。
- 最终注入的 LoRA 控制与可信触发词固定写在英文场景关系句之前，不会破坏三层提示词顺序。

## 工作流、UNET 与管理命令

```text
/comfy_ls
/comfy_use <序号>
/comfy_lock on|off|status
/模型列表
/模型切换 <序号|完整UNET文件名>
/违禁级别 none|lite|full
/comfy帮助
```

- `/comfy_ls` 每次重新扫描并列出 `workflow_dir` 下的直属 `.json` 文件；实际切换时再校验 manifest 和任务类型。
- `/comfy_use` 只允许热切换 manifest 认可的三条文生图工作流；旧版 `input_id` / `output_id` 临时覆盖参数已被拒绝，运行中有图片任务时也不会切换。
- `/模型列表` 实时读取 ComfyUI 的 UNETLoader 清单。
- `/模型切换` 在切换前刷新完整清单，并把模型应用到三条生图与两条重绘 Builder；独立 RTX 不使用 Anima UNET。
- `/comfy_lock on` 后只允许管理员绘图。
- `/违禁级别` 修改当前 QQ 群的 `none`、`lite` 或 `full` 词库策略。

## AstrBot 原生 plugin-page

支持原生插件页面的 AstrBot 会发现 `pages/control/index.html`。可从插件详情页打开“工坊控制台”，或访问：

```text
/plugin-page/astrbot_plugin_comfy_anima/control
```

该页面通过 AstrBot Dashboard 官方 Bridge 调用带插件权限的后端接口，不读取 Dashboard Cookie、Token 或父页面 DOM，也不需要再次登录。即使 `enable_web_ui=false`，原生 plugin-page 仍可使用。

页面主要提供：

- 核心绘图、并发、默认管线、采样器覆盖和 LLM Provider 配置。
- 三条可选生图工作流的实时扫描与热切换。
- 无蒙版整图改图的编排状态、入口和任务阶段。
- 工作流依赖检查，分别验证三条生图、整图 img2img、底图控制、独立 RTX、Quick 和 LanPaint。
- UNET 实时清单与切换。
- LoRA 搜索、元数据获取、语义建档、人工审核、组合、下载、受控删除，以及指纹化视觉清单、本地缩略图预热与缓存管理。
- 提示词工坊：查看 Composer / 索引状态、运行不调用 LLM 的本地诊断、清空诊断、更新 Danbooru 索引，并使用视觉资产搜索、分层编辑和 Prompt Lab。
- 环境配置档案；档案不包含密码、Token、Provider 提示词、权限、风控、资产库、Prompt Lab 或 LoRA 视觉缓存设置。
- 持久任务中心、阶段时间线和脱敏日志控制台。
- `纸感工坊`、`铅灰编辑部`、`墨夜控制室` 三套本地主题。

从早期版本升级时，旧环境档案可能只有单工作流字段。v1.2.1 会保留原档案名称、激活状态、地址、UNET、节点与分辨率，只为其补齐六个新工作流字段并原子迁移；界面不应再因为字段升级而显示“尚未保存档案”。

## 独立端口 WebUI

独立 WebUI 默认关闭。需要使用时至少配置：

```text
enable_web_ui=true
web_ui_host=0.0.0.0
web_ui_port=6198
web_ui_username=admin
web_ui_password=至少8位且不要与其他账号共用
```

启动后访问：

```text
http://AstrBot服务器IP:6198
```

独立 WebUI 与原生 plugin-page 使用相同业务接口和前端功能，但采用自己的登录会话。后端只允许监听回环地址、`0.0.0.0`、私有 IP 或链路本地 IP，不接受公网 IP 或域名作为绑定目标。密码和 `api_token` 不会通过设置 API 回显；插件不会主动输出这些值，WebUI 日志控制台还会对常见凭据格式做额外脱敏。

“提示词工坊”的诊断默认只保留数量、冲突、风险、哈希与阶段摘要，容量由 `prompt_diagnostics_capacity` 限制，插件重载后自动清空，也不会写入任务 SQLite 或持久日志。只有管理员显式开启 `prompt_diagnostics_include_content` 时页面才显示完整分层提示词；该开关适合可信局域网内的短时排查，使用后建议关闭并清空诊断。

实验能力检查目前只读取 ComfyUI 的实时节点注册情况，评估画师混合、质量栈和分层回放等候选能力。仓库没有附带经过审核的实验工作流，节点存在也不会自动激活、改写或提交任何实验管线。

视觉资产、Prompt Lab 批次和 LoRA 缩略图缓存是全局能力，不会写入或跟随局域网环境配置档案。从旧版升级时，缺失字段使用安全默认值，已有字段与环境档案不会被重写。

内置服务使用 HTTP，不自行提供 TLS。不要把 6198 端口直接暴露到公网，也不要让登录凭据或会话经过不可信网络。确需远程访问时，应使用可信 VPN，或由你自己的反向代理终止 HTTPS 并完成认证。

## 安全与权限

- 图片输入有格式、文件大小和像素总量限制；临时图片在任务结束后清理。
- 图片中文字、二维码和提示注入都按不可信视觉内容处理，不会变成系统命令。
- `/反推`、`/改图`、`/放大`、`/重绘` 和图片换角只读取本条或明确引用的图片。
- 明确的局部重绘必须有真实遮罩；未声明局部或遮罩的 `/重绘` 会转为无蒙版整图改图。生图与重绘控制标签互斥。
- LoRA / UNET 模型删除要求最新清单中的精确名称和二次确认；浏览器只提交精确名与确认名，实际文件路径由后端根据 Manager 清单解析。
- LoRA 视觉预览优先使用白名单根目录中的精确同名 companion 图；容器无挂载时，只允许当前 Manager origin 的固定预览端点读取最新精确记录。前端不能传 URL/路径，后端不提供模糊 basename、任意路径或 Civitai/任意 URL 代理。
- 视觉资产 URL 导入默认关闭；开启后仍只允许公共 HTTPS，单次远程包最多 16 MiB，并会拒绝私网/回环地址、URL 凭据、重定向、超限响应和携带敏感凭据的来源信息。局域网数据应改用粘贴或上传 JSON/CSV。
- Prompt Lab 候选是无执行能力的短期草稿；确认只产生经素材 revision、最新 LoRA 清单和 Prompt Composer 复核的结果，不自动出图。实际生成仍必须走普通 QQ 严格管线。
- `lora_download_allowed_hosts` 应只保留可信 Civitai 官方域名；不要放开任意下载主机。
- `unet_lan_only` 与 `lora_lan_only` 建议保持开启，避免清单请求访问公网、携带 URL 凭据或跟随不可信重定向。
- 群白名单、全局锁定、用户冷却和 `none|lite|full` 词库策略在最终提示词提交前仍会执行。
- 管理员忽略冷却、白名单或违禁词是独立配置；“忽略违禁词”默认应保持关闭。
- 默认取消只移除尚在 ComfyUI 队列中的任务。`allow_global_interrupt=true` 可能中断 ComfyUI 当前全局任务，只适合不与其他用户或程序共享的实例。
- Prompt Composer、Danbooru 报告和提示词诊断不会绕过上述权限、白名单、冷却、敏感词、LoRA 实时复核与工作流提交校验。

## 常见问题

### WebUI 为什么只看到三个工作流？

这是预期行为。下拉框只选择 `base`、`rtx`、`iterative` 三条文生图管线。底图控制用 `/底图控制`，独立 RTX 用 `/放大`，Quick / LanPaint 用 `/重绘`，整图 img2img 用 `/改图`。这些工具不会成为第四个可选文生图工作流；工作流依赖检查可以查看八份正式 API 工作流。

### 工作流依赖检查有项目不可用

先在同一 ComfyUI 中手动运行对应工作流，检查错误中报告的 `class_type`、模型和文件名。建议重新导入 `docs/workflows/导入Comfy工作流用下载插件用.json`，让 ComfyUI Manager 检测缺失节点。某条附加管线失败不会改变其他管线的依赖要求。

### `character_not_found` 或无法确认目标角色

先执行 `/lora刷新`，确认目标是否有唯一角色记录。普通角色名在目标 LoRA 真实缺失时会尝试纯语义 Tags；若要无条件禁止加载角色 LoRA，请使用：

```text
/换角色 A -> B --no-character-lora --preview
```

该选项不会绕过名称安全解析：歧义、近似候选以及显式但不存在的 `.safetensors` 路径仍会报错，不会静默降级。纯语义模式还要求可用的绘图 Provider，并且只支持 `keep-outfit`。

### 纯语义换角仍失败

检查绘图 Provider 是否可调用、`character_swap_timeout` 是否足够，以及模型是否返回了合格的受限英文身份 Tags。若请求同时要求 `target-outfit`，请改为默认 `keep-outfit`。插件会拒绝在纯语义模式中残留任何角色 LoRA。

### LoRA 明明在 Manager 中，插件仍说不可用

Manager 元数据不代表 ComfyUI 当前能加载该文件。检查 `/object_info` 中的 Lora Manager 节点清单、Manager 扫描状态、完整子目录路径和同 basename 冲突。严格模式不会使用仅存在于旧元数据或旧缓存中的记录。

### 自然语言能聊天但不出图

检查 `enable_natural_draw`、绘图思考模型、全局锁定、群白名单、冷却和违禁级别。普通 LLM 回复自动出图还要求 `enable_llm_pic_trigger=true`，并且最终回复包含合法的 `<pic prompt="...">`。

### `/反推` 或图片换角无法读取图片

确认使用 aiocqhttp / NapCat 发送或引用了单张图片，所选 Provider 支持图片输入，图片没有超过 `max_input_image_size_mb` 和 `max_input_image_pixels`。图片换角当前只接受单角色输入。

### `/重绘` 报遮罩错误

当请求明确包含“局部、遮罩、蒙版、白色区域、透明区域、inpaint”或 `--mode quick|lanpaint` 时，确认原图和遮罩尺寸完全一致；白色或透明区域是重绘区域，纯黑遮罩会被视为空。只发一张图片时，它必须是带透明区域的 PNG。普通整图换衣或换背景无需蒙版，会自动进入 `/改图`。

### `/改图` 为什么没有完全保持原图？

`/改图` 现在会把原图像素接入 Anima img2img，但扩散模型仍会随 denoise 重构细节。优先使用 `--mode preserve` 或较低 `--denoise`；需要只改局部时提供遮罩并使用 `/重绘`，需要严格姿势或空间结构约束时使用 `/底图控制 --m p`、`--m d` 或两者组合。

### 连接 `127.0.0.1` 失败

AstrBot 与 ComfyUI 很可能不在同一个网络命名空间。Docker 部署请使用宿主机地址、容器服务名或同网络地址，并确认反向代理允许插件所需的 HTTP 接口。

### `/画图` 合并转发失败

确认平台是 aiocqhttp / NapCat，且 OneBot v11 合并转发可用。可先使用 `/画图no` 判断生成链路本身是否正常。

### 取消后显卡仍在运行

默认取消只停止插件等待并删除排队项，不一定中断已经开始的 ComfyUI 任务。除非 ComfyUI 是独占实例，否则不要开启全局中断。

## 数据、升级与排查资料

运行时语义索引、视觉提示词资产库、Prompt Lab 草稿、LoRA 缩略图缓存、任务记录、下载状态和本地配置保存在插件数据目录，不应提交到源码仓库或包进发布 ZIP。升级前建议备份 AstrBot 插件配置、数据目录、自定义工作流与人工 LoRA 别名。

排查问题时请同时提供：

- AstrBot 插件日志中的错误码和阶段。
- 工作流依赖检查的对应项目结果。
- ComfyUI 运行同一 API 工作流时的节点错误。
- 是否使用 Docker / 反向代理，以及 AstrBot 访问的 `comfyui_url`。
- 相关 LoRA 的精确文件名和 `/lora刷新` 结果；不要提供服务器绝对路径、密码或 Token。

## 许可证

仓库当前未附带明确的 `LICENSE` 文件，许可条款仍待项目作者确认。在明确许可证发布前，不应默认本项目允许复制、修改、再分发或商用。

ComfyUI、自定义节点、模型、LoRA、Civitai 资源及其他第三方内容分别受其各自许可证和使用条款约束；使用者需要自行确认授权范围。

Prompt Composer v2、本地 Danbooru 索引接口、视觉资产库、分层编辑、Prompt Lab、LoRA 视觉清单和实验能力检测均为本仓库独立实现。本项目没有复制、打包或再分发 `comfyui-good-anima`、`Comfyui-Anima-Tools` 的源码、可执行文件、数据索引、预览图、Prompt 或工作流；若用户自行安装、导入或使用第三方内容，仍应分别遵守其许可证和使用条款。
