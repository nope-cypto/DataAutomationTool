# Windows EXE 打包复盘与迁移检查清单

> 用途：在另一个“Python Worker + Electron/Node.js 界面”项目封装 Windows x64 EXE 前，用本文档做环境审计、脚本审计和打包验收。
>
> 原则：先使用项目的实际入口、目标架构和依赖文件替换文中占位符，不要直接照搬项目名称或路径。

## 1. 本次故障链复盘

| 阶段 | 实际信号 | 已证实原因 | 调整 | 验证结果 |
| --- | --- | --- | --- | --- |
| Python Worker 编译 | `Nuitka: Scons C backend compilation failed` | Windows ARM64 主机上使用 Python 3.13 ARM64 + Zig/LLD 构建 x64 Worker，后端链接器失败 | 打包解释器固定为 Python 3.12 x64；Worker 改用 PyInstaller onedir | Worker EXE 成功产生 |
| npm 外层报错 | PowerShell 只显示 `npm ci failed` | 包装脚本只抛出二次错误，真实 stderr 不易追踪 | 为每个原生命令保留 stdout、stderr、exit code 和完整日志 | 后续每次失败都可定位到单一命令 |
| npm 启动 | `spawn EINVAL`，npm 没有任何输出 | Node.js 使用 `shell: false` 直接启动 Windows `npm.cmd` | 停止把 `.cmd` 当作普通 EXE 启动 | `spawn EINVAL` 消失 |
| cmd 引号处理 | `"...npm.cmd" 不是内部或外部命令` | `cmd.exe /c` 与 Node 的参数转义使引号成为字面量 | 直接用 `node.exe` 运行 `npm-cli.js`，完全绕过 `.cmd` 和 shell 引号 | `npm ci` 成功，安装 412 个包 |
| 源码边界测试 | `ENOENT: ...web_workbench\worker\api.py` | 测试在精简的打包暂存目录运行，却按完整源码树寻找文件 | 源码结构测试在原仓库运行；依赖安装、前端编译和安装包生成在暂存目录运行 | 回归测试和前端生产构建通过 |
| 安装后新建任务 | `无法创建任务目录` | Electron 默认使用 Windows“文档”，而文档可能被 OneDrive 接管或受控文件夹保护；映射盘也可能被误判为不支持 | 新建任务时打开不带预设路径的系统目录选择器；允许用户明确选择的本地固定盘或可写映射盘 | 取消选择时不创建目录；选择可写位置时任务可正常创建 |

### 已采取但不应写成“已证实根因”的预防措施

项目位于 Synology 等同步盘时，macOS 和 Windows 可能共享到同一个 `node_modules`。这会带来原生模块架构不匹配、文件被同步客户端占用、删除失败等风险。本次日志未证明它是某一次失败的唯一原因，但已通过“本机干净暂存构建”消除该风险。

## 2. 推荐的构建流程

```text
原始源码
  ├─环境预检
  ├─在源码目录运行源码/边界测试
  ├─在本机暂存目录构建 Python Worker
  ├─只复制前端源码到本机暂存目录
  │   └─排除 node_modules / dist / release / 旧日志
  ├─在暂存目录执行 npm ci
  ├─在暂存目录编译前端
  ├─在暂存目录生成 Windows 安装包
  └─只把最终产物复制回 release/
```

| 操作 | 运行目录 | 通过标准 |
| --- | --- | --- |
| 源码结构、开源边界测试 | 原始仓库 | 所有测试通过，不依赖打包暂存区的文件布局 |
| Python Worker 打包 | `%LOCALAPPDATA%\<App>\build\worker-*` | 生成 Worker EXE，且能独立启动并通过健康检查 |
| `npm ci` | `%LOCALAPPDATA%\<App>\build\frontend` | exit code 0，锁文件未改变 |
| 前端构建 | 本机前端暂存目录 | TypeScript/Vite 等生产构建成功 |
| Electron 打包 | 本机前端暂存目录 | 生成目标架构的安装包 |
| 产物回传 | 原仓库 `release/` | 只回传 EXE、blockmap 等发布产物 |

## 3. 开始打包前的环境预检

### 3.1 明确目标架构

先回答三个问题：

1. 最终 EXE 是 `x64` 还是 `arm64`？
2. Python Worker、Electron 和内嵌原生模块是否使用同一目标架构？
3. 构建主机是 x64 Windows 还是 Windows on ARM？

如果目标是 x64，推荐对打包用 Python 做强制检查：

