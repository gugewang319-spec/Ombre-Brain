# Fork 长期维护基线

本文记录 Ombre-Brain 生产 fork 相对官方仓库的长期维护差异。同步 upstream 时，应以本文列出的能力边界和回归测试为准，而不是机械保留某段历史代码。

## 基线

- 生产仓库：`gugewang319-spec/Ombre-Brain`
- 生产分支：`zeabur`
- 当前生产 SHA：`a7a8df642c752529de5ce64dca0faf9884a17b36`
- 官方远端：`Yinglianchun/Ombre-Brain`
- upstream 基线：`bbd6500de639f64fef6d63b705d2509d937b0a16`
- 当前生产与 upstream 的 merge-base：`bbd6500de639f64fef6d63b705d2509d937b0a16`

更新本文基线时，必须同时更新生产 SHA、upstream SHA、提交清单和净差异文件清单。

## 当前生产依赖

以下约定属于当前生产运行契约：

- `OMBRE_CONFIG_PATH=/data/state/config.yaml`
- Zeabur 自动部署分支为 `zeabur`
- `/data` 是持久化 Volume，至少承载 buckets 和 state
- Brain、Gateway 与 Nginx 由 Zeabur 单容器入口共同运行
- DeepSeek V4 后台结构化任务兼容
- API 响应与模型出站 payload 的 Unicode sanitizer

不得在普通 upstream 同步中静默改变这些约定。任何调整都必须单独审查、测试并准备回滚方案。

## 维护原则

> 保留能力和测试，不执着保留具体实现。

如果 upstream 提供语义等价、测试充分且更通用的实现，应优先回归官方实现，并保留或调整本 fork 的回归测试。不要为了保留历史 diff 而并行维护重复逻辑。

## Fork 独有提交

当前 `upstream/main..zeabur` 包含 11 个提交：

| 提交 | 目的 | 长期维护判断 |
| --- | --- | --- |
| `5b60759c231618a542682747d18bda862061b4ef` | 增加 Zeabur 单容器部署，组合 Brain、Gateway 与 Nginx | 生产部署能力，长期保留 |
| `04939a26b17d78a7201c91b9e80aefa3581e9c80` | 修复反代环境 Dashboard Cookie、鉴权和 bucket 加载 | 在 Zeabur 同源反代仍需要时保留 |
| `2baf0d908cd6830098104528bc054d4b1370e793` | 修复 bucket API datetime 序列化 | 已由后续统一 JSON safe 能力吸收 |
| `74eea3e33a5b8286487989f42f328da84a8b0d20` | 修复 moments datetime 序列化 | 已由后续统一 JSON safe 能力吸收 |
| `bf8b79dafd88e7056c8960b9dbd546c28516d2fa` | 增强 moments API 序列化、错误响应和 Dashboard 报错 | 官方提供等价 API 契约前保留 |
| `1751432583af31323210081e71821b5ed444d209` | 修复 moments API 非法 Unicode surrogate | 已由后续统一 sanitizer 吸收 |
| `2ebe85bd820afd9333828fc688b0c9a5a366bb90` | 增加身份环境变量覆盖 | 生产配置能力，按运行依赖保留 |
| `1acff8f5c20bbad374f6aac35821b7f07d29eaa9` | 增加全局 Unicode/类型安全 JSONResponse | 官方提供等价全局响应层前保留 |
| `4d58c6c5960d1df7d2b185f486b13a0d6ce3a6b9` | 合并 upstream 至 `bbd6500` | 同步节点，不是独立产品能力 |
| `e0520fce8c66ee14c748b7f475c1837bee15c6d2` | 修复 DeepSeek V4 Persona 和脱水结构化任务 | 当前模型组合必须保留 |
| `a7a8df642c752529de5ce64dca0faf9884a17b36` | 统一模型、Embedding、Rerank 出站 payload Unicode sanitize | 官方提供统一安全出站层前保留 |

早期的 bucket、moment 局部序列化提交虽然仍存在于历史中，但当前维护对象是后续形成的统一 JSON safe 和 Unicode sanitizer 能力。不应在同步时重新引入多套局部 helper。

## 差异文件维护分类

风险级别：

- **高**：upstream 修改后必须逐块人工合并，禁止整文件选择一方。
- **中**：改动范围较小，但相关功能被重构时可能产生语义冲突。
- **低**：通常是新增部署文件或回归测试，文本冲突概率较低。

