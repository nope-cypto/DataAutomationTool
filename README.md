# 资料自动化工具

在 Windows 本机运行的资料下载工具，支持柚子数据、麦子拓展数据和柚子关键词下载。

## 下载安装

前往 [最新版本下载页](https://github.com/nope-cypto/DataAutomationTool/releases/latest)，下载 `DataAutomationTool-Setup-<版本>-x64.exe` 后安装。

- 适用平台：Windows x64；请预先安装 Google Chrome。
- 直接使用安装包不需要安装 Python 或 Node.js。
- 下载页提供 SHA-256 校验文件、免责声明及许可证。当前 v1.1.5 安装包未附代码签名，Windows 可能显示未知发布者提示；请核对来源及校验值，不要关闭系统安全防护。

## 使用前请阅读

**本项目是独立的第三方工具，与所涉及的平台不存在官方隶属、授权或背书关系。只能在获得相应权限并遵守适用法律及平台规则的前提下使用；开源许可不代表取得第三方数据或接口的使用权。**

**软件按现状提供，不保证持续可用、数据准确完整或账号不受限制。在适用法律允许的范围内，作者和贡献者不提供担保，并依 MIT 许可证限制责任；法律不得排除或限制的责任不受影响。**

完整内容见 [免责声明](DISCLAIMER.md) 和 [安全说明](SECURITY.md)。cURL 可能包含 Cookie 或访问令牌，请勿分享或上传。

## 使用步骤

| 步骤 | 操作 | 结果 |
| --- | --- | --- |
| Step 0 | 输入任务名，选择保存位置 | 创建任务目录与 ASIN 输入表 |
| Step 1 | 选择国家并导入 ASIN 的 CSV/XLSX | 下载柚子数据 XLSX 和结果清单 |
| Step 2 | 提供 ASIN 输入表及已授权请求的 cURL | 保存麦子拓展原始响应 JSONL |
| Step 3 | 提供关键词 TXT/CSV/XLSX 及已授权请求的 cURL | 保存柚子关键词原始响应 JSONL |

任务输出保存在所选目录中。请先用少量数据验证结果，并备份重要文件。

## 开发与反馈

源码运行、测试和 Windows 打包步骤见 [贡献指南](CONTRIBUTING.md)。普通问题可提交 [Issue](https://github.com/nope-cypto/DataAutomationTool/issues)，请先移除凭据和业务数据；漏洞报告请按 [安全说明](SECURITY.md) 操作。

本项目采用 [MIT License](LICENSE)。
