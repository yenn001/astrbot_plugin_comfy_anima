# 更新日志

本项目遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [2.5.1] - 2026-10-08（构建 3.1.467）

### 改：角色名验证不过也能出图（新增可关闭的策略开关）

- **现象（用户实测）**：一条点了**两个角色**的 `/画图` 指令连续四次失败 ✗ ——
  依次报 `LLM 角色校验失败` / `动态 LoRA 处理失败` / `invalid_picture_protocol` ✗；
  用户的原话是"**没 LoRA 或者 Danbooru 过不了就停止生图**" ✓。
- **二审定位（三处否证后才确定）** ✓：
  - 真正的门是 `main.py` 的 `character_resolution_unverified` ✓，
    抛错文案 `无法通过本地 Danbooru 或当前唯一角色 LoRA + Gallery exact 确认角色“…”` ✓；
  - **否掉** `character_purity_mode` ✗（它只**过滤**提示词里别的角色名 ✓，代码里从不 raise ✓）；
  - **否掉** `strict_lora_validation` ✗（它管的是 **LoRA 清单解析** ✓，那 5 处 `strict=True`
    全在 `resolve_selections` ✓，与角色名验证无关 ✓）；
  - 判定依据是 `CharacterClaim.strict` ✓ —— **默认即为 False（宽松）** ✓，
    因此导演"发现"的候选名本来就会被放行 ✓（记 `llm_character_advisory_unverified_kept` ✓）；
    **但用户手写进指令的角色名**被构造为严格 ✗ → 验证不过即整张不出图 ✗。
- **改法（方案 A）**：在**门口**加策略开关 ✓，不改 claim 的构造 ✓：
  - 新增设置 **`allow_unverified_character_names`（默认 true）** ✓：
    开启 → 照画 ✓，但不加载该角色 LoRA ✓，并在任务事件记
    `llm_character_unverified_drawn`（WARNING，含 query 长度与 policy ✓）；
  - 关闭 → 维持原来的严格行为 ✓（宁可不出，也不画错角色 ✓）。
- **验证**：`_conf_schema.json` 同步新增该键 ✓（schema ⇔ 设置模型的不变量测试要求 ✓）；
  新增回归测试钉住两条分支 ✓；全量测试与门控部署见日志 ✓。
## [2.5.1] - 2026-10-06（构建 3.1.466）

### 修：意图门"静默 no_draw"可诊断；执行守卫不再掐断用户对话

- **现象**（用户日志证据）："娅娅，你在干嘛呢，拍张照片给我看看（用ComfyAnima，画出来）"
  → `intent gate: no_draw, not submitting to ComfyUI` ✗（不出图）→ 模型自行调用
  `astrbot_execute_shell` 诊断 ComfyUI ✗ → 守卫判"绘图请求越权工具" ✗ →
  `Agent execution was requested to stop by user` ✗ —— **整轮对话被掐断** ✗。
- **A1（诊断补全）**：`_event_intent_gate_result()` 的任一项校验不符都会**静默**返回空
  并落到 `no_draw` ✗。新增 `_log_intent_gate_rejection()`，在 `no_draw` 时逐项打印
  校验结果：`status / decision_id / result_hash / public_version / internal_target_version /
  user_id_hash / session_id_hash / user_message_hash / decision ledger` ✓
  —— 静默变可诊断，下一句日志就会指明**到底是哪一项**把它拒了 ✓。
  （注意：`bot_reply_draw_delivery_phrases` 属于**主动画给你看**那条路径，**不在这条链上**，
  所以加短语治不了本问题 —— 这也是本轮先把诊断做出来的原因。）
- **B（守卫与意图门一致）**：守卫原来只检查 `trace["intent"]` ✗，而同一会话里会**残留
  上一次绘图的 trace** ✓ → 普通轮次的诊断性 shell 被按"绘图请求"处理 ✗。
  现在额外检查 `trace["terminal_state"] == "no_draw"` ✓ —— 意图门本轮已判不绘图时直接放行 ✓。
- **C（不得掐断对话）**：守卫原先在拦截后调用 `event.stop_event()` ✗ → 代价是
  **结束用户这一轮对话** ✗。现改为**只标记 `blocked`** ✓ —— 终态自然不会提交 ComfyUI ✓
  （"本张不提交"的保护不变 ✓），但不再因此打断用户 ✓。
## [2.5.1] - 2026-10-06（构建 3.1.465）

### 修：普通聊天轮次不再摘掉 AstrBot 宿主工具（搜索/记忆/定时/MCP/技能/代码）

- **现象（用户对照实验实证）**：开启自然绘图模式后，AstrBot 里**一切搜索只能走本插件** ✗，
  Tavily 网页搜索、记忆读写、定时任务（`future_task`）、MCP 与技能管理、
  代码/文件读写、以及其它插件的工具**全部消失** ✗；**关掉插件后立刻全部恢复** ✓
  → 故障点确认在插件的"请求工具隔离" ✓。
- **根因**：`director_primary` 分支（自然绘图模式开启时）对**每一个** LLM 请求都用
  绘图**白名单**整体替换 `req.func_tool` ✗（源码注释自证 "removed from EVERY request" ✗），
  而 `drawing_request_allowlist()` 只保留"具备绘图相关能力"的工具 ✓ → 其余全被摘掉 ✗。
  实测被摘的还包括定时任务、记忆类（8 个）、MCP（5 个）、技能（5 个）、群/用户查询
  与执行类（11 个）✗。
- **修法（二审后的定案）**：
  - **普通聊天轮次：零隔离** ✓ —— 不再替换 `req.func_tool`，宿主与其它插件工具**原样保留** ✓✓；
  - **绘图轮次：保留白名单** ✓（`active` 分支不变 ✓，fail-closed 语义不动 ✓）；
  - 生图链路**不因此变弱** ✓：绘图轮次仍有白名单 ✓，且**执行阶段另有 fail-closed 关卡**
    （`if tool_name in BLOCKED_EXECUTION_TOOL_NAMES:` ✓）**不依赖**请求阶段隔离 ✓；
    聊天中途转绘图时 trace 一建立，后续 follow-up 轮次立即恢复隔离 ✓。
- 新增 `tests/test_ordinary_turn_tools.py`（3 条，源码为钉）：
  普通轮次分支**不得**出现 `req.func_tool = ` 或 `drawing_request_allowlist()` ✓；
  **绘图轮次分支仍隔离** ✓；**执行阶段关卡仍存在** ✓。
- 现有 `test_request_tool_isolation.py` 全部保留 ✓（它测的是隔离函数本身，两条路径都还在 ✓）。
## [2.5.0] - 2026-10-04（构建 3.1.464）

### 修（总根因）：中文角色名一律被丢弃，主体被解析成 "shadow"/"background"

- **现象**：`/重绘 角色是大肥鱼 --m p` 三次分别画出**鱼娘 / 普通女孩 / 一条真鱼** ✗，
  提示词开头是 `fish, fat fish, no humans, animal focus…` ✗；事件 `lora_count: 0` ✗。
- **事件实证**：`appearance_anchor_target {"canonical": "shadow"}` ✗✗ ——
  主体被解析成了反推事实里的一个词 ✗。
- **总根因**：`_requested_subject_hint()` 提取到「大肥鱼」✓ 之后，出口有一道
  **ASCII 门禁** ✗：`re.fullmatch(r"[A-Za-z][A-Za-z0-9_\- ]{0,48}", cleaned)` ✓
  → **中文名一律过不了** ✗ → 掉进"从文本里捞已知别名"的兜底 ✗ → 捞到 `shadow` ✗
  → `lora_count: 0` ✗ → 提示词里没有名字 ✓ → 导演照字面翻译成 `big fat fish` ✗ → 真鱼 ✓
  （这也解释了为何"达妮娅能中 ✗"—— 它靠的是兜底里一条**硬编码特例** ✓，根本没走主体解析 ✗）
- **修法（一行级）**：出口正则允许 CJK ✓
  （`[A-Za-z\u4e00-\u9fff]` 起头、主体允许汉字 ✓），其余清洗与长度上限不变 ✓。
- 与 3.1.463 的语义别名检索**配合**后，中文名才真正走通全链路：
  主体=大肥鱼 ✓ → 语义别名命中 LoRA ✓ → 触发词注入 ✓ → `lora_count ≥ 1` ✓
- 新增 `tests/test_chinese_subject_hint.py`（6 条）：中文名可提 ✓；带 `--m p` 可提 ✓；
  分隔符可提 ✓；ASCII 名照旧 ✓；**有「角色是X」时不得被别名兜底盖掉** ✓；
  无角色措辞时兜底仍可用 ✓。
## [2.5.0] - 2026-10-04（构建 3.1.463）

### 修：中文角色别名（如「大肥鱼」）选不中对应 LoRA

- **现象**：`/重绘 角色是大肥鱼 --m p` 完全不是 LoRA 里的角色；事件显示
  `lora_count: 0` ✗，而提示词开头是 `big fat fish` ✗（导演把中文名当普通中文译掉了）。
- **实测根因**：兜底函数 `_find_subject_lora_by_alias()` 只检查 LoRA 记录自身的
  `name / model_name / aliases`（都是**文件名类**）✗，**没有查语义索引** ✗ ——
  而条目 `deepseek anima0060` 的中文别名 `deepseek娘化(大肥鱼)` 与
  `character_names: deepseek娘化` **恰恰只存在于语义索引** ✓，于是中文名永远匹配不到，
  库里只剩一条**硬编码的「达妮娅」特例**在兜个别人物 ✗（这解释了"达妮娅能中、大肥鱼不能"）。
- **修法（小、且沿用既有 API）**：兜底函数改为实例方法 ✓，除记录自身字段外，
  一并检索语义条目的 `aliases / character_names / activation_terms / source_works` ✓
  （与 `_subject_lora_selections` 里 `entry_for(record).aliases` 的既有用法一致 ✓）；
  并处理 **29B 投影与原版同时命中** 的情况：优先选非 `_29b` 的那个 ✓，
  避免"同名多个"被误判为歧义 ✓。硬编码的「达妮娅」特例**保留**（不回归 ✓）。
- 新增 `tests/test_subject_alias_fallback.py`（5 条）：语义中文别名可命中 ✓；
  文件名直配照旧 ✓；**29B 投影不造成歧义** ✓；未知名字仍返回空 ✓；达妮娅特例仍可用 ✓。
- 仍待办（同一链路的下半段）：导演 LLM 会把中文名译成 `big fat fish` ✗ ——
  插件已有"不可翻译片段"机制但只接在 `direct_draw` ✗；LoRA 一旦选中，
  触发词经 `lora_activation_overrides` 注入 ✓，能大幅抵消该问题，故先落这一半并验收。
## [2.5.0] - 2026-10-04（构建 3.1.462）

### 重绘：点名角色时，剔除反推事实里的原图发色/瞳色

- **病根（提示词原文为证）**：`_filter_character_appearance_overrides` 只看文本里有没有
  `hair`／`eyes` 这类词就判定"**用户自己指定过**该槽位"（`\b(?:hair|hairstyle)\b` ✓）。
  而重绘传给它的文本是**反推事实**（含 `long blue-gray hair` ✗）→ 锚点里的 `blonde hair`
  **被整条丢掉** ✗ → 强制校验因此**不再报缺** ✗ → 任务"成功"但成图仍是原图发色 ✗
  —— 也因此"时好时坏"：反推**没提**发色的那一次就成了金发 ✓。
  （同一机制也解释了为何 `halo` 与 `blue eyes` 活着：前者反推没提 ✓，后者与反推同值 ✓）
- **主修（用户提出）**：`semantic_redraw_request(..., strip_appearance_colors=)` —— 点名
  canonical 角色时，从 `positive_tags` 里剔除**颜色词 + hair/eyes** 里的颜色部分
  （有限颜色词表 ✓），**保留** `long hair` / `side braid` / `hair ornament` / `ahoge` 等
  非颜色特征 ✓；**只在重绘这一条路径、且仅当点名了角色**时启用（纯图片编辑场景原样保留 ✓）。
- **补充**：外貌块改用**用户本人的话**（`event.message_str`）判断"是否自己指定过"，
  而不是拼装文本（防复发：拼装文本冒充"用户的话"是本轮与上一轮同类病根）✓。
- 新增 `tests/test_strip_appearance_colors.py`（4 条）：颜色被剔除且长度/光环保留 ✓；
  非颜色特征一律保留 ✓；**不点名时原样保留原图颜色** ✓；**用户原话一字不动** ✓。
- 验收：同一命令连画 3 次，`prompt_appearance_terms` 每次都应含 `blonde hair`、
  且不含 `blue-gray hair` —— 从"时好时坏"变为**确定**。
## [2.5.0] - 2026-10-04（构建 3.1.461）

### 诊断：把最终提示词的片段与命中的外观词记进任务事件

- **为什么加**：外貌锚点是否真的进了最终提示词，此前**无从确认** ✗ ——
  `workflow_payload_ready` 只记 `prompt_chars` / `prompt_sha256` / `tag_count` /
  `slot_markers`，而提示词诊断库是**内存态且只有 DELETE 路由**（`plugin_page.py:929`），
  取不到原文；于是"锚点有没有生效"只能靠长度差推断 ✗（推断正是反复出错的来源）。
- **加什么**：`workflow_payload_ready` 的 details 新增
  `positive_prompt_head`（提示词前 400 字符）与
  `prompt_appearance_terms`（提示词中命中的外观词，如 `blonde hair` / `blue hair` /
  `halo`）——一眼就能看出**两个发色是否并存**，或锚点是否根本没进提示词。
- 纯诊断，**不改变任何出图行为**。
## [2.5.0] - 2026-10-04（构建 3.1.460）

### 修：用户点名的 canonical tag 被截断，导致外貌锚点查错名字

- **现象**：`重绘 角色是toki_(Blue_Archive)；兔女郎，女仆，吊带袜` 不出金发，
  需要手动把"金发、蓝瞳、光环"写进要求才行。
- **实测根因（3.1.458 的观测字段把它照出来了）**：外貌查询实际发出的是
  `canonical="archive)"`（`_requested_subject_hint` 会**刻意删掉** `_(Blue_Archive)`
  这段"作品注释"，而外貌档案的键**恰恰需要它**）或 `canonical="background"`
  （删掉后抓不到，就回退到"从文本里捞已知 LoRA 别名"，于是从反推事实的
  `plain white background` 里捞到了背景 LoRA 的别名）→ `unavailable` → 零锚点 →
  提示词里没有 `blonde hair`。
- **用户对照实验（本次修正了我的判断）**：**同样的 img2img 强度**下，手动加金发 tag
  与不加是两个结果 → **唯一缺的是 tag 本身**，强度不是拦路环节。此前我把强度列为
  "可能的边界"是错的，已收回。
- **修法**：新增 `_appearance_canonical_hint()`——只在用户**真的写出** `name_(work)`
  这种 tag 形态时命中，返回**完整** canonical；重绘路径在建好意图计划后，
  若命中则用它**覆盖**计划里的主体（`requested_subject` + `identity_required=True`），
  从而走既有的外貌锚点门禁。**只匹配这一种字面形态**，因此
  "从描述文字里捞别名"这条错路被彻底绕开（反推事实里不会再产生主体）。
- **不影响其他路径**：`_requested_subject_hint` 及其"删作品注释"的行为**保持原样** ✗
  （LoRA 绑定确实需要短名），只是外貌查询改用自己的完整 canonical。
- **回归测试** `tests/test_appearance_canonical_hint.py`（6 条）：用户原话必须得到
  `toki_(blue_archive)`（而非 `archive)`）；大小写与空格归一；**没有作品括号就返回空**
  （宁可不查也不查错）；**反推事实文本绝不产生主体**（`plain white background` → 空）；
  多个 tag 取第一个；空输入安全。
## [2.5.0] - 2026-10-03（构建 3.1.459）

### 重绘三档默认强度重排：0.55 / 0.62 / 0.70

- **实测依据**：`--mode balanced`（0.55）改不动发色一类的外观变更；`--mode free`（0.78）
  能改但构图必漂。用户据此要求重排档位。
- **新档位**（`services/semantic_edit.py`）：
  | 档位 | 旧 | 新 |
  |---|---|---|
  | `preserve`（严格） | 0.32 | **0.55**（即原来的 balanced 值）|
  | `balanced`（平衡） | 0.55 | **0.62** |
  | `free`（自由） | 0.78 | **0.70** |
- **下限保持对三档一视同仁**（既有设计，`test_major_floor_applies_but_explicit_values_win`
  明确断言）：major 时三档都取 0.64，保证"大改"有足够强度；**只有在非 major 时**，
  三档才按 0.55/0.62/0.70 区分。改动过程中我曾试图给 `preserve` 开特例（不受下限影响），
  **被该测试当场拦下**，故收回。
- **同步另一处重复映射**：`main.py` 中反推 img2img 路径内嵌的同一份
  `preserve/balanced/free` 数值同步改为 0.55/0.62/0.70（两处原本重复，数值必须一致，
  否则同一模式在两条路径上强度不同）。
- 显式 `--denoise/--d` 依旧**优先于**一切基线（`explicit_denoise` 分支不变）。
## [2.5.0] - 2026-10-02（构建 3.1.458）

### 外貌证据：看清"在查谁"，并停止把接口错误当成数据

- **加观测（决定性）**：此前解析外貌的事件**只记数量、不记被查询的 canonical**，
  于是无法区分"查错了名字"与"查对了却没命中"——排查因此卡住一轮。
  现新增两个事件，把输入固定下来：
  - `character_swap_appearance_lookup`（解析器入口，记 `canonical`）；
  - `appearance_anchor_target`（导演侧锚点入口，记 `canonical` / `from_binding` /
    `requested_subject`）。
- **修掉把错误当数据**：`danbooru_character_posts` 在 gallery 连不上站点时收到的
  `HTTP 200 + [{"error": ...}]` 会被原样当成"1 条帖子"，于是网络故障被下游报成
  「样本不足，不补写猜测」，误导排查。现识别该形状并抛出带原文的错误
  （含 `error_info.summary`），交由解析器记为 `character_swap_appearance_unavailable`。
- 仍不改变"不猜"原则：错误时依旧不补写外貌，只是错误信息如实呈现。
## [2.5.0] - 2026-10-02（构建 3.1.457）

### 角色外貌档案：过期不再等于失效（TTL 只安排刷新）

- **现象**：`重绘 角色是toki_(Blue_Archive)；…` 两张都不出金发。
- **实测链（来自任务事件）**：外貌锚点的取用路径**已被 3.1.455 接通** ✓
  （事件出现 `character_swap_appearance_insufficient`，此前根本走不到解析器），
  但连续两次都因 `post_count: 1` 判为「样本不足」→ 无锚点 → 不成金发。
  而库中 toki 的档案本就是正确答案（`blonde hair` 支持率 **0.98**、**52** 个样本、
  来源 `danbooru_gallery`），**只因超出 TTL 被 `get()` 当作不存在**：
  `if age > self.ttl_seconds: return None`。
- **设计修正（本轮）**：TTL 的语义是「**该刷新了**」，不是「**证据失效了**」——
  一次通过样本与支持率门槛的聚合仍然成立，因此：
  1. `CharacterAppearanceProfileStore` 新增 `get_including_stale()` 与 `is_stale()`；
     过期档案**照常作为证据使用**，`get()` 语义不变（仍只返回新鲜档案）；
  2. 命中过期档案时立即用旧证据出图，**刷新改为后台任务**
     （`_refresh_appearance_profile()`，失败只影响新鲜度，不影响本次出图）；
  3. **负缓存**：确实取不到稳定外貌的角色，`APPEARANCE_UNRESOLVABLE_TTL_SECONDS`
     （6 小时）内不再重复慢查询，事件记为 `character_swap_appearance_negative_cached`。
