# AstrBot ComfyAnima 插件 v2.4.1

> 当前版本：**2.4.1**（内部构建 3.1.416）。2.9B 底模已完整支持，角色和风格 LoRA 自动适配变体。

让 AstrBot 里的角色（比如你的达妮娅）真的能“画图”的插件。

接上 ComfyUI + Anima 工作流之后，你只要在 QQ 里跟 Bot 说：

> “帮我画一张达妮娅自拍”
> “我想看娅娅的照片”
> “/画图 风格006 达妮娅”

Bot 就会真的生成图片发回来，而不是用嘴说自己画了。

---

## 最近更新（2.4.1）

这次更新主要解决“时好时坏”和“追画换人”两大问题：

- 🧠 **闲聊出图更懂你**：“检查穿着了！（画出来）”这种一句话能正确出图；说“不要画了”“明天再画”就不会画；
- 👤 **追画不再换人**：“重新画一张没有项链的”——不用再提角色名，自动还是达妮娅；
- 🔄 **2.9B 底模全自动适配**：角色和风格 LoRA 自动切换到 29B 变体，Legacy / 2.9B 来回切也不怕；
- 🏷 **角色认得更准**：就算 LLM 偷懒没在提示词里写角色名，也能按 LoRA 绑定正确挂载；
- 🕐 **出图同步现实时间**：中午聊天图里就是白天光线，晚上自动夜景——提示词里写了时间则以你为准；
- 🧹 **提示词更干净**：内部工具文本（skill / tool_calls）不再泄漏进画面描述；
- 🔎 **报错看得懂**：出问题会明确告诉你是【绘图导演思考模型】还是【图片反推多模态模型】、用的哪个 Provider、什么原因；
- 🤫 **不再刷屏**：普通聊天不会出现“未通过意图判断”提示（只记录在运行控制台日志里）；
- 💾 **设置保存修复**：WebUI 里改的设置终于能存住了（之前会提示保存失败并回滚）。

---

## 它能干嘛

- 🎨 **文生图**：一句话出图，支持风格预设和角色 LoRA；
- 🔁 **改图 / 重绘**：发一张图，让 Bot 按你的要求重新画；
- 👤 **换角色**：保持场景和衣服，把图里角色换成另一个人；
- 🎛 **底图控制**：用姿势 / 深度 / 线稿控制构图；
- 🧠 **LLM 导演**：让模型帮你把“达妮娅自拍”扩写成完整画面；
- 📚 **LoRA 管理**：自动识别角色、作品、触发词，支持风格组合；
- ⏳ **排队任务**：生成任务排队执行，不会一次卡死；
- 📊 **专属 WebUI**：在浏览器里管设置、看日志、管 LoRA。

---

## 安装

### 方式一：AstrBot 插件市场（推荐）

1. 打开 AstrBot 的 WebUI；
2. 进入“插件”页面，搜索 **ComfyAnima**；
3. 点安装，等待依赖装完；
4. 在插件设置里填上你的 ComfyUI 地址，保存。

### 方式二：手动安装

1. 下载本仓库最新的 `astrbot_plugin_comfy_anima_<版本>_release.zip`；
2. 解压后把 `astrbot_plugin_comfy_anima` 文件夹放进：
   ```text
   AstrBot/data/plugins/
   ```
3. 重启 AstrBot；
4. 在 WebUI 插件页启用并配置。

---

## ComfyUI 准备

插件默认连你已有的 ComfyUI：

```text
http://127.0.0.1:8188
```

需要准备：

- ComfyUI 已启动，并能在浏览器打开；
- 把本插件需要的 Anima 工作流放到 `workflow/` 目录（插件包已内置默认配置）；
- 模型 / LoRA 放在 ComfyUI 对应的 `models/` 路径里；
- 插件设置里选好你要用的工作流。

> 如果你的 ComfyUI 在另一台机器，把地址填成 `http://192.168.x.x:8188` 即可。

---

## 常用命令

| 你想干嘛 | 命令 |
|---|---|
| 直接出图 | `/画图 达妮娅自拍` |
| 用风格组合出图 | `/画图 风格006 达妮娅` |
| 让 LLM 帮忙想提示词 | `/画图 --llm 达妮娅自拍` |
| 发图后改图 | 先发图，再回复 `/重绘 角色是 kei（blue archive）` |
| 换角色 | 先发图，再回复 `/换角色 原图角色 -> 达妮娅 --preset 风格006` |
| 姿势/深度控制 | `/底图控制 <要求> --m p`（p=pose，d=depth，l=lineart，r=reference） |
| 反推图片 | 先发图，再 `/反推` |
| 反推后画图 | 先发图，再 `/反推画图 <要求>` |
| 看所有命令 | `/comfy帮助` |

---

## 自然语言

不用命令也能聊。在 smart 模式下，Bot 会自己判断你说的话是不是想画图。

```text
你：我想看娅娅的照片
Bot：开始生成并回复图片
```

如果不想让 Bot 自动画图，切到 strict 模式，只用命令触发。

---

## WebUI

默认地址：

```text
http://127.0.0.1:6198
```

可以在里面：

- 改 ComfyUI 地址、工作流、画布尺寸；
- 看生成日志和任务状态；
- 查看 / 编辑 LoRA 的角色、作品、激活词；
- 管理风格组合；
- 看队列、失败原因。

---

## 常见问题

**1. 一直提示“LoRA compatibility rejected”**
- 2.1.307 里 Legacy 模型会放行没有 2.9B 声明的 LoRA；
- 如果报的是 2.9B，说明该 LoRA 明确属于 2.9B，本版本暂不使用。

**2. 改图提示“请发送一张图片”**
- 先用 QQ 发图给 Bot，再**回复这张图片**发命令。

**3. 报错里带【绘图导演思考模型】或【图片反推多模态模型】**
- 换一个协议稳定的绘图导演模型（推荐 DeepSeek V4 系列）；
- 确认图片反推模型支持图片输入。

**4. 出图不像角色**
- 先确认 LoRA 已安装、已刷新；
- 在 WebUI 的 LoRA 详情里补角色 / 作品 / 激活词；
- 然后用“角色是 xxx”这种写法；
- 追画改图时不用重复角色名，插件会自动沿用上一张的角色。

**5. 任务状态是 partial / output_ready**
- 这是正常的。QQ 平台不返回 message_id，插件不会假装“已发送成功”；
- 只要图已经生成并发出，任务就是“输出就绪”。

---

## 进阶指南

想玩得细一点？看：

- [docs/ADVANCED.md](docs/ADVANCED.md)：三条出图路径、角色 LoRA、风格预设、换角、底图控制、模型分工、任务状态和调试口诀。

---

## 开发 & 发布

- 插件代码：`astrbot_plugin_comfy_anima/`
- 测试：`tests/`（pytest）
- 发布包：`release_<版本>/astrbot_plugin_comfy_anima_<版本>_release.zip`

贡献前请跑：

```bash
python -m pytest
python -m ruff check .
python -m compileall -q .
```

---

<!-- Roadmap (G10): multi-bundle image delivery is intentionally not
implemented. Queuing plus the existing “继续” continuation flow is the owner
decision for 3.1.400; do not reopen this as a new bundle feature without a
concrete user workflow that needs multiple simultaneous bundles in one reply. -->

## License

按仓库 LICENSE 文件执行。
