# Fork 长期维护基线

本文记录 Ombre-Brain 生产 fork 相对官方仓库的长期维护差异。同步 upstream 时，应以本文列出的能力边界、生产契约和回归测试为准，而不是机械保留某段历史代码。

## 当前基线

- 生产仓库：`gugewang319-spec/Ombre-Brain`
- 生产部署分支：`zeabur`
- `origin/zeabur`：`83a85b8ba798fd36c63f13f1ad49e8076e811c2b`
- 官方远端：`Yinglianchun/Ombre-Brain`
- `upstream/main`：`bbd6500de639f64fef6d63b705d2509d937b0a16`
- merge-base：`bbd6500de639f64fef6d63b705d2509d937b0a16`
- `origin/zeabur` 相对 `upstream/main`：ahead 16、behind 0
- 当前净差异文件：30
- 运行时代码及配置净差异：约 `+508/-250`
- 当前 fork 健康等级：**B（健康，但核心补丁分散度偏高）**

更新本基线时，必须同时更新生产 SHA、upstream SHA、merge-base、ahead/behind、独有提交清单和净差异文件清单。

## 健康度判断

当前 `upstream/main` 是 `origin/zeabur` 的祖先，fork 没有落后于 upstream。16 个 ahead 提交是 Git 拓扑数量，不代表存在 16 套互不相关的长期补丁：其中一个是 upstream 同步 merge 节点，多个早期局部序列化修复已经被后续统一安全层吸收。

当前实际需要维护的能力约 7–8 类：

1. Zeabur 单容器部署与 `/data` 持久化。
2. Dashboard 同源鉴权、Cookie 和 API 容错。
3. 身份配置环境变量覆盖。
4. API JSON/Unicode 安全响应。
5. LLM、Embedding、Rerank 出站 payload Unicode sanitizer。
6. DeepSeek V4 后台结构化任务兼容。
7. Bucket 历史时间字段的数据兼容与稳定排序。
8. 对应的回归测试和 fork/upstream 维护流程。

补丁数量尚未失控，主要风险来自实现分散在 `gateway.py`、`server.py`、`dashboard.html`、`reflection_engine.py` 等 upstream 活跃核心文件中。

## 当前生产依赖

以下约定属于当前生产运行契约：

- `OMBRE_CONFIG_PATH=/data/state/config.yaml`
- Zeabur 自动部署分支为 `zeabur`
- `/data` 是持久化 Volume，至少承载 buckets 和 state
- Brain、Gateway 与 Nginx 在 Zeabur 单容器入口中共同运行
- Brain 使用 8000，Gateway 使用 8010，Nginx 监听 Zeabur 提供的 `PORT`
- `/v1/` 转发到 Gateway，Dashboard、Auth 和 `/api/` 转发到 Brain
- DeepSeek V4 后台结构化任务兼容
- API 响应和模型出站 payload 的 Unicode sanitizer

普通 upstream 同步不得静默改变这些约定。任何调整都必须单独审查、测试并准备回滚方案。

## Fork 独有提交

当前 `upstream/main..origin/zeabur` 包含 16 个提交：