- **可见性**：命中过期档案时记录 `character_swap_appearance_stale_used`，
  含 `appearance_count` / `sample_count` / `age_days`，可判断用的是哪个年代的证据。
- **不引入猜测**：仍只使用该 canonical **自己**验证过的聚合；库里没有的角色依旧
  返回空（测试覆盖）。用户明确指定发色时仍由
  `_filter_character_appearance_overrides` 过滤，不会被档案顶回。
- 新增 `tests/test_stale_appearance_profile.py`（5 条）：新鲜档案两个读取口都返回；
  **过期档案 `get()` 隐藏但仍可作证据**；规范化键可命中；**未知角色两个口都返回空**；
  负缓存窗口有界。
- 未做（另行评估）：⑤ 第二证据源（wiki/放宽安全级）——它改变证据类别，需单独论证。
## [2.5.0] - 2026-10-02（构建 3.1.456）

### 紧急修复：保存设置被 schema 校验拒绝（group_block_levels）

- **现象**：在 Web 控制台**任何一次保存**都会弹出「`group_block_levels` 必须是字符串数组」，
  切换图片反推模型后保存时最容易撞上。
- **根因（我的回归）**：3.1.442 给 `group_block_levels` 加控件时，我按"字段在模型里是
  `dict[str, str]`"就把它放进了前端的**字典分支**，于是前端提交**对象**；而
  `_conf_schema.json` 里它的类型是 **`list`**（`default: []`）——
  **AstrBot 以 schema 为准做校验**，对象直接不合法 → 保存被拒。
  （后端 `_as_group_levels()` 其实**字典与列表都兼容**，所以问题不在它，而在 schema 校验。）
- **修法**：把 `group_block_levels` 从字典分支**移到数组分支**——每行 `群号=级别`
  作为数组元素提交，schema 通过，后端再按 `=` 解析。字典分支只保留
  `bot_character_preset_scopes`（它的 schema 确实是 `dict`）。
- **新增不变量测试** `tests/test_settings_serialization.py`：
  按 **schema 类型**逐字段核对前端序列化——`list` 必须发数组、（`dict` 必须发对象），
  并钉住本次事故字段（必须在数组分支、不得回到字典分支）。
  这条测试正是原先缺失的那一层：此前只核对了"字段有没有登记进类型集"，
  却没有核对"**提交形态与 schema 类型是否一致**"。
## [2.5.0] - 2026-10-02（构建 3.1.455）

### 没有 LoRA 也按 Danbooru 补全角色外貌（并保留 LoRA 触发词）

- **需求**：指定角色时，**即使本地没有该角色的 LoRA，也要去 Danbooru 取它的稳定外貌特征**；
  有 LoRA 时**两者并存**（LoRA 触发词 + 外貌特征）。
- **复核到的真实缺口（两条）**：
  1. `_subject_appearance_anchors()` 的第一步是 `if binding is None: return ()`——
     **外貌档案其实按 canonical tag 存、与 LoRA 无关**，却被 `binding` 前置卡住：
     点名一个本地没有 LoRA 的角色（如 `toki_(blue_archive)`）时，档案里明明有
     `blonde hair`（来源 danbooru_gallery，支持率 0.98）却**一个锚点都取不出来**；
  2. 该函数**只查缓存、不按需取**——即便有 LoRA 绑定，角色未被缓存过时同样取不到。
- **修法（合并为一条路，复用既有解析器）**：
  - canonical 取值：**有 binding 用 `binding.canonical`；没有就用计划里点名的
    `requested_subject`**（同一个 canonical 命名空间）；
  - 经既有的 `_resolve_character_appearance_profile(job, canonical)`：
    **缓存命中直接用**；**未命中则现去 Danbooru 取并写回缓存**；
    **取不到就不补、不猜**（解析器自带"样本不足不补写猜测"）；
  - 结果仍经 `_filter_character_appearance_overrides(..., scene_text)` 过滤，
    **用户明确指定发色/瞳色时不会被档案顶回**；随后走既有的
    `required_appearance_anchors` 强制与修复回路。
  - 为此给 `_generate_directed_instruction()` 增加可选 `job` 参数
    （解析器需要它记录事件），并在**重绘路径与 `_execute_job` 两条路径**传入；
    没有 `job` 时退化为"只查缓存"，行为与旧版一致。
- **可见性**：解析器自身已有事件——`character_swap_appearance_cache_hit` /
  `character_swap_appearance_resolved` / `character_swap_appearance_unavailable` /
  `character_swap_appearance_insufficient`，据此可判断外貌从哪来、是否命中缓存、
  以及是否因样本不足而未补。
- 新增 `tests/test_appearance_anchor_source.py`（6 条）：签名含 `job`；
  **无 LoRA 时 canonical 来自点名主体**；**有 LoRA 时来自 binding**；
  过滤会丢掉用户指定的发色而保留其它锚点；解析器在有 job 时被调用。
## [2.5.0] - 2026-10-02（构建 3.1.454）

### 重绘沿用反推身份，启用 Danbooru 外貌锚点补全

- **现象**：重绘时角色外貌不按 Danbooru canonical 特征补全，长相取决于反推描述
  与导演的发挥。
- **根因（已核实到机制层）**：外貌锚点机制（`_subject_appearance_anchors()`）
  挂在意图计划的 subject 上——`_generate_directed_instruction()` 内
  `if plan.identity_required and plan.requested_subject:` 才取锚点。而重绘的请求是
  "改什么"而非"是谁"，`_requested_subject_hint()` 只会从「角色是/为/换成/改成 X」
  这类说法里提取主体 → 重绘时**取不到主体** → 门禁始终关着 → 锚点恒为空。
- **修法（零新机制、零副作用）**：重绘路径在构建意图计划后，
  **仅当计划本就没有主体**时，采用反推结果里**唯一**且非空的身份名
  （`replace(plan, requested_subject=…, identity_required=True)`），
  于是既有门禁自然触发，canonical 外貌锚点经原路径送达导演。
  - **绝不覆盖**用户明确点名的角色（有主体就直接返回）；
  - **多人或不明确时不猜**（角色数 ≠ 1 或名字为空则不采用）；
  - **验证仍交给既有的 subject 绑定门禁**（其文档明示 Missing/ambiguous 会降级为
    tag-only 而非失败），因此本处不引入自造阈值。
- **可观测**：新增两个事件 `appearance_anchors_requested`（采用了哪个主体、原因）
  与 `appearance_anchors_skipped`（未采用的原因与角色数）。
- 新增 `tests/test_redraw_appearance.py`（6 条）：单一身份被采用；无人/多人/空名/
  字段缺失均安全返回空；已有主体不得被覆盖。
## [2.5.0] - 2026-10-02（构建 3.1.453）

### 修掉重绘间歇性失败：忽略标签外的 HTML 包裹噪声

- **实测根因（由 3.1.452 的诊断一次命中）**：导演返回的是**完整合法的**
  `<pic prompt="…" negative="…">` ✓，但**后面多了一个 HTML 闭合标签**——
  4 次的 `director_protocol_reason` 全是 `extra_content leading=0 trailing=4`，
  而原始响应结尾正是 `…"></p>`（`</p>` 恰好 4 个字符），另有若干次是 `</pic>`。
  严格校验要求"标签之外不能有任何内容"，于是被判 `invalid_picture_protocol`。
  该模型**有时加、有时不加**，所以时好时坏（近 14 次：6 成 8 败）。
- **同时证伪两个旧假设**：不是输出被截断（长度 850–1220，而
  `prompt_llm_max_tokens = 2500`），也不是标签数量不对（标签唯一）。
- **修法（确定性，不依赖模型听话）**：严格校验**之前**剥掉标签前后**固定的
  HTML 包裹噪声**（`<p>` / `</p>` / `</pic>` / `<br>` / `<br/>`），最多往返 6 轮；
  **标签之外若真有文字，仍旧照原样失败**（fail-closed 设计保留）。
  失败原因里新增 `wrapper_stripped=N`，可看出噪声出现频率。
- 新增 `tests/test_strict_tag_noise.py`（7 条）：`</p>`、`</pic>`、`<br>`、
  前后双侧包裹均被容忍；**真实文字与两个标签仍必须失败**。
- 待办：C（重试改变请求）暂缓——主修是确定性的，先看噪声类失败是否归零，
  再决定是否还需要让重试附加"不要 HTML 包裹"的纠正语。
## [2.5.0] - 2026-10-02（构建 3.1.452）

### 导演失败诊断修正：保留响应结尾 + 区分协议分支

- **先修正我自己的诊断假象**：3.1.451 引入的原始输出捕获按 800 字符**只留头部**，
  而"协议是否合法"取决于响应的**结尾**（标签有没有闭合、后面有没有多余文字）。
  于是我把**自己造成的截断**误判成了**模型的截断**，并据此提出了错误的
  "输出过长/需要加 tag 上限"方案。现改为 **头 1200 + 尾 600、中间省略并标注**，
  **保证结尾一定可见**；同时新增 `director_raw_chars` 记录原始总长度。
- **反证记录**：`prompt_llm_max_tokens = 2500`（≈8000+ 英文字符），而"疑似截断"的输出
  仅约 822 字符 —— **离预算差一个数量级**，因此"输出上限截断"这一假设不成立。
- **区分严格校验的两个分支**：新增 `protocol_reason`——标签数量不对记
  `tag_count=N`；标签外多余内容记 `extra_content leading=N trailing=N`。
  随任务事件落库（`director_protocol_reason`），不再只能看到一个笼统的
  `invalid_picture_protocol`。
- 仅诊断增强，**不改变出图行为**；B（tag 上限）与 C（重试改变请求）**暂缓**，
  等拿到完整响应再定内容。
## [2.5.0] - 2026-10-02（构建 3.1.451）

### 导演失败可诊断：记录模型原始输出 + 澄清传输映射

重绘连续失败时，插件只留下错误类型（`invalid_picture_protocol` /
"结构化分镜输出工具不可用"），**看不到模型到底返回了什么**——排查只能靠推断。
本版把这条诊断链补上：

- **P1 记录模型原始输出**：导演协议校验失败时，`PromptDirectorError` 现在携带
  模型原始返回（压空白 + 截断），并在任务事件 `image_task_failed` 中以
  `director_raw_output` / `director_detail` 落库。三个失败点均覆盖：
  唯一标签校验、标签外多余内容、以及"连续两次失败"的终态错误。
- **P2' 传输解析单一化**：新增 `resolve_director_transport()`
  （`services/prompt_contracts.py`），把原先内联在导演里的 transport 表达式
  提取为唯一真相，供导演与日志共用。
- **P5 修正设置提示**：`structured_director_mode` 的原 hint 写"auto 优先
  Function Calling"，**与实际不符**。真实映射为：
  **只要当前模型提供结构化输出工具，无论选哪一项都走 `function` 传输；
  模型不提供该工具时，`json`/`function_call` 走 JSON 传输，
  `auto` 与 `legacy` 都走 `<pic>` 标签传输。**
- 本版为**诊断与文档**改动，不改变出图行为（传输解析与原先的内联表达式等价）。

## [2.5.0] - 2026-10-02（构建 3.1.448）

### 可见性构图规则：点名要看的细节不得被外层衣物遮住

- **问题**：原「构图」段只约束**画什么**，不约束**看不看得见**。于是导演可以合法地
  写出"穿吊带袜 + 穿长睡裙"——**陈述为真，但吊带袜在裙下看不见**（用户反馈"哪有吊带袜"）。
- **改法**（`prompts/director_draw.txt` 构图段新增两条）：
  1. **可见性优先**：用户点名要看的部位或服饰若被外层衣物遮住，必须用能露出它的构图与动作
     （掀起 / 撩开 / 褪下 / 敞开 / 松开），并写出对应可见性 tag
     （`skirt lift` / `clothes lift` / `dress lift` / `undressing` / `partially undressed`），
     **不得只描述被遮住的穿着状态**；
  2. **点名局部时优先半身或局部特写**，不用全景把刚被点名的细节稀释掉。
- `prompts/director_creative_default.txt` 的「景别决定细节」后同步一条可见性规则。
- 与 3.1.447 的词典修复配套：前者保证"吊带"不被翻译丢弃，本条保证它**被画出来且看得见**。

## [2.5.0] - 2026-10-02（构建 3.1.447）

### 注册一致性闸门 + 吊带袜翻译缺口修复

- **先量后写**：新增配置项要同时出现在 8 处，漏一处就复现一类既有缺陷。动手前先量出真实缺口，
  再据此写测试，避免把猜测写成断言。
- **修掉量出的真实缺口**：
  - `enable_layered_lora_retrieval` 可保存但 bootstrap 不下发 → 补入 bootstrap；
  - 四个意图判定数字框（`intent_judge_auto_confidence_floor`、
    `intent_judge_local_embedding_threshold`、`intent_judge_local_rerank_threshold`、
    `intent_judge_online_timeout`）未登记进前端 `numberFields` → 补入。
- **新增注册不变量测试** `tests/test_registration_invariants.py`（5 条）：
  白名单 ⇒ bootstrap（含密码豁免与理由）、表单复选框 ⇒ `booleanFields`、
  表单数字框 ⇒ `numberFields`、豁免清单不得过期、schema 键 ⇔ 设置模型字段。
- **修复「吊带丝袜」画不出吊带**（有代码实证）：A1 词典按键长从长到短做子串匹配，
  而 `吊带袜` 并非 `吊带丝袜` 的子串（字序为 吊带·丝·袜），于是最长命中落到 `丝袜`
  → `pantyhose`，**"吊带"在翻译这一步就丢了**。现补入
  `吊带丝袜` / `吊带长筒袜` / `蕾丝吊带袜` / `吊带网袜` 四个变体，并把 `吊带袜` 的映射
  由 `garter belt, thighhighs` 修正为 **`garter straps, thighhighs`**
  （Danbooru 里 `garter belt` 指腰间束带，可见的吊带是 `garter straps`）。
- **新增** `tests/test_garment_translation.py`（8 条）：按代码同样的最长键匹配规则复核词典，
  断言任何"吊带X袜"说法都不得退化成无吊带的普通袜，且无吊带说法不被误加吊带。
- **补齐槽位诊断词表**：`_PROMPT_TAG_SLOT_KEYWORDS["clothing"]` 原先漏收
  `thighhighs` / `pantyhose` / `garter straps` / `nightgown` / `pajamas` / `lingerie` 等，
  导致服装槽位标记**低估**真实覆盖（实测三张图 clothing=1 即因此偏低）。

## [2.5.0] - 2026-10-02（构建 3.1.446）

### tag 串下限（Phase 1：只测量与告警，不改变出图行为）

- **背景（实测）**：`prompt_term_count` 在 94 次出图里 min=4 / p25=20 / **中位数 22.5** /
  p75=26，**23% 不足 20**、几乎无 30+。Anima 成图质量由 tag 串与自然语言场景句共同承载，
  所以"长期压在及格线"是真实的质量缺口，而非臆测。
- **提示词改造**（"更适配"的实质）：`director_draw.txt` 与 `director_creative_default.txt`
  原写"允许**少量** Danbooru 词作锚点"——与新要求直接矛盾，改为
  **「tag 串不少于 20 个，按槽位凑齐：身份 ≥3、服装（含饰品，从上到下）≥5、
  动作 ≥2、镜头 ≥2、场景 ≥2、主光 ≥2；只设下限，不设上限」**。
- **计数口径**（复用既有设施，零新增解析）：先用 `split_hybrid_prompt()` 把提示词在
  句子边界切开，再用 `split_character_validation_terms()` 数 **tag 块**里的词条——
  场景句内部的逗号不会虚增计数，加权组 `(x:1.2)` 与 `v1.2` 不会误判为句界。
- **配置**：`min_prompt_tags`（默认 20，0 = 关闭，0–60）。已接入设置模型、schema、
  保存白名单、bootstrap 与独立控制台控件。
- **观测**：`workflow_payload_ready` 事件新增 `tag_count`、`tag_block_chars`、
  `slot_markers`（六槽位关键词标记，用于定位"差在哪个槽位"）。
- **行为边界**：下限**只对 `txt2img` 告警、不阻断**；`img2img`（改图）靠源图供细节，
  短提示词合法，故不受下限约束，但同样记录计数。
- 后续：Phase 2（不足时让导演按偏薄槽位补一轮）需另行批准。

## [2.5.0] - 2026-10-02（构建 3.1.445）

### 新增两套用户可选主题（暗色霓虹 / 密集终端）

- 控制台原有主题机制（`theme.js` 首屏恢复 + `app.js` `applyTheme` + `app.css`
  的 `html[data-theme]` 覆盖块 + 顶部主题选择器）保持不变，只是新增两套皮肤：
  - **暗色霓虹 `neon`**：深色玻璃质感、青紫渐变强调色、去掉硬偏移阴影、圆角卡片；
  - **密集终端 `console`**：全局等宽字体、无阴影、方角、扁平深色，信息密度更高。
- 实现要点：两套主题都以 CSS 变量覆盖为主（含 `--hard-shadow` 置空以取消粗野风硬阴影、
  `--font-display` 去掉衬线），再加针对侧栏/卡片/表格/表单/按钮的结构性覆盖；
  追加在 `app.css` 末尾以取得源码顺序优先级。
- 在四处同时登记（缺一会导致选不到或空白）：`web/theme.js` 白名单、
  `web/app.css` 主题块、`web/app.js` `themeMetaColors`、`web/index.html` 选择器选项。
- 新增 `tests/test_theme_registry.py`：四处登记必须一致，且每个主题都要有
  `theme-color` 元色。

## [2.5.0] - 2026-10-02（构建 3.1.444）

### 补上 `intent_router_probe_plan` 的界面控件

- 该键在 3.1.443 接线后已具备真实效果，但独立控制台里没有控件（当初因"死配置"
  被排除，理由已消失）。现补入设置表单「生成与超时」分组、bootstrap 载荷与前端类型集。
- 语义提示写在控件上：关闭后导演跳过一次资产预检直接出图（更快，但少了
  LoRA/Danbooru 预检）。

## [2.5.0] - 2026-10-02（构建 3.1.443）

### 死配置清理：接线一个、移除两个、加闸门

- **接线** `intent_router_probe_plan`：此前只被装载、从未被读取。现在关闭它会让
  `_build_auto_draw_intent_plan` 返回不带探针的计划，导演因而不进入两阶段资产探测、
  直接单阶段出图（省一轮工具调用，代价是不做 LoRA/Danbooru 预检）。
  **默认保持 `true`，出厂行为不变。**
- **移除** 两个无消费点的配置项（连同字段、装载与 schema 条目）：
  - `show_command_progress`：已被 `send_generation_notice` 与
    `show_chat_generation_details` 取代；
  - `follow_up_draw_priority`：未完成的设计，只有 `after_delivery` 一个候选值，
    等于没有选择。
- **新增配置面闸门** `tests/test_config_schema_gate.py`：遍历 `_conf_schema.json`
  每个键，要求它在生产代码里有消费点（含"字段被 PluginSettings 方法消费、
  且该方法被调用"这类间接路径）；无消费点者必须在允许清单里写明理由。
  清单本身也被测试守护（接线或移除后必须同步清理）。
- 待决：`conversation_draw_cooldown_seconds` 仍无消费点，已登记在允许清单中；
  它的接线会改变沉浸聊天的出图节奏，需单独批准。

## [2.5.0] - 2026-10-02（构建 3.1.442）

