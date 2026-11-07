# 航运账单 Agent

Python + LangChain 本地账单处理工作台。解析邮件及附件、PDF/图片、Excel 和 Word，生成带来源证据的结构化费用记录，匹配已有账单并输出增量修改建议。

## 启动

需要 Python 3.11+。Windows PowerShell 执行：

```powershell
.\setup.ps1
.\start.ps1
```

浏览器访问 http://127.0.0.1:8507 。也可双击 start.cmd。复制 .env.example 为 .env，在本机填写 Responses API 的地址、模型和密钥。使用 MinerU 时填写 MINERU_API_TOKEN，并设置 BILLING_OCR_PROVIDER=mineru。

默认合成演练不调用外部服务。真实分析会将材料发送给配置的服务；PDF/图片及邮件内对应附件会在启用 MinerU 时上传解析。已有账单 JSON 可选，当前记账主体由使用者确认。

## 流程与输出

文件解析 → OCR → GPT 结构化提取 → 来源核验 → 标准化 → 匹配旧账及增量校验 → JSON 结果与审计记录。

- CREATE：新增建议；UPDATE：有明确修改指令的更新建议。
- NO_CHANGE：无需修改；PENDING_REVIEW：证据不足、歧义或冲突待审。
- 保留原始费用名称、原文引用、变更前后值和处理问题。
- 金额使用 Decimal 核验，输出 JSON 数字；币种按 ISO 4217 检查。
- AR/AP 根据已确认的记账主体及付款关系判断，未知保持待审。

当前是串行处理流水线，不连接真实财务系统写账。没有数据库；运行材料和记录保存在本机 runs/。侧栏可以加载历史运行。

## 测试与限制

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

已通过 70 项自动测试，以及真实 PDF、图片、EML 正文和附件的解析提取联调。真实结果仍存在账务方向及币种等人工确认事项，不能等同于生产入账验收。

题目指定 OCR 的适配器保留在 parsers.py，需要外网可下载的文件地址，尚未完成该服务的真实验证。实际联调用用户选择的 MinerU 替代。旧 DOC 需要 LibreOffice 或转换为 DOCX，未用真实老格式样例验证。

详见 [使用与排障](docs/operator-guide.md)。源码不包含凭据、真实账单、真实运行记录或本地虚拟环境。
