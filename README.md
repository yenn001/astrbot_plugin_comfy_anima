# AstrBot Comfy Anima 插件

> 正式版：v1.1.4

面向 aiocqhttp / NapCat QQ、并针对随包附带的 Anima 工作流专门适配的 ComfyUI 绘图插件。支持自然语言 LLM 分镜、局域网 LoRA 查询工具、动态 LoRA 注入、普通 LLM 回复中的 `<pic>` 标签自动出图、QQ 合并转发和群级风控。

## 功能

- 用户发送“帮我画一个……”时，插件调用后台选择的 AstrBot 聊天模型，把自然语言导演为高收敛英文 Danbooru Tags，再提交 ComfyUI。
- LLM 可自行调用 `list_anima_loras`，把 ComfyUI 实际可加载列表与 ComfyUI-Lora-Manager 元数据合并，搜索角色、画风、触发词和说明，并使用实际存在的名称。
- LLM 可调用 `list_anima_lora_presets` 取得完整风格底座栈；默认使用 `风格001`，也可选择其他 `风格NNN` 或自定义风格名称。
- 风格底座与角色 LoRA 分工明确：风格栈负责画质、美感、画师、皮肤、背景等，明确角色则由 LLM 再调用 `list_anima_loras` 独立查询并追加。
- 支持管理员通过 Civitai 模型页 URL 下载 LoRA；完成后自动补抓元数据并刷新 LLM 可查询清单。
- 保存或覆盖画师/风格组合后，会先返回保存结果，再延迟约 2 秒自动重载本插件，使新风格立即按持久化配置重新初始化。
- 提供 Anima UNET 模型实时列表与切换；切换前强制重新读取局域网 ComfyUI 最新完整模型清单。
- 所有 LoRA 查询、组合管理、下载及实际出图都经过强制刷新门禁；Manager 扫描或实际可加载清单读取失败时停止后续操作。
- 每次生图会把各来源先解析成最新精确 LoRA 文件再合并；保存的风格/混合预设权重不可被 LLM 静默覆盖，同名 basename 会被阻止并要求使用完整文件夹路径。
- 风格与功能 LoRA 自动使用 Manager/Civitai 的明确触发词；角色 LoRA 只补能与角色身份确证匹配的主触发词，不会把默认服装、发色等整包回灌到正面提示词。
- AstrBot 原生 `plugin-page` 可直接管理核心绘图参数、LLM 导演、权限、LoRA、组合预设、UNET、任务与日志；独立端口 Web UI 继续作为可选的局域网入口。
- 思考模型下拉框同时读取 AstrBot 已保存配置和当前已加载实例；LoRA 清单利用 Civitai 标题、触发词与标签建立角色、作品和中英文别名归档，并在多候选时拒绝模糊猜测。
- Web UI 支持单项、批量与全库 Civitai 元数据获取、分类筛选、目录指纹变化检测、绘图导演 LLM 多选建档和命名环境配置档案切换。
- 插件专属持久日志控制台支持凭据脱敏；LoRA 页面明确区分资料与建档状态；WebUI 可在纸感工坊、铅灰编辑部、墨夜控制室三套主题间即时切换。
- 逐 LoRA 语义建档会独立调用、校验、最多两次结构修复并立即落盘，支持部分成功、人工审核优先、完整安全资料档案、持久任务时间线和插件重载后恢复。实时 Manager + ComfyUI 可加载清单始终是唯一文件存在性依据。
- 详情身份始终以刚刷新的 ComfyUI 可加载记录为准，SHA-256 作为不可变关联依据；目录指纹在应用 AI 别名覆盖前固化，避免刚完成的档案被误判为过期。
- 支持加速/采样、画质增强、细节修复、构图/姿势、光影/色彩、背景/环境、服装/概念七类功能 LoRA，并严格隔离 UNET、checkpoint 等非 LoRA 资产。
- 任务时间线支持升降序和每页 10-200 条并逐阶段同步持久控制台；风格名称可省略尾部括号备注；绘图导演支持换装冲突处理和可选负面提示词。
- 后台可自由创建、命名、启停和保存 LoRA 串组合；也可通过管理员命令即时创建、覆盖、列出或删除，无需重载插件。
- `<lora:名称:权重>` 不会作为普通文本送入提示词节点，而是注入工作流的 LoraManager 节点 `462`。
- 为普通角色扮演对话注入可编辑的绘图 System Prompt；LLM 回复包含 `<pic prompt="...">` 时自动替换为图片。
- 自动删除 `<think>...</think>` 与 `<pic>` 控制标签，不把思考内容发到 QQ。
- `/画图` 使用 NapCat/OneBot v11 合并转发发送图片；`/画图no` 直接发送图片。
- `/反推` 使用 AstrBot 多模态 Provider 分析用户明确发送或引用的图片，返回结构化 Anima Tags、构图和置信度；`/反推画图` 可继续交给绘图导演并生成图片。
- 反推 JSON 本地格式整理器和多模态修复重试均可独立开关；即使关闭整理，`<think>` 隔离、深度限制、非有限数拒绝和必填字段校验仍强制执行。
- `/放大 [倍率]` 将用户发送或引用的图片上传到 ComfyUI，通过独立 RTX 工作流处理；Anima 正常生图也可在同一工作流内直接串联 RTX。
- 每次返回生图或 RTX 结果时附带实际处理耗时与 ComfyUI 报告的 GPU 型号。
- 新版内置 `anima_v2_api.json` 使用独立工作流档案映射正面、负面、UNET、LoRA、采样器、分辨率和输出节点；旧 `anima_api.json` 保留为回退，并已把全部文本编码节点接入 LoRA 后的 CLIP。
- 管理员可以不重载插件地列出和切换工作流。
- 支持 `none`、`lite`、`full` 群级违禁词策略、群白名单、全局锁定及独立管理员特权。