### WebUI 补全档 1 + 档 2（32 个控件）

- 按 `WEBUI_TIER_PLAN.md` 的分档，把两个高价值档补进独立控制台设置表单：
  - **档 1（10 项）**：回显最终提示词、每回复最多出图数、会话配方续画、
    升级清空配方、预设清单闸门、意图闸门模式、导演结构化传输、轮询间隔、
    出图总超时、HTTP 超时；
  - **档 2（22 项）**：提示词/图片体积上限、导演超时与回退、路由超时、并行预检、
    LLM 并发上限、全局中断、视觉意图、场景提取三项、用户偏好两项、
    管线与动态 LoRA 模式、LoRA 检索两项、分群放行等级、转发显示名、
    锁定命令、底模切换。
- **排除 5 个"死配置"**：`show_command_progress`、`conversation_draw_cooldown_seconds`、
  `follow_up_draw_priority`、`intent_router_probe_plan`、`director_reference_file`
  —— 它们只在 `models.py` 声明与装载，**全插件没有任何消费点**（已用脚本逐键核验），
  补控件只会得到不起作用的开关。需先决定"接线"还是"从 schema 移除"。
- 新增保存端校验：四个枚举字段（意图闸门 / 导演传输 / 管线模式 / 动态 LoRA 模式）
  限定取值；17 个数值字段补范围校验。
- 前端：`web/`（真源）新增 32 个控件与类型集归类；`group_block_levels`
  复用字典字段的 `键=值` 行双向转换；`pages/control/` 由同步脚本产出。

## [2.5.0] - 2026-10-02（构建 3.1.441）

### WebUI 配置面对接修复（P1–P3）与新增配置的界面入口

- **P1（缺陷修复）**：`enable_bot_reply_draw`、`bot_reply_draw_cooldown_seconds`、
  `bot_reply_intent_backend`、`bot_reply_draw_delivery_phrases` 四个控件一直渲染在
  设置表单里、bootstrap 也下发当前值，但**不在保存白名单** `WEB_UI_EDITABLE_FIELDS`
  ——保存被静默丢弃（只改它们还会报"没有收到可保存的设置"）。现已纳入白名单，
  并补判定后端枚举、冷却范围校验。
- **P2（新增配置补控件）**：`enable_bot_character_binding`、`bot_character_preset`、
  `bot_character_preset_scopes`、`suppress_intermediate_draw_text` 四项新增配置
  此前只能手改 JSON 或用 AstrBot 原生页；现补入独立控制台设置表单与 bootstrap 载荷。
  绑定预设（含作用域值）在**保存期**即校验是否为契约角色预设，非法直接拒绝并列出可用项
  （运行期仍是 fail-soft 警告）。
- **P3（补齐已有配置的控件）**：`chat_roleplay_draw_prompt`、`director_extra_instruction`、
  `director_creative_preference`、`intent_judge_positive_anchors`、
  `intent_judge_negative_anchors`、`intent_judge_fallback`、
  `intent_judge_online_temperature`、`intent_router_min_confidence`、
  `enable_local_intent_router` 九项后端早已可保存、bootstrap 早已下发，仅缺前端控件；
  现补入意图判定与提示词定制两处。
- 前端：`web/`（真源）新增 13 个控件、类型集与收集逻辑补齐（含字典字段按 `键=值` 行
  的双向转换）；`pages/control/` 由 `scripts/sync_web_assets.py` 同步。
- 复核：四方审计（表单 / 白名单 / schema / 模型）A 类归零；bootstrap 轴仅剩
  `web_ui_password`（不回显属正确设计）。

## [2.5.0] - 2026-10-01（构建 3.1.440）

### 工具轮次不再逐轮刷屏 + 家族映射去重

- **绘图链中间轮次可静默**（新配置 `suppress_intermediate_draw_text`，默认关）：
  AstrBot 的 respond 阶段会投递 agent 每一轮的结果，绘图请求走多轮工具环时
  一次会连出多条近似重复的话。开启后对 `intent=True` 的绘图链中间 decoration
  丢弃 Plain 正文（该阶段对空链直接跳过、不发送也不触发 `after_message_sent`），
  非文本组件保留；终稿 decoration 发生在 `on_agent_done` 消费 trace 之后，走
  正式渲染路径不受影响。**默认关闭 = 保持既有设计约定**（每轮台词照常放行，
  非绘图会话亦不受影响）。
- **家族映射后去重**：`adapt_lora_selections_for_target` 把 legacy 名提升为
  专属变体名时可能与栈内已有的同名条目碰撞，导致同一 LoRA 被写进节点两次、
  权重叠加。现返回前按 canonical 名去重（保序，后出现的权重覆盖）。

## [2.5.0] - 2026-10-01（构建 3.1.439）

### BOT 角色预设绑定

- 新增配置 `enable_bot_character_binding`、`bot_character_preset`、
  `bot_character_preset_scopes`：把"这个 BOT 是谁"变成**配置事实**，
  不再依赖运行时 persona（`AstrMessageEvent` 不暴露角色/身份信息，此前无法可靠取得）。
- 生效条件：**未显式点名其它角色**、且未执行换角命令时，出图自动套用绑定的
  契约角色预设（身份锚点 + 必需触发词 + 角色 LoRA）；用户点名别人时绑定自动让位。
- 作用域可覆盖：全局默认 + 按会话/平台（`unified_msg_origin` / `session:sender` /
  `self:session:sender` / 平台段）分别指定，精确优先。
- **保存期校验**：绑定预设必须是契约角色预设（身份锚点与必需触发词齐全），
  非法即拒绝保存并列出可用项；运行期仍是 fail-soft 警告，不阻断出图。
- 验收（两次真实出图，措辞均未点名角色）：日志 `bot character binding applied:
  preset=达妮娅`，配方 `identity_anchor` 由空变为 `denia_(wuthering_waves)`。

## [2.4.3] - 2026-09-09（构建 3.1.433）

### 配方锚点经 event extra 传递（放行链激活，完成 3.1.431/432）

- 排查实锤：`<pic>` 渲染恒走无配方分支（terminal trace 在 on_agent_done 被
  清空），`options.preset_manifest.identity_anchor` 恒为空——3.1.431/432 的
  配方背书放行因 `recipe_identity_anchor` 恒空从未执行过一次；
- 修复：注入阶段把 identity_anchor 落入 event extra（`_persist_identity_hint`），
  bind 调用点优先读取该值、回退 preset_manifest；放行分支与 raw 回查逻辑
  零改动（此时才有真实输入可用）；
- 附带修复：双人合照时 BOT 声明了其他角色但漏写自己（自拍视角），导致
  exact 角色集不含配方锚点——现在锚点经由 extra 稳定到达放行分支。

## [2.4.3] - 2026-09-09（构建 3.1.434）

### 终端修复链补权威配方材料 + 管线归位

- BOT 最终输出不合规触发 terminal repair 时，修复导演此前只看到用户原话与
  工具证据 JSON——看不到配方注入块（该块为 per-request 临时部件且 repair
  请求绕开 on_llm_request），产出的 prompt 与角色完全无关；
- 修复：repair 的 scene_text 显式随行 `<authoritative_picture_recipe>` 块
  （锚点/触发词/角色 LoRA/栈/pipeline），产出指令的 pipeline 强制归位为配方
  声明值（不再由修复导演自由改写）。

## [2.4.3] - 2026-09-09（构建 3.1.435）

### 全部出图路径采样可控

- Quick/LanPaint 重绘（InpaintWorkflowBuilder）此前完全不读全局采样覆写——
  补齐 steps/cfg/sampler/scheduler 四键（请求显式值优先；重绘强度 denoise
  维持仅请求显式值，不做全局化）；
- 全部 manifest 的底图采样器绑定补 `sampler_input`/`scheduler_input`——
  采样器名/调度器全局覆写此前是"代码就绪、绑定缺失"的死配置（仅 anima_ttp
  生效）；node 100（放大二段瓦片采样器）与 TTP 的 node 8 有意不补，
  全局采样器/调度器只作用底图采样。

## [2.4.3] - 2026-09-09（构建 3.1.436）

### 闸门 LoRA 比对权重语义对齐 merge（抄错权重不再停图）

- 根因：BOT 在 `<pic>` 标签里把锁定槽位权重抄错（如 real skin 写 0.25，
  预设锁定 0.65）——merge 按"锁定槽位 LLM 覆盖无效"规则丢弃该覆盖、实际
  栈保持 0.66，但渲染段 expected 快照按"标签原样"记录了 0.25，闸门三元组
  精确比对 fail-closed 停图。expected 与 merge 语义内部矛盾；
- 修复：`assert_preset_invariants` 的 LoRA missing 判定改为 (name, family)
  存在性匹配（权重以实际栈为准），权重漂移降级为 warning 供审计。条目
  缺失/负面池/身份锚点三类拦截原样保留；配方合并的权重冲突检查与
  `assert_manifests_equal` 严格全等零改动。

## [2.4.3] - 2026-09-09（构建 3.1.432）





### 绑定漂移自愈（完成 3.1.431 未竟的放行）

- 排查实锤：LoRA Manager 实时刷新后 record 元数据/指纹漂移，
  `resolve_lora_identity_bindings` 会静默返回空（与"从未绑定"不可区分），
  3.1.431 的配方背书放行因迭代空绑定而失效；
- 修复：放行分支在常规绑定为空时，按归一化文件名回查语义索引的 raw 绑定
  （不筛 sha/指纹），命中会话配方 identity_anchor 即放行，并记录 entry 与
  record 的内容哈希差异供观测；找不到或不匹配仍严格拒绝。

## [2.4.3] - 2026-09-09（构建 3.1.431）


### 双人合照 strict 绑定死锁热修

- 自拍/多人合照场景下，BOT 按权威指令把配方栈写进 prompt 但可能不写自身
  锚点 tag（exact 角色集只含其他角色），配方角色 LoRA 被误判"与最终角色
  不一致"而 fail-closed 停图；现在绑定 canonical 等于会话配方
  identity_anchor 的 LoRA 由配方背书放行（身份有据，非猜测），无关绑定
  仍然严格拒绝；
- 配方注入使用指令补充：多人合照或自拍视角同样必须写锚点并声明
  characters（含自己）。

## [2.4.3] - 2026-09-09（构建 3.1.430）


### 绘图身份材料对齐（"我是谁"热修）

- 配方上下文注入补齐权威角色 LoRA（`character_lora_name` 与完整
  `lora_manifest`）并附使用指令：此前该注入只有锚点与触发词，BOT 写
  `<lora:>` 时会自行查目录并选错家族变体（2.9B 底模挂 legacy 文件），
  导致杂饰与人脸漂移；
- 无配方时（新会话首图/升级清空后）注入唯一 manual 默认角色绑定作为
  **参考材料**（条件式指令：用户点名其他角色则忽略本块）——材料语义，
  绝不构成 fail-closed 闸门不变量。

## [2.4.3] - 2026-09-08


### TTP 瓦片细节增强：放大分三档

- 新增 `enable_ttp_detail`：开启后 RTX 预放大（默认 1.3×）→ 2×2 切块 →
  逐块 WD14 反推并以低降噪（0.05）重绘细节 → 重叠拼合；关闭即纯 RTX
  插值放大。耗时约为纯 RTX 的 3-5 倍，实测四组对照确认不换脸、无接缝；
- 新工作流模板 `anima_ttp_api.json`（含 base/rtx/ttp 三个互斥输出变体与
  manifest 档案），`rtx_generation_workflow_file` 指向即整体替换放大链；
- 新增 CFG/采样器/调度器全局覆写（0/留空 = 用工作流原始值），补齐采样
  参数只有步数可覆盖的缺口；`KSampler Adv. (Efficient)` 类无降噪输入的
  采样器在档案中可显式声明不写降噪。

### 负面提示词三档语义

- **单张**：绘图契约（BOT auto-draw 与导演共用 HYBRID 契约）明确要求排他
  意图（"别画X/去掉X"）必须以英文 tag 进入本次 negative；
- **会话粘性**：新增 `user_negatives` 持久清单——"以后都别画X""再也不画X"
  即登记、"可以画X了""解禁X"即解除；命中后由 BOT 以角色口吻转述确认
  （规则插件侧生效，与措辞无关），另有 `/别画 X`、`/解禁 X` 命令保底；
  每次出图自动并入负面并参与清单审计；Web 控制台新增面板可见可删；
- **全局**：新增全局附加正/负词设置，追加进每张图并参与审计；
- **止血**：会话配方提交不再吞并全量负面（导演/场景词不持久化），粘性词
  只随显式指令增减——杜绝"一次场景排除永久压制后续出图"的事故性污染。

### 编辑入口对标（重绘/底图控制不再裸奔）

- 新增会话产物登记表：插件交付的每张图记录 sha/尺寸；`<edit>`、`/重绘`、
  `/底图控制` 的目标图精确命中时，自动沿用会话配方的角色 LoRA 栈、身份
  锚点、负面池并激活清单审计（fail-closed）；未命中（外部图）只挂负面类
  不变量，绝不误套角色；
- `/重绘`、`/底图控制` 的负面提示词恒挂（配方池+粘性+全局）。

### 兼容说明

- `rtx_generation_workflow_file` 需指向 `workflow/anima_ttp_api.json` 以启用
  TTP 链（不指向则维持原 RTX 行为）；旧模板保留可随时指回；
- 2.4.3 版本变更会使旧会话配方清空一次，先成功出一张图即可恢复续画。

## [2.4.2] - 2026-09-08


本次发布包含两大功能与一项限制解除（开发过程见下方 3.1.4xx 构建记录）：

- **合并转发图片修复**：aiocqhttp 适配器只对顶层图片段做 base64 转换，合并
  转发节点内的 `file://` 路径宿主机 NapCat 读不到导致聊天记录空白；转发图片
  现改为内联 base64（需搭配 NapCat ≥ 4.18.19，其修复了 Highway 上传超时）；
- **Bot 回复意图续画（管理员会话专属）**：生图语义判定不再只限用户消息——
  Bot 自己的交付语（"给你看"等）经意图判定 draw_now 后，走与 `<pic>` 同一条
  导演主链续画，图片追加进同一条回复（无技术脚注）；仅管理员会话生效，会话
  无成功配方不出图，同会话默认 30 秒冷却；新增 4 个设置项
  （`enable_bot_reply_draw`、`bot_reply_draw_cooldown_seconds`、
  `bot_reply_intent_backend`、`bot_reply_draw_delivery_phrases`），Web 控制台
  "LLM 绘图导演"卡片可直接编辑；管理员门禁跟随 AstrBot 平台主管理员列表；
- **解除意图判断模型选用限制**：普通聊天意图判断模型可与绘图导演、图片反推
  选用同一模型。

### 文档

- README 新增"v2.4.2 更新了什么"通俗小节（内部构建 3.1.426）。

## [2.4.1] - 2026-09-08（构建 3.1.424）

### 修复 Web 控制台 Bot 回复四字段显示为空（423 遗留）

- `web_ui_bootstrap` 的 settings 是显式白名单投影，423 只加了表单字段没有加
  投影键，导致开关/冷却/后端/词表在页面上永远显示空值（保存本身不受影响）；
  四键已补进投影；
- 新增通用漂移守卫测试：控制台设置表单的每个可填字段必须出现在 bootstrap
  投影中（唯一例外 `web_ui_password`，秘密值不回传浏览器），今后任何表单
  字段漏接投影都会在测试层直接失败。

## [2.4.1] - 2026-09-08（构建 3.1.423）

### Bot 回复续画设置项补进 Web 控制台

- 控制台"LLM 绘图导演"卡片新增"Bot 回复意图续画"小节：开关、同会话冷却、
  判定后端、交付语词表四项可直接编辑保存（后端本就按 `_conf_schema.json`
  规范化，无需改动）；
- "权限与风控"卡片与后端选择器旁注明：管理员门禁跟随 AstrBot 平台主管理员
  列表（`admins_id`），插件内不另设名单；
- `web/app.js` 经 `scripts/sync_web_assets.py` 同步到 `pages/control/` 镜像。

## [2.4.1] - 2026-09-07（构建 3.1.422）

### Bot 回复续画收敛进主渲染链（消除平行捷径）

- 架构判决（两图对照+五图受控实验）：421 从配方历史快照携带外观词方向错误——
  配方把旧形态冻结为"真相"，而角色 LoRA 的默认形态才是本人；捷径手工组装
  与主路径双份维护即屎山之源；
- 重构：`<pic>` 渲染循环体提取为 `_render_picture_instruction`，`<pic>` 主路径
  与 Bot 回复重入共用同一条渲染链；判定只决定"画不画"，命中后把 Bot 原话与
  权威配方块（身份锚点/激活词/角色 LoRA/LoRA 栈）交给带工具链的绘图导演，
  场景身份与 `<pic>` 路径同源；
- 配方不变量（LoRA 栈经 dynamic_loras、负面池合并、身份锚点保底）从捷径迁入
  共享渲染段的 recipe_obj 分支，单一实现，同时修复 `<pic>` 追画在配方在场时
  对这些不变量的依赖缺口；
- 删除：`generate_bot_reply_scene`、捷径手工 options 组装、421 外观词过滤器
  （`_recipe_appearance_terms`）；
- 沉浸交付保持：图片 append 进本条回复、无技术脚注、无错误提示外漏、
  排队通知抑制（`_run_job` 新增 `notify_queue`）；重入 guard 防同事件二次判定。

## [2.4.1] - 2026-09-07（构建 3.1.421）

### Bot 回复续画外观锁定（"人不像"修复）

- 根因（五组受控对照出图实锤）：角色 LoRA 存在多形态时，仅靠激活词会漂到
  LoRA 默认形态；此前续画提示词只携带身份锚点，配方中上次成功出图的发色/
  瞳色/肤色/体型等外观描述符全部丢失，人脸与会话既有形象不一致；
- 修复：提交前从配方正向池确定性挑出外观身份词（`_recipe_appearance_terms`，
  发/眼/皮肤/耳/尾/角/刘海/呆毛/体型/脸型 + 构图词 1girl/solo），缺失者前置
  进最终提示词；服装、姿势与场景词不携带，仍由导演按 Bot 原话改写；
- 清单闸门与 `<pic>` 路径零改动。

## [2.4.1] - 2026-09-07（构建 3.1.420）

### Bot 回复续画提交链完整修复（五缺陷一次到位）

- `lora_preset` 不再传配方的 `preset_name`（`<pic>` 路径留下的清单标签，
  常为占位名 conversation_pic，非可解析 LoRA 组合），消除
  "找不到 LoRA 组合"提交失败；
- 配方 LoRA 栈改经 `dynamic_loras` 指令参数通道逐项注入（名+权重原样
  保留）：`preset_manifest` 只承载提交前不变量核对、从不注入 LoRA，
  此前缺该通道会在闸门处静默丢图（`missing LoRA stack entries`），比
  显式报错更难排查；Bot 回复路径的导演契约禁止凭空输出 `<lora:>` 标签，
  指令参数是唯一程序化注入口；
- 负面提示词改为配方负面池与导演负面的去重合并，满足闸门"负面池每项
  必须存活到最终 workflow"的不变量；
- 身份锚点确定性保底：导演输出缺原文锚点时前置补齐（闸门按原文子串
  核对，此前全靠导演复述，模型省略即 fail-closed 丢图）；
- 成功出图的会话配方回写条件纳入 `bot_reply_intent`（经
  `_commits_session_picture_recipe` 助手），Bot 回复续画后配方时间戳与
  指纹同步刷新；
- 角色 LoRA 进入 strict 解析键集合：目录绑定断裂时显式报错而非静默
  出白图，与 `<pic>` 追画的失败语义一致。