| 文件 | 修改原因 | 分类 | 冲突风险 |
| --- | --- | --- | --- |
| `Dockerfile.zeabur` | 构建 Python、Nginx、应用文件和持久化目录，提供单容器入口 | 部署适配 | 低文本风险；高运行风险 |
| `zeabur/nginx.conf.template` | 将 `/v1/` 转发给 Gateway，将 Dashboard、Auth 和 API 保持在 Brain 同源 | 部署适配 | 低文本风险；高运行风险 |
| `zeabur/start.sh` | 启动并监管 Brain、Gateway、Nginx，传播退出信号 | 部署适配 | 低文本风险；高运行风险 |
| `config.example.yaml` | 记录 DeepSeek V4 auto thinking 语义和 Persona 800 token 默认值 | 配置/功能 | 高 |
| `dashboard.html` | 同源鉴权、Cookie、bucket 容错、moments 错误显示、Persona thinking 配置 | 部署适配/功能增强 | 高 |
| `scripts/one_click.sh` | 新安装配置使用 Persona `max_tokens=800` | 安装适配 | 高 |
| `server.py` | 安全 JSONResponse、bucket/moment 序列化、Persona thinking 持久化和热更新、模型 payload sanitize | 核心功能/稳健性 | 高 |
| `utils.py` | 身份环境变量、统一 JSON safe、Unicode sanitizer、模型 wrapper 和 Persona 默认值 | 核心基础设施 | 高 |
| `gateway.py` | 安全 API 响应、普通聊天出站 sanitize、内部模型任务 wrapper、Persona thinking 热更新 | 核心功能 | 高 |
| `persona_engine.py` | V4 thinking、JSON mode、800 tokens、finish_reason 分类和 Unicode-safe 调用 | 功能增强 | 高 |
| `dehydrator.py` | V4 后台任务关闭 thinking、严格 JSON 任务 response_format 和 Unicode-safe 调用 | 功能增强 | 高 |
| `dream_engine.py` | Dream JSON 和完整 ChatCompletion payload sanitize | 稳健性 | 中 |
| `embedding_engine.py` | Embedding 输入统一 sanitize | 稳健性 | 中 |
| `import_memory.py` | 导入提取任务的模型 payload sanitize | 稳健性 | 中 |
| `portrait_engine.py` | Portrait JSON payload 和重试请求 sanitize | 稳健性 | 中 |
| `reflection_engine.py` | 反思、日记、每日摘要等模型 payload sanitize | 稳健性 | 中 |
| `reranker_engine.py` | HTTP rerank JSON payload sanitize | 稳健性 | 中 |
| `reclassify_api.py` | 重分类模型请求使用统一安全 wrapper | 稳健性 | 中 |
| `scripts/compare_dynamic_alpha_rrf.py` | 离线 Embedding 请求 sanitize | 工具稳健性 | 低 |
| `scripts/local_memory_worker.py` | urllib JSON 请求在编码前 sanitize | 工具稳健性 | 低 |
| `test_deepseek_v4_structured_tasks.py` | 覆盖 Persona/脱水 V4 参数、配置保存和错误分类 | 回归测试 | 低 |
| `test_global_unicode_json_response.py` | 覆盖全局 API Unicode 安全响应 | 回归测试 | 低 |
| `test_identity_environment_overrides.py` | 覆盖身份环境变量优先级 | 回归测试 | 低 |
| `test_llm_unicode_sanitize.py` | 覆盖模型 payload、Path、dict key、Portrait 和幂等性 | 回归测试 | 低 |
| `test_moments_api_serialization.py` | 覆盖 moments/bucket datetime、Path、surrogate 和错误响应 | 回归测试 | 低 |

## 高风险文件

### `server.py`

该文件同时承载大量官方 API 路由、Dashboard 配置持久化和本 fork 的统一 JSONResponse。同步时重点检查：

- `OMBRE_CONFIG_PATH` 是否仍被尊重，不能退回固定写入容器内 `/app/config.yaml`
- 未知配置字段是否在持久化时得到保留
- Persona `thinking_mode` 是否能加载、保存、热更新并立即生效
- bucket、moments 和其他 API 是否仍使用全局安全响应层
- 所有内部模型任务是否经过统一出站 sanitizer

### `gateway.py`

这是普通聊天、召回、Provider 转发和 Persona 更新的共同主路径。同步时重点检查：

- 普通聊天不得被强制加入结构化任务专用的 `response_format` 或 `thinking=disabled`
- OpenAI 与 Anthropic 的流式/非流式请求仍经过 Unicode sanitize
- 新增的内部 LLM、Embedding 或 Rerank 调用不得绕过统一出站层
- Persona 配置热更新仍包含 `thinking_mode`

### `utils.py`

该文件同时承载配置加载、环境变量覆盖、响应序列化和模型请求 wrapper。同步时重点检查：