## 环境要求

1. AstrBot 通过 aiocqhttp 连接 NapCat。
2. AstrBot 能访问 ComfyUI 的 `/prompt`、`/history`、`/view`、`/queue`、`/system_stats` 和 `/upload/image`。
3. ComfyUI 已安装工作流所需的模型、LoRA、ComfyUI-Lora-Manager 与 `RTXVideoSuperResolution` 节点。
4. 建议 AstrBot v4.26.1 或更高版本，以使用原生 `plugin-page`；旧版本仍可使用插件配置页及可选的独立端口 Web UI。

如果 AstrBot 在 Docker 中，`127.0.0.1` 指向 AstrBot 容器自身。请改填宿主机地址、ComfyUI 容器服务名或同网络可访问地址。

## 安装与首次配置

1. 在 ComfyUI 中导入 [插件安装工作流](docs/workflows/导入Comfy工作流用下载插件用.json)，按提示安装缺失的自定义节点；如有缺失的模型或 LoRA，也请一并准备。
2. 将整个 `astrbot_plugin_comfy_anima` 目录放入 AstrBot 插件目录。
3. 在管理面板重载插件；AstrBot v4.26.1+ 会自动发现“工坊控制台”插件 Page。
4. 设置 `comfyui_url`。
5. 在“绘图思考模型”中选择一个已配置的聊天模型。
6. 已安装 ComfyUI-Lora-Manager 时保持 `enable_lora_manager=true`；插件会自动访问 `comfyui_url/api/lm/loras`，同时保留 `object_info` 回退。
7. 建议保持 `strict_lora_validation=true`，这样后台组合在出图时、管理员命令在保存时都会核对 ComfyUI 实际可加载名称。
8. 需要通过 QQ 下载 Civitai LoRA 时开启 `enable_lora_download`，按网络环境设置 `lora_download_timeout`，并保持 `lora_download_allowed_hosts` 仅包含受信任的 Civitai 官方域名。
9. 先执行 `/anima ping`，再用 `/画图no 1girl, white hair, portrait` 测试。

`auto_draw_system_prompt` 留空时使用插件附带的 `prompts/director_reference.txt`。后台填写的自定义 System Prompt 会立即用于普通对话注入，并作为人设/风格偏好叠加到自然语言分镜；插件的实时 LoRA、输出协议和换装安全约束不会再被自定义内容覆盖。自定义内容仍必须要求需要绘图时输出合法的 `<pic prompt="英文 tags">`，没有标签就不会自动触发图片。

## AstrBot 原生 plugin-page

AstrBot v4.26.1+ 会自动发现 `pages/control/index.html`。在插件详情页打开“工坊控制台”，或访问：

```text
/plugin-page/astrbot_plugin_comfy_anima/control
```

原生页面复用与 6198 面板相同的业务接口和三套主题，但认证由 AstrBot Dashboard 负责：页面位于受限 iframe 中，只能通过官方 Bridge 调用带 `plugin` 权限的扩展 API，不读取 Dashboard Cookie、Token 或父页面 DOM，也不需要再次登录。危险操作使用页面内确认框；插件自动重载后会通过 Bridge 重新连接，不会刷新带短期资源令牌的 iframe。即使 `enable_web_ui=false`，原生页面仍可使用。

页面内的主题与自动建档偏好在允许存储时保存在当前页面环境；若浏览器阻止 sandbox iframe 的 `localStorage`，会安全退化为本次页面会话内记忆，不影响管理功能。

## 独立端口 Web UI

插件可以在 AstrBot 之外启动一个轻量级局域网管理面板。默认关闭，启用前必须设置登录密码：