## [2.4.1] - 2026-09-07（构建 3.1.419）

### Bot 回复续画热修复（三缺陷）

- 观测：开关/管理员/空会话/判定非 draw_now 四个静默出口补 info 日志
  （判定行带 backend 与 reason），今后任何一次不触发都一眼可见卡点；
- 交付语词表：新增 `bot_reply_draw_delivery_phrases`（默认含"给你看/
  给你瞧瞧/快看"等），仅注入 Bot 回复判定实例；规则后端同步拦截否定
  （"不给你看/别给你看"）与疑问（"要不要给你看？"）句式；用户消息闸门
  词表不受影响；
- 冷却表：访问时驱逐过期条目，不再无界增长。

## [2.4.1] - 2026-09-07（构建 3.1.418）

### Bot 回复意图续画（管理员会话专属）

- 新增 `enable_bot_reply_draw`（默认关）：会话对象为 AstrBot 管理员且会话
  存在成功出图配方时，对 Bot 回复做意图判定（`bot_reply_intent_backend`，
  独立于用户消息闸门）；判定 draw_now 时由导演把 Bot 原话改写为场景、
  配方锁定角色身份与质感续画一张，图片追加进同一条回复且不附技术脚注；
- 沉浸感三支柱：画面是 Bot 刚说过的话的视觉延续；人与风格取自会话配方
  不漂移；图长在 Bot 自己的消息里。会话无成功配方时不出图；
- 同会话冷却 `bot_reply_draw_cooldown_seconds`（默认 30 秒）；判定结果走
  账本封签契约，载荷校验失败拒绝提交（fail-closed）；
- 解除意图判断在线模型的选用限制：可与导演/反推选用相同模型。

## [2.4.1] - 2026-09-07（构建 3.1.417）

### 合并转发图片投递修复

- `/画图` 合并转发卡片空壳或整条不达的根因修复：AstrBot aiocqhttp 适配器只对
  顶层图片段做 base64 转换，`Node.content` 内的图片段原样携带容器内文件路径，
  宿主机进程（NapCat）无法读取；转发分支现改为内联 base64 图片段；
- `/画图no` 普通图片消息路径行为不变；
- 新增 `tests/test_forward_payload.py` 钉住两条投递分支的图片段形态。

## [2.4.1] - 2026-09-05（构建 3.1.416）

### 自然闲聊出图稳定性

- 意图闸门先于提示词注入执行，"（画出来）"等组合句式正确触发出图；
- "不要画了 / 明天再画"等否定与推迟表达不再误触发；
- 角色身份绑定三层修复：家族形态归一化、未声明角色时唯一文件绑定即身份、
  编译期声明的 canonical 并入绑定期望集合——追画不换人。

### 报错与体验

- 全部模型类报错带【绘图导演思考模型】/【图片反推多模态模型】标签与 Provider；
- 普通聊天不再出现"未通过意图判断"提示（仅记录运行控制台日志）；
- WebUI 设置保存失败（AstrBotConfig 对象丢失）修复；
- 提示词不再泄漏 skill / tool_calls 等内部文本；
- 新增 `enable_time_context`：按现实时段自动补充 morning/day/sunset/night 光影标签
  （提示词或消息已写明时间时不覆盖）。

### 2.9B 模型族

- 配方/清单/严格键的家族后缀归一化（29B/ 与 _29b、_legacy）；
- 角色 LoRA 记录按当前底模家族自动兜底匹配。

---

## [2.4.1] - 2026-08-30

### Intent Judge Stage 1

- 新增双后端意图判断服务：off/rule/local/online/auto/both。
- 本地后端使用 AstrBot Embedding + Rerank Provider，本地优先、失败降级 no_draw。
- 在线后端使用独立 LLM Provider，输出 JSON 三分类。
- WebUI 增加意图判断模式与 Provider 下拉选择。

### Blueprint G1-G10 Consolidation

- G1：新增 `on_llm_request(priority=15)` 意图路由闸门 hook 点，结果写入
  event.extra；`intent_router_gate_mode=off` 默认保持 no-op，不改变现有路径。
- G2：`chat_intent_classifier` 识别“角色预设 + 视觉动作/场景词”为 draw_new，
  由 `enable_visual_task_intent` 控制。
- G3：新增 `services/user_picture_preferences.py` 持久化用户图片偏好
  （`user_picture_preferences_v1.json`），提供保存/使用/清除 API；
  `enable_user_picture_preferences` 默认关闭。
- G4：判定 draw 意图时在 event.extra 写 `enable_streaming=False`。
- G5：Scene Bridge 新增 `scene_context_from_event`，从可用 AstrBot 只读接口
  收集最近消息/人格名/记忆，缺失或异常时优雅回退并记录来源。
- G6：任务事件 schema 常量补充
  `intent_router_gate_start/result`、`visual_task_intent_promoted`、
  `user_picture_preference_saved`、`scene_extracted`、
  `roleplay_text_blocked`、`draw_terminal_forced`、
  `director_instruction_generated`。
- G7：新增蓝图专项测试（视觉任务意图、无配方澄清、偏好持久化、
  禁用流式、角色扮演文本拦截、事件码）。
- G8：补齐蓝图配置字段并写入 `_conf_schema.json`，默认值向后兼容。
- G9：保留 `intent_judge_backend=off` 并增加配置校验测试。
- G10：多 bundle 不单独实现，排队 + “继续” 已足够；路线图见 README 注释。

<!-- Roadmap note (G10): multi-bundle image delivery is intentionally NOT
implemented. The owner decision is that queuing plus the existing "继续"
continuation flow is sufficient for 3.1.400; revisit only if a concrete user
workflow needs multiple simultaneous bundles in one reply. -->

## [2.1.307] - 2026-08-28

### Immersive + Prompt Refactor Stage 1

- 新增 PromptCatalog：版本化提示词资源唯一确定性解析，重复/缺头 loud 失败。
- 拆分配置：chat_roleplay_draw_prompt / director_creative_preference；
  旧 auto_draw_system_prompt 仅作回滚源，不再复制使用。
- 协议收口 v3.1：任务提示词与传输协议分离，Director 拼接顺序固定。
- 资产探针三态化：probe_evidence_ok / probe_miss / probe_fatal，
  MISS 不封存绘图终态。
- 照片请求路由拆分：director_primary 下 photo-only 不再进入 natural draw。
- 确定性 IntentPlan 与只读 ToolSet 裁剪。
- ResponseEnvelope / BundleLedger / DeliveryReceipt：挂载归属硬校验，
  无 message_id 不得标 SENT。
- 身份绑定确定性解析：多 canonical 失败关闭。
- 双 Manifest 合并：预设权威覆盖、配方独有槽保留、不静默丢弃保存权重。

## [2.1.306] - 2026-08-27

### 调用链收敛重构 Stage 1

- 新增 `services/drawing_state_machine.py`：每个 event 一个 drawing run，严格
  queued → submitting → running → completed → delivery，终态不可重开，
  queued/submitting/running 可取消。
- 新增 `services/drawing_orchestrator.py`：事件级唯一提交闸门（同一 event 第二次
  提交抛 `DuplicateSubmissionError`）、幂等 run_id 分配、终态后旧 hook 只读。
- `_create_image_task_record` 改为把 orchestrator 分配的 run_id 直接写入
  `task_runs`，任务库、交付与诊断共享同一 run_id。
- 活动 agent run 期间到达的绘图消息（AstrBot `FOLLOW_UP_NOTICE`）在
  `on_llm_request` 阶段识别并提升为受控绘图轮次，不再裸奔进角色扮演回复。
- 绘图轮次请求阶段额外移除 shell/python/file/grep 等高权限工具；执行阶段对
  越权工具调用 fail-closed 并请求停止事件。
- 普通聊天多 `<pic>` 回复在 Stage 1 只允许第一次提交，后续 prompt 明确拒绝并
  给出提示（待 Stage 2 多 bundle 支持）。

### 上线期间发现并处理的问题

- **角色预设身份终检误杀**：contract-enabled 角色预设未建立 expected 身份基线，
  预设自己的 `denia_(wuthering_waves)` 被判为“未授权额外 Character”。
  处理：预设分支先调用 `_verified_prompt_character_canonicals` 建立基线，
  拒绝信息附带具体身份名。
- **Director JSON 修复解析过严**：模型返回 Markdown 围栏或带短尾的 JSON 时被拒。
  处理：`_strict_json_object` 增加围栏/嵌入对象候选解析，仍走严格字段白名单。
- **`pipeline="txt2img"/"draw"` 未知管线**：模型用同义词表达 base 管线导致提交前拒绝。
  处理：`_normalize_pipeline` 增加 `txt2img/text2img/文生图/draw/生图/生成/standard/normal → base`，
  未知值仍拒绝。
- **follow-up 期间 `<pic>` 协议泄漏**：模型抢用 `send_message_to_user` 把协议文本当消息发出。
  处理：Director Primary 下所有 LLM 请求构造阶段移除竞争交付与宿主执行工具；
  会话标记改用引用计数，嵌套 begin/end 不清除外层会话。
- **“画一套/想看…”类意图漏识别**：自然绘图与意图分类只认“张/个/幅”。
  处理：补 `套/组` 量词与 `想看/我要看/给我看 + 照片/图/自拍/样子`；
  “在干嘛/在做什么/日志/怎么回事”保持 debug 优先，避免把查岗当画图。
- **中间工具轮回复刷“绘图终止协议修复未完成”**（2026-08-28 01:19–01:22 生产日志）：
  模型在同一条回复里先返回 `<pic>` 又继续调用 `astr_kb_search` 等工具时，
  装饰阶段把中间结果当成终态：提前渲染了图片并把 terminal trace 留在
  `repair_attempted` 状态；之后每一轮工具循环都被替换成
  “❌ 绘图终止协议修复未完成”，最长刷了约 3 分钟。
  处理：带 trace 的 `on_decorating_result` 一律只做中间态清洗
  （移除 `<pic>/<edit>/<think>`，保留角色台词），不再修复、提交或封存；
  最终回复由 `on_agent_done` 终态守卫消费后才允许渲染。图片成功交付后立即
  清空 trace；事件已有终态 run 时只保留清洗后的台词、绝不再次提交；
  Director Primary 下同回复重复提交也不再向用户显示 Stage 1 错误文本。

### Stage 2 Director Primary（沉浸式）

- 新增 `director_primary` 配置：显式绘图走 Director 主链路；
  普通聊天在工具隔离下恢复角色台词 + `<pic>` 终端渲染（先聊后图）。
- 工具循环中间轮只清洗控制标签、保留台词；只有 `on_agent_done` 消费后的
  最终回复才执行修复与出图，避免中间装饰阶段提前出图或刷错误文本。
- 终态修复失败时保留角色台词，只附加失败提示，不再吞掉整条回复。

## [2.1.305] - 2026-08-27

### LLM 工具调用边界状态机

- 新增确定性意图分类器：debug_only > 续接 > draw_new > edit_last_image > query_only > clarify。
- 新增会话绘图配方：成功交付后持久化；插件更新首载清空旧配方，同版本重载保留，预设/LoRA/模型族变化即时失效。
- 新增 PresetManifest 提交前不变量：负面池、LoRA 栈、模型族、身份锚与预期不一致时停止提交。
- 新增 `<pic>` 终端确定性解码：单次 HTML 转义、全角括号与零宽字符归一化、LoRA 属性白名单。
- Intent Router 增加 debug 优先级提示与 0.7 置信度门槛，低于阈值降级 clarify。
- 动态任务上下文改走 `req.extra_user_content_parts`，system prompt 只保留稳定规则。
- `metadata.yaml` 补齐 `display_name`、`short_desc`、`astrbot_version`、`support_platforms` 与配置项国际化。

## [2.1.303] - 2026-08-27

### 图片交付工具隔离

- 普通聊天绘图请求按请求隔离 `send_message_to_user` 等竞争交付工具，避免 Agent 在终止校验前发送裸 `<pic>` 或虚假成功文本。
- 隔离无法验证时 fail-closed，并保留 LoRA/资产查询工具链。

## [2.1.302] - 2026-08-27

### Intent Router WebUI

- Added visible independent intent-router model controls to both WebUI settings surfaces, including manual Provider ID, timeout, temperature and Smart/Strict mode.

## [2.1.301] - 2026-08-27

### Independent intent routing and handoff

- Added a separately configured `intent_router_model` that classifies ordinary-chat drawing intent after asset lookup without submission authority.
- Added `smart`/`strict` interaction settings and explicit failed-handoff feedback while preserving Legacy/2.9B isolation and the terminal seal.

## [2.1.300] - 2026-08-26

### Legacy 角色 XXX 预设组合

- 扩展“风格与角色串”全局预设，支持角色 canonical、作品、身份锚点、必需触发词、变体和正/负 Tag 池。
- 同一 Legacy LoRA 可被多个角色预设独立复用；LoRA Manager 元数据提供触发词和 Tag 参考，不静默覆盖用户配置。
- Bot/LLM 可按角色预设名、canonical 或作品字段选择预设；命中后禁用 Danbooru 角色身份替换、重叠和追加。
- 身份锚点或必需触发词为空时，保存和 ComfyUI 提交均被阻断。

## [2.1.2] - 2026-08-26

### Bot/LLM 绘图交接状态封存

- 修复中间装饰阶段失败后清空 terminal trace，导致后续旧的 LLM `<pic>` 响应绕过阻断并继续提交 ComfyUI 的问题。
- 失败终止现在在同一事件内保持 sticky seal，直到最终 Agent 响应被消费；后续响应只返回同一阻断结果，不再产生图片。
- 保持 LoRA、模型族隔离和 fail-closed 校验不变。

## [2.1.1] - 2026-08-08

### 普通聊天图片终止协议修复

- 扩展普通聊天绘图意图，覆盖“我要看……照片”“穿给我看”“再出一遍 cos”等视觉交付与续画表达，并排除现有图片分析、纯查询和明确不出图请求。
- 在主 LLM 请求阶段建立终止追踪，不再依赖 LoRA、Danbooru 或 Prompt Plan 工具是否被调用。无工具的明确绘图请求若只返回散文，会进行一次无工具、有界的 `<pic>` 修复；仍无效则停止且不提交 ComfyUI。
- 将完整缓冲、终止追踪和终止校验统一为 `<pic>/<edit>` 协议不可关闭的传输保证。旧 `enable_chat_draw_terminal_guard` 仅作兼容字段；关闭普通聊天图片协议应使用 `enable_llm_pic_trigger`。
- 修复两套 WebUI 启动数据漏出图开关的问题。守卫复选框现在强制勾选并禁用，前端与后端保存都会把旧的错误 `false` 配置归一化，避免保存无关设置时静默关闭普通聊天出图。
- 新增无工具修复、装饰阶段顺序、负向请求、旧配置归一化和 WebUI 回填回归。本版不增加依赖、ComfyUI 节点、模型或工作流文件。

## [2.1.0] - 2026-08-08

### 本地反推、角色声明分层与 Control Stack v2

- 新增 `CharacterIdentityClaim` 来源分层。用户明确作品与角色、严格角色 LoRA 和真实歧义继续 fail closed；绘图导演给出的未知裸名称或虚构作品限定降级为 `creative_fallback`，不再把 DeepSeek 娘、模型娘、网络拟人或原创 OC 错当成必须存在的 Danbooru 角色。
- 新增本地 `LoadImage -> wd_tagger_mira -> ShowText|pysssss` 反推工作流和能力声明证据。默认 `reverse_backend=workflow`，支持显式 `vision` 和 `hybrid`；workflow 失败不静默调用视觉模型，多人空间绑定能力不足时明确停止。
- `/反推` 输出安全规范化 Tags；`/反推画图` 无修改要求时直接复用 Tags，带修改时视觉图像不会传给绘图导演。反推工作流支持独立模型、General/Character 阈值、分类、Session 和超时配置。
- Anima Control Stack v2 支持最多两张 SHA 去重输入、四个唯一通道和回复图优先顺序。每个 Pose、Depth、Lineart、Reference 通道独立保存来源、强度、作用窗口、缩放策略与 Reference 范围；未使用分支从工作流物理删除。
- 双图自然绑定支持“姿势用图1，构图用图2”。来源不完整或冲突时只报告计划问题，不提交 ComfyUI。自由模式和纯 Pose/Depth 结构重画跳过不必要的反推；保守/平衡内容模式才读取源图 Tags。
- 新增 Control Stack v2 WebUI 设置、反推依赖配置、环境档案 schema v3 迁移、双图工作流合同与普通聊天图片终端强制缓冲。本版不自动下载模型或自定义节点。

## [2.0.3] - 2026-08-06

### 日常聊天自动绘图结果精简

- 新增 `show_chat_generation_details`。默认 `true` 保持兼容；关闭后，普通聊天中的自动 `<pic>` 和 `<edit>` 工具链不再追加 Seed、图片数、LLM/ComfyUI/准备耗时及 GPU 明细。
- 该开关只控制普通 Agent 对话装饰阶段。所有显式绘图、反推、改图、控制、放大和重绘命令继续返回完整统计，不降低任务中心与持久控制台的可观测性。
- 独立 WebUI、原生 plugin-page、AstrBot 配置 Schema 和安全设置保存白名单同步支持该字段。本版不增加依赖、ComfyUI 节点、模型或工作流文件。

## [2.0.2] - 2026-08-05

### 命令能力矩阵与角色同根变体修复

- 修复 `remielle_dan` 一类基础 Character 与活动/服装变体被当成多个身份的问题。声明路径现在会合并同根变体，并在单角色、单 Copyright 场景中使用提示词已有的 Copyright exact；未显式要求变体时优先基础 canonical，显式变体仍保留。
- 新增 `control_draw` 与 `redraw` 参数上下文。`/底图控制`、`/控制画图` 和 `/反推画图` 可同时表达 `--m p/d/l/r` 控制通道与 `--mode preserve/balanced/free` 内容自由度；`/重绘` 可在同一入口区分整图模式与 `quick/lanpaint` 遮罩模式。
- 控制生成反推合同加入 preserve/balanced/free 继承边界；自由模式只继承所选控制通道锁定的约束。无控制通道的 `/反推画图` 按内容模式选择默认 denoise，显式 `--denoise` 优先。
- `/改图`、`/重绘` 和 `/反推画图` 在自然语言换角前先剥离结构化选项，避免 `--mode`、`--m` 或其他字段污染目标角色名。换角无法消费的内容自由度会明确拒绝，不再静默忽略。
- `/方案` 明确拒绝控制与换角字段；`/anima draw --llmcc` 接入专用换角链；`/换角色` 区分引号错误与枚举错误；`/放大` 区分未知选项与倍率格式错误。本版不增加 Python 依赖、ComfyUI 节点、模型或工作流文件。

## [2.0.1] - 2026-08-04

### 每用户 FIFO 图片任务队列

- 同一用户已有图片任务时，普通生图、反推、反推画图、语义换角、整图改图、底图控制、RTX 放大和遮罩重绘统一进入个人 FIFO 队列，不再返回“等待完成后重新发送”。
- 默认每位用户最多等待 3 个任务；新增 `max_queued_jobs_per_user`，支持 0–10，并同步加入 AstrBot 配置、独立 WebUI 和原生 plugin-page。排队期间的后续指令不受普通冷却误拦，队列容量仍限制连续提交。
- 入队时主动回传位置，轮到时再次通知并自动执行。`/anima status` 显示插件运行/等待数量；`/anima cancel current|queue|all` 与任务中心支持取消当前、等待队列、全部或指定排队项。
- 普通生成任务也进入持久任务中心。队列只持久化脱敏运行元数据，不保存提示词、图片或消息对象；插件重启后无法恢复的 queued 图片任务会明确标记为 interrupted。
- 修复“排队协程尚未真正启动就被取消”时任务中心残留 queued 的竞态。取消入口会主动写入终态并从 FIFO 移除，协程侧清理保持幂等。
- 本版不增加 Python 依赖、ComfyUI 自定义节点、模型或工作流文件。

