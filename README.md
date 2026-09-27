# batchcode

**一次调用，多个代理。** 面向终端用户和 AI agent 的轻量任务 CLI：会话分支与并发、可编辑上下文、provider 请求编译、明确的最终答案提交。

**当前版本：v0.3.1**（兼容 v0.3.0 会话存储；收紧会话引用语义，不兼容 0.2.x CLI／会话格式）。Python 3.10+ 标准库，无 pip 第三方依赖；支持 Debian/Ubuntu（含 proot），不支持原生 Termux 或 Windows。

## 安装

从 [Releases](https://github.com/YiJieqwq/batchcode/releases) 下载 ZIP：

```bash
unzip batchcode-v0.3.1.zip
cd batchcode
bash install.sh
```

或克隆仓库后运行安装脚本。安装器准备本地 `.venv`、注册 PATH 命令、执行离线自检；不用手动激活 venv。只安装必要系统依赖，不执行 upgrade，拒绝涉及 coreutils 的包事务。注册 PATH 需要可写且已在 PATH 的 `/usr/local/bin` 或 `~/.local/bin`；无权限明确失败，不等密码。嵌入/测试可以 `bash install.sh --local`。

填写两个 **JSON 格式的 `.txt` 文件**的 `api_key`：

```text
model/deepseek-flash.txt
websearch/tavily.txt
```

搜索没 key 不妨碍模型运行：缺失搜索工具不会注入 schema，但子代理会收到动态提示 `web_search is temporarily unavailable`。模型必须在**合并后的有效配置**中有 key；绝不自动换模型/服务商。这里只检查本地调用条件，非空 key 不保证远端鉴权成功。

> 不要把 ZIP 覆盖解压到已填密钥的目录。安装脚本不会覆盖运行配置，但解压器可能覆盖同名 `.txt`。本版本不迁移 0.2.x 会话、不删除旧数据。请在新目录安装；默认 profile 是公开空 key 样板，填 key 后不要提交到 Git。

## 一次调用完成任务

```bash
batchcode task --name=调研 --content="总结 /workspace/inbox/文档.md"
batchcode task 调研 --content="核实结论并附来源"

batchcode task --parallel=2 \
  --task='{"name":"技术","content":"分析技术可行性"}' \
  --task='{"name":"成本","content":"分析成本与风险"}'

batchcode task --tasks-stdin <<'JSON'
[
  {"name":"支持论据","fork_from":"调研","content":"检查支持证据"},
  {"name":"反方核查","fork_from":"调研","content":"检查反面证据"}
]
JSON
```

**位置参数只引用已有会话，写错名称或 ID 直接报 `NOT_FOUND`，绝不自动创建或近似匹配。** 不填引用才新建：可用 `--name=名称` 同步命名，省略 name 则自动生成显示名。

```bash
# 新建并命名（重名报错，不会偷偷续聊）
batchcode task --name=调研 --content="第一轮任务"
# 引用已有会话，继续任务
batchcode task 调研 --content="继续核实"
# 引用已有会话，同时重命名
batchcode task 调研 --name=文献调研 --content="继续核实"
# ID 也能引用；输出依然用映射得到的名称
batchcode task s_0123456789abcdef0123456789abcdef --name=新名称 --content="继续"
```

`--name` 不是配置项，不进入 sconf 或 info.json。重命名只改索引，ID、历史和成果路径保持；重名、会话忙或运行预检失败时不改名。通过预检后先改名再运行，远端 API 失败不会撤回已成功的改名。改为自己的现有名称是 no-op。`task rerun REF --name=新名称 --msg_id=N` 也支持同样规则。

批量对象的 `session` 只用于已有引用，`name` 用于新建命名或续聊重命名。不要把批次共用 `--name` 加在命令上，应在每个对象里写 name。`fork_from` 是显式新建分支：省略 session、用 name 指定新分支名，不再把 session 当目标名称。

所有已有引用都接受 **name 或生成的 sessionid**（例如 `s_` 加 32 位十六进制 UUID）。显式 `session add NAME` 和 `session fork ... NEWNAME` 仍可新建，目标不可自指定 ID。

同源批量 fork 取同一快照；不同会话并发，同会话必须串行。name 与 ID 指向同一个会话时也判为重复。批次中局部配置/执行失败不会取消其他独立任务；输入结构或批次重复 ID 错误在执行前拒绝。

## 输出：答案与轨迹是两条轴

```bash
batchcode task 调研 --answer=summary --granularity=fine --content="查阅材料"
```

- **`--answer=summary`（默认）**：子代理通过 `submit_answer` 提交最终答案。任务完成、已无法完成且无后续操作，或没有任务且无后续操作时，**都要求至少提交一次，包括问候／测试**；不得为了提交而执行无关文件／搜索操作。允许反复修订，不截断、不限提交次数或累计提交长度；每次回传程序计算的字符数。最后一次有效提交才用于交付，提交不会结束循环，后续收尾仍保存 ctx。
- **`--answer=full`**：stdout 保留本次全部可见 `assistant_content`。不输出 reasoning 或工具反馈正文；可用显式 ctx 查询查看原始事件。
- **`--granularity=coarse`（默认）**：stderr 不显示工具调用摘要，提示 `Tool call records are hidden`。
- **`--granularity=fine`**：stderr 显示调用摘要（submit 参数正文仍隐藏）；工具反馈正文不显示。
- 本轮没有有效提交，兜底**本轮最后一条完整 content**，stderr 提示 `NO_SUBMISSION` 和本轮 evt 起止 ID。这是模型漏交时的异常兜底，不再把问候设计为常规兜底路径；不靠程序语义分类判失败。提示词不保证模型永不漏交，因此 warning 保留。历史/fork 继承的 submit 不计本轮。
- 错误和 warning 始终输出。已有答案不能掩盖超时/失败；状态和退出码照实返回。

示例 stdout：

```text
[task 2/2 done, max_elapsed 7.3s]

调研/status: completed, sessionid=s_..., elapsed 7.3s, submitted=true
调研/input: msg_id=7, evt_id=19
调研/answer: 结论……必要限制与来源……
调研/artifact: /安装目录/sub_workspace/s_.../report.md

核查/status: completed, sessionid=s_..., elapsed 6.2s, submitted=false
核查/input: msg_id=1, evt_id=1
核查/answer: 直接回复……
```

示例 stderr：

```text
[critical 0, warning 1]
warning/NO_SUBMISSION: session=核查 Returned last complete content; evt_start=1, evt_end=2
[tool feedbacks are hidden in stderr]
调研/evt/21: read_file: {"path":"/workspace/inbox/文档.md"}
```

**输出前缀使用会话 name，不使用长 ID**，即使输入用 ID，答案和工具轨迹仍以当前 name 定位。诊断中的会话定位也显示 name；状态行保留一次稳定 sessionid，列表和 info 仍能查 ID。

**必须收集 stdout、stderr 和退出码，禁止 `2>/dev/null`。** 模型文字可能仿冒状态头，不要靠全文关键词判断成功。`done` 是结束数，不是成功数；`max_elapsed` 是最大单任务耗时，排队等待不算其中。模型的事实准确性不由 `completed` 保证。

结果在任务结束后按提交顺序汇总，不是实时终端流。完整输出通过本地临时文件交付，避免父/子进程管道复制全部正文。API 流式处理与终端输出粒度相互独立。

## 配置：gconf 默认值 + 会话覆盖

```bash
batchcode gconf get deepseek-flash
batchcode gconf get deepseek-flash --temperature --top-p
batchcode gconf set deepseek-flash --temperature=0.8
batchcode gconf add research --heredoc <<'JSON'
{
  "url":"https://api.deepseek.com/v1/chat/completions",
  "model":"deepseek-flash",
  "api_key":""
}
JSON
batchcode gconf del research

batchcode session set conf 调研 --modelconf=deepseek-flash --temperature=0.6
batchcode session set conf 调研 --unset=temperature
batchcode session get conf 调研 --temperature --modelconf
```

- `modelconf` 始终是配置名称；`model` 始终是服务端模型 ID。
- 每份 `model/*.txt` 同时提供连接、采样和运行默认值；`add --heredoc` 读取完整 JSON，补齐可选默认值，已存在拒绝覆盖。需要 url/model/api_key 字段，但 api_key 可为空。
- **task 显式参数写回该会话 conf**，不再是一次性临时设置。只保存显式覆盖，不固化继承值。批次共用设置写各会话，逐任务设置优先；parallel 仅为批次参数，不写每个会话。
- 运行流程：显式参数覆盖 sconf → 根据 modelconf 复制 gconf 到内存 tmpconf → sconf 存在的字段逐项覆盖 → 检查最终 tmpconf → 本次快照固定。之后修改 gconf 不改变在跑任务。
- 基础 gconf 缺 key，但会话覆盖补齐可运行；stderr 会提示基础缺 key。最终配置仍缺 key 则失败，不自动路由。
- 普通配置查看隐藏 api_key，**ctx/工具参数/反馈/成果原文不做正则脱敏**；鉴权头从不注入对话。
- `get --temperature` 是筛选字段，不接受 `--temperature=...` 赋值。
- 删除仍被启动选择器或会话直接引用的 gconf 会拒绝；先解除引用。

默认选择文件独立为 `startup/selection.json`，首次安装从 `selection.default.json` 生成：

```json
{"default_modelconf":"deepseek-flash","default_websearch":"tavily"}
```

它只保存“默认选谁”，不是另一套运行参数。可直接编辑该文件。显式选择/会话选择优先，模型配置没指定 websearch 才继承这里；`--websearch=none` 或 JSON null 明确关闭。工具集合和不可用说明按本轮快照动态注入，不永久写入历史。

完整参数表见 [CONFIG.md](docs/CONFIG.md)。四项默认配额为 **0 = 不主动限制**，总任务超时默认 **1800 秒**，单步网络/大小保护保留。外层 exec 更短时仍会提前中断。DeepSeek 默认思考开启、effort=auto（省略 API 字段）、temperature/top_p=1；参数是否被模型采用取决于模式。

## 会话管理：明确操作目标

```bash
batchcode session add 调研
batchcode session add 复核 --heredoc <<'JSON'
{"modelconf":"deepseek-flash","temperature":0.6}
JSON
batchcode session list
batchcode session get info 调研
batchcode session get conf 调研
batchcode session get ctx 调研 --evt_start=5 --evt_end=10
batchcode session get ctx 调研 --msg_start=2 --msg_end=5
batchcode session get ctx 调研 --evt_id=5
batchcode session get ctx 调研 --msg_id=2
batchcode session export ctx 调研 /workspace/outbox/research.ctx.json
batchcode session rename 调研 文献调研
batchcode session fork ctx 文献调研 分支A
batchcode session fork conf 文献调研 分支B
batchcode session fork all 文献调研 分支C
batchcode session del ctx 分支A
batchcode session del conf 分支B
batchcode session del all 分支C
```

查询范围是 **ID 而非数组位置**。按 evt 返回事件落盘原文，按 msg 返回组织记录和引用的事件原文。显示超过 24000 字符**整次拒绝**（stdout 不输出半份数据），提示缩小范围或 export。无筛选的 get ctx 返回原文件；即使编译失败，仍可查/导出。export 默认拒绝覆盖已有文件。

显式引用必须已存在；`task REF`、`session set conf REF`、get/export 等引用错误直接报错，不新建。创建使用省略引用的 task（可选 --name）、`session add` 或显式 fork。`session del ctx/conf/all` 不存在仍为幂等 no-op。fork 来源必须存在、目标必须新建。

`info.json` **没有 name**，名称唯一真相为 `session_index.json`。实际路径、锁、parent_id 都用不可变 ID。rename 只更新索引，不移动目录，不改历史；同名删除重建获得新 ID，旧成果不会被覆盖。list 展示名称及 ID，Active 依据运行锁，不把配置管理锁算运行。

**删除 ctx 只是清空历史，不删除会话身份，也不使它无法运行**：仍出现在 session list，可以用同一 name／ID 接收新任务。删除 ctx 保留配置及编号高水位；删除 conf 清空覆盖；删除 all 删除会话记录、运行审计，但保留成果。fork 不复制旧日志和成果。删除不是 provider 侧撤回或磁盘安全擦除。

## 历史编辑与 rerun

```bash
batchcode session evt edit 调研 --evt_id=19 --content="修改的输入"
batchcode session evt del 调研 --evt_id=19
batchcode session evt add 调研 --after_evt=19 --content="补充条件"
batchcode session evt add 调研 --after_msg=7 --content="加到这条 user msg 末尾"
batchcode session msg add 调研 --after_msg=0 --content="插入开头"
batchcode session msg add 调研 --after_msg=7
batchcode session msg del 调研 --msg_id=7 --drop-suffix

batchcode task rerun 调研 --evt_id=19
batchcode task rerun 调研 --msg_id=7
batchcode session evt edit 调研 --evt_id=19 --content="改完再跑" --rerun --drop-suffix
```

- 局部编辑只允许 user 消息；msg 不提供 edit。编辑只改所指内容和该 evt timestamp，不猜测语义连贯性、不修补旧回答。
- add 不接受 drop-suffix。evt edit 带 drop-suffix 保留修改后的目标，丢掉其后逻辑内容（含同 msg 后续 evt）；evt del 删除目标及其后；msg del 删除目标 msg 及其后。
- edit --rerun **必须显式 --drop-suffix**，缺少则修改前报错。单独 --drop-suffix 只编辑/截断，不自动调用模型。
- rerun 定位已存在 user，保留整条输入及此前、永久丢掉其后上下文，再交 provider。它**不能修改 timestamp**，发生重跑的时间另记在运行信息中。检查失败不截断；开始执行后即使 API 失败也不恢复旧后文。
- 文件/其他工具副作用不回滚。需要保留原分支先 fork。
- 新 evt/msg ID 始终递增、不重编号；逻辑顺序由 msgs 数组及 evt_ids 决定，历史插入可以形成 `[10,81,11]`，不能按数字排序编译。
- `msg add --after_msg=0` 的 0 只表示最前面，不是真实 ID。未传 content 可建立空 msg；仍可按 ID 查询/继续填入。编译忽略空 msg，stderr 提示一次。删光最后 evt 同样允许。
- 非 user evt 只有在所属 msg 末尾才能用作插入锚点；下一有效 msg 为 user 时插其开头，否则建立 user msg；末尾可追加。`evt add --after_msg` 则始终追加到所选 user/空 msg 的末尾。
- **assistant 工具请求到全部 tool 反馈之间不能插入**，多个反馈之间也不行。按逻辑顺序跳过空 msg 检查调用 ID 配对，非法位置写入前拒绝。空 tool_calls null/[] 不算待反馈请求。

## 编译、诊断与边界

ctx 结构和编译规则见 [CONTEXT.md](docs/CONTEXT.md)。stderr 任务头为 `[critical m, warning n]`；同一个重复编译问题只计一次。critical 阻止对应操作，warning 表示可以继续但存在忽略/降级，不替模型验证事实。原始文本保留，编译在内存中完成，不把时间前缀写回。

工具：read_file、list_directory、write_file、submit_answer，以及可用时的 Tavily web_search/fetch_url。写入只在 `sub_workspace/<sessionid>/`；无 shell，`exec_command` 在 TODO。只支持 UTF-8 文本，不含 PDF/Word 解析和通用多模态/Responses API。

**这不是 OS 级 sandbox**，无法对抗同 UID 任意进程改文件；允许读取的文件会发送给模型服务。不要扩大 read_roots 到整个私人工作区，凭据目录和程序状态始终禁止工具读取。详细边界见 CONFIG.md。文件操作失败会区分 FILE_NOT_FOUND／PERMISSION_DENIED／IS_A_DIRECTORY／NOT_A_DIRECTORY 等，反馈包含请求路径和 errno；JSON 解析/类型错误才报告参数问题。

## 诊断与卸载

```bash
batchcode self-check
batchcode doctor --websearch=tavily --samples=1 --timeout=3
batchcode doctor --json
bash uninstall.sh
```

self-check 离线；doctor 显式测容器内 DNS，不发密钥/模型请求、不修 DNS。正常查询无诊断时 stderr 为空。卸载只移除这份安装的 PATH 入口和私有 venv，保留配置、密钥、历史、成果和源码；有活动命令则拒绝，不触碰系统 Python/coreutils/DNS。重新运行 install.sh 可重装。

## 开发与验证

```bash
python3 -m unittest discover -s tests -v
python3 scripts/package.py
```

[测试范围与限制](docs/TESTING.md) · [更新记录](CHANGELOG.md) · [AGENT.md](AGENT.md) · [TODO](docs/TODO.md)

MIT License。发行包白名单构建，拒绝默认 profile 的非空 key；不包含运行历史、运行配置、venv、修 DNS 脚本或私人测试报告。