- `make_json_safe` 和 `sanitize_unicode` 不应出现重复或语义分叉
- sanitizer 保持幂等，正常 Unicode 和 JSON 原生结构不变
- 非法 surrogate 使用 replacement，不使用 `ignore`
- 环境变量覆盖优先级不被 upstream 配置重构破坏

### `dashboard.html`

这是大型单文件界面，文本冲突和隐性运行回归风险都高。同步后必须实际验证：

- Dashboard、Auth 和 API 使用同一 public origin
- Cookie 能随请求发送
- bucket API 非数组或错误响应不会导致整页崩溃
- moments 错误信息可见
- Persona thinking 的加载、留空/自动、保存链路完整

### `persona_engine.py`

必须保留：

- 显式 `thinking_mode` 优先
- `deepseek-v4-*` 未显式配置时后台任务默认 `disabled`
- `response_format={"type":"json_object"}`
- 默认 `max_tokens=800`，显式配置优先
- 空 content、`finish_reason=length`、非法 JSON、API 异常分别记录
- 完整 payload 在模型 SDK 序列化前经过 sanitize

### `dehydrator.py`

必须保留：

- DeepSeek V4 后台任务默认 `thinking=disabled`
- 显式 `thinking_mode` 优先
- 只有严格 JSON 任务设置 `response_format=json_object`
- 普通文本脱水、merge 和 moment 不被强制 JSON
- 所有模型调用经过统一出站 sanitizer

### `config.example.yaml` 与 `scripts/one_click.sh`

这两个文件和 `utils.py` 的内置默认值必须保持一致。重点核对 Persona `max_tokens`、`thinking_mode` 的 auto 语义，以及新安装配置是否符合生产预期。

## Zeabur 部署文件的运行高风险

以下文件即使很少产生 Git 文本冲突，也必须作为运行高风险文件审查：

- `Dockerfile.zeabur`
- `zeabur/nginx.conf.template`
- `zeabur/start.sh`

同步或改动后必须确认：

- `/data` 仍为持久化路径
- `OMBRE_CONFIG_PATH=/data/state/config.yaml` 的外部配置仍生效
- Brain 使用 8000，Gateway 使用 8010，Nginx 使用 Zeabur 提供的 `PORT`
- `/v1/` 仅转发到 Gateway，Dashboard、Auth、`/api/` 转发到 Brain
- `Set-Cookie` 和请求 Cookie 不被反代破坏
- 任一子进程退出时容器能正确退出，TERM 能传递给所有子进程
- Docker 构建仍包含应用所需的 Python、资源、脚本和 Dashboard 文件

## 必须长期保留的能力

在 upstream 未提供经过验证的等价实现前，必须保留：

1. Zeabur 单容器部署与 `/data` 持久化契约。
2. `OMBRE_CONFIG_PATH=/data/state/config.yaml` 的配置持久化路径。
3. Dashboard 在同源反代环境中的鉴权和 Cookie 行为。
4. DeepSeek V4 后台结构化任务兼容：
   - Persona JSON mode
   - Persona 默认 800 tokens
   - DeepSeek V4 auto thinking disabled
   - 严格 JSON 脱水任务的 response format
   - 可诊断的 Persona 失败分类
5. API 响应的全局 JSON/Unicode 安全层。
6. ChatCompletion、Embedding、Rerank 和原始 HTTP 模型 payload 的统一 Unicode sanitizer。
7. 身份环境变量覆盖，如果生产环境仍依赖它。
8. 上述能力对应的回归测试。

## 可被官方等价实现替代的部分

未来可在验证等价性后回归官方实现：

- bucket 和 moments 的局部 datetime/surrogate 补丁，可由官方全局 JSON encoder 替代。
- Dashboard 的同源鉴权、bucket 数组保护和 moments 错误显示，可由官方等价 UI/API 契约替代。
- DeepSeek 模型名判断，可由官方 Provider capability 或模型能力层替代。
- 各引擎中的逐调用 wrapper，可由官方统一 client transport/middleware sanitizer 替代。
- 身份环境变量覆盖，可由官方明确支持的配置覆盖系统替代。
- 安装脚本中的 Persona 默认值差异，可在官方默认值和语义一致后消失。

替代前必须满足：

1. 官方实现覆盖相同输入边界和错误场景。
2. 本 fork 的相关回归测试继续通过，或已按官方接口等价调整。
3. Zeabur 的持久化、配置和代理行为未改变。
4. 普通聊天调用链没有受到后台结构化任务参数影响。

完整同步流程见 `docs/upstream-sync-sop.md`。