## [2.0.0] - 2026-08-04

### 多人语义换角与 LoRA 三层身份架构

- 语义换角从单主体升级为最多六个可观察角色槽位。用户继续使用自然语言指定来源角色，例如“把黄色头发的角色换成目标角色”，插件按明确身份、唯一性别、唯一外观组合、衣装/动作组合的顺序选择；左右方向只在双胞胎式歧义无法消除时作为最后兜底，不新增 `--subject` 一类参数。
- 多人场景会保护未选中的角色特征和角色 LoRA。被选中角色的身份与稳定外貌才允许移除；其他角色的头发、服装、动作、位置和 LoRA 不得被分类模型越权删除。`--preview` 继续保证不提交 ComfyUI。
- `/画图 ... --llm cc u`、`--llm c u`、`--llmcc u`、`--lcc u` 与 `/反推画图 ... --l cc u` 共用同一换角入口。反推结果可表达最多六个角色的性别、外观、衣装、动作和位置；VLM 只负责观察，本地确定性代码负责选择与保护。
- LoRA 语义档案升级为 Schema v3，彻底分离 LoRA 文件身份、共享/角色专用激活词和 Danbooru Character/Copyright canonical。文件名、标题、别名、描述或激活词只可帮助发现，不能授权角色身份；LLM 也不能写入身份绑定字段。
- 新增 `identity_bindings[]` 与 `activation_terms[]`。人工绑定有 SHA-256 时跟随 LoRA 文件内容，Manager 描述、Tags 或训练词变化不会令其失效；文件 SHA 改变后立即失效。无 SHA 时才使用语义指纹保护。
- 修复 `black deniav1-2.safetensors`、`black_denia` 与 `denia_(wuthering_waves)` 被误当成同一名字的问题。普通 `/画图 --llm`、文字换角和反推换角都可同时保留正确 canonical 与一个或多个独立激活词；激活词不会进入 Character exact，也不能借同名碰撞注入额外身份。
- 两套 WebUI 的 LoRA 详情同步增加共享激活词和逐角色 Danbooru exact 绑定编辑。保存时实时核对 Character/Copyright exact 与作品一致性；旧客户端未发送新字段时保留已有绑定，显式空数组才清除。
- Prompt Contract 升级到 v3.0，明确多人角色归属、身份授权与激活词边界。本版不增加 Python 依赖、ComfyUI 自定义节点、模型或工作流文件。

## [1.9.24] - 2026-08-04

### Danbooru Schema v2、持续更新与统一角色证据链

- 本地 Danbooru 索引升级到 Schema v2，支持 Alias 一对多、全局歧义与 canonical/category 冲突；旧 Schema v1 继续只读兼容，但不会被错误升格为新快照能力。括号无论被转义一层或多层，最终只输出一层 ComfyUI 安全转义。
- 新增从官方 `/tags.json` 与 `/tag_aliases.json` 生成索引的持久任务。使用固定 API 高水位、正向 ID 游标、identity/full 模式、General/Meta 阈值、代理、限速、429/5xx 重试、断点续传、内容哈希、完整性退化保护和原子替换；失败或取消保留旧库。
- 新增可选定期更新：默认关闭，开启后默认每 168 小时运行；启动到期补跑、失败 6 小时退避、重复任务复用，并在任务中心和提示词工坊显示当前状态与下次时间。
- 新增共享 LoRA 身份证据层。当前角色/作品元数据、实时训练触发词、未过期语义档案、中文/罗马字配对和管理员多语言 CSV 只发现候选；本地 Character/Copyright exact 才能授权。新下载但尚未归档的角色 LoRA 请求也会开放最新 LoRA 工具并强制刷新。
- 修复多角色 LoRA 截断、作品名误选唯一角色 LoRA、描述词污染严格别名、`Fate/Grand Order` 拆分、`hatsune_miku` 无作品后缀、空格/下划线不等价、角色括号误作权重、索引更新过程中混用 revision，以及 LLM 未声明的未知 `character_(work)` 绕过最终门等问题。
- WebUI 两套入口同步增加官方 API 参数、自动更新开关、进度、检查点、Alias/冲突/来源截止与本地化 CSV 状态。本版不增加 Python 依赖、ComfyUI 节点、模型或工作流文件。
- `--llm cc u` 现在作为明确的换角 Ultra 入口加入帮助与回归。Standard 最多采用 6 项可信稳定外貌，Ultra 最多采用 10 项；本地 exact、Gallery 与当前 LoRA 证据门保持不变，不会用更高预算换取角色幻觉。

## [1.9.23] - 2026-08-04

### 本地快照缺项角色授权与终端修复兼容

- 修复薇欧拉一类“当前 LoRA Manager 元信息唯一且在线 Danbooru Gallery 能 exact 确认，但插件内置 Danbooru 快照尚无该 Character”的错误拒绝。授权链固定为：当前唯一可加载角色 LoRA → 本地 Copyright exact → 构造有界 canonical → Gallery category-4、非弃用、同名 exact。
- 外部 exact 只在单个当前角色 LoRA 文件上建立请求级授权，不写回本地 SQLite，也不会成为全局别名。该授权贯穿提示词编译、角色 LoRA 绑定、触发词注入后复核和额外身份拦截；多 LoRA、跨作品、错分类、已弃用或 Gallery 离线继续 fail closed。
- 资产工具完成查询后的第二次调用改为无工具严格 JSON 修复，同时兼容合法 `<pic>` 与 `emit_anima_plan_v1` 结构化响应。错误散文、未知字段、混合控制标签、重复/畸形 JSON 和错误工具调用仍被拒绝。
- 新增中文名加本地化作品标点、英文名无作品但当前 LoRA 唯一、Gallery 离线/错分类/已弃用、多个角色 LoRA 歧义、严格 JSON 修复和错误散文等回归。本版不增加依赖、ComfyUI 节点、模型或工作流文件。

## [1.9.22] - 2026-08-03

### 角色 LoRA 元数据绑定与无工具终端修复

- 修复本地资产工具首轮已经找到角色、作品、风格和 LoRA 后，第二轮协议修复仍继续携带同一批查询工具的问题。修复轮现在是独立的无工具 `<pic>` 终端调用，避免重复查询耗尽步骤后落入 `invalid_picture_protocol`。
- 将“角色 LoRA 属于谁”和“LoRA 用什么训练触发词激活”拆成两个证据域。角色归属由当前可加载记录中的角色名与作品元数据经过 Danbooru Character/Copyright exact 证明；`kei (student) (blue archive)` 之类非 canonical 训练触发词只在唯一身份绑定后用于激活。
- 新增混合名称桥接：`《BlueArchive》Kei`、本地化作品名加 ASCII 角色名会先 exact 作品，再构造并 exact 验证 `kei_(blue_archive)`。CamelCase 作品名会安全归一化，不进行模糊授权。
- 保持原有 fail-closed 边界：多角色 LoRA、作品冲突、不能唯一绑定的角色资产和额外 Character 身份仍会被过滤或停止。本版不增加依赖、ComfyUI 节点、模型或工作流文件。

## [1.9.21] - 2026-08-03

### 多语言角色名转译与作品消歧

- 新增独立 `LocalizedCharacterAliasIndex`，允许一个中文、日文或韩文 alias 对应多个 Danbooru Character canonical；本地化数据只发现候选，不能直接授权角色身份。
- `search_anima_danbooru_tags` 现在可识别 `《作品》的角色` 形式。`《鸣潮》的菲比` 会先把“鸣潮” exact 到 Copyright `wuthering_waves`，再唯一选择并 exact 复核 Character `phoebe_(wuthering_waves)`；裸“菲比”因同名风险要求作品，不按热度猜选。
- 所有 LLM 生图入口的提交前角色编译器复用同一解析层，并在命中后再次走原有 Character identity resolver。任务时间线新增脱敏事件 `localized_alias_exact_used`，不保存完整用户提示词。
- 支持管理员自行放置 Autocomplete-Plus 兼容的 `tag,category,count,alias` CSV 到插件数据目录。外部数据集不随源码或发布包再分发，来源、许可证和更新责任由管理员管理；损坏 CSV 不会禁用内置事实修正。
- Prompt Contract 升级为 v2.1，明确要求本地化角色查询携带作品限定，并禁止候选按热度授权。本版不增加 Python 依赖、ComfyUI 节点、模型或工作流文件。

## [1.9.20] - 2026-08-03

### Prompt Contract v2、普通聊天终止守卫与跨语言角色别名

- 将绘图导演拆分为版本化、按任务加载的最小合同：普通生图、Prompt Plan 增量、反推画图、整图语义改图、底图控制、遮罩重绘和换角中间编辑分别声明职责；`<pic>`、`<edit>`、Function Call 与严格 JSON 传输互斥，不再用“忽略前文规则”覆盖输出协议。Auto Function 响应一旦出现畸形、冲突或错误工具调用，不会再接受同一响应夹带的 `<pic>`，只能通过下一次独立修复或安全停止。
- 重写内置 `director_reference.txt` 为纯创作参考。动态 System Prompt 只注入本次实际可用的 LoRA、Danbooru 或 Prompt Plan 能力；遮罩重绘、换角中间编辑与 Prompt Plan 不再承载整图场景扩写手册。结构化 JSON 拒绝重复键、NaN/Infinity、非对象根、未知字段和非字符串角色声明。
- 新增普通聊天资产查询终止状态机，覆盖 LoRA、风格组合、Danbooru 与 Prompt Plan 工具。启用守卫时普通 Agent 回复强制完整缓冲；所有工具调用必须完成且零失败，最终只允许一个合法 `<pic>`，多 `<pic>`、`pic+edit`、裸 Tags、假完成文案和纯查询误出图均被修复一次或失败关闭。
- 终止修复只携带本轮插件生成的有界资产证据，不信任模型泄露的裸 Tags；精确 LoRA 文件名、保存组合控制和 verified canonical 可继续进入修复结果。失败分支同步清理 reasoning、会话最后一条 assistant 文本、事件状态与 LoRA 快照；AstrBot 真实取消标志会在任何修复调用前终止并完成同样清理。
- 内部 LLM 事件隔离改为引用计数，避免同一 QQ 事件中的重叠反推、分镜或修复调用提前解除普通聊天协议隔离。
- 修复 `飞鸟马时（toki）`：用户紧邻角色名写出的 ASCII 别名可独立发现候选，但最终 Character canonical 与基础 identity root 仍须 exact；没有角色 LoRA 时也能确认 `toki_(blue_archive)`。未声明 `characters` 且提示词同时含基础身份与 Bunny/Armed 变体时，只保留 exact 基础 canonical；只有多个变体而不存在基础 canonical 时继续停止。
- 用户显式作品名现在优先进入有限 work hints，外貌证据阶段复用包含作品与别名的查询上下文。角色 LoRA 继续只是可选增强；工作流注入前会把每个已选择 LoRA 的原子触发词重新通过本地 Character exact，并要求命中的身份与最终 canonical 完全一致，即使该 LoRA 被误归档为画师/风格也不能绕过角色闸门。Armed/Bunny 等变体不会替代基础身份，无法绑定的自动候选会被真正移出 `dynamic_loras` 后回退语义 Tags，而不是只跳过触发词却继续加载模型。
- 独立端口 WebUI 与 AstrBot 原生插件页同步新增“普通聊天绘图终止守卫”开关和完整缓冲说明。本版不增加 Python 依赖、ComfyUI 自定义节点、模型或工作流文件。

## [1.9.19] - 2026-08-03

### 全图 LLM 角色证据编译

- 新增统一的提交前角色编译器。自然语言绘图、`/画图 --llm`/Ultra、普通聊天 `<pic>`、反推画图、无蒙版整图改图、底图控制和带 LLM 追加要求的 Prompt Plan 均使用同一角色校验阶段；纯 `/画图` 原始 Tags 与局部遮罩重绘不强制改写。
- `<pic>`、JSON 与请求内 `emit_anima_plan_v1` 新增可选 `characters` 身份声明。声明仅作为查询提示，最终必须由本地 Danbooru Character exact 或唯一别名确认；Copyright 只负责作品限定，模糊、跨作品冲突和虚构 canonical 均在 ComfyUI 提交前停止。
- 最终正面提示词中的 Character/Copyright Tags 会再次批量 exact 扫描。角色 canonical 统一转义并放回主体锚点附近，错误角色和错误作品被移除；即使 LLM 忘记声明角色，只要最终 Tags 能 exact 命中仍会进入校验。
- 单角色外貌只接受公开安全级 Danbooru Gallery 共现档案、当前唯一角色 LoRA 的原子稳定外貌，以及用户明确指定的覆盖。未经证据支持的发型、发色、发饰、瞳色、耳型、体型和独特身体特征会删除，冲突关系句与负面角色特征同步清理。
- 多角色仅执行逐身份 canonical 与错误 Character/Copyright 清理，不做无法安全绑定人物的全局外貌删除。当前角色 LoRA 仍只是可选增强，文件存在和触发词来自每次任务的最新 Manager/ComfyUI 快照。
- 任务中心新增 `llm_character_validation_*` 与 `llm_character_prompt_compiled` 阶段事件，只记录来源、数量、证据类型和覆盖槽位，不保存原始提示词、Provider 原文或隐私内容。

## [1.9.18] - 2026-08-03

### 混合提示词换角与反推协议隔离

- 绘图参数解析不再用空格重组原始提示词；Tags、英文画面句与中文换角要求的换行会保留，只剥离已识别的选项。裸 apostrophe、Danbooru 反斜杠、短参数和带引号选项保持兼容。
- Provider 给出的作品限定会先通过本地 Danbooru Copyright exact 或唯一标点变体确认，再构造 Character 候选。`firefly_(honkai_star_rail)` 可安全归一为 `firefly_(honkai:_star_rail)`；冲突、模糊或碰撞仍然 fail closed。
- `/反推`、`/反推画图`、整图改图、图片换角和底图控制的反推阶段，在首次调用与 JSON 修复重试的完整窗口内隔离普通聊天 `<pic>` 协议，避免 JSON-only 请求被绘图人设污染。
- 普通换角若仍有 `uncertain_tags`，首次错误直接显示最多三个具体未决词；预览最多显示十二个，任务数据库仍只保存脱敏 ID 与计数。
- 新增 Firefly 混合提示词端到端回归，要求本地确定性特征替换、零未决项、保留衣装/镜头/场景关系并移除旧角色外貌。

## [1.9.17] - 2026-08-02

### 多源外貌证据与逐槽位安全降级

- 修复 v1.9.16 的“Gallery 缺一个核心槽位就整单停止”。当前角色 LoRA 或 Danbooru Character exact 已精确确认时，缺失槽位会删除旧角色值、拒绝猜测新值，并由 canonical/角色 LoRA 的模型原生知识兜底。
- 保留弱身份路径的安全门槛：没有精确 LoRA、也没有本地 Character exact 时，发型、发色或瞳色缺少可信替代证据仍然停止，不允许 Provider 猜测绕过校验。
- 将当前唯一命中角色 LoRA 的原子稳定外貌触发词纳入证据包，并与 Danbooru Gallery 共现档案去重合并；角色身份、衣装、动作、场景与质量词不会被误归为外貌槽位。
- 新增逐槽位决策结果、证据来源和模型原生兜底类别。任务中心记录 `character_swap_model_native_slot_fallback`，预览与普通生成结果会明确说明哪些源特征已删除、哪些目标特征有证据、哪些未猜写。
- 增加 Kei 类缺瞳色回归：12 个 Gallery 样本、四项非瞳色外貌、精确当前角色 LoRA 时不再整单失败，同时不得保留错误源瞳色；另有无精确身份对照测试保证 fail closed 未被削弱。

## [1.9.16] - 2026-08-02

### Danbooru Gallery 角色证据与槽位化换角

- 直接调用 ComfyUI-Danbooru-Gallery 的网络状态、Character autocomplete 与帖子接口；LoRA 已精确命中时也必须解析 canonical 和稳定外貌，不再只给纯语义回退使用。
- 角色外貌缓存升级为 v2。只接收 safe、solo、单一精确 Character 的有效帖子，排除删除、待审、封禁以及 alternate hair、palette swap、genderbend、cosplay 等非默认变体。
- 发色与瞳色使用“该槽位有标注的样本数”作为支持率分母，同时保留覆盖率门槛；新增发髻、单侧髻、发饰、X 发饰、发夹、嘴下痣等具体槽位，具体 Tag 优先于泛化 Tag。
- 修复目标 LoRA 触发词与 Gallery 外貌二选一、加载目标 LoRA 时主动丢弃外貌、最终校验不检查目标外貌三项根因。目标 LoRA、canonical 与可信外貌现在合并写入正面提示词，并从负面提示词清理。
- 新增槽位守恒：运行入口删除源发型、发色或瞳色后，若目标证据缺少对应核心槽位则停止提交 ComfyUI；任务中心与 QQ 结果显示目标外貌数量、来源和特征类别。

## [1.9.15] - 2026-08-02

### 限定范围的角色特征替换器

- 消化 A佬工作流 `CharacterFeatureSwapNode` 的有效设计：显式换角默认只替换发型、发色、发饰、瞳色、独特身体特征、体型与耳型，不再要求每个普通 Tag 都完成身份/衣装/画面全量分桶。
- 新增 `local:character-feature-swap` 确定性路径。目标角色仍须由当前 LoRA 或本地 Danbooru character exact 证明；源 Prompt 即使没有 Character Tag，也可以删除明确的旧角色特征并插入目标身份。
- 未索引的场景、材质和描述词默认保留，因此 `spot light`、`leather texture` 等普通词不会再触发整单 `uncertain_tags`；加权或复合外貌组、多角色和目标身份不确定仍回退严格 Provider 路径。
- 发饰与耳型边界独立处理：hairband、hair ornament、rabbit ear hairband 可替换，ear piercing、earrings、in-ear monitor 等耳部附件保留；衣装、动作、镜头、背景与材质不受角色特征替换影响。
- 修复 Copyright 清理范围：只有能与明确源 Character lineage 对齐的作品 Tag 才随源角色删除，未匹配的 Copyright 不再因分类模型误判而被无条件移除。
- 任务中心和 QQ 结果会显示“角色特征替换器（未调用 LLM）”、七类替换范围与实际删除数量。新增真实 Rio 舞台 Prompt、无源 Character、未索引普通词、耳饰边界、Copyright 守恒及入口路由回归。

## [1.9.14] - 2026-08-02

### 换角分类入口路由验证

- 将“本地确定性分类优先、LLM 分类兜底”提取为独立入口路由，普通 QQ 换角命令与底层规划器使用同一决策路径。
- 新增入口级异步回归：完整本地证据时 Provider 调用必须为零并记录 `character_swap_classifier_bypassed`；不完整证据必须调用原严格 Provider 分类。
- 保留 v1.9.13 的本地 Danbooru 快路径和脱敏失败证据，并避免同版本不同构建覆盖已部署包。

## [1.9.13] - 2026-08-02

### 本地确定性换角快路径与失败证据

