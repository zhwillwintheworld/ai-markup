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
