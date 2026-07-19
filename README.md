# AstrBot Comfy Anima

> 当前正式版本：v1.2.0

面向 AstrBot、aiocqhttp / NapCat QQ 与 ComfyUI 的 Anima 绘图插件。它把自然语言分镜、直接 Tags、生图、图片反推、单角色语义换角、RTX 放大、遮罩重绘、LoRA 实时索引和管理页面放在同一套受控流程中。

本插件针对仓库内附带的 Anima 工作流与 manifest 设计，不是任意 ComfyUI 工作流的通用适配器。开始部署前，建议先阅读“六条处理管线”和“依赖”两节。

- 项目地址：<https://github.com/yenn001/astrbot_plugin_comfy_anima>
- 更新记录：[CHANGELOG.md](CHANGELOG.md)
- 配置字段：[\_conf_schema.json](_conf_schema.json)

## 六条处理管线

插件所说的“六管线”是三条文生图管线，加上一条独立放大和两条遮罩重绘管线。它们不是六个都能设为默认生图工作流。

| 管线 | 内置 API 工作流 | 用途 | 使用入口 | 可在生图下拉框选择 |
| --- | --- | --- | --- | --- |
| Anima 原图 | `anima_base_api.json` | 只生成 Anima 原图，不做二次放大 | `--pipeline base` | 是 |
| Anima + RTX | `anima_rtx_api.json` | Anima 生图后执行 RTX 放大 | `--pipeline rtx` | 是 |
| Anima + 迭代放大 | `anima_iterative_api.json` | Anima 生图后进行迭代采样和细节重构 | `--pipeline iterative` | 是 |
| RTX 独立放大 | `rtx_upscale_api.json` | 只放大用户提供的图片，不重新调用 Anima | `/放大` | 否 |
| Quick 遮罩重绘 | `anima_inpaint_crop_api.json` | 裁切遮罩附近区域，适合快速、小范围修改 | `/重绘 --mode quick` | 否 |
| LanPaint 精细重绘 | `anima_lanpaint_api.json` | 多步遮罩重绘，适合复杂结构或精细修改 | `/重绘 --mode lanpaint` | 否 |

因此，WebUI 的“当前生图工作流”只出现三个可选项是正常行为。独立 RTX、Quick 和 LanPaint 会显示在“检查六管线依赖”结果中，但不会进入生图工作流下拉框，也不会被 `/comfy_use` 设为默认文生图入口。

默认生图管线由 `default_generation_pipeline` 决定，仓库默认值为 `rtx`。单次请求的优先级为：

1. 显式 `--pipeline base|rtx|iterative`。
2. 兼容参数 `--upscale` 或 `--no-upscale`。
3. 绘图导演在用户明确表达时选择的管线。
4. WebUI / 插件配置中的默认管线。

`workflow/anima_v2_api.json` 与 `workflow/anima_api.json` 作为兼容、回滚资产保留，不属于六条默认处理管线。

## 主要能力

- 自然语言绘图：由 AstrBot 中已配置的聊天 Provider 把中文画面要求整理为 Anima / Danbooru 风格英文 Tags。
- 直接 Tags：`/画图` 和 `/画图no` 跳过 LLM，直接把用户输入写入工作流。
- 图片反推：使用 AstrBot 多模态 Provider 提取结构化 Tags、构图、角色候选和置信度。
- 单角色语义换角：从图片或完整 Tags 中移除原角色身份，保留服装、姿势、构图、背景和风格，再以目标 LoRA 或纯语义 Tags 重建整张图。
- LoRA 实时刷新：查询、保存组合、换角和提交任务前读取 LoRA Manager 与 ComfyUI 当前实际可加载清单。
- LoRA 管理：搜索、Civitai 元数据、语义建档、中英文别名、人工审核、组合预设、下载与受控删除。
- 模型管理：实时读取并切换 Anima UNET；工作流 manifest 决定实际节点绑定。
- 两套管理页面：AstrBot 原生 `plugin-page` 与可选的独立端口 WebUI，共用同一套后端能力。
- 任务与日志：记录脱敏的阶段、状态、耗时、重试和错误，不把完整提示词、图片路径或 Provider 原始回复写进任务时间线。

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

六条新管线的当前模板明确引用下列文件名。使用不同 UNET 时，优先通过 `/模型列表` 与 `/模型切换` 写入运行配置；更换 CLIP、VAE 或工作流拓扑时，需要同步检查 API 工作流以及 manifest 中的节点绑定。兼容工作流与 `docs/workflows/` 依赖检查资产可能保留不同的历史模型名，应按各自文件内容单独核对，不能把下表视为整个仓库所有 JSON 的统一模型声明。

| 类型 | 内置文件名 |
| --- | --- |
| UNET | `miaomiaoHarem_anima8Step10.safetensors` |
| CLIP | `qwen_3_06b_base.safetensors` |
| VAE | `qwen_image_vae.safetensors` |