| 提交 | 目的 | 分类 | 长期维护判断 |
| --- | --- | --- | --- |
| `5b60759c231618a542682747d18bda862061b4ef` | 增加 Zeabur 单容器部署，组合 Brain、Gateway 与 Nginx | 部署差异 | 当前生产长期保留 |
| `04939a26b17d78a7201c91b9e80aefa3581e9c80` | 修复同源反代环境中的 Dashboard 鉴权、Cookie 和 bucket 加载 | 部署差异、bug fix | Zeabur 架构仍使用同源反代时保留 |
| `2baf0d908cd6830098104528bc054d4b1370e793` | 修复 bucket API datetime 序列化 | bug fix、数据兼容 | 已由后续统一 JSON safe 能力吸收 |
| `74eea3e33a5b8286487989f42f328da84a8b0d20` | 修复 moments datetime 序列化 | bug fix、数据兼容 | 已由后续统一 JSON safe 能力吸收 |
| `bf8b79dafd88e7056c8960b9dbd546c28516d2fa` | 增强 moments API 序列化、错误响应和 Dashboard 报错 | bug fix、数据兼容 | upstream 提供等价 API 契约前保留 |
| `1751432583af31323210081e71821b5ed444d209` | 修复 moments API 非法 Unicode surrogate | bug fix、数据兼容 | 已由后续统一 sanitizer 吸收 |
| `2ebe85bd820afd9333828fc688b0c9a5a366bb90` | 增加身份环境变量覆盖 | 部署差异、配置能力 | 生产仍依赖环境覆盖时保留 |
| `1acff8f5c20bbad374f6aac35821b7f07d29eaa9` | 增加全局 Unicode/类型安全 JSONResponse | bug fix、数据兼容 | upstream 提供等价全局响应层前保留 |
| `4d58c6c5960d1df7d2b185f486b13a0d6ce3a6b9` | 合并 upstream 至 `bbd6500` | upstream 同步 | 同步节点，不是独立产品补丁 |
| `e0520fce8c66ee14c748b7f475c1837bee15c6d2` | 修复 DeepSeek V4 Persona 和脱水结构化任务 | 模型适配 | 当前模型组合必须保留；未来移入 Provider capability 层 |
| `a7a8df642c752529de5ce64dca0faf9884a17b36` | 统一模型、Embedding、Rerank 出站 payload Unicode sanitize | bug fix、数据兼容 | upstream 提供统一安全出站层前保留 |
| `e52310d6712d035e2361f6c81f28aa2932bbeff4` | 增加 fork 维护基线和 upstream 同步 SOP | 维护文档 | 长期保留并随生产更新 |
| `193b84c37655e5e09035cc8c87de48a9b73a03fb` | 修复 Reflection backfill 的 bucket 时间混合类型排序 | bug fix、数据兼容 | 保留能力；未来采用公共时间归一化层 |
| `90e3c12ae092410d167c2459acbd3b1318572670` | 修复 Import results 的 created 时间混合类型排序 | bug fix、数据兼容 | 保留能力；未来采用公共时间归一化层 |
| `03e4b1460257d1bc94ee7071aee45d35d522c0f2` | 增加 Reflection DeepSeek V4 结构化 JSON 任务兼容 | 模型适配 | 保留能力；未来移入 Provider capability 层 |
| `83a85b8ba798fd36c63f13f1ad49e8076e811c2b` | 恢复 dedicated daily 非 DeepSeek 模型的 thinking 控制并保持参数互斥 | bug fix、模型适配 | 保留能力；未来移入 Provider capability 层 |

早期 bucket、moment datetime 和 surrogate 提交虽然仍存在于生产历史中，但当前维护对象是后续形成的统一 JSON safe 和 Unicode sanitizer 能力。不得为了整理提交数量而 rebase 或重写生产历史。

## 当前净差异文件

当前共有 30 个净差异文件。

### 运行时代码与配置：17 个

- `config.example.yaml`
- `dashboard.html`
- `dehydrator.py`
- `dream_engine.py`
- `embedding_engine.py`
- `gateway.py`
- `import_memory.py`
- `persona_engine.py`
- `portrait_engine.py`
- `reclassify_api.py`
- `reflection_engine.py`
- `reranker_engine.py`
- `scripts/compare_dynamic_alpha_rrf.py`
- `scripts/local_memory_worker.py`
- `scripts/one_click.sh`
- `server.py`
- `utils.py`

这些文件合计净差异约为 `+508/-250`。

### Zeabur 部署文件：3 个

- `Dockerfile.zeabur`
- `zeabur/nginx.conf.template`
- `zeabur/start.sh`

### Fork 回归测试：8 个

- `test_deepseek_v4_structured_tasks.py`
- `test_global_unicode_json_response.py`
- `test_identity_environment_overrides.py`
- `test_import_results_time_sort.py`
- `test_llm_unicode_sanitize.py`
- `test_moments_api_serialization.py`
- `test_reflection_backfill_time_sort.py`
- `test_reflection_structured_tasks.py`

### 维护文档：2 个

- `docs/fork-maintenance.md`
- `docs/upstream-sync-sop.md`

## 最近新增的数据兼容能力

### Reflection bucket 时间排序

Reflection memory enrichment backfill 会读取 bucket YAML frontmatter 的 `metadata.updated_at` 或 `metadata.created`。历史数据可能被 YAML 解析为 `datetime`，也可能仍是 ISO 8601 字符串。

