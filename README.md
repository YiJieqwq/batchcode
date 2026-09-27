# batchcode

**一次调用，多个代理。** 面向终端用户和 AI agent 的轻量 CLI：支持本地材料处理、联网核实、会话分支与并发任务，保留完整可见回复，并将工具轨迹与正文分流。

Python 3.10+ 标准库实现，无第三方 pip 依赖。支持 Debian / Ubuntu（含 proot），暂不支持原生 Termux、Windows。

## 安装

下载发行包，解压后：

```bash
unzip batchcode-v0.2.1.zip
cd batchcode
bash install.sh
```

也可以从 GitHub 克隆：

```bash
git clone https://github.com/YiJieqwq/batchcode.git
cd batchcode
bash install.sh
```

安装器准备私有 `.venv`，初始化配置/数据目录，并注册 PATH 入口，随后直接运行 `batchcode`，不需要激活虚拟环境。

- 优先使用可写且已在 PATH 中的 `/usr/local/bin`，其次 `~/.local/bin`；无可用目录则明确报错。
- 缺少 Python / venv / CA 时只安装必要 apt 包。需要 root 或免交互 sudo，不等待密码。
- **绝不执行系统 upgrade；拒绝涉及 coreutils 的包事务。**
- 不覆盖其他程序的同名命令。搬家后重跑安装器可更新自己的入口。
- `bash install.sh --local` 只安装本地入口，不注册全局命令，供嵌入或 CI 使用。
- 重复安装保留配置和数据；不要直接解压新发行包覆盖已填写密钥的目录。

填写下面两个 **JSON 格式的 `.txt` 文件**中的 `api_key`：

```text
model/deepseek-flash.txt
websearch/tavily.txt
```

不用联网工具，可以不填写 Tavily key。安装与 `batchcode op self-check` 不请求付费 API。

> `.txt` 默认配置在 Git 仓库中是空密钥样板。填写后不要提交配置文件！其他自定义 `.txt` 默认忽略。更稳妥的方式是创建被忽略的 `model/my-deepseek.txt`，用 `op config g --model=my-deepseek` 选择。

## 单任务

```bash
batchcode task --session=01 --content="总结 /workspace/inbox/文档.md"
batchcode task --session=01 --content="把结论压缩成三句话"
batchcode task --websearch=tavily --content="查询某事件，并阅读一手来源核实"
```

session 不传则自动生成。文件路径可读范围由 `config.json` 控制，默认安装目录的同级 `../inbox` 和自身 `sub_workspace`。

## 一次提交多个任务

无需先写任务文件，重复 `--task` 即可：

```bash
batchcode task --parallel=2 --granularity=fine \
  --task='{"session":"01","content":"总结 /workspace/inbox/文档.md"}' \
  --task='{"session":"02","content":"查询相关事件","websearch":"tavily"}'
```

长文本也可用带引号的 heredoc，一次命令完成：

```bash
batchcode task --tasks-stdin --parallel=2 <<'JSON'
[
  {"session":"technical","content":"分析技术可行性"},
  {"session":"cost","content":"分析成本和风险"}
]
JSON
```

子进程并发执行，等待全部结束后按提交顺序汇总。不同会话互不阻塞，同一会话同时执行返回 `SESSION_BUSY`。一个任务失败不会取消其他任务。`--parallel` 控制**本次批次**的并发数，不是跨 CLI 进程的全局配额。

## 输出与粒度

**必须同时收集 stdout、stderr 和退出码。不要使用 `2>/dev/null`。** stderr 包含错误原因与必要警告；coarse 已负责隐藏调用摘要，不需要丢弃整条流。

fine stdout：

```text
[task 2/2 done, max_elapsed 7.3s]

01/status: completed, elapsed 7.3s
01/evt/1: 让我看看文档内容
01/evt/4: 上半篇主要讨论……
01/evt/7: 下半篇补充了……

02/status: completed, elapsed 6.2s
02/evt/1: 让我查查……
02/evt/5: 查到了，结论是……
```

fine stderr：

```text
[tool feedbacks are hidden in stderr]
01/evt/2: read_file: {"path": "/workspace/inbox/文档.md"}
01/evt/5: read_file: {"path": "/workspace/inbox/文档.md", "offset": 12000}
02/evt/2: web_search: {"query": "查询内容"}
```

默认 coarse 的 stdout **同样保留所有可见自然语言回复**，不是只取最后一条。stderr 仅给出 `Tool call records are hidden`，另加不能隐藏的错误/警告。

- 事件序号在同一会话中持续递增。工具返回也占序号但不展示，因此允许编号间隙。
- 不展示 `reasoning_content` 等内部推理字段；正常可见 `content` 不截断。
- fine/coarse 都不是保密模式，模型可能在可见回复里复述资料。
- 结果缓存到结束后输出，fine **不是实时 token 流**。
- `done` 表示所有任务已结束，不等于都成功；`max_elapsed` 是最大单任务耗时，不是整批墙钟耗时（排队时差异更明显）。
- 答案是模型文本，不可信作协议解析依据；读取退出码和程序生成的状态。`completed` 仅表示获得最终文本，不保证事实正确或每个子目标都完成。

## 配置：只改传入的字段

```bash
batchcode op config g --model=deepseek-flash --parallel=2
batchcode op config s --session=01 --websearch=tavily
batchcode op config g
batchcode op config s --session=01
batchcode op config s --session=01 --unset=websearch
```

优先级：**任务对象 > 本次 task 命令 > 会话配置 > 全局配置 > 内置默认值**。