插件不会自动下载缺失的 UNET、CLIP、VAE、LoRA 或自定义节点。

### ComfyUI 自定义节点

六条管线使用的关键非核心节点如下：

| 能力 | 必需节点类 |
| --- | --- |
| Anima 动态 LoRA | `Lora Loader (LoraManager)`，来自 ComfyUI-Lora-Manager |
| RTX 生图后放大 / 独立放大 | `RTXVideoSuperResolution`，工作流记录的节点包标识为 `comfyui_nvidia_rtx_nodes` |
| 迭代放大 | `PixelKSampleUpscalerProvider`、`IterativeImageUpscale`、`ColorMatch` |
| Quick 重绘 | `InpaintCropImproved`、`InpaintStitchImproved` |
| LanPaint | `LanPaint_KSampler`、`LanPaint_MaskBlend` |

RTX 两条路径还需要满足 NVIDIA RTX 节点上游对显卡、驱动和运行环境的要求；没有该环境时可使用 `base`，或在迭代节点可用时选择 `iterative`。

可先把 [docs/workflows/导入Comfy工作流用下载插件用.json](docs/workflows/导入Comfy工作流用下载插件用.json) 导入 ComfyUI，让 ComfyUI Manager 检查基础 Anima / LoRA Manager / RTX 依赖。迭代放大、Quick 与 LanPaint 还应按上表逐项确认节点类是否注册；管理页面的“检查六管线依赖”和 ComfyUI 报出的缺失 `class_type` 才是当前实例的最终依据。各节点仓库名称可能随上游调整。

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
8. 先执行 `/anima ping`，再在管理页面点击“检查六管线依赖”。
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
```

- `/画图` 使用 QQ 合并转发发送结果。
- `/画图no` 直接发送图片。
- 两个命令都跳过 LLM，输入应是可直接用于 Anima 的 Tags。
- `--preset` 接受 LoRA 组合的稳定序号或精确名称；名称含空格时请加引号。

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
| `--llm` | 强制使用绘图导演 |
| `--raw` / `--no-llm` | 直接使用输入 Tags |
| `--preset "风格001"` | 使用一个 LoRA 组合 |

示例：

```text
/anima draw 她在雨夜回头看向镜头 --pipeline rtx --seed 123
/anima draw 1girl, white hair, portrait --raw --pipeline base --preset 风格001
/anima prompt 一名少女站在海边，夕阳逆光
```

### LLM 回复自动出图

开启 `enable_llm_pic_trigger` 后，普通角色扮演或对话模型可以用控制标签触发图片：

```xml
<pic prompt="1girl, close-up, rain, blue eyes" pipeline="rtx" negative="text, watermark">
```

明确的遮罩重绘请求可使用：

```xml
<edit prompt="red evening dress, detailed fabric" mode="quick" negative="school uniform">
```

`<pic>` 与 `<edit>` 互斥；`<think>...</think>` 中的标签不会执行。插件还会检查真实图片、遮罩、权限、风控、管线和 LoRA 清单，模型输出并不直接获得任意工作流控制权。

## 图片反推与独立 RTX 放大

把图片与命令放在同一条消息中，或回复一张图片后发送：

```text
/反推 重点分析构图和光线
/反推画图 保持构图，改成红色礼服，使用RTX放大
/放大 2
```

- `/反推` 只返回经过结构校验的 Tags、负面词、构图、描述、角色候选和置信度。
- `/反推画图` 先反推可观察事实，再交给绘图导演和所选 Anima 管线重新生成。它不是像素保真的图生图。
- `/放大` 只执行独立 RTX 工作流，不加载 Anima UNET。倍率范围为 `1` 到 `4`，留空使用 `rtx_scale`。
- 插件只读取用户本条消息或明确引用消息中的图片，不接受命令文本里的任意图片 URL。

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

普通“画某角色穿新衣”仍属于文生图；只有明确提到遮罩、蒙版、白色 / 透明区域或 inpaint 时，才会进入局部重绘。

## 单角色语义换角

语义换角会重新生成整张图，只把角色身份从 A 改为 B，并尽量保留衣服、姿势、动作、表情、构图、背景、光线、画风和非角色 LoRA。它不是人脸替换、像素级编辑或局部重绘。

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
- 绘图 Provider 生成数量受限、只描述身份与稳定外观的英文普通 Tags。
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
/lora组合保存 <角色|风格|混合|auto> <名称|数字|auto> <LoRA串> [--trigger "触发词"] [--description "说明"]
/保存风格 <名称|数字> <LoRA串> [--trigger "触发词"] [--description "说明"]
/lora组合删除 <序号|名称>
```

