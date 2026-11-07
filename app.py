"""Local operator workbench. All displayed execution facts come from pipeline results."""
from collections import Counter
import json
from pathlib import Path, PureWindowsPath
import shutil
import uuid

import streamlit as st

from billing_agent.pipeline import run_pipeline
from billing_agent.api import settings

ROOT = Path(__file__).resolve().parent
STAGES = {"parse": "解析材料", "extract": "提取费用", "reconcile": "匹配与校验"}
OPERATIONS = {"CREATE": "新增", "UPDATE": "更新", "NO_CHANGE": "无需修改", "PENDING_REVIEW": "待审核"}

st.set_page_config(page_title="航运账单工作台", page_icon="⚓", layout="wide")
st.title("航运账单工作台")
st.caption("从邮件与账单提取费用，逐项核对变更与来源。结果为审核建议，不会写入财务账本。")

with st.sidebar:
    st.subheader("本次处理")
    selected_mode = st.radio("运行方式", ["合成样本演练", "API 真实分析", "Codex 真实分析"])
    is_demo = selected_mode == "合成样本演练"
    entity = st.text_input("当前记账主体", value="ACME" if is_demo else "", help="使用单据中的完整名称，用于判断应收和应付。")
    if not is_demo:
        st.caption("分析时将材料文本发送给你配置的模型服务。当前本地文件识别服务：" + ("MinerU（PDF/图片会上传解析）" if settings().get('BILLING_OCR_PROVIDER') == 'mineru' else "题目指定 OCR（需要下载地址）"))
        if selected_mode == "Codex 真实分析":
            st.caption("Codex 入口：" + ("已发现" if shutil.which("codex") else "未在 PATH 中发现，请配置 CODEX_CLI_PATH"))
        else:
            st.caption("API 地址、模型及密钥从项目本机配置读取。")
    st.divider()
    st.caption("文件 → 解析 → 提取 → 匹配与校验 → 结果与证据")
    history = sorted((ROOT / 'runs').glob('*/result.json'), reverse=True)[:30]
    if history:
        st.divider()
        chosen_run = st.selectbox('查看已有运行', history, format_func=lambda p: p.parent.name)
        if st.button('加载运行记录'):
            try:
                st.session_state['billing_result'] = json.loads(chosen_run.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                st.error('运行记录无法读取，请选择其他记录。')

uploaded = []
existing_upload = None
map_upload = None
sample_name = None
if is_demo:
    st.info("合成样本演练：使用预先编写的提取结果验证业务规则，不调用模型或 OCR。")
    sample_name = st.selectbox("演练场景", ["新增费用", "明确修改金额", "冲突待审核"])
else:
    uploaded = st.file_uploader(
        "添加邮件、账单或费用表（单文件最多 25 MB）",
        type=["eml", "pdf", "jpg", "jpeg", "png", "tif", "tiff", "xlsx", "xls", "doc", "docx", "txt", "csv"],
        accept_multiple_files=True,
    )
    st.caption("启用 MinerU 后，本地 PDF/图片及邮件内图片/PDF 附件会上传解析。提供 OCR 地址映射时优先调用题目指定服务；同名 .txt 旁路文本会标记为人工提供。")
    left, right = st.columns(2)
    with left:
        existing_upload = st.file_uploader("已有账单 JSON（可选）", type=["json"], key="ledger")
    with right:
        map_upload = st.file_uploader("题目 OCR 地址映射 JSON（可选）", type=["json"], key="ocr_map")
    with st.expander("OCR 地址怎么填写"):
        st.write("键为上传的文件名或邮件附件名，值为指定 OCR 服务能够下载的 HTTP(S) 地址。网盘分享页通常不能直接用作文件下载地址。")
        st.code('{"bill.pdf": "https://your-file-host.example/bill.pdf"}', language="json")

def read_uploaded_json(item, expected_type):
    if item is None:
        return None
    if item.size > 5 * 1024 * 1024:
        raise ValueError("JSON 文件不能超过 5 MB")
    data = json.loads(item.getvalue().decode("utf-8-sig"))
    if not isinstance(data, expected_type):
        raise ValueError("已有账单必须是数组，OCR 映射必须是对象")
    return data

if st.button("运行合成演练" if is_demo else "开始分析", type="primary", disabled=not entity.strip() or (not is_demo and not uploaded)):
    st.session_state.pop("billing_result", None)
    try:
        existing = read_uploaded_json(existing_upload, list)
        mapping = read_uploaded_json(map_upload, dict)
        if mapping is not None and not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()):
            raise ValueError("OCR 映射的文件名和地址都必须是文字")
        if is_demo:
            chosen = {"新增费用": "invoice.json", "明确修改金额": "update.json", "冲突待审核": "conflict.json"}[sample_name]
            paths = [ROOT / "examples" / chosen]
            if chosen != "invoice.json":
                existing = json.loads((ROOT / "examples" / "existing.json").read_text(encoding="utf-8"))
        else:
            if len(uploaded) > 30:
                raise ValueError("一次最多处理 30 份文件")
            upload_dir = ROOT / "uploads" / uuid.uuid4().hex
            upload_dir.mkdir(parents=True)
            seen = set()
            paths = []
            for item in uploaded:
                name = PureWindowsPath(item.name).name
                if name in ("", ".", "..") or name.casefold() in seen:
                    raise ValueError("上传文件有重名或无效名称，请重新选择")
                if item.size > 25 * 1024 * 1024:
                    raise ValueError("文件超过 25 MB：" + name)
                seen.add(name.casefold())
                target = upload_dir / name
                target.write_bytes(item.getvalue())
                paths.append(target)
            # Sidecar text belongs to its image/PDF and must not be extracted twice.
            paths = [p for p in paths if not (p.name.endswith(".txt") and (p.parent / p.name[:-4]).exists())]
        with st.status("正在处理材料…", expanded=True) as progress:
            def on_event(event):
                stage = STAGES.get(event.get("stage"), event.get("stage", "处理"))
                state = {"start": "开始", "end": "完成", "error": "失败"}.get(event.get("status"), "进行中")
                suffix = f" · {event['duration_seconds']} 秒" if event.get("duration_seconds") is not None else ""
                st.write(f"{stage} · {state}{suffix}")
            result = run_pipeline(paths, entity.strip(), existing, mode="demo" if is_demo else "api" if selected_mode == "API 真实分析" else "codex", ocr_map=mapping, output_dir=ROOT / "runs", on_event=on_event)
            progress.update(label="处理结束，部分材料失败" if result["incomplete"] else "处理结束，请核对结果", state="error" if result["incomplete"] else "complete", expanded=False)
            st.session_state["billing_result"] = result
    except Exception as exc:
        st.error(f"未完成处理：{type(exc).__name__}。请检查文件、配置与本地运行记录。")
        if isinstance(exc, (ValueError, json.JSONDecodeError, FileNotFoundError)):
            st.caption(str(exc)[:500])