排序前必须统一归一化为可比较的 `datetime`：

- 支持 `datetime`
- 支持 ISO 8601 字符串
- 支持带时区字符串
- 空值和非法值使用稳定最小值并排在最后
- 不得用 `str(value)` 代替时间解析
- 不修改或重写现有 bucket 数据

### Import results created 时间排序

`/api/import/results` 对 bucket `metadata.created` 排序时遵循相同兼容规则。该修复只改变展示排序边界，不改变 import 写入流程、bucket schema 或生产数据。

## DeepSeek V4 后台结构化任务契约

以下规则只适用于明确要求结构化 JSON 的后台任务，不得影响普通聊天调用链。

### Persona

- 请求包含 `response_format={"type":"json_object"}`
- `deepseek-v4-*` 未显式配置 `thinking_mode` 时，默认发送 `thinking.type=disabled`
- 显式 `thinking_mode` 优先于自动默认
- 默认 `max_tokens=800`，显式配置仍优先
- 空 content、`finish_reason=length`、非法 JSON 和 API 异常分别记录

### Dehydration

- DeepSeek V4 后台任务未显式配置时默认 `thinking.type=disabled`
- 只有现有协议要求严格 JSON 的任务才加入 `response_format=json_object`
- 普通文本脱水、merge 和 moment 不得被强制 JSON mode

### Reflection

所有明确执行严格 JSON 解析的 Reflection 请求必须包含：

```json
{"response_format":{"type":"json_object"}}
```

DeepSeek V4 参数规则：

- 显式 `reflection.thinking_mode` 优先
- 未显式配置时默认 `thinking.type=disabled`
- 非 DeepSeek 模型不得收到 DeepSeek `thinking` 参数

Dedicated daily client 的互斥规则：

- 实际模型为 `deepseek-v4-*`：只发送 `thinking`，不得发送 `enable_thinking`
- 实际模型不是 DeepSeek V4 且使用 dedicated daily client：发送 `enable_thinking=False`，不得发送 `thinking`
- 其他非 DeepSeek、非 dedicated daily client：两者都不自动发送
- 任何请求不得同时包含 `thinking` 和 `enable_thinking`

## 主要高风险文件

### `gateway.py`

该文件承载普通聊天、Provider 转发、Recall、Persona 热更新和安全出站边界。同步时必须确认：

- 普通聊天不得被后台结构化任务的 `response_format=json_object` 污染
- 普通聊天不得被自动加入 `thinking=disabled`
- OpenAI 和 Anthropic 的流式、非流式 payload 继续经过 Unicode sanitize
- Persona 热更新继续传递 `thinking_mode`

upstream 对该文件修改频繁，属于最高冲突风险。

### `server.py`

该文件承载大量 API 路由、Dashboard 配置持久化、全局安全 JSONResponse、后台 scheduler 和本 fork 的时间兼容边界。同步时必须确认：

- `OMBRE_CONFIG_PATH` 继续指向外部持久配置，不得退回固定写入 `/app/config.yaml`
- 未知配置字段在持久化时得到保留
- Persona 和 Reflection 的 `thinking_mode` 可加载、保存、热更新并立即生效
- Bucket、Moments 和其他 API 继续使用统一安全响应层
- Reflection backfill 与 Import results 的时间排序保持混合类型安全

upstream 对该文件修改频繁，禁止整文件选择 ours 或 theirs。

### `dashboard.html`

这是大型单文件界面，文本冲突和隐性运行回归风险都高。同步后必须实际验证：

- Dashboard、Auth 和 API 使用同一 public origin
- Cookie 随请求发送
- bucket/moments 错误响应不会导致整页崩溃
- Persona 和 Reflection thinking 配置能够加载、留空、保存

### `reflection_engine.py`

该文件同时承载 Reflection、每日聊天记忆、活动摘要、日记候选和 dedicated daily client。同步时必须确认：

- 严格 JSON 任务继续使用 JSON mode
- DeepSeek V4 自动默认和显式配置优先级不变
- `thinking` 与 `enable_thinking` 始终互斥
- 普通文本任务没有被错误强制 JSON
- Bucket 时间排序保持 `datetime`/字符串兼容
- 错误日志不泄露完整对话、memory 或 API Key

### `config.example.yaml`