- `/lora刷新` 触发 Manager 扫描并立即更新 LLM 可查询清单。
- `/lora下载` 只接受配置允许的 Civitai HTTPS 主机；下载后会尝试补抓元数据并刷新清单。文件下载成功而后处理失败时会报告“部分成功”。
- 组合保存会解析成最新精确文件名并做数量、分类和重复校验。同名保存表示覆盖。
- `/保存风格 001 ...` 会规范为 `风格001`。开启 `auto_reload_after_style_save` 时，画师 / 风格组合持久化成功后会延迟重载插件。
- 管理页面可以为 LoRA 建立带来源和置信度的角色 / 作品 / 风格档案，并允许人工审核别名；人工事实优先于 LLM 推断。
- 可选 Embedding / Rerank 只帮助候选召回和排序，不能替代最终的真实文件确认。

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
- “检查六管线依赖”，分别验证三条生图、独立 RTX、Quick 和 LanPaint。
- UNET 实时清单与切换。
- LoRA 搜索、元数据获取、语义建档、人工审核、组合、下载与受控删除。
- 环境配置档案；档案不包含密码、Token、Provider 提示词、权限和风控设置。
- 持久任务中心、阶段时间线和脱敏日志控制台。
- `纸感工坊`、`铅灰编辑部`、`墨夜控制室` 三套本地主题。

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

内置服务使用 HTTP，不自行提供 TLS。不要把 6198 端口直接暴露到公网，也不要让登录凭据或会话经过不可信网络。确需远程访问时，应使用可信 VPN，或由你自己的反向代理终止 HTTPS 并完成认证。

## 安全与权限

- 图片输入有格式、文件大小和像素总量限制；临时图片在任务结束后清理。
- 图片中文字、二维码和提示注入都按不可信视觉内容处理，不会变成系统命令。
- `/反推`、`/放大`、`/重绘` 和图片换角只读取本条或明确引用的图片。
- 重绘必须有真实遮罩；生图与重绘控制标签互斥。
- LoRA / UNET 模型删除要求最新清单中的精确名称和二次确认；浏览器只提交精确名与确认名，实际文件路径由后端根据 Manager 清单解析。
- `lora_download_allowed_hosts` 应只保留可信 Civitai 官方域名；不要放开任意下载主机。
- `unet_lan_only` 与 `lora_lan_only` 建议保持开启，避免清单请求访问公网、携带 URL 凭据或跟随不可信重定向。
- 群白名单、全局锁定、用户冷却和 `none|lite|full` 词库策略在最终提示词提交前仍会执行。
- 管理员忽略冷却、白名单或违禁词是独立配置；“忽略违禁词”默认应保持关闭。
- 默认取消只移除尚在 ComfyUI 队列中的任务。`allow_global_interrupt=true` 可能中断 ComfyUI 当前全局任务，只适合不与其他用户或程序共享的实例。

## 常见问题

### WebUI 为什么只看到三个工作流？

这是预期行为。下拉框只选择 `base`、`rtx`、`iterative` 三条文生图管线。独立 RTX 用 `/放大`，Quick / LanPaint 用 `/重绘`。点击“检查六管线依赖”可以查看全部六项。

### “检查六管线依赖”有项目不可用

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

确认原图和遮罩尺寸完全一致；白色或透明区域是重绘区域，纯黑遮罩会被视为空。只发一张图片时，它必须是带透明区域的 PNG。

### 连接 `127.0.0.1` 失败

AstrBot 与 ComfyUI 很可能不在同一个网络命名空间。Docker 部署请使用宿主机地址、容器服务名或同网络地址，并确认反向代理允许插件所需的 HTTP 接口。

### `/画图` 合并转发失败

确认平台是 aiocqhttp / NapCat，且 OneBot v11 合并转发可用。可先使用 `/画图no` 判断生成链路本身是否正常。

### 取消后显卡仍在运行

默认取消只停止插件等待并删除排队项，不一定中断已经开始的 ComfyUI 任务。除非 ComfyUI 是独占实例，否则不要开启全局中断。

## 数据、升级与排查资料

运行时语义索引、任务记录、缓存、下载状态和本地配置保存在插件数据目录，不应提交到源码仓库。升级前建议备份 AstrBot 插件配置、数据目录、自定义工作流与人工 LoRA 别名。

排查问题时请同时提供：

- AstrBot 插件日志中的错误码和阶段。
- “检查六管线依赖”的对应项目结果。
- ComfyUI 运行同一 API 工作流时的节点错误。
- 是否使用 Docker / 反向代理，以及 AstrBot 访问的 `comfyui_url`。
- 相关 LoRA 的精确文件名和 `/lora刷新` 结果；不要提供服务器绝对路径、密码或 Token。

## 许可证

仓库当前未附带明确的 `LICENSE` 文件，许可条款仍待项目作者确认。在明确许可证发布前，不应默认本项目允许复制、修改、再分发或商用。

ComfyUI、自定义节点、模型、LoRA、Civitai 资源及其他第三方内容分别受其各自许可证和使用条款约束；使用者需要自行确认授权范围。