- `op config g` 持久修改全局默认；`op config s` 持久修改会话覆盖。
- task 参数只临时覆盖，不写回配置。
- `--websearch=none` 明确关闭；任务 JSON 也可用 `null`。`--unset=websearch` 是取消覆盖、恢复继承。
- 模型参数选择文件，例如 `deepseek-flash` 或 `deepseek-flash.txt`；不是直接向服务发送这个参数，实际模型 ID 取文件中的 `model`。
- `parallel` 只允许全局或批次级。granularity 可按会话/任务覆盖；混合粒度批次各自生效。
- 可显式更换模型；切换配置文件名时去除历史中的厂商推理字段，保留普通对话和工具历史。不是对所有第三方协议的兼容承诺。
- 高级资源与路径限制在本地 `config.json` 编辑；完整表见 [配置与安全](docs/CONFIG.md)。

## 会话分支与管理

```bash
batchcode task list
batchcode op fork-session --session=01 --target-session=02
batchcode op delete-session --session=01
```

列表只显示 ID，不调用 API，正常 stderr 为空：

```text
Active sessions:
01
Inactive sessions:
02
03
```

Active 依据独立的运行锁判断，不把短暂配置修改或残留 `status=running` 当成正在运行。

**编辑不存在的会话自动创建。** 仅查看不创建；删除不存在会话是成功的 no-op；fork 来源必须存在，目标必须不存在。

Fork 复制历史和会话覆盖、不复制日志或成果文件。历史文件引用仍指向原文件，所以不是文件系统快照。一次 fork 后并发执行：

```bash
batchcode task --parallel=2 \
  --task='{"fork_from":"base","session":"branch-a","content":"分析支持论据"}' \
  --task='{"fork_from":"base","session":"branch-b","content":"分析反对论据"}'
```

同批共享源会话只取一次快照；源正在运行则拒绝 fork。该批不能同时执行源会话或构造分支依赖链。

所有工具写入固定在 `sub_workspace/<session>/`，子代理使用相对文件名。不同会话的 `report.md` 不会互相覆盖；同会话同名文件可替换。实际路径通过 `<session>/artifact:` 返回。删除会话保留成果。

## 文档与开发

- [AGENT.md](AGENT.md)：供主 agent 使用的简明接口约定。
- [配置与安全](docs/CONFIG.md)：权限、资源限制和协议边界。
- [测试记录](docs/TESTING.md)：已测与未测范围。
- [CHANGELOG.md](CHANGELOG.md)：版本变更。

```bash
python3 -m unittest discover -s tests -v
python3 scripts/package.py
```

GitHub Actions 配置了 Python 3.10 / 3.12 / 3.14 的离线回归及安装打包检查，是否通过以实际 Actions 结果为准。

MIT License，沿用仓库原有 LICENSE。

## 只读 DNS 诊断（v0.2.1）

```bash
batchcode op doctor
batchcode op doctor --model=deepseek-flash --websearch=tavily --samples=3 --timeout=10
batchcode op doctor --websearch=tavily --json
```

在**容器内**测量所选 API 域名的系统解析耗时，不需要填写密钥，不调用模型/搜索 API，不修改 `/etc/resolv.conf`，也不探测或选择其他公共 DNS。只有显式调用才联网；原 `op self-check` 仍离线。
每次解析在可终止的独立进程中执行（默认单次最多 10 秒），避免诊断被阻塞的解析器无限挂住。退出码 0 表示本次 DNS 采样未见异常；1 表示解析失败、间歇失败或中位数至少 1 秒的启发式警告；2 表示配置/参数错误。**快不代表答案正确，慢也不自动证明 DNS 配置错误。** 不检查 TLS、代理、API 服务响应或实际计费性能。
详情见 [DNS 排障](docs/DNS.md)。独立 DNS 修复脚本不纳入项目。

## 模型采样与思考参数（v0.2.1）

```bash
batchcode task --temperature=0.7 --top-p=1 --reasoning-effort=auto --content="任务"
batchcode op config g --temperature=1
batchcode op config s --session=01 --thinking=enabled --reasoning-effort=high
batchcode op config s --session=01 --unset=temperature
```

支持 `temperature`、`top_p`、`presence_penalty`、`frequency_penalty`、`thinking`、`reasoning_effort`。CLI 用连字符（也接受下划线），JSON 用下划线。所有字段可选；可以写在模型 `.txt` 顶层，也可通过 task / 全局配置 / 会话配置覆盖。
优先级：任务对象 > 命令 > 会话 > 全局 > 模型配置（顶层优先于 extra_body）> 服务端默认。全局未设置这些字段时不覆盖模型配置；`--unset` 恢复继承。任务 JSON 中 `null` 明确不发送该字段。

内置 DS profile：`thinking="enabled"`、`reasoning_effort="auto"`、`temperature=1`、`top_p=1`。**auto 是 batchcode 约定，意味着不发送该字段，使用服务端默认；不是 DS API 的字面合法深度值。** 当前官方文档默认思考深度为 high，而不是保证模型自动选择深度。
`thinking` 可用 auto/enabled/disabled；effort 的其他值原样传递，是否支持取决于模型。temperature 范围 0–2，top_p 0–1，两种 penalty 为 -2–2；不填则不强制发送。DS 不再支持 penalty，思考模式下 temperature 等参数也可能无效，因此默认 DS profile 不添加无效 penalty。通常只调整 temperature/top_p 之一。
开启思考后，既有 4096 输出 token 上限可能不足；需要时调整 `config.json` 的 `max_output_tokens`，不要把输出截断误诊成 DNS 故障。