result = st.session_state.get("billing_result")
if result:
    st.divider()
    st.subheader("处理结果")
    st.caption("本次结果来源：" + {"demo":"合成演练","api":"API 真实分析","codex":"Codex 真实分析"}[result["mode"]])
    for err in result["errors"]:
        st.error(f"{err['document']}：{err['message']}")
    counts = Counter(r["operation"] for r in result["records"])
    st.write(" · ".join(f"{label} {counts.get(op, 0)}" for op, label in OPERATIONS.items()))
    if not result["records"]:
        st.warning("没有可展示的费用记录。请先查看材料处理错误；空结果不代表账单无误。")
    else:
        rows = []
        for r in result["records"]:
            detail = r.get("charge_details", {})
            rows.append({"操作": OPERATIONS.get(r["operation"], r["operation"]), "单据编号": r.get("document_info", {}).get("reference_no"), "费用": detail.get("charge_item"), "金额": detail.get("amount"), "币种": detail.get("currency"), "应收/应付": r.get("financial_attributes", {}).get("posting_type"), "待核对事项": len(r.get("audit_trail", {}).get("issues", []))})
        st.dataframe(rows, hide_index=True, width="stretch")
        with st.expander("逐条查看证据、字段变更与审核问题"):
            for index, record in enumerate(result["records"], 1):
                st.write(f"记录 {index}")
                st.json(record)
        st.download_button("下载账单 JSON", json.dumps(result["records"], ensure_ascii=False, indent=2), "billing-records.json", "application/json")
    with st.expander("查看实际执行记录"):
        st.caption("模型和 Token 仅显示服务实际返回的值；未提供的字段显示为空。")
        st.dataframe(result["events"], hide_index=True, width="stretch")
        st.download_button("下载完整运行报告", json.dumps(result, ensure_ascii=False, indent=2), "billing-run.json", "application/json")
else:
    st.divider()
    st.write("先运行一条合成样本，观察新增、更新和待审核的区别；也可切换到 API 真实分析并上传材料。")
