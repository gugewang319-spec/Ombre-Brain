# Upstream 同步标准流程

本文规定如何把 `Yinglianchun/Ombre-Brain` 的新版本安全同步到生产 fork。所有同步必须先进入独立 sync 分支，经审查和测试后再以 fast-forward-only 推进 `zeabur`。

维护差异和能力边界见 `docs/fork-maintenance.md`。

## 基本规则

- 不直接在 `zeabur` 上合并 upstream。
- 不修改或推送 `main`。
- 不 force push。
- 不 rebase 生产历史。
- 不在同步过程中修改 Zeabur 环境变量或 `/data`。
- 高风险文件禁止整文件选择 ours/theirs。
- 优先采用 upstream 的等价实现，但必须保留能力和回归测试。
- 任一基线、合并、测试或部署门禁失败时立即停止。

## 1. 刷新并确认工作区

```bash
git status --short
git fetch origin --prune
git fetch upstream --prune

git rev-parse origin/zeabur
git rev-parse origin/main
git rev-parse upstream/main
git merge-base origin/zeabur upstream/main
```

要求：

- 工作树干净。
- 当前生产 SHA 与远端 `origin/zeabur` 一致。
- `origin/main` 只记录，不修改。
- 明确当前生产已包含到哪个旧 upstream 基线。

记录以下四个值：

```text
OLD_PRODUCTION_SHA=<同步前 origin/zeabur>
OLD_UPSTREAM_BASE_SHA=<生产已包含的 upstream 基线>
NEW_UPSTREAM_SHA=<当前 upstream/main>
MAIN_SHA=<同步前 origin/main>
```

不要依赖短 SHA 执行生产写操作。

## 2. 审计 upstream 新增提交

```bash
git log --oneline --decorate --graph OLD_UPSTREAM_BASE_SHA..upstream/main
git diff --stat OLD_UPSTREAM_BASE_SHA..upstream/main
git diff --name-status OLD_UPSTREAM_BASE_SHA..upstream/main
```

逐项回答：

- 作者新增、删除或重构了哪些能力？
- 是否改动配置 schema、默认值、持久化路径或环境变量？
- 是否改动 Dashboard/Auth/API 路径？
- 是否改动普通聊天、Persona、脱水、Portrait、Reflection、Embedding 或 Rerank 调用？
- 是否新增统一 JSON encoder、Provider capability 或 Unicode sanitizer？
- 是否修改 Docker、启动脚本、Volume 或端口？

## 3. 找出重叠文件

分别列出 upstream 新改文件和 fork 维护文件：

```bash
git diff --name-only OLD_UPSTREAM_BASE_SHA..upstream/main
git diff --name-only OLD_UPSTREAM_BASE_SHA..origin/zeabur
```

重点审查交集，尤其是：

- `server.py`
- `gateway.py`
- `utils.py`
- `dashboard.html`
- `persona_engine.py`
- `dehydrator.py`
- `config.example.yaml`
- `scripts/one_click.sh`

同时检查 Zeabur 运行高风险文件：

- `Dockerfile.zeabur`
- `zeabur/nginx.conf.template`
- `zeabur/start.sh`

## 4. 创建同步分支

同步分支必须从当前远端生产创建，不能从 `main` 或 upstream 创建：

```bash
git switch -c sync/upstream-main-NEW_UPSTREAM_SHORT_SHA origin/zeabur
git rev-parse HEAD
git status --short
```

HEAD 必须等于 `OLD_PRODUCTION_SHA`，工作树必须干净。

如果同名本地或远端分支已经存在，应先核对它的用途和 SHA；不要覆盖或删除未知分支。

## 5. 只在同步分支合并 upstream

```bash
git merge --no-commit --no-ff upstream/main
```

如有冲突，保持 merge 未完成状态并逐文件处理。禁止在此阶段切换或推进 `zeabur`。

### 冲突处理规则

高风险文件不得使用整文件 ours/theirs。必须逐块判断：

1. upstream 是否已经提供等价实现。
2. 官方实现是否覆盖本 fork 的生产场景。
3. 是否可以删除本 fork 的重复实现并保留测试。
4. 是否需要把本 fork 的最小能力移植到 upstream 新结构。