- 当源提示词已由本地 Danbooru exact 四分类完整覆盖、目标身份可确定且处于普通保留衣装模式时，直接构造完整换角分类，跳过 LLM Provider 调用。
- 快路径只接受一个可证明的源角色；Character 与匹配 Copyright 清理，稳定外貌清理，General 衣装、附件、动作、镜头、场景、效果与状态保留。未索引或复合歧义项自动回退原严格 LLM 分类，不放宽安全边界。
- 截图中的 75 项 Eri → Viola 提示词可由 74 项 exact 证据加一个受控表情 Tag 全本地完成，目标 LoRA 与触发词保持 `viola-000020.safetensors + Viola`。
- `image_task_failed` 新增经过任务存储脱敏的 CharacterSwapError 详情，可显示具体 Tag ID、Danbooru 类别和验证状态，同时继续屏蔽完整 Prompt、Provider 正文、路径和凭据。

## [1.9.12] - 2026-08-02

### 本地 Danbooru 四分类接入语义换角

- 在换角分类前批量 exact 查询源提示词的本地 Danbooru 分类，并把 `Character`、`Copyright`、`Artist`、`General` 证据传给受约束分类模型。
- `Character` 与源作品 `Copyright` 由确定性规划强制清理；`Artist` 保留为风格；`General` 只有稳定头发、眼睛、物种、halo、体型等外貌会删除，衣装、附件、动作、镜头、场景和暴露状态会纠偏保留。
- 修复 75 项密集 Eri 兔耳提示词连续触发 `unsafe_source_identity_classification`：即使模型把 hairband、leotard、earrings、afterimage、pose、background 等 General Tag 放入身份或未决桶，本地 exact 类别也会覆盖错误归类。
- 扩充确定性外貌与附件边界：支持 breast-size wrapper、low ponytail、side/single braid、hair streaks、halo 颜色/形态、眉形、species-girl；fake ears、hairband、bow、collar、earrings、jewelry 与 leotard 按附件/衣装处理。
- 任务时间线新增源 Tag exact 四分类数量与 General/Artist 纠偏计数；不可用时记录降级并继续原严格路径，不保存完整提示词或 Provider 响应。

## [1.9.11] - 2026-08-02

### 密集 Danbooru Tags 换角分类修复

- 修复最终残留误报：顶层 Tag 改用精确匹配，只有加权或复合组继续使用有边界的包含校验，避免 `black hair -> black hairband`、`animal ears -> fake animal ears`、`tongue -> tongue out` 等误伤。
- 增加严格 Danbooru 角色 lineage 清理：相同角色名、相同最终 Copyright 的 costume variant 与独立 Copyright 上下文会随源角色一起移除，不会把其他作品角色误并入。
- 对分类结果增加确定性覆盖：稳定源外貌统一清理，明确衣装和普通暴露、表情、状态 Tags 自动纠正并保留，模型把 `official alternate costume`、`areola slip` 等误分为身份时不再误删。
- 仅在当前精确角色 LoRA、确定性触发词、单主体、无未决 Tag 且所有删除项通过严格校验时，将分类最低置信度放宽到 `0.75`；`0.74`、仅元数据、Danbooru/Provider 纯语义路径继续按原门槛拒绝。
- 任务时间线新增分类实际置信度、安全门槛、角色变体归并数及普通画面 Tag 修复数，便于定位每次换角的真实处理阶段。

## [1.9.10] - 2026-08-02

### 真实 LoRA/Danbooru 短名桥接修复

- 对已由可信 LoRA 归档得到的短角色名与 Copyright 作品提示，构造有限的 `character_(work)` 候选并重新通过本地 Danbooru `Character` exact 校验。`Rio + Blue Archive` 现在可直接确认 `rio_(blue_archive)`，不会因 `rio` 同时存在 Armed、Dress 等前缀结果而失败。
- 修复多角色语义归档把显式 ASCII 角色名借用到相邻角色的问题。用户写明 `(rio)` 时只保留 Rio，不再因归档中罗马字姓名的排序方式误加入 Toki。
- 对当前唯一可加载、已归档为角色且分析置信度足够的 LoRA，允许从可信角色名/别名中选择与用户复合中英文名称一致的单一触发词。即使本地 Danbooru 快照尚未收录新角色，`viola-000020.safetensors` 仍可使用归档中的 `Viola`，但不会放宽到其他文件或不确定身份。
- Danbooru 四分类权限保持不变：Character 才能授权索引身份，Copyright 只构造作品限定，Artist 不参与角色命中，General 仅用于外貌/画面属性；写入 ComfyUI 的角色括号继续统一转义为 `\(` 与 `\)`。

## [1.9.9] - 2026-08-02

### Danbooru 四分类与多角色 LoRA 换角回归修复

- 严格固定 Danbooru 的 Artist、Copyright、Character、General 边界：只有本地 `Character` exact/唯一 alias 能授权目标身份；Copyright 只约束作品，Artist 不参与角色命中，General 只补稳定外貌或其他画面属性。
- 可信 LoRA 语义归档现在可把中文角色名桥接为有限的罗马字 discovery 候选，再交给本地 Character 索引复核。修复 `《BlueArchive》的调月莉音` 被无关 Kirino/Chise 候选阻断，以及 Viola 复合中英文名称无法命中已有 LoRA 的问题。
- Civitai 单条 `trainedWords` 中的“角色身份, 默认服装, 细节”会先拆成独立 Tags；多角色 LoRA 必须按用户目标唯一选择对应身份，不再默认取第一个角色。用户未要求 Armed 等变体时，多角色变体包只辅助查明 canonical，默认改用普通语义身份，显式要求角色 LoRA 时才加载对应变体触发词。
- 已由当前 LoRA 元数据唯一确定的身份 ID 会覆盖分类模型把同一 ID 重复标为外观/衣装的错误，避免无意义的两次 JSON 修复失败。索引态统一使用普通括号比较，写入 ComfyUI 时统一输出 `\(` 与 `\)`，消除正负提示词触发词一致性误报。

## [1.9.8] - 2026-08-02

### 强制角色 LoRA 与换角衣装分类热修复

- 文字换角和自然语言换角现在识别“请使用/必须使用角色 LoRA”等正向控制语句，并在解析后从目标角色与额外编辑要求中剥离，避免误触发非身份改图导演。
- 用户明确要求角色 LoRA 时，插件只接受本次强制刷新后的 LoRA Manager 与 ComfyUI 可加载清单中唯一确认的目标文件；缺失、跨身份歧义或无法唯一选定时明确停止，不再静默回退纯语义 Tags。
- 对分类器落入 `uncertain` 的明确单项衣装 Tag 增加整词级确定性修复，例如 `buruma`、`white thighhighs`、`shirt` 和 `uniform`。衣装会按换角模式保留或替换，不再阻断已经唯一确认的目标角色 LoRA。
- 确定性衣装词表与全局身份安全词表保持隔离，避免 `bra` 子串误伤 `twin braids` 等角色发型；成功回复与任务日志会明确记录实际加载的目标 LoRA、权重及是否为用户强制要求。

## [1.9.7] - 2026-08-01

### 无作品限定 Danbooru 角色换角热修复

- 修复 `hatsune_miku` 等合法角色 canonical 因名称片段碰巧包含服装词而被 LoRA 触发词启发式误拦截的问题；纯中文“初音未来”现在可先由 Provider 给出 discovery canonical，再由本地 Danbooru `character` exact 索引授权。
- 无限定 canonical 只作为检索候选，绝不会仅凭 Provider 回答直接放行。未知角色名、本地索引缺失、分类不是 `character` 或候选冲突都会安全停止；`blue_hair`、`school_uniform`、`1girl` 和质量词仍不能伪装成角色身份。
- 统一前段 JSON 校验与最终换角规划器的身份合同，避免角色在解析阶段 exact 成功后又被第二道 LoRA 规则误判。

## [1.9.6] - 2026-08-01

### 密集提示词下的语义换角身份增强

- 修复纯语义换角把目标 canonical 固定追加到提示词末尾的问题。exact 身份现在使用 ComfyUI 安全括号转义，并插入 `1girl/1boy, solo` 之后、场景与风格词之前。
- 修复自然语言风格预设只识别不消费的问题；已解析的 `风格006`、完整显示名称和显式“使用风格”短语不会继续污染 CLIP 正向提示词。清理时不再遍历删除全部别名，避免误删 `masterpiece`、`anime` 等合法画面 Tags。
- 新增可选的 Danbooru 稳定外貌证据：对已经由本地 `character` exact/唯一 alias 确认的目标，通过当前 ComfyUI 的 Danbooru Gallery 查询最多 100 张公开安全级单人帖子，按至少 12 张样本和 65% 支持率提取最多四项发色、瞳色、发长、光环等稳定特征。
- 外貌证据只保存 canonical、聚合 Tag、支持率、样本数和时间，不保存原始帖子、图片或 URL；衣装、动作、身体尺寸和低支持率特征不会进入缓存。用户明确要求修改头发、眼睛、光环、耳朵或肤色时，相应默认特征自动让位。
- 修复 Danbooru Gallery 分块响应被单次 `read()` 截断的问题；客户端现在持续流式读取到 EOF 并保持 12 MiB 硬上限。聚合器只接受明确 `rating=g`、`solo`、唯一角色、非删除/待审/标记且 Post ID 不重复的样本，缓存读取也会重新验证 canonical、来源、白名单 Tag、支持率和时间戳。
- 正负提示词比较现在将 `black_hair` 与 `black hair` 视为同一语义项，避免重复注入，也会清除负面提示中与目标稳定外貌冲突的下划线形式。
- 使用同一 UNET、同一 Seed、同一风格006 栈进行了 512×512 对照：单 canonical 可识别 Rio；仅提前、轻度加权或转义在密集彩色光效提示中仍会失效；严格过滤后 83 张有效样本仍稳定给出 `black hair, red eyes, long hair, halo`，加入这些真实共现证据后恢复目标身份。

## [1.9.5] - 2026-07-30

### 生成耗时分段统计

- 图片生成结果新增总耗时、插件内 LLM 提示词处理、ComfyUI 提交/生成/下载，以及 LoRA 刷新、工作流构建、上传和安全校验等准备耗时。
- 普通绘图、自然语言绘图、方案追加、反推画图、语义换角、底图控制、局部重绘、整图改图和独立 RTX 放大统一使用同一套安全计时元数据；未调用插件内绘图导演时明确显示“LLM 提示词：未调用”。
- 分段统计只保存秒数和调用次数，不记录提示词正文、Provider 原始响应或其他敏感内容。

## [1.9.4] - 2026-07-28

### Danbooru exact 角色只保留 canonical 身份

- 本地 Danbooru `character` exact 或唯一 alias 一旦确认已知角色，正面身份现在只注入规范 canonical Tag，例如飞鸟马时只新增 `toki_(blue_archive)`。
- Provider 返回的发色、发型、瞳色、体型等外貌候选会在 exact 身份路径全部丢弃，避免 `long white hair`、`twintails` 等模型记忆对已知角色造成过约束、冲突或幻觉。
- 原创角色仍保留用户指定的稳定外貌；本地索引无法 exact 确认而进入受控 Provider 回退时，仍可使用经过分类器高置信验证的有限外貌候选。

## [1.9.3] - 2026-07-28

### 本地 Danbooru 角色精确检索

- 语义换角现在优先查询管理员导入的本地 Danbooru `character` 分类。用户直接给出英文 canonical 或唯一 alias 时可在调用绘图模型前完成确认；纯中文请求会让绘图模型同时返回 canonical、最多八个同角色罗马字候选与作品提示，再由本地索引批量 exact。
- 新增安全查询变体：例如 Provider 返回并不存在的 `asuma_toki_(blue_archive)` 时，会剥离最后作品限定查询唯一 alias `asuma_toki`，并复核返回 canonical 的作品仍为 `blue_archive`，最终稳定固定到 `toki_(blue_archive)`。兔女郎等变体保持独立，错误作品限定不会借用同名 alias。
- Prefix、keyword、Embedding 与 Rerank 只能处理本地索引生成的有限候选池；任何候选在使用前都必须重新通过 `character` exact。多个不同角色身份冲突时，Embedding/Rerank 只给出候选顺序，插件仍会停止而不猜选。
- 任务时间线与 `--preview` 增加 Danbooru 查询变体、匹配类型、候选数量、Embedding/Rerank 可用状态和 exact 结果说明，不记录 Provider 原始回复或完整用户提示词。
- 已使用 `.88` 的真实 111,513 项索引验证飞鸟马时、兔女郎飞鸟马时、今汐与 RIO；其中角色分类共 32,091 项。

## [1.9.2] - 2026-07-28

### 文本换角安全边界与命令参数热修复

- `/画图` 与 `/画图no` 的文本换角现在完整支持 `--preview` / `--v`、`--no-character-lora` / `--no-lora` / `--nl`、`--weight` / `--w`、`--mode keep-outfit|target-outfit` 与 `--m k|t`，且选项可放在 `--llm c`、`--llmcc` 或 `--lcc` 前后。换角与 ControlNet 模式、`--raw` / `--no-llm` 明确互斥，避免参数顺序导致静默失效或错误路由。
- 修复共享外貌被误判为原角色残留的问题：只有经高置信目标证据明确选中的原子外貌才能在最终提示词中重新授权，例如原角色与目标角色都具有 `long hair`，或目标候选明确为 `long silver hair`；加权、复合或未经目标证据确认的片段仍会失败关闭。
- 对分类器落入 `uncertain` 的原子稳定外貌增加窄范围确定性修复，只处理发色、发长、发型、瞳色、肤色、物种特征和体型等可验证单项；饰品、表情、镜头、光影、衣装、加权组及复合语法不会被自动吞并。仍有未决项时继续停止提交，预览模式会直接列出未决 Tags。
- 已知角色的可选外貌证据统一要求分类置信度至少 `0.92`；不足时保留已验证的 `character_(work)` 主身份并丢弃可疑外貌，不再因模糊细节污染角色身份，也不要求必须补齐眼耳口鼻发色。

## [1.9.1] - 2026-07-28

### 纯语义角色身份热修复

- 已知角色改为以一个合格的 `character_(作品)` canonical Tag 作为主身份锚点；目标外貌从必填式清单收敛为 0–4 项可选高置信证据。模糊、争议或只记得一部分的发型、瞳色、耳型、体型等外貌会被省略，不再为了凑数量污染目标身份。
- 本地 Danbooru 索引的 `character + exact + verified` 结果会规范化并固定 canonical 主锚点；后续分类器只评估源 Tags 清理和可选外貌，不再重新否定已 exact 证明的身份。LoRA exact、Danbooru exact、Provider 高置信和普通 Provider 结果使用分层证据与对应门槛，prefix/keyword/fuzzy 仍不能直接授权身份。
- 用户目标或附加要求中的“置信度 100%”“confidence=1”等自定义置信度会被移除并标记为忽略，不能覆盖 Provider、Danbooru 或最终分类安全阈值。
- 修复角色别名含 `/` 时被误判为显式 LoRA 路径的问题，例如 `今汐/今夕` 现在仍按自然角色别名解析。严格文件语义仅由 `lora:` 前缀或 `.safetensors`、`.ckpt`、`.pt`、`.bin` 后缀触发。

## [1.9.0] - 2026-07-28

### `/画图` 显式文字换角

- `/画图` 与 `/画图no` 新增仅由指令触发的文字换角模式：`--llm c`、`--llmcc`、`--lcc`；可与 Ultra 组合为 `--llm c u`、`--llmcc u`、`--lcc u`。普通聊天、`/anima draw` 和普通 Standard/Ultra 分镜不会自动启用该模式。
- 输入格式固定为“完整原 Tags，把角色换成目标角色”；后续可继续写换装等覆盖要求。该路径直接复用既有确定性语义换角、权限、风控、LoRA 双刷新和工作流提交链，不会先让普通绘图导演自由改写边界。
- 换角会删除旧角色姓名、作品身份以及发型、发色、瞳色、异色瞳、耳角尾、体型、痣等稳定外貌；服装、动作、表情、视线、构图、背景和风格默认保留，除非用户明确覆盖。
- 目标角色 LoRA 改为可选增强：最新清单中可唯一确认时使用；完全缺失或同一身份存在多个版本而无法唯一选择时，使用经验证的纯语义 Tags。显式模型文件、跨身份歧义、近似名称和不可信候选仍失败关闭，不会猜选。
- 原创角色支持用户直接给出发色、瞳色、耳型、物种、体型、痣等稳定外貌；语义规划必须建立至少三项协调特征，并禁止继承原角色未指定的身份外观。

### 命名风格与 LoRA 错误可观察性

- 保存的命名风格支持完整名、唯一派生别名、直接称呼和常见倒装语序；例如 `风格GZC`、`GZC`、`用风格GZC` 与 `风格使用gzc` 可解析为同一唯一组合，别名碰撞继续失败关闭。
- 动态 LoRA 精确校验开始区分保存风格、指令参数、绘图导演输出和用户提示词，并在日志与用户错误中保留脱敏后的具体缺失名称，避免把所有问题统一误报为“LLM 选择了不存在的 LoRA”。

## [1.8.4] - 2026-07-27

### Standard / Ultra 自适应视觉扩写

- 重构内置绘图导演提示词：吸收镜头分层、面部与发丝微观细节、服装结构与材质、手势接触、前中后景、环境互动、主光/轮廓光和色彩关系，同时拒绝把三段展示文本、8–10 个分析段或 10–15 个加权长句直接提交给 Anima。
- 新增 Standard 与 Ultra 两档密度。`--llm` / `--l` 保持稳定简洁；`--llm ultra`、`--llm u`、`--l ultra`、`--l u` 启用华丽高密度分镜。
- Ultra 允许更多有效 Tags、视觉短语、材质、空间和光影细节，以及不改变身份、服装类别、主动作和剧情结果的题材化装饰；仍禁止重复同义词、默认质量口号、整段权重和互相冲突的光源。
- 普通对话与内部绘图导演共享同一强制扩写协议；图片反推提示词也开始按镜头提取手势、接触点、材质、景深层次与光源关系，为改图和控制生成提供更完整的可观察证据。

## [1.8.3] - 2026-07-27

### LoRA 组合编辑、简称与实时触发词

- 组合新增独立简称/别名与管理备注；安全的 `风格数字 + 空格/括号 + 画师名` 显示名会自动派生数字简称，歧义仍失败关闭。
- WebUI 新增组合编辑、改名、取消编辑、简称和备注字段，并显示手动补充、LoRA Manager 最新元数据和角色/风格规则处理后的最终有效触发词。
- 修复手动触发词会屏蔽组合成员 Manager 触发词的问题。手动值现在作为补充；生成前仍强制刷新 Manager 与 ComfyUI，并按角色身份、风格和功能分类安全合并。
- `/lora组合保存` 增加 `--alias` 与 `--note`，旧配置无须迁移即可继续读取。

## [1.8.2] - 2026-07-26

### 显式命令防止被自然语言路由抢占

- 修复 `/画图 ... dramatic pose ... --llm` 被高优先级底图控制路由误判、随后要求附图并终止事件的问题。
- 自然绘图、底图控制、语义改图、蒙版重绘、换角色和 RTX 放大现在统一检查 AstrBot 已激活的命令处理器；显式命令一旦命中，自然语言路由立即退出。
- 兼容 AstrBot 在处理前移除 `/` 唤醒前缀的行为，并保留 `/帮我画一只猫` 这类仅使用斜杠唤醒、但未命中显式命令的自然语言入口。

## [1.8.1] - 2026-07-26

### `/方案` 追加要求解析修复