upstream 经常修改该文件。同步时必须逐字段合并，确认：

- Persona 默认 `max_tokens=800`
- Persona、Dehydration、Reflection 的 `thinking_mode` 语义一致
- 留空表示 auto，而不是无条件走 Provider 默认
- 新旧持久配置都能加载，未知字段不会丢失

## 次级高风险文件

- `utils.py`：统一 sanitizer、JSONResponse、模型 wrapper、配置加载和环境覆盖
- `persona_engine.py`：Persona JSON mode、thinking、token 上限和错误分类
- `dehydrator.py`：严格 JSON 与普通文本任务边界
- `scripts/one_click.sh`：新安装默认配置必须与 `utils.py`、`config.example.yaml` 一致

这些文件文本冲突概率可能低于主要高风险文件，但存在较高语义回归风险。

## Zeabur 部署文件的运行高风险

以下文件即使很少产生 Git 文本冲突，也必须作为运行高风险文件审查：

- `Dockerfile.zeabur`
- `zeabur/nginx.conf.template`
- `zeabur/start.sh`

同步或修改后必须确认：

- `/data` 仍为持久化路径
- `OMBRE_CONFIG_PATH=/data/state/config.yaml` 仍生效
- Brain、Gateway 和 Nginx 端口与路由不变
- `/v1/` 仅转发到 Gateway
- Dashboard、Auth、`/api/` 转发到 Brain
- Cookie 和 `Set-Cookie` 不被代理破坏
- 任一子进程退出时容器能正确退出，TERM 能传播给所有子进程
- Docker 构建继续包含全部 Python、资源、脚本和 Dashboard 文件

## 必须长期保留的能力

在 upstream 未提供经过验证的等价实现前，必须保留：

1. Zeabur 单容器部署与 `/data` 持久化契约。
2. `OMBRE_CONFIG_PATH=/data/state/config.yaml`。
3. Dashboard 同源鉴权和 Cookie 行为。
4. DeepSeek V4 Persona、Dehydration、Reflection 后台结构化任务兼容。
5. Dedicated daily 非 DeepSeek 模型的 `enable_thinking=False` 行为及参数互斥。
6. API 响应的全局 JSON/Unicode 安全层。
7. ChatCompletion、Embedding、Rerank 和原始 HTTP 模型 payload 的统一 sanitizer。
8. Bucket 历史时间字段的混合类型排序兼容。
9. 身份环境变量覆盖，如果生产环境仍依赖它。
10. 上述能力对应的回归测试。

## 可由 upstream 等价实现替代的部分

未来可在验证等价性后采用官方实现：

- Bucket、Moments 和 Import API 的局部 datetime/surrogate 补丁
- 官方统一 JSON encoder 或安全响应层
- 官方统一模型 transport/middleware sanitizer
- DeepSeek 模型名判断和 Provider 私有 thinking 参数分支
- 官方公开、稳定的时间归一化函数
- Dashboard 同源鉴权、错误显示和结构化任务配置 UI
- 身份环境变量覆盖体系

替代前必须满足：

1. upstream 实现覆盖相同输入边界和错误场景。
2. fork 回归测试继续通过，或已按官方接口等价调整。
3. Zeabur 持久化、配置和代理行为没有改变。
4. 普通聊天没有受到后台结构化参数影响。

## 已记录技术债

以下是后续可逐步处理的结构性技术债，本基线不授权立即重构：

1. 提取 Provider / thinking / JSON task policy 独立模块，统一模型能力识别、JSON mode 和互斥参数。
2. 提取公共时间归一化模块，避免跨模块调用私有 parser 和重复日期 helper。
3. 提取模型安全出站 transport，统一 ChatCompletion、Embedding、Rerank 和原始 HTTP JSON 边界。
4. 逐步拆分 Dashboard 配置加载、验证、保存和 UI 绑定逻辑，降低大型单文件冲突面。

当前不要为了减少 diff 立即进行大规模重构。先保持生产稳定，先建立或保留能力级回归测试，再以独立分支、小提交逐步抽取。

## Upstream 同步原则