```powershell
py -3.12-64 -c "import platform, struct, sys; print(sys.version); print(platform.machine()); print(struct.calcsize('P') * 8)"
```

通过标准：能启动 Python 3.12，指针宽度为 `64`，并且实际打包脚本使用的就是这个解释器。不要只检查 `python --version`；它不能证明架构正确。

### 3.2 固定工具链

- 在 CI 和本机使用相同的 Node.js 主版本，项目通过 `engines`、`.nvmrc` 或工具链配置声明版本。
- 提交 `package-lock.json`，发布构建使用 `npm ci`。
- Python 运行依赖和打包依赖分开锁定，例如 `requirements.txt` 和 `requirements-build.txt`。
- 明确锁定 PyInstaller/Nuitka、Electron、electron-builder 等打包工具的版本。
- 在 Windows on ARM 上产出 x64 包时，优先使用完整的 x64 打包链；避免无意中混用 ARM64 Python 和 x64 目标。

### 3.3 干净目录

以下目录不应在 macOS/Windows 之间共享，也不应提交到 Git：

```gitignore
node_modules/
dist/
release/
__pycache__/
.pytest_cache/
.build-logs/
*.build/
*.dist/
*.onefile-build/
```

同步盘中可以保留源码，实际构建目录应放在：

```text
%LOCALAPPDATA%\<AppName>\build\
```

### 3.4 安装后的可写数据目录

构建目录与运行数据目录应分开。Windows 安装后的日志、数据库和临时状态应写入用户可写位置，例如：

```text
%LOCALAPPDATA%\<AppName>\logs
```

如果任务位置由用户决定，新建流程应显式打开系统目录选择器，不使用“文档”或上次路径作为隐式预设。Worker 应在创建前验证目录是本地、可写且符合项目的隐私策略。

通过标准：安装版在普通用户权限下可以创建任务，无需管理员权限，不向 `Program Files`、`resources`、`app.asar` 或被拒绝的同步目录写入。

## 4. Python Worker 打包检查

### 4.1 解释器预检必须在安装依赖之前完成

脚本至少检查：

- Python 主次版本。
- `platform.machine()` 和指针宽度。
- 打包器、浏览器自动化库、Excel/JSON 等必需模块可导入。
- 打包器需要的运行时资源真实存在，例如 Playwright 的 driver `node.exe` 和 `cli.js`。

通过标准：脚本输出实际 Python 绝对路径，并在架构不符时立即终止。

### 4.2 打包输出与资源校验

- 在独立的本机暂存目录生成 `work`、`spec` 和 `dist`。
- 对动态导入和非 Python 资源使用显式的 hidden imports / collect data 配置。
- 打包后检查主 EXE 以及必须的运行时文件，再复制到 Electron 资源目录。
- 打包失败时保留警告文件；打包成功且验证完成后再清理临时目录。

Windows 系统 DLL 的 `Library not found` 警告不必然表示构建失败。判定顺序应是：

1. 打包命令的 exit code。
2. 主 EXE 是否产生。
3. Worker 是否能在目标 Windows 上启动。
4. 健康检查和一次最小业务调用是否通过。

## 5. Node.js / npm 调用规则

### 5.1 从 Node.js 脚本启动 npm

Windows 上的 `npm.cmd` 是批处理文件，不是普通 EXE。如果构建器本身是 Node.js，推荐直接运行 npm 的 JavaScript 入口：

```js
import { spawn } from "node:child_process";
import path from "node:path";

const npmCli = process.env.npm_execpath
  || path.join(path.dirname(process.execPath), "node_modules", "npm", "bin", "npm-cli.js");

const child = spawn(
  process.execPath,
  [npmCli, "ci", "--foreground-scripts", "--no-audit", "--no-fund"],
  { cwd: localFrontendStage, env: process.env, shell: false },
);
```

通过标准：日志中的调用链是 `node.exe ...npm-cli.js ci`，而不是直接 spawn `npm.cmd`。