```text
enable_web_ui=true
web_ui_host=0.0.0.0
web_ui_port=6198
web_ui_username=admin
web_ui_password=至少8位且不要与其他账号共用
```

启动后使用浏览器访问 `http://AstrBot服务器IP:6198`。面板包含：

- 运行概览、ComfyUI 地址、默认分辨率、当前风格和 UNET 状态。
- 核心绘图参数、LLM 绘图导演 System Prompt、权限与风控设置；思考模型下拉框直接读取 AstrBot 已保存 Chat Provider，并标明当前是否已加载可用。
- 强制刷新后的 LoRA 搜索、Civitai URL 下载及元数据刷新；同时展示角色、画师/风格、七类功能型、混合、未分类、作品归档、角色名和可搜索别名。
- 每个 LoRA 均可即时执行 LoRA Manager 的“从 Civitai 获取元数据”；支持单选、多选和全库批量操作，完成后再次刷新真实可加载清单。
- 使用目录指纹检测新增、修改和删除；可让所选绘图导演 Provider 完整阅读模型说明、全部触发词、标签与别名，并归入角色、画师/风格、混合或未分类。支持单项、多选、全选及仅归档变化项。
- LoRA 表格显示 `资料就绪 / 建档中 / 可搜索 / 待确认 / 失败 / 资料变化` 状态；分类和建档状态可交叉筛选，`unclassified` 不再被误算成完成。
- “完整档案”会在再次强制刷新后展示模型与版本说明、全部触发词、标签、作者、许可、示例图安全生成参数、使用建议、文件/版本状态、元数据健康和字段来源；不向浏览器返回服务器绝对路径。
- 每个 LoRA 支持人工审核角色名、作品名、画师/风格名和自然语言别名；人工事实优先于 LLM 推断，且只写逻辑索引，不移动或改名实际文件。
- 仅删除 LoRA 时只同步逻辑索引，不会误触发全库 LLM 重归档。
- 可把 ComfyUI 地址、工作流、节点映射、UNET 和默认分辨率保存为命名环境档案并来回切换；密码、Token、Provider、提示词、权限与风控不会进入档案。
- 角色、画师/风格和混合 LoRA 串的创建、覆盖、校验与删除。
- 实时读取并切换当前工作流档案声明的 UNET 模型（Anima V2 为节点 `44`）。
- 显示当前工作流档案及各采样器模板 Steps / CFG / Denoise，并允许把采样步数设为 `0`（跟随模板）或 `1–100`（全局覆盖）。
- 安全删除 LoRA 与非当前 UNET：页面只提交精确名称和二次确认，不接收文件路径；后端强制刷新最新 Manager/ComfyUI 清单后解析路径，并在删除后再次刷新。
- 任务中心持久保存 run_id、状态、进度、当前阶段、逐项重试、成功、失败和取消事件；阶段时间线默认最新在上，可切换升序/降序和每页 10/20/50/100/200 条，页面刷新或插件重载后仍可恢复。
- 专属运行控制台每约 1.2 秒读取一次本插件持久日志视图，支持级别、模块和关键词筛选、暂停、跟随最新、复制与清空；任务创建、启动、逐阶段、重试、成功/失败/取消和收尾都会同步写入具体日志，重复等待心跳会折叠但时间线保留完整事件。
- 三套主题按当前浏览器独立记忆，无需保存配置或重载插件：`纸感工坊`、`铅灰编辑部`、`墨夜控制室`。

安全约束：

- 只允许绑定 `0.0.0.0`、回环地址或私有局域网 IP，不接受公网 IP 或域名。
- 密码不会通过 Web API 回显；设置页密码框留空表示保持原密码。
- 使用 HttpOnly、SameSite 登录 Cookie、CSRF Token、登录频率限制和安全响应头。
- 配置保存、组合修改和 UNET 切换后会自动重载当前插件；重载后需要重新登录。
- LoRA 页面上的每一次查询、刷新、组合操作和下载都会先执行强制刷新门禁。
- 日志写入 SQLite 持久视图前会遮盖常见 API Key、Token、Bearer、密码、Cookie、Session 和 URL 凭据；任务事件不会保存原始提示词、完整模型回复或思考内容。
- 建议只在可信局域网开放端口；若需要跨公网访问，请在可信反向代理后配置 HTTPS 和额外访问控制。

## 局域网 LoRA 工具