- 修复 `/方案 EX-005 再出个cos给我看看` 把整段文字误当作方案名称、从而报告方案不存在的问题。
- `/方案` 现在先按 ID、完整名称或唯一短名称解析最长方案前缀，再把剩余文本作为追加画面要求；ID 大小写不敏感，名称尾部括号备注可省略，歧义继续失败关闭。
- 有追加自然语言时只调用一次绘图导演并保留未被明确替换的方案事实；显式 `--raw` 时直接追加高级 Tags，不调用导演。所有成功路径仍只进入一次 `_run_job()`，保留权限、风控、LoRA 强制刷新与提交前复核。

## [1.8.0] - 2026-07-26

### Danbooru Anima CSV 兼容

- 支持常见的无表头 `tag,category,count,aliases` Anima 导出，并仅清理超长或歧义别名，保留全部 canonical tag。

### LLM Danbooru 只读查询

- 绘图导演和普通对话 Prompt 会动态获知本地索引是否就绪、canonical / alias 数量与 revision，不再只知道“应输出 Danbooru 风格 Tags”。
- 新增 `search_anima_danbooru_tags` 只读工具，支持 exact、prefix、keyword 与最多 12 项的 batch 查询；只有 exact canonical / unique alias 结果会标记为 verified。
- 工具结果不暴露索引 URL、SQLite 路径、完整 provenance 或 SHA-256；LoRA 工具任务自动附带查库能力，普通确定性绘图仍保留 request-local 结构化快速路径。

### Prompt Lab 与 QQ 方案闭环

- Prompt Lab 确认候选时可持久化为短 ID `P-XXXXXX`；方案数据原子写入 AstrBot `plugin_data`，插件重载和升级后仍保留。
- 新增管理员命令 `/方案列表` 与 `/方案 <ID或名称>`。方案可继续覆盖 seed、分辨率、步数、CFG、管线和 LoRA 预设，但不会再次交给 LLM 改写；实际执行仍经过原有权限、敏感词、LoRA 实时刷新、提交前复核和 `_run_job()` 主链。
- 新增只读 LLM 工具 `list_anima_prompt_plans`，普通对话可先确认真实方案 ID，再按需读取完整提示词；非管理员不可查询，工具不会暴露持久化路径。
- 双 WebUI 增加方案名称、保存开关、方案库、复制 QQ 指令和自定义方案删除；内置 `EX-001` 至 `EX-005` 提供雨夜霓虹、海边烟花、和风庭院、低角度动作和咖啡馆暖光示例，不能覆盖或删除。

## [1.7.1] - 2026-07-26

### LoRA Manager 预览兼容修复

- 兼容 LoRA Manager 将 `preview_url` 的 `path` 作为独立预览标识、而不是 `.safetensors` 文件路径的部署方式。
- 仍只接受最新 Manager 清单提供的同源 `/api/lm/previews` 地址、单一 `path` 参数、无重定向和受限字节流；不接受客户端自定义 URL 或跨源地址。

## [1.7.0] - 2026-07-26

### 视觉提示词资产库

- 新增本地 SQLite 视觉资产库，支持角色、画师、服装、背景和姿势五类资产，以及名称/别名/Tags 搜索、收藏、自定义项和分类筛选。
- 支持管理员导入经审核的 JSON/CSV，保留数据来源、版本/命名空间、导入时间和 SHA-256；新快照会先在临时库中完整验证，失败时不覆盖上一份可用数据。
- 远程导入默认关闭。显式开启后仍只允许解析到公网地址的 HTTPS，并受 DNS/IP 固定、禁止凭据/重定向、单次最大 16 MiB、记录数和字段长度等边界约束；局域网数据改用粘贴或上传 JSON/CSV。
- 安装包不捆绑任何第三方大型提示词数据、索引或预览图。

### 分层提示词编辑与 Prompt Lab

- 提示词工坊增加身份、服装、姿势、镜头、背景、画师/风格、场景关系和 LoRA 八个明确槽位，可单独编辑、锁定和重新组合。
- 新增确定性 Prompt Lab：相同 Seed、资产池和锁定层会生成相同的 1–6 个候选，更换非锁定层时不会破坏已锁定身份、LoRA 或其他强约束。
- Prompt Lab 候选是有容量和 TTL 的无执行草稿，创建候选不会自动提交 ComfyUI。确认时会再次核对素材 revision、LoRA 最新清单并经过 Prompt Composer；确认结果要实际出图时仍须进入普通 QQ 绘图入口，由原有权限、风控和工作流校验负责最终提交。
- 分层编辑和候选重组为本地确定性过程，不会增加额外 LLM 请求，也不会暴露隐藏思维链。

### LoRA 视觉清单与本地缩略图

- 新增 LoRA 视觉 manifest，对当前语义清单生成稳定指纹，展示精确文件、分类、元数据和预览状态，并支持分页、筛选、收藏、受限预热和缓存裁剪。
- 缩略图优先使用显式 `lora_visual_roots` 白名单下的精确同名 companion 图。如果 AstrBot 容器没有 LoRA 挂载，可改由 LoRA Catalog 调用当前 Manager origin 的固定 `/api/lm/previews` 端点；只允许最新清单中的精确记录和 Manager 原始 `preview_url`，固定单一 `path` 参数、禁止重定向并受 4 MB 上限约束。
- 前端无法为 LoRA 预览提交 URL 或文件路径；后端不访问 Civitai 预览或任意远程 URL，不提供模糊 basename/任意路径代理，且所有预览字节都会先解码验证并重编码为内容寻址 WebP。
- 单图默认限制为 4 MB，预热工作线程默认 2 且最多 4，缩略图缓存默认 256 MB；可安全关闭缓存或按配额清理。
- 视觉 manifest 仅用于管理与预览，不取代 LoRA Manager 的生成前强制刷新、精确文件唯一性检查和提交前再次复核。

### 配置与升级兼容

- 新增 `enable_prompt_asset_library`、`prompt_asset_remote_import_enabled`、`prompt_asset_max_download_mb`、`enable_prompt_lab`、`prompt_lab_batch_capacity`、`prompt_lab_ttl_seconds`、`enable_lora_visual_gallery`、`lora_visual_roots`、`lora_visual_cache_mb`、`lora_visual_warmup_workers`、`lora_visual_preview_max_mb` 和 `lora_visual_thumbnail_size`。
- 所有新字段都是插件全局能力，不写入局域网环境配置档案。旧配置缺少字段时使用安全默认，已有值和环境档案不会被覆盖。
- 发布包继续排除运行时 SQLite/DB/WAL/SHM、视觉资产数据、Prompt Lab 草稿、缩略图缓存、临时导入文件、日志和编译缓存。

### 第三方边界

- 上述能力均为本仓库独立实现；没有复制、捆绑或再分发 `Comfyui-Anima-Tools` 的源码、大型资产数据、预览图、提示词文本或工作流。

## [1.6.0] - 2026-07-26

### Prompt Composer v2

- 新增不产生第二次 LLM 调用的本地三层提示词合成：硬控制与 LoRA、视觉短语、末尾英文场景关系句统一去重和排序。
- 普通聊天 `<pic>`、自然语言绘图、显式 `/画图 --llm`、反推画图、底图控制和改图等语义入口复用同一套 Composer；未使用 `--llm` 的直接 Tags 命令继续保持原样直通。
- LoRA 控制和可信触发词统一插入场景关系句之前，修复分镜完成后追加触发词可能落到自然语言句尾的问题。
- 新增 `off|conservative|standard` 自适应负面词策略；默认 `conservative` 只按多人接触、手持物、全身与极端透视等已检测风险补充少量负面词，不覆盖用户显式 negative。

### 本地 Danbooru 硬锚点索引

- 新增可持久化的本地 JSON / CSV Tag 索引和原子更新流程；仓库与安装包不附带第三方标签库，管理员需自行配置 `danbooru_index_url`。
- 更新地址支持 HTTPS；明文 HTTP 仅允许回环或私有局域网地址，并拒绝 URL 凭据、危险地址、超时和超出体积上限的响应。更新失败时保留上一份可用数据库。
- 默认 `report` 模式只报告未知或冲突锚点，索引缺失不会阻止绘图。`guarded` 为未来结构化角色 / 作品 / 画师 anchor 协议预留；当前普通绘图生产路径会安全降级为等效 `report`，不会虚假宣称已经执行阻断。
- 用户原始 Tags、手工预设触发词和 LoRA Manager 触发词始终保持信任边界，不会被索引校验器删除或拦截。

### 提示词工坊、诊断与实验能力检查

- AstrBot 原生 plugin-page 与独立 WebUI 新增提示词状态、本地诊断、诊断清空、Danbooru 索引后台更新和实验节点能力检查入口。
- 诊断采用有界内存存储，默认只暴露数量、冲突、风险、哈希与阶段摘要；重载自动清空，不写入任务 SQLite 或持久日志。完整分层内容必须由管理员显式开启隐私开关。
- 实验注册表当前仅检测画师混合、质量栈与分层回放所需节点。仓库没有附带已审核的实验工作流，节点就绪也不会自动激活或提交实验管线。
- Prompt Composer、索引报告和诊断沿用既有群白名单、全局锁定、冷却、敏感词、管理员权限、LoRA 实时复核与工作流提交校验，不形成安全旁路。

### 第三方边界

- 上述能力均为本仓库独立实现；没有复制、打包或再分发 `comfyui-good-anima` 的 GPLv3 源码、二进制、标签索引、Prompt 或工作流。

## [1.5.7] - 2026-07-23

### Windows ComfyUI 控制模型依赖检查修复

- 修复 `.34` Windows ComfyUI 将 ControlNet 子目录模型枚举为 `Anima\\文件名`，而插件工作流使用 `Anima/文件名` 时被错误标记为四个 LLLite 模型缺失的问题。
- 工作流依赖检查现在统一模型枚举和工作流输入中的目录分隔符后再比较；不会更改实际提交给 ComfyUI 的工作流模型名。
- 已确认 `.34` 的四个目标文件真实存在于 `models/controlnet/Anima/`，`ComfyUI-Anima-LLLite` 节点正常导入，并且 ComfyUI `folder_paths` 对正斜杠和反斜杠都能解析到同一文件。
- 增加 Windows 反斜杠 `object_info` 模型枚举回归测试。

## [1.5.6] - 2026-07-23

### Danbooru Tags 撇号与转义字符解析修复

- 修复 `/画图`、`/画图no`、`/anima draw` 及复用生成参数解析器的命令把 `worm's eye view`、`bird's-eye view` 等 Tag 中英文撇号误判为未闭合 shell 引号的问题。
- 参数 tokenizer 改为保留裸文本中的单引号和反斜杠，因此 `kei \(blue archive\)` 等 Danbooru 转义写法不再被改写。
- 仍支持 `--negative "bad hands, text"`、`--preset "风格 1"` 等成对引号参数，并继续拒绝真正未闭合的显式引号。
- 增加用户原始命令形态、带撇号参数值和未闭合引号回归测试。

## [1.5.5] - 2026-07-23

### `/画图 --llm` 协议兼容修复

- 修复 `structured_director_mode=auto` 在 Provider 忽略 Function Calling 时，第二次修复仍重复携带同一输出工具、从而连续触发 `invalid_picture_protocol` 的问题。
- 首次 Function Call 无法解析时，第二次请求会移除输出工具和临时 Function Calling 覆盖，改用严格的单一 `<pic>` 标签协议；安全校验仍然保持失败关闭。
- `/画图` 与 `/画图no` 现在会捕获 `PromptDirectorError` 并返回可读的中文错误，不再让 AstrBot 把内部错误码显示成处理函数异常。
- 增加自动协议降级与命令层异常边界回归测试。

## [1.5.4] - 2026-07-23

### `/画图 --llm` 可选提示词优化

- `/画图` 与 `/画图no` 新增显式 `--llm`（短写 `--l`）执行路径：先调用当前绘图导演生成 v1.5.3 引入的 Tags + 自然句混合提示词，再沿用原命令的合并转发或直接图片发送方式。
- 不带 `--llm` 时继续固定使用原始 Tags，不受全局 `enable_prompt_llm` 默认值影响；`--raw` / `--no-llm` 可明确保持原样。
- 修复参数解析虽已支持 `--llm`、但直接绘图处理器始终硬编码 `use_prompt_llm=False` 的执行层缺口；底图控制分支也会保留显式选择。
- 显式请求 LLM 优化但绘图导演不可用时直接返回错误；生成通知、可选最终提示词展示和 Provider 信息会正确区分优化模式。
- 更新帮助与 README，并增加直接绘图执行层、缺失导演和长短参数回归。

## [1.5.3] - 2026-07-23

### Anima Tags + 自然语言混合提示词优化

- 统一普通聊天 `<pic>`、内部 Function Calling、JSON 回退与修复重试的正面提示词规范：先输出有序 Danbooru/Anima tags，再以英文句号分隔一句自然语言场景描述。
- 修复结构化调用临时指令中的 `do not add prose` 与内置参考规范相互冲突的问题；自然语言句现在明确属于 `positive_tags` 字段本身，不是函数参数之外的回复文本。
- 将自然句定位为关系条件层：重点表达动作方向、手持物、接触点、衣料状态、空间层次、环境互动与主光，并允许复述少量高价值锚点形成双重编码。
- 增加长度、时态、单句、禁用元描述与事实一致性约束，并加入海边烟花场景的高质量混合示例。
- 新增 Function Calling 请求内容、系统协议与 request-local Schema 描述回归。

## [1.5.2] - 2026-07-22

### 普通对话自动绘图续流修复

- 修复 `emit_anima_plan_v1` 被注册到 AstrBot 全局 Tool Manager 后，普通对话 Agent 把它当作真实工具执行、消费 JSON 结果并继续回复文字，导致 ComfyUI 从未收到生成任务的问题。
- `emit_anima_plan_v1` 现在只在插件内部绘图导演的单次 `llm_generate()` 请求中动态构造为不可执行 Function Calling Schema，不再出现在普通聊天工具列表。
- 普通对话控制协议新增私有工具隔离约束：需要生图时必须输出最终可见 `<pic>` 标签，由结果装饰器接管并提交 ComfyUI。
- 新增全局注册泄漏回归，确保内部 Schema 不读取全局 Tool Manager，并继续保留 v1.5.1 的 AstrBot 并行列表解析兼容。

## [1.5.1] - 2026-07-22

### AstrBot 原生 Function Call 续流修复

- 修复 AstrBot 4.26.x 将 `tools_call_name` 与 `tools_call_args` 返回为并行列表时，`emit_anima_plan_v1` 被误判为非法调用、导致工具调用后不再进入工作流的问题。
- 同时兼容旧式标量字段与新版列表字段；列表长度不一致、标量/列表混用、工具名错误或多个不同调用仍会失败关闭。
- 新增无可见文本的真实列表式 Function Call 导演回归，确认结构化计划可直接继续生成；全量测试增至 552 项。

## [1.5.0] - 2026-07-21

### 出图性能与结构化规划

- 新增任务级 LoRA 规划快照：同一任务的查询、预设校验与 LLM 工具调用复用一次强制刷新；提交前仍执行第二次强刷，并核验实际选中的文件内容与元数据。
- 拆分 Provider 准备并发与 ComfyUI 生成并发，反推、分镜、分类不再长期占用 GPU 生成槽。
- 新增本地优先意图判断；普通自然语言绘图不再无条件进入 LoRA Tool Loop，明确角色、LoRA 或未知风格请求才查询资产。
- 新增分层 LoRA 检索：精确路径、唯一文件名和唯一可信别名直接命中，歧义候选才使用 Embedding/Rerank。
- 新增 `emit_anima_plan_v1` Function Calling 与严格结构化 Provider 响应适配器，保留 JSON 与 `<pic>` 兼容回退。
- 底图控制的图片上传与反推可并行，GPU 型号在任务准备阶段预取，减少出图后的额外等待。
- 新增快照、调用预算、结构化响应、检索短路与并发槽回归测试。

## [1.4.2] - 2026-07-21

### 纯语义换角与 Provider 响应兼容

- 修复“纯语义身份 Tags 规划未返回可验证结果”误拒绝：统一读取 AstrBot 的字符串、Mapping、`completion_text`、可见 `result_chain` Plain/JSON 组件，同时识别 `role=err`、无 choices 和全模型失败，不再把 Provider 错误误报为 JSON 格式错误。
- 纯语义身份规划新增结构兼容层，支持明确的 `canonical_identity_tag + appearance_tags`、旧版 `identity_tags`、安全字段别名、百分比/0–100 整数置信度和 Danbooru 括号转义；非 ASCII、路径、LoRA、控制词和低置信度仍然失败关闭。
- `--no-character-lora` 现在真正以语义身份为执行依据；多个目标角色 LoRA 文件变体不再阻断纯语义模式，但错别字建议、显式文件请求、多人、错误身份锚点以及最终角色 LoRA 注入仍会停止。
- LoRA 工具分镜和重绘分镜使用同一套可见响应解包逻辑；明确 Provider 失败不再被当作提示词协议问题重复运行完整工具循环。
- 增加纯语义结构兼容、Provider 错误、结果链 JSON、低置信度、合法限定角色名和重复目标 LoRA 文件回归测试；全量测试增至 513 项。

## [1.4.1] - 2026-07-20

### Provider 失败闭锁与语义改图合同

- 修复 AstrBot Provider 错误文本被误当成正向提示词并提交给 ComfyUI 的致命问题；分镜输出现在必须是合法 `<pic>` 或结构化 JSON，错误输出仅修复重试一次，连续失败会在提交前终止。
- 增加执行层双重安全闸门：工作流构建前与 LoRA 触发词注入后再次检查，Provider 失败文本和违反语义改图合同的提示词均无法进入节点 11。
- 为无蒙版整图改图增加可机器验证的语义合同，覆盖明确目标衣物/饰品、可靠旧服装删除、构图/姿势保留，以及旧服装触发词抑制。
- 分离“保留策略”与“改动强度”。重大换衣即使使用 preserve，也会采用 `0.64` 的默认 denoise 下限和 `16` 步采样；显式 `--denoise` 与 `--steps` 始终优先。
- 新增 Provider 失败、协议重试、提交阻断、LoRA 后置语义校验及自适应改图强度回归测试。

## [1.4.0] - 2026-07-20

### 真正的整图 img2img 与提示词保真

- 新增 `anima_img2img_api.json`，原图经 `LoadImage → ImageScale → VAEEncode` 直接进入 Anima 主采样器，不再只依赖反推文本重构画面。
- `/改图` 的保守、平衡、自由模式默认使用 `0.32 / 0.55 / 0.78` denoise，并允许高级用户显式覆盖；无控制模式的 `/反推画图` 默认使用平衡 img2img。
- Quick 重绘移除提示词影响极弱的旧 `InpaintModelConditioning` 链，改为裁切图与遮罩直接进入快速 LanPaint，再缝合回原图。
- 底图控制在启用多模态反推和绘图导演时，会先读取同一张底图的主体、构图、场景与画风事实，再生成最终提示词；图像条件任务的导演失败会停止，不再静默回退原始中文提示。
- Pose + Depth 不再因双模式组合自动衰减；三模式与四模式仅分别降至 `0.85 / 0.75`。Reference 默认强度提升至 `0.72`，控制结束比例延长至 `0.90`。
- 反推、整图改图、底图控制与遮罩重绘在用户未明确指定风格组合时不再自动注入默认风格，减少原图内容被预设压过的问题。
- 提交前任务时间线记录工作流类型、正向节点、提示词长度与哈希、采样参数、控制强度、LoRA 数量和输出节点，但不保存完整提示词或图片路径。

## [1.3.1] - 2026-07-20

### Reference 误判修复与反推控制网