具体要求：

- `server.py`：保留 `OMBRE_CONFIG_PATH`、未知配置字段、Persona 配置持久化和安全 API 响应。
- `gateway.py`：普通聊天不得继承后台结构化任务的 thinking/response_format；新增模型边界必须 sanitize。
- `utils.py`：统一配置、响应和模型 sanitizer，不保留重复 helper。
- `dashboard.html`：保留同源 Cookie、错误处理和 Persona thinking 配置链。
- `persona_engine.py`：保留 JSON mode、V4 auto thinking disabled、800 tokens 和错误分类。
- `dehydrator.py`：只有严格 JSON 任务使用 response_format，普通文本任务不强制 JSON。
- 部署文件：保留 `/data`、端口、反向代理和进程监管契约。

完成冲突处理后：

```bash
git status --short
git diff --check
git diff --cached --check
```

然后创建一个明确的 upstream 同步提交。不要 squash、rebase 或改写既有生产提交。

## 6. 判断并采用官方等价实现

如果 upstream 已提供同类能力，优先做等价性审查，而不是默认叠加本 fork 实现。

至少核对：

- 输入边界是否一致。
- 非法 surrogate 是否使用 replacement 而不是 `ignore`。
- dict key、Path、嵌套 payload 和 SDK 内部序列化是否覆盖。
- DeepSeek V4 的显式配置优先级是否一致。
- JSON mode 是否只用于严格结构化任务。
- 普通聊天模型、thinking、temperature 和路由是否保持原行为。
- 配置能否从 YAML 加载、Dashboard 保存、热更新和持久化。
- 未知配置字段是否保留。

若官方实现等价：

1. 使用官方实现。
2. 删除本 fork 的重复实现。
3. 保留或调整回归测试，使其验证能力而非内部函数名。
4. 在同步审查中记录被官方替代的维护项。

## 7. 完整测试

至少运行：

```bash
python -m pytest -q

python -m py_compile \
  utils.py \
  gateway.py \
  server.py \
  persona_engine.py \
  dehydrator.py \
  embedding_engine.py \
  reranker_engine.py

bash -n zeabur/start.sh
bash -n ob
bash -n scripts/doctor.sh
bash -n scripts/one_click.sh

git diff --check
```

如果 upstream 或冲突处理修改了其他 Python 或 Shell 文件，应把它们加入对应语法检查。

相关能力测试至少应覆盖：

- Dashboard/Auth/API serialization
- 配置环境变量覆盖和持久化
- Persona/Dehydrator DeepSeek V4 参数
- Unicode JSONResponse
- Unicode LLM/Embedding/Rerank payload
- moments API serialization
- 普通聊天没有收到后台结构化任务参数

如果环境支持，还应运行：

```bash
docker build -f Dockerfile.zeabur .
```

任何测试失败都不得推送生产分支。

## 8. 推送同步分支并审查

先只推送 sync 分支：

```bash
git push -u origin sync/upstream-main-NEW_UPSTREAM_SHORT_SHA
```

随后审查：

```bash
git log --oneline --decorate --graph origin/zeabur..origin/sync/upstream-main-NEW_UPSTREAM_SHORT_SHA
git diff --stat origin/zeabur..origin/sync/upstream-main-NEW_UPSTREAM_SHORT_SHA
git diff --name-status origin/zeabur..origin/sync/upstream-main-NEW_UPSTREAM_SHORT_SHA
git diff --name-status upstream/main..origin/sync/upstream-main-NEW_UPSTREAM_SHORT_SHA
git diff --check origin/zeabur..origin/sync/upstream-main-NEW_UPSTREAM_SHORT_SHA
```

审查报告必须说明：

- 合入了哪些 upstream 提交。
- 哪些高风险文件发生重叠。
- 哪些 fork 实现被官方实现替代。
- 哪些 fork 能力仍需保留。
- 测试结果和未覆盖风险。
- `main`、Zeabur 配置、环境变量和 `/data` 是否保持不变。

## 9. 创建生产更新前备份

同步分支审查通过后、推进生产前创建远端备份：