如果必须调用 `.cmd`/`.bat`，按 [Node.js 官方 child_process 文档](https://nodejs.org/api/child_process.html#spawning-bat-and-cmd-files-on-windows) 使用明确的 Windows 命令解释器，并为含空格路径做专门的 Windows 回归测试。对固定 npm 入口，直接运行 `npm-cli.js` 可减少 shell 转义层。

### 5.2 区分警告和失败

以下信号通常是警告，需记录但不应单独判定构建失败：

- `npm warn deprecated ...`
- `npm warn install-scripts ...`
- `packages are looking for funding`

最终以 exit code 和预期产物为准。但应在发布前审查 deprecated 和 install scripts，确认它们来自锁定且可信的间接依赖。

## 6. 测试与工作目录的边界

测试的工作目录必须与它所验证的对象一致：

- 需要检查完整源码树的测试：在原始仓库运行。
- 需要检查打包输入是否干净的测试：在暂存目录运行。
- 需要检查安装后行为的测试：安装 EXE 后运行。

暂存目录是精简的打包输入，不应为了让源码结构测试通过而复制整个仓库。正确的调整是把测试放到它实际验证的上下文中。

## 7. 构建日志必须包含的信息

每次打包产生一份带时间戳的日志，至少记录：

- 源码绝对路径。
- 本机暂存路径。
- Node.js 版本和架构。
- Python 绝对路径、版本和架构。
- 每个原生命令的完整命令行。
- stdout、stderr 和 exit code。
- 最终产物的绝对路径。

错误信息应指向真实阶段，例如：

```text
[Worker build] ...
[Source boundary tests] ...
[npm ci] ...
[Frontend build] ...
[Electron installer build] ...
```

排障时从第一个非零 exit code 向上查找第一条真实 error。末尾的 `build failed` 通常只是外层汇报，不是根因。

日志可能包含本机用户名、私有注册表地址或认证信息。上传 GitHub 或发给第三方前，用 `<REDACTED>` 替换敏感值。

## 8. 开源发布前检查

- [ ] 仓库中没有 API key、cookie、token、个人路径和真实业务输出。
- [ ] `.gitignore` 排除本机依赖、构建中间件、日志和抓取产物。
- [ ] 依赖授权与项目开源许可证兼容。
- [ ] 开源边界测试能防止私有品牌资源、云端地址或被删功能重新进入发布包。
- [ ] README 说明支持的 Windows 版本、架构、Python/Node.js 版本与打包命令。
- [ ] GitHub Actions 使用与本地相同的锁文件和主版本工具链。
- [ ] 安装包名称包含版本和架构。
- [ ] 开源许可证、贡献说明和安全说明已完整。

## 9. 最终验收清单

### 构建验收

- [ ] 从干净 clone 开始，不依赖开发机现有的 `node_modules` 或 Python 虚拟环境。
- [ ] Python Worker 从锁定依赖重新生成。
- [ ] `npm ci` 成功且没有改写 `package-lock.json`。
- [ ] 前端测试与生产构建通过。
- [ ] Electron 打包命令 exit code 为 0。
- [ ] 最终安装包存在，文件名和架构正确。

### 运行验收

- [ ] 在一台没有开发环境的目标 Windows 上安装。
- [ ] 应用能启动，Worker 能被 Electron 找到并启动。
- [ ] Worker 健康检查通过。
- [ ] 执行一次最小抓取/核心业务流程。
- [ ] 输出目录可写，并且实际生成预期文件。
- [ ] 关闭应用后 Worker 进程正常退出。
- [ ] 卸载、重装和覆盖升级至少各测试一次。

### 发布验收

- [ ] 安装包的 SHA-256 已记录。
- [ ] GitHub Release 中的源码、版本标签和 EXE 来自同一次构建。
- [ ] CI 能在新的 Windows runner 上重复生成安装包。
- [ ] 发布说明记录目标架构和已知限制。

## 10. 交给另一个项目时的执行指令

可将下面这段与本文档一起交给开发者或代理：

```text
请使用 WINDOWS_EXE_PACKAGING_CHECKLIST.md 审计当前项目的 Windows EXE 打包流程。

先识别项目的真实技术栈、入口文件、目标架构、构建主机架构和依赖锁文件，然后将检查清单映射到本项目，不要直接照搬其他项目的路径和版本。

依次完成：
1. 输出现有构建流程图和风险清单。
2. 建立能捕获真实打包失败的回归测试或诊断命令。
3. 修正架构混用、同步盘构建、`.cmd` 启动、测试工作目录和日志缺失问题。
4. 从干净环境重新构建。
5. 在目标 Windows 上完成安装和最小业务冒烟测试。
6. 报告每项的通过证据、未解决风险和最终产物路径。

完成标准：所有适用的检查项均有可验证结果，最终 EXE 可在干净的目标 Windows 上安装、启动并执行一次最小核心流程。
```
