# 使用、修改与排障

## 启动和查看

双击 start.cmd，保持启动窗口运行，在浏览器打开 http://127.0.0.1:8507 。首次使用新机器需先运行 setup.ps1；模型和 MinerU 密钥在本地 .env 中配置。

侧栏选择“API 真实分析”，填写当前记账主体，上传文件，按“开始分析”。记账主体必须由使用人确认；收货人不一定等于付款方。已有账单 JSON 可选，程序只输出修改建议，不连接财务账本。

侧栏“查看已有运行”可以加载过去的真实处理结果，查看逐条证据和执行记录，无需再次支付模型调用或上传文件。模型和 Token 仅显示服务实际返回值。长文件或邮件有多个附件时，解析阶段可能持续数分钟。

## 输出含义

- CREATE：证据和规则允许的新增建议，仍由人验收。
- UPDATE：匹配到已有记录，且有字段及新值的明确修改指令。
- NO_CHANGE：匹配且没有需要修改的字段。
- PENDING_REVIEW：存在来源、金额、冲突、匹配或账务方向问题，需要人工确认。

来源文件读取成功、模型返回 JSON、费用可以入账是三件事。没有费用或附件识别失败时看 errors；空结果不能解释为没有问题。邮件附件出错时保留正文，但相关记录转待审核。

## 配置与职责

本项目是 Python + LangChain 串行处理流水线：parsers.py 读取材料，mineru.py／题目 OCR 识别，api.py 调用模型提取，rules.py 做确定性核验，pipeline.py 编排并记录事件，app.py 展示。它没有将三个提示词伪装成真实子 Agent 调用，也没有依赖 OpenCode。

修改模型：本机 .env 中 BILLING_API_BASE_URL、BILLING_API_MODEL、BILLING_API_KEY。修改 OCR：BILLING_OCR_PROVIDER=mineru，配 MINERU_API_TOKEN；指定题目接口用 specified 并提供地址映射。提供显式映射时优先使用题目接口。

修改费用别名：rules.py 的 ALIASES。新增规则需配真实风险回归测试。禁止仅通过放宽引用校验来消除待审。金额、币种、提单号的来源及模型候选值保存在 runs/<运行编号>/chunks.json 与 records.json。

## 排障

- 启动失败：在本项目目录运行 setup.ps1；确认 Python 3.11+。已装好后不用重复安装。
- 端口被占用：关闭原启动窗口，或修改 start.ps1 的端口后访问新地址。
- MinerU HTTP 401／API Token 错误：更新本机 Token；不要把密钥截图到报告。
- OCR 超时：保留运行记录，稍后重试。邮件中每个 PDF/图片附件分别解析，耗时会累计。
- 指定 OCR 缺下载地址：本地路径不可作为外网下载链接；没有地址时用已配置的 MinerU 或明确标记的人工文本。
- 字段引用不通过：打开原文和 quote 比对，不能直接把模型猜测当真值。
- AR/AP 未知：确认实际付款方、收款方及当前记账主体，补充有据可查的材料。

运行 ` .\.venv\Scripts\python.exe -m pytest -q ` 可做本地测试，不会用测试数据修改真实账本。分享交付包时不要包含 .env、uploads、runs 或个人凭据。