- 下次 upstream 更新必须按 `docs/upstream-sync-sop.md` 操作。
- 只在独立 `sync/upstream-main-<sha>` 分支合并 upstream。
- 高风险文件禁止整文件选择 ours 或 theirs，必须逐块审查。
- 禁止 rebase 或改写生产 `zeabur` 历史。
- 官方出现等价实现时，优先采用官方实现并保留回归测试。
- 保留能力和测试，不执着保留当前具体实现。
- 不要在 upstream 同步中顺手进行大规模本地重构。
- 完成全量 pytest、py_compile、Shell 语法检查和 `git diff --check` 后，才可进入生产合入审查。

完整同步和部署验证流程见 `docs/upstream-sync-sop.md`。

## 2026-07-18 维护记录

- 当前生产头：`83a85b8ba798fd36c63f13f1ad49e8076e811c2b`
- 当前文档目标头：由本次维护记录提交产生，以文档分支 HEAD 为准

### 1. 分离生产分支

- Zeabur 使用 `zeabur` 作为生产部署分支。
- `main` 保持不动。
- 后续生产更新只通过 fast-forward-only 推进，不产生额外 merge commit。

### 2. 同步 upstream

- `upstream/main` 基线为 `bbd6500de639f64fef6d63b705d2509d937b0a16`。
- `zeabur` 完整包含当前 upstream。
- 当前 behind 为 0。

### 3. 配置持久化

- 持久配置路径为 `OMBRE_CONFIG_PATH=/data/state/config.yaml`。
- `/data/state` 与 `/data/buckets` 使用持久卷。
- API Key、Token 和密码继续通过 Zeabur 环境变量提供，不写入仓库文档或配置样例。

### 4. DeepSeek V4 结构化任务兼容

- Persona 使用 JSON mode，并按模型和显式配置决定 thinking 参数。
- Dehydrator 只对协议要求严格 JSON 的任务启用 JSON mode。
- Reflection 的六类 JSON 任务均纳入结构化请求：分类、反思、每日聊天窗口摘要、每日活动摘要、每日聊天记忆候选和日记记忆候选。
- DeepSeek V4 未显式配置时默认 `thinking.type=disabled`。
- 显式 `thinking_mode` 优先于自动默认。
- Dedicated daily 的非 DeepSeek 模型（如 Qwen）保留 `enable_thinking=False`。
- `thinking` 与 `enable_thinking` 始终互斥。

### 5. Unicode 安全

- API `JSONResponse` 使用统一安全序列化边界。
- ChatCompletion、Embedding、Rerank 和 raw HTTP 模型 payload 在序列化前统一 sanitize。
- 非法 Unicode surrogate 使用 replacement 替换；正常 Unicode、数字、布尔值、`None` 和数据结构保持不变。

### 6. Bucket 时间兼容

- 已覆盖 Reflection enrichment backfill、memory-edge backfill、entity-edge backfill、Reflection 候选排序和 `/api/import/results`。
- `datetime`、ISO string、带时区字符串、空值和非法值统一转换为稳定可比较的排序键。
- 本轮修复没有批量改写生产 bucket，也没有修改 memory schema。

### 7. Reflection Provider 配置错配

- 生产 Reflection 模型为 `reflection.model=deepseek-v4-flash`。
- `reflection.base_url` 为空时曾错误回退到 SiliconFlow embedding provider，造成 model 与 Provider 不匹配。
- 通过 `OMBRE_REFLECTION_MODEL`、`OMBRE_REFLECTION_BASE_URL`、`OMBRE_REFLECTION_API_KEY` 将 model、base URL 和凭据固定到同一 Provider。
- Reflection scheduler 在服务重启后读取并使用上述配置。

### 8. Keepalive 告警验证

- 容器内验证目标为 `http://127.0.0.1:8000/health`，对应 Brain 自身的健康端点。
- 五次验证均返回 HTTP 200，耗时约 0.006–0.024 秒。
- 基于这五次样本，告警判断为部署启动阶段的偶发毛刺；未发现持续性健康端点故障。
- 当前无需修改 keepalive 代码。

### 9. 测试和维护流程

- 当前记录的最高全量测试结果为 `55 passed`。
- 已建立 `docs/fork-maintenance.md`。
- 已建立 `docs/upstream-sync-sop.md`。
- 高风险文件禁止整文件选择 ours 或 theirs。
- 保留能力和测试，不执着保留具体实现。
- 当前 fork 健康等级为 B（健康，但核心补丁分散度偏高）。
