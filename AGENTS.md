# Dockerfile 生成要求

本目录下的单测镜像任务，按以下约束生成和维护 Dockerfile/Containerfile。

## 基础约束

- 目标是生成可用 `podman build` 构建的 Dockerfile/Containerfile。
- 镜像用于构建后再进入容器或通过 `podman run` 显式执行单测；不要在 Dockerfile 构建阶段直接执行单测。
- `WORKDIR` 固定为 `/workspace`。
- Dockerfile/Containerfile 禁止使用 `COPY` 和 `ADD`。
- 如果需要向镜像中写入脚本或文件内容，使用 `RUN cat > ... <<'EOF'`、`RUN echo ...` 等方式生成。
- Dockerfile/Containerfile 末尾不要写 `CMD ["/bin/bash"]`；进入容器或执行单测时在 `podman run` 命令中显式指定命令。

## 项目初始化配置

- 每个项目开始生成 Dockerfile/Containerfile 前，先让用户填写或确认项目配置，不要把某个项目的基础镜像、Git 仓库、commitId 写成通用固定值。
- 优先读取本目录的 `unit-test-docker.config.yml` 了解当前项目配置；如果不存在或缺少字段，再让用户补充。
- `unit-test-docker.config.yml` 中的相对路径和命令默认相对该配置文件所在目录。
- Agent 不得擅自修改 `unit-test-docker.config.yml` 或其他 `config.yml`/`config.yaml` 中的项目级配置，尤其是基础镜像、Git 仓库、commitId、源码目录、单测脚本路径、平台、TLS、代理等字段。
- 如果基础镜像不存在、manifest 不兼容、拉取失败或构建时暴露出基础镜像问题，只能向用户反馈具体报错和建议方案，等待用户确认后才能修改配置；不能由 Agent 自己决定替换基础镜像并落盘到配置文件。
- 生成或调整 Dockerfile/Containerfile 时必须以已经确认的配置为准；如需临时验证替代基础镜像，只能在对话中说明或使用临时命令参数，不得擅自写入项目配置。
- 推荐让用户提供或维护 `unit-test-docker.config.yml`，格式如下：

```yaml
schema_version: 1
project:
  name: your-project-name
  local_dir: path/to/local-project
  image_name: your-project-tests
  dockerfile_path: path/to/Dockerfile
  workspace_dir: /workspace
  source_dir: /workspace/YOUR_PROJECT
  test_script_path: /workspace/YOUR_PROJECT/test/demo.py
  test_script_template: script/demo.py
base_image:
  optional: true
  value: ""
  strip_scheme_for_from: true
source:
  repo_url: https://github.com/example/project.git
  commit_id: 40-character-git-commit-id
  clone_depth: 1
  init_submodules: true
platform:
  value: linux/amd64
podman:
  tls_verify: false
proxy:
  enabled: false
  http_proxy: ""
  https_proxy: ""
  no_proxy: ""
```

- `base_image.value` 是选填项；用户不填时，不要擅自使用历史项目的基础镜像，应先向用户确认或按当前任务明确给出的默认值处理。
- `source.repo_url`、`source.commit_id`、`project.source_dir`、`project.test_script_path` 是项目级配置；每个项目开始时都需要由用户填写或确认。
- 用户提供基础镜像时可能带 `http://`，但 Dockerfile 的 `FROM` 应使用不带 scheme 的 OCI 镜像引用。
- Dockerfile/Containerfile 内的代理配置以项目配置为准；如果用户未提供代理，不要硬编码历史项目代理。
- 如果所选基础镜像没有当前宿主架构的 manifest，在 Apple Silicon/arm64 Podman 环境下构建和运行时可使用 `--platform linux/amd64`。
- 如果 registry 需要非 TLS 拉取，构建时可使用 `--tls-verify=false`，但应来自项目配置或用户确认。

## 源码获取

- Dockerfile/Containerfile 应在构建阶段用 `git clone` 获取项目源码，不依赖宿主目录挂载覆盖 `/workspace`。
- `git clone` 的 repo 地址来自项目配置 `repo_url`。
- checkout 的 commit 来自项目配置 `commit_id`。
- clone 目标目录来自项目配置 `source_dir`。
- clone/fetch/checkout/submodule 初始化命令应在 Dockerfile 中完成。
- Gradle/Android 项目应在源码 checkout 后、镜像构建阶段预下载默认单测命令使用的 Gradle wrapper 分发包，例如执行 `./gradlew --no-daemon --version`；这只用于把 Gradle 打进镜像，不属于执行单测。不要等到进入容器运行 `demo.py` 时才首次下载 Gradle。
- 在 Apple Silicon/Podman 通过 `--platform linux/amd64` 跑 Android/Kotlin 项目时，如果 Kotlin daemon 写增量缓存失败（例如 `Cannot create empty file ... source-to-classes.tab`），应在容器内项目 `gradle.properties` 追加 `org.gradle.daemon=false`、`kotlin.compiler.execution.strategy=in-process`、`kotlin.incremental=false`、`kapt.incremental.apt=false`，避免依赖 Kotlin daemon 和增量缓存。
- 若镜像中设置的代理影响 `apt` 或 `git` 访问，可在相关 `RUN` 命令前临时清空 `http_proxy`、`https_proxy`、`HTTP_PROXY`、`HTTPS_PROXY`。

## 单测脚本

- 单测输出脚本以本目录通用模板 `script/demo.py` 为准。
- `script/demo.py` 只保留通用骨架，不包含任何具体项目的构建、执行、日志格式解析等核心逻辑。
- 每个项目的单测执行脚本都需要基于 `script/demo.py` 修改：复制或嵌入该骨架后，保留统一输入/输出结构。
- 核心扩展点是 `parse_log(ut_log: str)`；每个项目只需要在该方法中实现自己的 parse 流程，把原始单测日志解析为统一结果。
- 单测执行命令可通过模板的 `--` 参数传入；如果项目必须补充构建或运行前准备，可在项目实际脚本中扩展，但不能改变最终输出格式。
- 所有项目的 `parse_log` 返回值必须使用统一格式：
  `passed_tests`
  `failed_tests`
  `skipped_tests`
