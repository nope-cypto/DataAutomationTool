# 贡献指南

感谢参与资料自动化工具。提交改动前请确保：

1. 功能仍只在本机运行，不新增账号系统、遥测或项目自有云端依赖。
2. 下载步骤只保存第三方服务返回的原始档案；不要加入跨批次汇总、合并去重、特征计算或分析报表。
3. 不提交 Cookie、cURL、真实 ASIN/关键词资料、任务输出或浏览器用户目录。
4. 新增网络请求时保留合理超时、停止与断点续抓能力，并避免在日志中输出凭据。
5. 提交前运行 Python 测试、开源边界测试和前端构建。

```powershell
cd DataAutomationTool-source
python -m pytest
cd web_workbench\frontend
npm test
npm run build
```

Issue 请提供可复现步骤、系统版本和已经脱敏的错误信息，不要附上完整 cURL 或请求头。
