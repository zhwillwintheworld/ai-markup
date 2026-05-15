# android-upload 单测镜像构建经验总结


## 配置难度分析

本项目的配置难度属于中高，主要难点不在 Dockerfile/Containerfile 语法，而在 Android、Gradle、Kotlin 单测环境的可复现构建。镜像需要同时固定基础镜像、源码仓库、commit、Android SDK 版本、Gradle wrapper 缓存、单测入口脚本和输出格式。

当前项目还叠加了私有镜像仓库认证、Apple Silicon 宿主机运行 `linux/amd64` 容器、Google Android SDK 下载限流等因素。构建过程对网络、平台架构、registry 登录状态和缓存命中情况都比较敏感。

## 镜像选择原因

- 镜像定位与 Kotlin/Android 构建环境匹配，适合 `android-upload-service` 的 Gradle 单测场景。
- 当前基础镜像在 Apple Silicon 环境下缺少 `linux/arm64` manifest，因此构建和运行命令统一使用 `--platform linux/amd64`。
- registry 拉取需要认证，构建前必须完成 `podman login ark-swalm1-cn-beijing.cr.volces.com`。

## 环境构建流程

整体构建流程遵循“先基础环境、再 Android SDK、再源码、最后测试入口”的顺序：

1. 拉取私有基础镜像。
2. 安装系统依赖：
   `bash`、`ca-certificates`、`curl`、`git`、`openjdk-17-jdk`、`unzip`。
3. 解析容器内真实 Java 路径，并软链到 `/opt/java-home`。
4. 设置核心环境变量：
   `ANDROID_SDK_ROOT`、`ANDROID_HOME`、`JAVA_HOME`、`GRADLE_USER_HOME`、`SOURCE_DIR`、`PATH`。
5. 下载并安装 Android command line tools。
6. 安装 Android SDK 组件：
   `platforms;android-34`、`build-tools;34.0.0`、`build-tools;33.0.1`。
7. 从 `https://github.com/gotev/android-upload-service.git` 拉取源码，并 checkout 到 commit：
   `25e6806b6629eee8bfb19dceed879ea45726b333`。
8. 初始化子模块，并给 `gradlew` 与 `examples/app/gradlew` 添加执行权限。
9. 向项目 `gradle.properties` 追加容器默认配置：
   `org.gradle.daemon=false`、`kotlin.compiler.execution.strategy=in-process`、`kotlin.incremental=false`、`kapt.incremental.apt=false`。
10. 执行 `./gradlew --no-daemon --version` 预下载 Gradle wrapper 分发包。该步骤只缓存构建工具，不执行单测。
11. 通过 `RUN cat > /workspace/android-upload/test/demo.py <<'EOF'` 写入统一单测入口脚本。
12. 给 `demo.py` 添加执行权限，并写入 `/etc/profile.d/android-sdk.sh`。

本次成功构建结果：

```text
image: localhost/android-upload-test:latest
image id: febcbe26ea8264803eb1b42bbe97cab60eab6bc5693e49785d4adc38aa4048e7
size: 3025157021 bytes
```

## 宝贵经验

### 配置过程注意点

- Gradle/Android 项目要在源码 checkout 后预下载 wrapper，例如执行 `./gradlew --no-daemon --version`。
- Apple Silicon 上运行 amd64 Android/Kotlin 构建时，建议禁用 Gradle daemon、Kotlin daemon 和增量缓存，减少 overlay 文件系统或模拟环境下的缓存文件创建失败。

### 错误处理

- Android SDK 安装阶段，`platform-tools_r37.0.0-linux.zip` 下载触发 Google HTTP 429 限流。
- 本项目默认运行的是 JVM 单测 `testDebugUnitTest`，不依赖 `adb`，因此可以移除 `platform-tools` 安装项，保留 `platforms;android-34` 与 `build-tools`。
- SDK 下载失败时应优先判断失败组件是否真实必需；不必为了非必要组件阻塞整个单测镜像。
- 构建日志中出现长时间静默不一定是卡死，拉取大镜像层、下载 SDK、解压 Gradle wrapper 都可能阶段性无输出。
- 如果基础镜像设置了代理或历史环境变量，且影响 `apt`、`git`、`sdkmanager`，可在相关 `RUN` 命令前临时清空代理变量。

### 不同系统的迁移策略

Linux 宿主通常最直接。如果宿主是 `amd64`，并且基础镜像也支持 `amd64`，构建和运行命令基本可以直接复用。若项目配置固定平台，仍应按配置显式指定 `--platform`。

macOS 上需要区分 Intel 和 Apple Silicon。Apple Silicon 如果遇到基础镜像没有 `arm64` manifest，应统一使用 `--platform linux/amd64`。同时需要确保 Podman machine 已启动，私有 registry 登录信息在 Podman 环境中可用。

Windows 上建议通过 WSL2 或 Podman Desktop 运行。需要额外注意工作目录路径、换行符、shell 行为和 registry 登录状态。脚本文件应保持 Linux shebang 可执行，避免 CRLF 导致 `/usr/bin/env` 或脚本解释异常。

容器内部最终都是 Linux 环境，因此单测入口、Gradle、Android SDK、路径和权限应以 Linux 行为为准，不应依赖宿主系统特有能力。宿主系统差异主要体现在 Podman 连接、平台架构、路径映射和登录凭据管理上。