- 修复“用风格001-1画出来”“使用风格2”等 LoRA 风格预设语言被误判为 Reference 控制的问题。Reference 现在要求明确的参考图、原图外观、配色或画风语义。
- `/底图控制` 与 `/控制画图` 在省略 `--m` 时可在命令域内识别“构图不变”“姿势不变”“按线稿上色”；显式 `--m` 始终独占优先，不会被正文追加其他模式。
- 命令中的保存风格名称会正常写入 `lora_preset`；“构图和姿势不变，用风格001-1画出来”稳定解析为 Pose + Depth + 风格预设，不再启用 Reference。
- `/反推画图` 支持 `--m p|d|l|r`、组合短参数及命令域自然推断。同一张 QQ/引用图片只读取一次，先进行多模态反推，再复用为 Anima 控制图。
- 反推控制继续复用现有 base / RTX / iterative 输出、LoRA Manager 双刷新、精确文件复核、触发词注入、任务中心及 GPU/耗时回传。

## [1.3.0] - 2026-07-20

### Anima 底图控制与精确短参数

- 新增 `/底图控制` 与 `/控制画图`，一张发送或引用图片可选择 Pose、Depth、Lineart、Reference，并支持 `--m p d` 或重复 `--m` 组合。
- 控制生成复用原有提示词导演、风控、LoRA Manager 双刷新、精确文件校验、触发词注入、UNET 切换、任务中心、GPU 与耗时回传；不会建立绕过 LoRA 新鲜度门禁的第二套逻辑。
- Pose 使用 OpenPose 预处理，Depth 使用 Depth Anything V2，Lineart 使用线稿预处理，Reference 使用 Anima any-test-like v2 柔性参考；单模式保持较强约束，多模式自动降低竞争强度。
- 底图未显式指定尺寸时按原图宽高比推导安全画布；控制结果仍支持 base、RTX 和 iterative 三种输出管线。
- 新增自然语言控制路由，识别“参考姿势/动作”“保持空间构图/透视”“按线稿上色”“参考外观/配色/画风”，并处理否定与“只参考”；裸“构图”“景深”“上色”不会误触。
- 新增上下文相关短参数：生成可用 `--p b|r|i`、`--sz`、`--st`、`--sd`、`--c`、`--n`、`--pr`；整图改图、遮罩重绘与换角的 `--m` 各自使用不会冲突的短值。
- 模型与 LoRA 文件继续禁止单字母模糊匹配；短参数只规范化固定枚举，不扩大资产选择权限。
- WebUI / plugin-page 工作流工具区与实时依赖检查增加 Anima 底图控制能力。

## [1.2.2] - 2026-07-19

### 图片编辑路由与纯语义换角修复

- 修复 `/重绘 把泳装换成……` 等服装修改被误判为角色替换的问题。泳装、比基尼、丝袜、礼服、制服、裙装及其他明确服饰词不会再充当角色身份。
- `/重绘` 未声明局部、遮罩、蒙版或 Quick/LanPaint 模式时，会按无蒙版整图 `/改图` 处理；明确遮罩请求仍严格要求原图与有效蒙版。
- 支持角色与衣服一起变化，例如“把达妮娅换成米浴并穿红色礼服”：先应用非身份服装约束，再执行经过验证的身份替换，保留未要求改变的构图、姿势、背景与画风。
- 修复纯语义身份规划缺少内部 LLM 事件隔离的问题，避免普通 `<pic>/<edit>` 自动绘图协议污染严格 JSON 请求。
- 纯语义 JSON 规划现在复用安全格式整理器，可确定性处理 `<think>`、代码围栏、无害附加字段、数字字符串及逗号分隔 Tag 字符串，同时继续拒绝控制词、URL、路径、模型文件和 LoRA 语法。
- 将所有模糊的 `ValueError` 日志拆分为 `schema`、`confidence`、`unsafe_tag`、`identity_anchor` 等具体校验码；每次失败、重试与耗时都会进入任务时间线和持久控制台，但不会记录原始 Provider 回复。

## [1.2.1] - 2026-07-19

### 无蒙版整图语义重绘

- 新增 `/改图 <要求> --mode preserve|balanced|free`，只需发送或引用一张原图，不需要用户制作蒙版。
- 新增 aiocqhttp / NapCat 自然语言整图改图路由；普通换衣、换背景、换表情和“重新画一张”会进入语义重绘，明确遮罩、蒙版、白色/透明区域或局部区域仍进入 Quick / LanPaint。
- 整图改图按原图宽高比推导约一百万像素、64 倍数的安全画布；显式 `--size`、`--pipeline`、`--preset`、Seed、Steps 和 CFG 仍可覆盖。
- 反推结果新增整图修改协议，将画面拆成身份、服装、表情、动作、镜头、构图、场景、光线和画风；用户明确替换的旧内容必须从正面 Tags 删除。
- 换衣只在反推或实时 LoRA 元数据能证明旧服装时添加窄范围 negative；角色身份、脸、发色、瞳色和体型不会被误伤。
- 任务中心与持久控制台新增整图改图输入、反推、约束规划、ComfyUI 提交和完成阶段；WebUI 独立工具区显示该编排能力及就绪状态。
- 明确拒绝把 `--denoise` 冒充整图改图强度；当前实现是反推后重新生成，不声称像素级图生图或局部保持。
- 修复旧版全局配置档案在六管线字段加入后被整体判为损坏的问题。v1 档案会只补齐六个新增工作流字段并原子迁移到 v2，原有档案名称、激活状态、局域网地址、UNET、节点和分辨率保持不变；真正缺少旧必需字段的损坏档案仍会拒绝加载。

## [1.2.0] - 2026-07-19

### 六管线与遮罩重绘

- 拆分 Anima 原图、Anima+RTX、Anima+迭代采样放大，并保留独立 RTX 图片放大；默认管线可在 WebUI 选择，请求可用 `--pipeline` 或自然语言覆盖。
- 两套 WebUI 现在固定分区展示三条可切换生图管线与三个独立图片工具；独立 RTX、Quick 和 LanPaint 不再与默认文生图入口混淆。
- 新增 Quick Inpaint Crop 与 LanPaint 遮罩重绘、`/重绘` 指令、透明 PNG Alpha 遮罩和严格的原图/遮罩尺寸与歧义校验。
- LLM 控制协议增加 `<pic pipeline="...">` 与互斥的 `<edit mode="...">`，插件仍以确定性意图、真实图片和遮罩做最终裁决。
- 所有生成与重绘 LoRA 在规划前和提交前分别强制刷新 Manager + ComfyUI，并重新解析精确可加载名称。
- `/comfy_use` 与 WebUI 工作流选择现在只切换三条受 manifest 管理的生成管线；旧版工作流仅展示为回滚资产，不再出现“提示切换成功但下一张图仍走别的 Builder”的假成功。
- 恢复 `--upscale`、`--no-upscale` 与旧 `enable_upscale` 配置的兼容优先级；显式 `--pipeline` 最高，LLM 在用户未指定时省略 pipeline 并跟随 WebUI 默认值。
- UNET 切换会先原子重建三条生成、两条重绘和独立 RTX Builder，再报告当前实例已应用；最终生成与重绘 Tags 会在提交前统一执行风控。
- 迭代 denoise 只作用于二次采样节点，不再降低空 Latent 底图采样的 1.0 denoise。

### 换角稳健性修复

- `/反推画图` 中的明确换角要求会直接进入语义换角管线；“角色/人物/主角”等泛指会交给图片反推补全真实原角色。
- 新增 `--no-character-lora` / `--no-lora` 及对应自然语言表达。禁用目标角色 LoRA 时仍执行实时清单刷新、歧义和错字校验，只使用经分类确认的普通身份与外观 Tags。
- 纯 Tags 换角强制以权威 `replace` 模式写入 LoRA 节点；即使最终动态栈为空，也会清除模板静态角色 LoRA，并在提交前拒绝任何残留角色身份元数据。
- 加强纯语义 Provider JSON、非有限数、提示注入控制词、加权组身份泄漏和负面目标身份冲突校验。
- 角色解析支持作品名与角色名的自然中文语序；只有精确文件名、明确角色名以及来源可信且未过期的语义别名可授权换角，自动提取的标题、Tags、trained words 和单独作品名不会被当成角色身份。错别字只返回唯一候选建议，不会自动换成近似角色。
- 图片换角使用更小的专用反推 JSON 协议，降低完整反推结构连续失败概率。
- 新增独立 `character_swap_timeout`（默认 240 秒）作为整个 Tags 分类阶段的总预算；首次超时仅可在剩余预算内进行一次受限重试。
- 图片换角的精简反推 JSON 现在由解析层执行精确字段、类型、单角色、英文 Tags 与控制文本校验，而不只依赖提示词约束。
- 已在 Linux、真实 ComfyUI、实时 LoRA Manager 清单与 512×512 低成本管线中完成发布前验证。

## [1.1.6] - 2026-07-19

### 单角色语义换角

- 新增 `/换角色 A -> B` 图片入口与 `/换角色 A -> B | <完整 Tags>` Tag 入口；明确定位为 Anima 整图语义重绘，不冒充局部重绘或像素级编辑。
- 默认 `keep-outfit` 只替换角色身份，保留衣服、姿势、动作、表情、构图、背景、光线、风格及非角色 LoRA；可选 `target-outfit` 仅使用当前 LoRA 元数据中可证明为默认服装的触发词。
- 图片模式复用现有结构化反推，并按原图宽高比生成约一百万像素、64 倍数的安全画布；不会照搬 4K/8K 原始尺寸。
- 换角分类模型只返回编号 Tag 的严格 JSON 分类，不能造词、不能指定 LoRA 文件；无效结构仅低温重试一次，低置信度、遗漏、重复、越界或不确定分类全部失败关闭。
- 目标角色只从强制刷新后的当前可加载清单、精确文件名、可信角色名及未过期人工/高置信语义别名中唯一解析；Embedding/Rerank 不参与最终文件决定。
- 规划前与提交前分别刷新/复核 LoRA 身份、SHA 与来源指纹；目标被删除、换内容、同名歧义、A/B 同文件、多角色或多个角色 LoRA 时停止提交。
- 修复带新 SHA 的同名文件仍回退到旧 name-only 语义档案，以及来源指纹变化后旧语义覆盖仍可生效的问题。
- 新增身份词抑制门禁，防止保存组合的手工触发词或其他 LoRA 元数据把已删除的 A 身份重新注入；B 的可靠身份与外观词会从负面提示词中移除。
- 任务中心记录输入、反推、实时刷新、角色解析、受约束分类、验证、提交和完成/失败阶段，但不保存完整提示词、图片路径或 Provider 原始回复。
- WebUI 与 AstrBot 原生 plugin-page 新增实时工作流清单和热切换；生图、独立 RTX 放大与无效文件明确分型，独立放大工作流只展示不允许设为生图工作流，运行中有图片任务时拒绝切换。

## [1.1.5] - 2026-07-18

### 对话保存风格持久化修复

- 新增管理员 LLM 工具 `save_anima_lora_style`，支持在普通 Bot 对话中明确要求保存或覆盖完整 LoRA 风格串。
- 普通对话 System Prompt 强制要求：只有工具返回 `STYLE_SAVE_COMMITTED` 后才能声称保存成功，禁止用 shell、聊天记忆或口头承诺冒充持久化。
- 对话保存复用与 `/保存风格` 相同的 Manager 强制刷新、精确 LoRA 解析、角色隔离、数量限制与配置事务。
- 配置保存现在要求存在真实 `save_config()` writer；写盘后会从 `AstrBotConfig.config_path` 回读校验。writer 缺失、无实际写盘或内容不一致时回滚内存修改且不重载。
- 对话工具保存成功后延迟 10 秒自动重载，为外层聊天模型保留发送最终确认的时间；重载后的新 Registry 与 WebUI 从已验证磁盘配置恢复。

## [1.1.4] - 2026-07-18

### Provider 统一发现与 LoRA 混合检索

- 修复 AstrBot v4.26.1 Provider Source 继承配置未合并，导致已保存模型在插件面板中漏列的问题。
- 绘图导演、图片反推、LoRA Embedding 与 LoRA Rerank 改为四个独立 Provider 选择器；反推会标明视觉、纯文本或能力未知。
- 新增可选 LoRA 混合检索：每次先强制刷新 Manager 与 ComfyUI 当前可加载清单，再执行 Embedding 召回与 Rerank 精排。
- 精确文件名、唯一 basename 与确定性别名保持优先；向量结果不能证明文件存在，也不能复活已删除 LoRA。
- 新增隐私安全的向量缓存，只保存 Provider/文档哈希与归一化向量；Provider 异常、非法响应和超时自动回退词法搜索。
- 图片反推会在调用前拒绝明确声明为纯文本的 Provider，旧配置中能力未知的模型仍保持兼容。

## [1.1.3] - 2026-07-18

### 反推 JSON 与原生管理页面

- 新增可独立开关的本地反推 JSON 格式整理器；开启时兼容围栏、说明文字、尾逗号和单引号字典，关闭后只接受一个严格 JSON 对象。
- 新增反推修复重试开关。关闭后只调用一次多模态 Provider，并保留原始校验错误码；只有实际执行两次仍失败才返回 `repair_exhausted`。
- 无论开关状态，始终执行响应长度限制、嵌套/未闭合 `<think>` 隔离、结构深度限制、非有限数拒绝、对象类型和 `positive_tags` 校验。
- 新增 AstrBot v4.26.1 原生 `plugin-page` 工坊控制台，通过官方 Bridge 复用现有 LoRA、预设、UNET、配置、任务和日志业务接口，不依赖 6198 面板登录。
- 原生页面与独立端口页面共用前端逻辑；使用页面内确认框替代受限 iframe 禁用的 `confirm/prompt`，并在插件重载后通过 Bridge 重试连接，避免短期资源令牌过期导致 401。
- 对 iframe 的 `localStorage/sessionStorage` 限制采用安全内存回退，不会因沙箱 `SecurityError` 中断 LoRA 自动建档。
- 明确 Embedding/Rerank 不用于 JSON 修复；其后续最有价值的用途是实时 LoRA 清单上的语义候选召回与可选重排。

## [1.1.2] - 2026-07-18

### 图片反推可靠性修复

- 强制保留内置结构化反推协议；管理员自定义 System Prompt 只作为分析偏好叠加，不再替换 JSON、安全和字段约束。
- 支持从说明文字和代码块中提取嵌套 JSON，并兼容尾逗号、Python 单引号字典、字符串内花括号和常见字段别名。
- 多个候选对象始终以最后一个对象作为最终答复；尾部对象损坏或截断时直接修复重试，不会误用前面的示例 JSON。
- 完整剥离嵌套及未闭合 `<think>`，并用引号感知方式修复尾逗号；深层递归响应也会转为受控校验错误。
- 首次结构校验失败后，使用同一图片和同一多模态 Provider 执行一次低温严格 JSON 修复重试；连续失败后明确停止，不会进入绘图导演或 ComfyUI。
- `/反推画图` 在调用 ComfyUI 前再次检查导演生成的最终正面提示词，避免图片内容绕过群级违禁词策略。
- 任务时间线记录响应接收、校验失败、修复请求和校验成功等阶段，仅保存长度、错误码和解析策略，不保存原始模型回复、图片或提示词。
- Provider 异常和反推结构错误改用安全错误码记录，并保留真实失败阶段，避免异常正文进入持久控制台。

## [1.1.1] - 2026-07-17

### LoRA 正确性修复

- 修复 Anima V2 加载 LoRA 后没有把可靠 Manager/Civitai 触发词写入正面提示词的问题。
- 风格与功能 LoRA 使用全部明确触发词；角色 LoRA 只使用能与角色身份确证匹配的主触发词，避免默认服装和外观词破坏换装。
- 各来源先按同一次强制刷新得到的最新清单解析成精确文件，再执行去重和合并；保存的风格/混合预设权重不再被 LLM 静默覆盖。
- 增加同 basename 歧义门禁，并要求 LoRA Manager 使用 `lora_syntax_format=full`；即使关闭严格校验也不会猜选同名文件。
- 修复旧 `anima_api.json` 的所有正负与二次文本编码节点未使用 LoRA 后 CLIP 的问题，并清除陈旧 TriggerWord Toggle 回退词。
- LoRA 工具超时预算覆盖 Manager 扫描和完整工具链；工具失败、超时或返回无效结果时停止本次绘图，不再静默退回无工具分镜或原始文本。
- Anima V2 继续默认启用 RTX；补充三份工作流拓扑、512×512 RTX、精确 LoRA、触发词和歧义回归测试。

## [1.1.0] - 2026-07-17

### 新工作流与图片能力

- 新增独立档案驱动的 `Anima V2 + RTX` API 工作流；旧 `anima_api.json` 原样保留作为兼容回退，新旧节点映射不会串线。
- Anima 可在同一次任务中直接输出 RTX 放大图，也可通过 `--no-upscale` 返回原图。
- 新增 `/反推`、`/反推画图` 与 `/放大`，支持 aiocqhttp/NapCat 同消息图片及引用图片。
- 在线反推复用 AstrBot 已配置的多模态 Provider，不在插件中重复保存 API Key，也不导入原工作流中的明文在线 API 节点。
- 所有生图与 RTX 放大结果显示处理耗时和 ComfyUI GPU 型号。

### WebUI 与安全管理

- WebUI 读取当前工作流档案和采样器模板，允许用 `0–100` 覆盖采样步数；`0` 表示跟随工作流。
- WebUI 新增 LoRA 与 Anima UNET 文件删除。浏览器只提交最新清单中的精确名称和确认名称，文件路径只在后端从 Manager 实时清单中解析。
- 删除前强制刷新 Manager 与 ComfyUI；当前 UNET、重名资产、危险路径和仍被组合引用的 LoRA 默认禁止删除。
- 显式选择“从组合移除后删除”时会先持久化清理组合；删除完成后再次刷新清单并同步语义索引在库状态。
- 反推、反推画图、RTX 放大和资产删除写入持久任务中心及脱敏控制台。

### 验证与依赖

- 新增 Pillow 输入图片验证，限制格式、文件大小和像素总量。
- 新增工作流档案、独立 RTX、输入图片、反推解析、模型删除与 WebUI 路由测试。

## [1.0.0] - 2026-07-16

首个公开正式版。

### 核心能力

- 支持自然语言 LLM 分镜与 `/画图`、`/画图no` 精确提示词绘图。
- 针对随包 Anima API 工作流适配内容节点、LoRA Manager 节点、UNET 节点和动态分辨率。
- 支持普通 LLM 回复中的 `<pic prompt="...">` 自动出图，并过滤 `<think>` 内容。
- 支持 aiocqhttp / NapCat QQ 图片直发与合并转发。

### LoRA 与模型管理

- 每次 LoRA 查询、组合、下载和绘图前强制刷新 LoRA Manager 与 ComfyUI 实际可加载清单。
- 支持角色、画师/风格、混合及七类功能型 LoRA 分类，排除 UNET、checkpoint 等非 LoRA 资产。
- 支持 Civitai 元数据获取、URL 下载、逐 LoRA 语义建档、中英文别名和人工审核。
- 支持命名 LoRA 风格组合、括号备注简称命中、角色与风格独立组合。
- 支持实时读取和切换 Anima UNET 模型。

### 管理与安全

- 提供带登录认证的独立端口 Web UI、三套主题、环境配置档案和持久任务中心。
- 提供持久运行控制台、日志脱敏、任务阶段时间线、升降序与分页。
- 支持群级敏感词策略、白名单、全局锁定和管理员特权。
- 运行时数据库、LoRA 语义索引、缓存、密钥和本地配置不包含在源码仓库或正式安装包中。