推荐安装 [willmiao/ComfyUI-Lora-Manager](https://github.com/willmiao/ComfyUI-Lora-Manager)。插件会读取：

- 展示名、实际文件路径、目录、基础模型和 SHA-256。
- CivitAI 模型标题、触发词、标签、说明、推荐权重信息和预览地址。
- 从标题、文件名、作品名和触发词生成的角色中英文别名；已知作品会归一为中英双语逻辑归档，例如 `鸣潮 / Wuthering Waves`、`绝区零 / Zenless Zone Zero`。
- 收藏状态、备注及使用提示。
- ComfyUI `/object_info` 中明确属于 LoRA 输入字段的真实可加载名称。UNET、checkpoint、diffusion model、embedding、VAE 与 ControlNet 不会混入 LoRA 清单；Manager 元信息只负责补充，不能替代 ComfyUI 的可加载证据。
- 可选启用 AstrBot Embedding + Rerank 混合搜索：向量只负责在本次刷新后的真实 LoRA 集合中召回与排序，生成前仍会再次刷新并校验精确文件名。
- WebUI 可分别选择绘图导演 Chat Provider、图片反推多模态 Chat Provider、Embedding Provider 与 Rerank Provider；列表来自 AstrBot 已保存配置与 Provider Source 的安全合并结果。

`list_anima_loras` 每次调用都会强制让 LoRA Manager 扫描磁盘、分页读取完整最新索引，并同时读取 ComfyUI 实际可加载清单；`refresh` 参数仅为旧提示词兼容。强制刷新会绕过 `lora_manager_scan_interval`，失败时不会回退到旧缓存继续绘图。

为避免删除或重命名 LoRA 后仍选中旧记录，Manager-only 元数据不会再被视为可加载文件；只有同时出现在 ComfyUI 实际清单中的名称才会提供给 LLM。每次实际构建工作流前还会再次执行同样的强制刷新与严格校验。

角色检索无需输入完整文件名。可以使用角色名、作品名、Civitai 触发词或部分名称，例如 `达妮娅`、`denia`、`鸣潮达妮娅`、`绝区零 sunna`、`拉米尔`、`remielle`。只有唯一高置信候选才会自动解析为真实文件名；若同一角色存在多个服装或版本 LoRA，插件会要求提供更完整名称，不会自行猜选。

若自动元信息仍缺少中文名或常用简称，可在 AstrBot 配置或端口 Web UI 的 `lora_alias_rules` 中人工补充，每行格式如下：

```text
black deniav1-2=达妮娅,denia,鸣潮达妮娅
```

这些分类和别名只作用于插件索引、搜索与展示，不会移动、重命名或复制实际 LoRA 文件。

### LoRA 语义建档

Web UI 会先对最新可加载目录计算稳定语义指纹。文件名、SHA-256、Civitai 描述、全部触发词、标签、角色/作品线索或别名发生变化时会标记为待更新；目录不变时“仅建档变化项”不会重复调用 LLM。

当前建档流程不再把多个 LoRA 塞进一个批量回复。每个 LoRA 都会独立执行以下步骤：

1. 再次刷新 LoRA Manager，并与 ComfyUI 实际可加载清单取交集。
2. 聚合 Manager 列表、metadata、model-description、usage-tips、模型/版本双描述、全部触发词、标签、作者、许可和示例图安全参数。
3. 让 `prompt_llm_provider_id` 所选绘图导演只返回一个带精确 `asset_id` 的 JSON 档案。
4. 验证身份、分类结构、证据来源和置信度；格式错误时把验证错误反馈给模型，最多自动修复两次。
5. 单项成功立即原子写入 `lora_semantic_v2.json`；单项失败写入 `failed` 状态并继续处理后续 LoRA，不回滚已经成功的结果。

高置信且结构完整的记录进入 `searchable`；低置信、证据不足或 `unclassified` 进入 `review_needed`。分类包括 `character`、`artist_style`、七类功能型、`mixed` 与 `unclassified`。人工审核事实使用 `manual` 来源并具有最高优先级。每个事实保留 `observed / derived / llm_inferred / manual` 来源、置信度和证据，建档摘要也会持久保存。

后台运行记录保存在 `task_events.sqlite3`，包括阶段、项目、尝试次数、心跳、进度和安全错误码；不会保存原始 Prompt、完整 LLM 回复、思考过程、API Key 或 Cookie。插件重载会把未完成任务标记为 `interrupted`。

语义建档专用 System Prompt 位于 `prompts/lora_semantic_analysis.txt`。它与绘图用 `<图像生成要求>` 分离，允许整理可靠的中英文译名、罗马音和作品简称，同时要求身份一致、证据可追踪。旧 `lora_archive.json` 只用于安全迁移和回滚兼容，不再是新建档主索引。

配置项 `lora_catalog_url` 支持以下形式：

```text
http://192.168.1.50:8188
http://192.168.1.50:8188/object_info
http://192.168.1.50:8000/loras.json
http://192.168.1.50:8000/loras.txt
http://192.168.1.50:8000/loras/
```

- 地址仅填写 IP 和端口时，插件自动追加 `/object_info`，从 ComfyUI 节点信息提取 LoRA 文件名。
- JSON 可使用字符串列表，或 `{ "loras": [{"name": "...", "trigger_words": [...]}] }`。
- 文本清单每行一个文件；也支持 `名称|触发词1,触发词2|描述`。
- HTTP 目录页会读取指向 `.safetensors`、`.pt`、`.ckpt` 或 `.bin` 的链接。
- 默认只允许私有、回环或链路本地 IP，禁止公网地址、域名、URL 凭据和重定向。
- LLM 独立查询角色时通常选择 1 个最匹配的角色 LoRA；完整风格底座按预设整体使用，不应按这一建议截断。
- `strict_lora_validation` 开启时，任何不在清单中的 LoRA 都会在提交 ComfyUI 前被拒绝。
- `dynamic_lora_mode=append` 会保留工作流节点 462 中已有的基础画质 LoRA；`replace` 则只保留本次动态选择。

提示词示例：

```text
<lora:black deniav1-2:1.00>, 1girl, black denia \(wuthering waves\), cowboy shot, from side
```

插件会移除前面的 LoRA 标签，将它写入当前工作流档案声明的 LoRA 节点（Anima V2 为节点 `462`）的 `text` 与 `loras.__value__`；剩余英文 tags 写入档案声明的正面提示词节点（Anima V2 为节点 `11`）。旧 `anima_api.json` 回退工作流仍使用内容节点 `210`。

## Civitai LoRA 下载

管理员可以直接发送 Civitai 模型页 URL：

```text
/lora下载 https://civitai.com/models/123456/example-model
/lora下载 https://civitai.red/models/123456/example-model?modelVersionId=789012
```

下载规则：

- 仅接受 `https` 模型页 URL，支持的站点为 `civitai.com` 与 `civitai.red`；不接受 HTTP、其他域名、文件直链或带 URL 凭据的地址。
- URL 带有 `modelVersionId` 时下载指定版本；没有 `modelVersionId` 时自动选择该模型最新的可用版本。
- LoRA 文件下载完成后，插件会再次抓取对应 Civitai 元数据，并刷新 LoRA Manager/LLM 可查询清单，无需手动执行 `/lora刷新`。
- 如果文件已经成功下载，但后续 Civitai 元数据抓取或清单刷新失败，命令会明确返回“部分成功”；这表示 LoRA 文件已落盘，仅元数据或即时索引尚未完整更新，不会误报为完全失败。
- 此命令仅限 AstrBot 管理员使用，并受 `enable_lora_download` 开关控制。

相关配置：

- `enable_lora_download`：是否开放 `/lora下载` 管理命令；不需要远程下载时建议关闭。
- `lora_download_timeout`：单次 Civitai 查询与下载允许等待的超时时间，请根据 LoRA 文件大小和外网速度设置。
- `lora_download_allowed_hosts`：下载 URL 主机白名单。默认应保留 `civitai.com`、`civitai.red`；该配置用于显式收紧可信主机，不代表插件支持其他站点的页面格式。

## Anima UNET 模型切换

Anima V2 的主模型由档案映射到节点 `44` 的 `UNETLoader.unet_name`，不使用 CheckpointLoader；旧工作流仍按各自档案或回退配置解析。管理员命令：

```text
/模型列表
/模型切换 2
/模型切换 miaomiaoHarem_anima13.safetensors
```

- `/模型列表` 每次实时读取 `comfyui_url/object_info/UNETLoader`，不会使用旧缓存。
- `/模型切换` 在解析序号或名称之前会再次读取全部最新数据，新放入 ComfyUI UNET 目录的模型可立即被发现。
- 切换结果保存到 `unet_model_name`，并写入当前工作流档案声明的 UNET 输入；Anima V2 使用节点 `44` 的 `unet_name`，随后自动重载插件。
- `unet_loader_node_id` 默认 `429`，仅作为没有 UNET 档案绑定的旧工作流回退；`unet_model_input_name` 默认 `unet_name`。

## LoRA 组合预设与风格底座

管理面板的 `lora_presets` 使用 AstrBot `template_list`，可新增三类模板：

- `角色 LoRA 组合`：角色身份、服装或角色变体。
- `画师/风格 LoRA 组合`：完整风格底座，建议成套保存画质、美感、画师、皮肤、背景等 LoRA。
- `混合 LoRA 组合`：角色与画师/风格 LoRA 的成套组合。

自然语言绘图的标准约定是：`风格NNN` 只保存完整风格底座，角色 LoRA 不放进风格串。角色由 LLM 根据画面人物另行查询，这样同一个 `风格001` 可以自由搭配达妮娅、黑娅或其他角色。

每个组合可填写名称、LoRA 串、trigger words、说明和启用状态。`loras` 每行使用 `精确名称=权重`。随包默认的 `风格001` 为：

```text
(画质)anima-highres-aesthetic-boost=0.50
(美感细节)anima-rl-v0.1=0.40
anima-base-1-masterpiece-v51=0.50
748cm_v2_anima=0.30
hanaru_epoch24=0.31
nekoya_v1_epoch21=0.30
real skin.baka.v1-000010=0.65
(写真背景)anima3-photo-background-v3=0.30
```

- 默认风格名称是精确的 `风格001`。快捷保存时填写数字 `001` 会规范为 `风格001`，前导零会保留；也可直接填写完整名称。
- 风格显示名可以附加尾部备注，例如 `风格2（凛然）`；自然语言使用 `风格2` 时会解析到该完整名称。若多个预设共享同一省略备注简称，插件会要求使用完整名称，不会猜选。
- 同名保存采用覆盖更新：再次保存 `风格001` 会替换原有 `风格001`，不会创建两个同名组合。
- `风格001` 及其他 `风格NNN` 中不得放入角色 LoRA；角色 LoRA 应保持在 LoRA Manager 清单中，供 `list_anima_loras` 按角色独立查询。
- `trigger_words` 会在应用组合时自动追加到正面提示词，LoRA tags 则注入节点 `462`。
- 关闭 `enabled` 后，该组合不会出现在 LLM 查询结果中，也不能被绘图指令选择。
- 单个组合数量受 `max_preset_loras` 限制；组合、提示词内 LoRA 与其他动态 LoRA 的去重后总数受 `max_total_dynamic_loras` 限制。
- 管理员查看、保存或删除 LoRA 组合前都会强制刷新 Manager；后台录入的组合会在实际出图前再次刷新并严格校验。任何已经删除或改名的 LoRA 都会在提交 ComfyUI 前被拒绝。
- 应用任意画师/风格组合时，插件会自动以 `replace` 模式替换节点 `462` 的旧风格栈，再把角色 LoRA 追加在后；无需手动切换全局 `dynamic_lora_mode`。

自然语言示例：

```text
请用风格001帮我画一名站在雨夜车站的少女
用风格001画达妮娅，分辨率832x1216
用“水墨电影感”这个组合画一个山顶日出场景
```

LLM 的处理顺序如下：

1. 用户指定风格时查询该精确名称；未指定时默认查询 `风格001`。
2. 使用 `list_anima_lora_presets` 返回的完整风格 LoRA 栈及 trigger words。
3. 如果画面包含明确角色，再用 `list_anima_loras` 查询角色，把角色 LoRA 和 trigger words 追加到风格栈之后。
4. 任何一步都只使用工具真实结果，不根据风格名或角色名编造 LoRA。

因此“用风格001画达妮娅”会先查询 `风格001` 的完整底座，再独立查询 `denia` 角色 LoRA，最终两者同时生效；达妮娅 LoRA 不会被保存进 `风格001`。

## 使用方式

### 自然语言绘图

直接发送普通 QQ 消息：

```text
帮我画一个赛博朋克风格的猫，在下雨的东京街头
用风格001画达妮娅站在海边，分辨率832x1216
```

插件会使用所选模型分析镜头、优化英文提示词并生成图片。自然语言中的 `分辨率832x1216`、`分辨率 832x1216` 和 `分辨率 832×1216` 会作为生成参数写入分辨率节点，不会混进正面提示词；未指定时默认使用 `832x1216`。

### 直接 Tag 指令

```text
/画图 1girl, white hair, blue eyes, rain, neon city, cinematic lighting
/画图no 1girl, black dress, portrait, looking at viewer
/画图no 1girl, white hair, portrait --preset 风格001
/画图 1girl, red dress, night city --preset "水墨电影感"
```

- `/画图`：以 QQ 合并转发发送，适合减少刷屏。
- `/画图no`：直接发送图片，更简洁。
- 两个指令都绕过 LLM，输入内容直接写入工作流提示词节点。
- 两个指令都支持 `--preset <序号|名称>`（别名 `--lora-preset`）；包含空格的自定义名称需要加引号。

### 图片反推与 RTX 放大

把图片和命令放在同一条 QQ 消息中，或回复一张图片后发送：

```text
/反推 重点分析构图和光影
/反推画图 保持构图，换成红色礼服，用风格2
/放大 2
```

- `/反推` 只返回结构化 Tags、负面词、构图、画面说明、候选身份和置信度。
- `/反推画图` 会把可靠的可观察事实交给绘图导演，再经过实时 LoRA 查询与 Anima 工作流生成；低置信角色身份不会自动当成事实。
- `enable_reverse_json_formatter=true` 时，本地整理器兼容代码围栏、JSON 前后说明、尾逗号和单引号字典；关闭后只接受一个完整、双引号、无围栏的严格 JSON 对象。
- `enable_reverse_json_repair_retry=true` 时，首次校验失败才会让同一多模态 Provider 重新查看原图并生成一次严格 JSON；关闭后只调用一次并直接返回安全错误。
- `/放大` 不调用生图 UNET，只通过独立 RTX 工作流处理原图；允许倍率范围为 `1–4`，留空使用后台默认值。
- 图片内文字、二维码和指令一律视为不可信视觉内容，不会当作系统指令执行。插件不接受命令文本中的任意图片 URL。

### LLM 回复自动绘图

普通角色扮演回复只要包含以下控制标签就会触发：

```text
<think>这里可以是模型内部的分镜分析</think>
<pic prompt="1girl, close-up, rain, blue eyes, cinematic lighting">
```

换装等确有排除需求时可选：

```text
<pic prompt="1girl, red evening gown, silver hair" negative="school uniform, necktie">
```

插件会移除控制标签，保留标签外的正文，并把图片加入最终 QQ 回复；可选 `negative` 会写入工作流负面节点。绘图导演会先删除角色默认服装正面词、强化目标服装，并仅在元数据有证据时加入少量旧服装负面词；角色身份词不会进入负面提示。`<think>` 内的 `<pic>` 不会触发。

### 高级 Anima 指令

```text
/anima draw <剧情或提示词>
/anima prompt <剧情>
/anima status
/anima cancel
/anima ping
/anima help
```

`/anima draw` 支持：

```text
--negative "bad hands, text"
--seed 123456
--size 1024x1536
--steps 30
--cfg 5
--upscale / --no-upscale
--llm / --raw
--preset "风格001或自定义名称"
```

例如：

```text
/anima draw 她在雨夜回头看向镜头 --preset 风格001
/anima draw 1girl, white hair, portrait --raw --preset "水墨电影感"
```

`--preset` 可使用 `/lora组合列表` 显示的序号或精确名称；每次任务只能选择一个组合。

## 管理指令

以下切换指令仅 AstrBot 管理员可用：

```text
/comfy_ls
/comfy_use <序号> [input_id] [output_id]
/comfy_lock on|off|status
/模型列表
/模型切换 <序号|完整UNET文件名>
/lora刷新
/lora下载 <Civitai模型页URL>
/lora组合列表 [角色|风格|混合]
/lora组合保存 <角色|风格|混合|auto> <名称|数字|auto> <LoRA串> [--trigger "触发词"] [--description "说明"]
/保存风格 <名称|数字> <LoRA串> [--trigger "触发词"] [--description "说明"]
/lora组合删除 <序号|名称>
/违禁级别 none|lite|full
/comfy帮助
```

- `/comfy_ls` 每次重新扫描 `workflow_dir` 下直属的 `.json` 文件。
- `/模型列表` 实时显示局域网 ComfyUI 当前全部 UNET 文件；当前模型会标记为 `✅ 当前`。
- `/模型切换` 切换前强制刷新最新清单，支持列表序号或完整文件名，并优先持久化到当前工作流档案声明的 UNET 节点（Anima V2 为节点 44）。
- `/comfy_use` 按列表序号热切换，并可覆盖提示词输入节点与图片输出节点；不需要重载插件。
- `/comfy_lock on` 开启后仅管理员能绘图。可在配置中关闭此命令入口。
- `/lora刷新` 让 LoRA Manager 重新扫描磁盘，并立即更新 LLM 可查询清单。
- `/lora下载` 从受支持的 Civitai HTTPS 模型页下载 LoRA；未指定 `modelVersionId` 时选择最新版本，下载后自动补抓元数据并刷新清单。文件已下载但元数据或刷新阶段失败时会明确报告“部分成功”。
- `/lora组合列表` 显示全部组合（包含禁用项）及稳定的全局序号，也可按角色、风格或混合分类筛选；筛选后序号不会改变。
- `/lora组合保存` 创建或覆盖同名组合（名称匹配不区分大小写）。分类使用 `auto` 时会依据 LoRA Manager 元数据推断；名称使用数字会规范为 `角色N`、`风格N` 或 `组合N` 并保留前导零，使用 `auto` 会选择下一个可用编号。组合自身数量不得超过单次动态 LoRA 总上限。
- `/保存风格` 是完整风格栈的快捷入口，例如 `/保存风格 001 <LoRA串>`；保存为 `风格001`，同名时直接覆盖。
- 保存的分类为“画师/风格”时，`auto_reload_after_style_save=true` 会在成功持久化后自动重载插件；角色与混合组合不会触发自动重载。
- `/lora组合删除` 按稳定的全局序号或精确名称删除组合，禁用组合也可以删除。
- `/违禁级别` 修改当前 QQ 群的过滤策略并保存配置。
- `/comfy帮助` 查看包含 `/lora下载` 在内的当前可用命令；下载入口是否可用取决于 `enable_lora_download`。

保存示例：

```text
/保存风格 001 <lora:(画质)anima-highres-aesthetic-boost:0.50> <lora:(美感细节)anima-rl-v0.1:0.40> <lora:anima-base-1-masterpiece-v51:0.50> <lora:748cm_v2_anima:0.30> <lora:hanaru_epoch24:0.31> <lora:nekoya_v1_epoch21:0.30> <lora:real skin.baka.v1-000010:0.65> <lora:(写真背景)anima3-photo-background-v3:0.30> --description "默认完整风格底座"
/保存风格 风格001 <lora:你新喜欢的真实LoRA名称:0.70> --description "同名保存，覆盖旧的风格001"
```

示例名称仅表示分类结构，请使用自己的真实 LoRA 名称。风格串中不要加入 `Denia` 等角色 LoRA；角色由 LLM 调用 `list_anima_loras` 动态查询。LoRA 名称必须与 LoRA Manager/ComfyUI 清单中的实际名称一致；开启严格校验后，不存在的名称会被拒绝保存。

## 风控说明

- `lite`：拦截未成年人色情、非自愿性行为、兽交、乱伦等高风险中英文词。
- `full`：包含 Lite，并额外拦截一般露骨色情、重度血腥、自残及毒品词。
- `none`：不进行词库检查，但仍受全局锁定和白名单约束。
- 中文检查会识别简单的空格/标点拆分；英文使用单词边界以减少误判。
- 可分别配置管理员无视冷却、白名单和违禁词；“无视违禁词”默认关闭。
- 群白名单只约束群聊，私聊仍受全局锁定和违禁词策略约束。

## 内置工作流

默认生图工作流为 `workflow/anima_v2_api.json`，独立图片放大工作流为 `workflow/rtx_upscale_api.json`。节点映射以同名 manifest 为唯一真源：正面节点 `11`、负面节点 `12`、UNET 节点 `44`、LoRA Manager 节点 `462`、KSampler 节点 `19`、分辨率节点 `28`、原图输出 `88`、RTX 节点 `552`、RTX 输出 `458`。模板默认分辨率为 `832x1216`，采样参数为 `8 Steps / CFG 5 / Denoise 1`。

旧 `workflow/anima_api.json` 原样保留为兼容回退。它使用旧节点 `210/13/429/437/285/20`，仅在显式切换到该工作流且没有 manifest 绑定时才读取配置中的 legacy 节点字段；新旧节点不会混用。

明确引用的基础模型：

- UNet：`miaomiaoHarem_anima8Step10.safetensors`
- CLIP：`qwen_3_06b_base.safetensors`
- VAE：`qwen_image_vae.safetensors`

Anima V2 通过 `Lora Loader (LoraManager)` 接收插件在每次强制刷新后的动态选择，不再在工作流中固定重复加载某一组角色或风格 LoRA。保存的风格组合与本次角色 LoRA 会在提交前去重并注入一次。

默认工作流使用 `Lora Loader (LoraManager)` 与 `RTXVideoSuperResolution` 等自定义节点。此前会在 `object_info` 注册、但运行时仍依赖可选 `sageattention` Python 包的 `PathchSageAttentionKJ` 已从模板移除，UNET 会直接连接 LoRA Manager。插件不会自动下载缺失模型、LoRA 或自定义节点。

## 取消行为

默认取消只删除尚在 ComfyUI 队列中的任务。运行中的任务可能继续占用显卡，但插件会停止等待。只有 ComfyUI 不与其他用户或程序共用时，才建议开启 `allow_global_interrupt`，因为它会中断 ComfyUI 当前全局任务。

## 常见问题

- 工作流校验失败：在同一 ComfyUI 中手动运行工作流，检查缺失节点、模型和 LoRA。
- 能对话但自然语言不出图：确认已选择绘图思考模型，并检查群白名单、全局锁定和违禁等级。
- 普通角色扮演回复不自动出图：确认 `enable_llm_pic_trigger` 已开启，且最终回复确实包含合法 `<pic prompt="英文 tags">`。
- `/画图` 合并转发失败：确认当前平台为 aiocqhttp/NapCat，并允许 OneBot v11 合并转发。
- 连接 `127.0.0.1` 失败：AstrBot 与 ComfyUI 不在同一主机或容器网络。
- 图片过大：提高 `max_image_size_mb` 或关闭二次放大。
