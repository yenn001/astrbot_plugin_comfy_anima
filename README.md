# AstrBot ComfyAnima 插件

> 当前版本：2.4.0。2.9B 可执行路径暂缓，当前稳定路径是 Legacy 单图。

让 AstrBot 里的角色（比如你的达妮娅）真的能“画图”的插件。

接上 ComfyUI + Anima 工作流之后，你只要在 QQ 里跟 Bot 说：

> “帮我画一张达妮娅自拍”
> “我想看娅娅的照片”
> “/画图 风格006 达妮娅”

Bot 会生成图片并尝试发回来；如果平台没有回执，任务会诚实显示为“输出就绪”。

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

1. 在 [Releases](https://github.com/yenn001/astrbot_plugin_comfy_anima/releases) 下载对应版本的 source-only ZIP（当前为 `astrbot_plugin_comfy_anima_2.4.0.zip`）；
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
- 插件包已内置默认 Anima 工作流；只有使用自定义工作流时，才需要额外放入 `workflow/` 目录；
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
- 2.4.0 的 Legacy 路径会放行没有 2.9B 声明的 LoRA；
- 如果报的是 2.9B，说明该 LoRA 明确属于 2.9B，本版本暂不使用。

**2. 改图提示“请发送一张图片”**
- 先用 QQ 发图给 Bot，再**回复这张图片**发命令。

**3. 改图提示“LLM 分镜超时”**
- 换一个协议稳定的绘图导演模型（推荐 DeepSeek V4 系列）；
- 确认图片反推模型支持图片输入。

**4. 出图不像角色**
- 先确认 LoRA 已安装、已刷新；
- 在 WebUI 的 LoRA 详情里补角色 / 作品 / 激活词；
- 然后用“角色是 xxx”这种写法。

**5. 任务状态是 partial / output_ready**
- 这是正常的。QQ 平台不返回 message_id，插件不会假装“已发送成功”；
- 只要图已经生成，任务就是“输出就绪”；平台是否收到无法由插件机器确认。

---

## 进阶指南

想玩得细一点？看：

- [docs/ADVANCED.md](docs/ADVANCED.md)：三条出图路径、角色 LoRA、风格预设、换角、底图控制、模型分工、任务状态和调试口诀。

---

## 开发 & 发布

- 插件代码：`astrbot_plugin_comfy_anima/`
- 测试：`tests/`（pytest）
- 发布包：`release_<版本>/astrbot_plugin_comfy_anima_<版本>_release.zip`
- 更新记录：[CHANGELOG.md](CHANGELOG.md)；配置项：[_conf_schema.json](_conf_schema.json)

贡献前请跑：

```bash
python -m pytest
python -m ruff check .
python -m compileall -q .
```

---

## License

当前仓库未附正式 LICENSE；第三方模型、节点、LoRA 和数据请按各自许可使用。