- 容器内单测脚本位置来自项目配置 `test_script_path`，例如 `/workspace/YOUR_PROJECT/test/demo.py`。
- 因为禁止 `COPY`/`ADD`，修改项目内实际单测脚本后，需要同步修改 Dockerfile/Containerfile 中对应的 `RUN cat > ...` 内容。
- 项目内实际 `demo.py` 作为统一单测入口，不再拆出 `run_notes_tests.py` 作为输出入口。
- `demo.py` 最终 stdout 只输出模板格式：
  `passed_tests`
  `failed_tests`
  `skipped_tests`
- 构建/测试阶段进度写到 stderr；需要详细 qmake/make/QtTest 输出时使用 `--verbose`。
- 在 Apple Silicon 上通过 `--platform linux/amd64` 运行时，qmake/make 构建可能需要几十秒到数分钟；看到持续进度提示时不要误判为卡死。

## 命令参考模板

- 构建镜像：
  `podman build --platform <platform> --tls-verify=<true|false> -f <Dockerfile路径> -t <image_name> .`
- 进入容器：
  `podman run --platform <platform> --rm -it <image_name> /bin/bash`
- 执行单测：
  `podman run --platform <platform> --rm <image_name> <test_script_path> --json`
- 进入容器后执行单测：
  `cd <test_script_dir> && python3 demo.py --json`

## 项目记忆文档要求

- 用户要求理解某个源码目录并生成项目记忆时，默认在本目录 `build/project-memory.md` 下生成 Markdown 文档。
- 生成前应优先阅读目标源码目录的 `README.md`、`.github/` 目录、`pubspec.yaml`/`package.json`/`pom.xml`/`build.gradle`/`Cargo.toml`/`pyproject.toml` 等能够体现项目定位、依赖、测试和 CI 的文件。
- 如果用户指定了具体源码目录，例如 `dart_style/`，文档内容必须基于该目录内的真实文件，不要泛泛描述同类项目。
- 文档必须包含以下一级章节：
  - `一、Repo 技术栈（5 个维度标签）`
  - `二、Repo 介绍模板`
  - `三、环境可配置性结论`
- `Repo 技术栈（5 个维度标签）` 必须按以下 5 个层级输出：
  - `L1 编程语言`
  - `L2 框架 / UI 库 / 中间件 SDK / 数据科学库`
  - `L3 运行时、容器、云平台、OS、部署环境`
  - `L4 数据库 / 缓存 / 搜索引擎 / 存储中间件`
  - `L5 构建工具、测试工具、CI/CD、项目脚手架、业务领域场景、规范工具`
- `Repo 介绍模板` 必须按“Repo 介绍：是 xxx，用了 xx 方法，解决 xx 问题”的句式总结，并补充以下三部分：
  - `是什么（身份/定位）`
  - `用了什么方法（技术手段/方法论）`
  - `解决什么问题（目标/价值）`
- `环境可配置性结论` 必须明确给出 `可配置` 或 `不可配置`，并包含以下内容：
  - `可配置性分析`
  - `不可配置原因`
  - `对 Repo 环境构建方式的初步判断`
- 可配置性判断应结合项目实际依赖、语言运行时、CI 命令、测试命令、系统服务、数据库、中间件、私有依赖、平台架构和网络要求；不要只根据项目名称或语言生态下结论。
- 如果 README 中的产品功能“可配置/不可配置”和 Repo 环境“可配置/不可配置”含义不同，必须区分说明，避免混淆。
- 文档中涉及命令、文件名、依赖名、运行时版本、CI 工作流、测试命令和路径时使用代码块或行内代码，确保可追溯。

## 经验总结文档要求

- 用户要求生成镜像构建、单测镜像配置或错误复盘类经验总结时，默认在本目录 `build/` 下生成 Markdown 文档。
- 文档文件名使用项目名和主题，推荐格式为 `<project-name>-image-build-experience.md`。
- 经验总结必须基于当前项目的实际配置、Dockerfile/Containerfile、构建命令和真实报错，不要写成泛泛的 Docker 教程。
- 文档至少包含以下一级章节：
  - `配置难度分析`
  - `镜像选择原因`
  - `环境构建流程`
  - `宝贵经验`
- `宝贵经验` 下至少包含以下二级章节：
  - `配置过程注意点`
  - `错误处理`
  - `不同系统的迁移策略`
- `配置难度分析` 应说明难点来源，例如基础镜像、语言栈、包管理器、网络、架构、私有 registry、测试框架、日志解析等。
- `镜像选择原因` 应引用项目配置中的基础镜像，并说明是否需要去掉 `http://` scheme、是否需要 `--platform`、是否需要 `--tls-verify=false` 或 registry 登录。
- `环境构建流程` 应按实际 Dockerfile/Containerfile 顺序描述安装项、安装顺序、源码 checkout、依赖预下载、脚本写入和入口命令。
- `错误处理` 应记录真实尝试、报错信息、定位过程和最终处理方式；如果为了绕过非必要组件做了调整，需要说明为什么不影响单测目标。
- `不同系统的迁移策略` 应分别说明 Linux、macOS、Windows/WSL2 的差异，重点覆盖平台架构、Podman 连接、路径、换行符、registry 登录和容器内 Linux 行为。
- 文档中涉及命令、镜像名、commit、路径、错误信息时使用代码块或行内代码，确保可复制和可追溯。