```bash
git ls-remote --heads origin backup/zeabur-pre-upstream-NEW_UPSTREAM_SHORT_SHA
git push origin OLD_PRODUCTION_SHA:refs/heads/backup/zeabur-pre-upstream-NEW_UPSTREAM_SHORT_SHA
git ls-remote --heads origin backup/zeabur-pre-upstream-NEW_UPSTREAM_SHORT_SHA
```

如果备份分支已存在，必须确认它指向 `OLD_PRODUCTION_SHA`；否则停止。不要覆盖或删除已有备份。

## 10. Fast-forward-only 推进生产

再次刷新并确认生产没有被其他人推进：

```bash
git fetch origin
git rev-parse origin/zeabur
git rev-parse origin/sync/upstream-main-NEW_UPSTREAM_SHORT_SHA
git merge-base --is-ancestor origin/zeabur origin/sync/upstream-main-NEW_UPSTREAM_SHORT_SHA
```

要求：

- `origin/zeabur` 仍等于 `OLD_PRODUCTION_SHA`。
- ancestor 检查退出码为 0。
- 工作树干净。

然后执行：

```bash
git switch -C zeabur origin/zeabur
git merge --ff-only origin/sync/upstream-main-NEW_UPSTREAM_SHORT_SHA

git rev-parse HEAD
git status --short
git diff origin/sync/upstream-main-NEW_UPSTREAM_SHORT_SHA..HEAD

git push origin zeabur
```

禁止 cherry-pick 同步提交，避免制造重复提交；禁止 force push。

推送后核验：

```bash
git ls-remote --heads origin \
  main \
  zeabur \
  sync/upstream-main-NEW_UPSTREAM_SHORT_SHA \
  backup/zeabur-pre-upstream-NEW_UPSTREAM_SHORT_SHA

git status --short
git log --oneline --decorate --graph -15
```

确认 `main` 仍等于同步前记录的 `MAIN_SHA`。

## 11. Zeabur 部署后验证

推送 `zeabur` 后，应确认自动部署已触发，并验证：

### Dashboard 与代理

- `/dashboard` 可访问。
- 登录、退出和 Cookie 会话正常。
- `/api/buckets`、moments 和配置页面正常。
- `/gateway-health` 与 Brain health 正常。

### 配置持久化

- 运行时仍使用 `OMBRE_CONFIG_PATH=/data/state/config.yaml`。
- Dashboard 保存后写入持久化配置，而不是容器内临时 `/app/config.yaml`。
- 重启后配置仍存在。
- 未知配置字段未丢失。

### 聊天与记忆

- OpenAI-compatible 非流式和流式聊天正常。
- Anthropic-compatible 路由如生产使用，也应验证。
- 主聊天模型、thinking、temperature 和路由符合生产配置。
- bucket、moment、召回和 memory detail 正常。
- 非法 Unicode 不再导致 UTF-8 surrogate 编码异常。

### Persona 与脱水

- Persona 可成功生成结构化 JSON。
- DeepSeek V4 后台 Persona 默认关闭 thinking，显式配置优先。
- Persona 默认或配置的 token 上限生效。
- 脱水严格 JSON 任务使用 response format。
- 普通文本脱水不被强制 JSON。
- Dashboard 修改 Persona thinking 后能立即热更新并持久化。

## 12. 回滚原则

发生生产回归时，优先使用保留历史的 revert，而不是 force push 回旧 SHA。根据同步提交结构选择正确的 revert；如果需要回滚 merge commit，应明确指定主线父提交并在独立回滚分支先测试。

备份分支用于定位更新前生产状态和恢复验证，不得删除。回滚完成后同样需要运行测试并验证 Zeabur 部署、配置持久化、聊天和记忆功能。

## 禁止事项

- 直接修改或推送 `main`
- 在 `zeabur` 上直接合并 upstream
- force push
- rebase 或改写生产历史
- 删除 sync 或 backup 分支
- 未经审查整文件选择 ours/theirs
- 测试失败后继续推送生产
- 在同步过程中修改 Zeabur 环境变量或 `/data`
- 把 API Key、密码、Token 或生产私密对话写入日志、提交或审查报告
