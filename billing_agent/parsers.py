"""Bounded byte parsers. Attachments never become filesystem paths."""
import hashlib
import io
import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path
import subprocess
import tempfile
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from urllib.parse import urlparse
import requests
from .models import Chunk
from .api import settings

OCR_URL='https://gateway.pltplt.com/ai/process'
MAX_BYTES=25*1024*1024
MAX_TEXT=500_000
MAX_ATTACHMENTS=50

def plain_ocr_tables(text):
    """Deterministic text view of OCR tables; preserve surrounding Markdown."""
    class TableText(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.rows=[]; self.cells=[]; self.parts=[]
        def handle_starttag(self,tag,attrs):
            if tag in ('td','th'):self.parts=[]
            elif tag=='br':self.parts.append(' ')
        def handle_data(self,data):self.parts.append(data)
        def handle_endtag(self,tag):
            if tag in ('td','th'):
                self.cells.append(' '.join(''.join(self.parts).split()));self.parts=[]
            elif tag=='tr':
                self.rows.append(' '.join(self.cells));self.cells=[]
    def convert(match):
        parser=TableText();parser.feed(match[0]);parser.close()
        return '\n'.join(parser.rows)
    return re.sub(r'<table\b[^>]*>.*?</table\s*>',convert,text,flags=re.I|re.S)

def extract_ocr_text(value):
    if isinstance(value,str) and value.strip(): return value
    if isinstance(value,dict):
        for key in ('text','ocr_text','recognized_text','content'):
            if isinstance(value.get(key),str) and value[key].strip():return value[key]
        for key in ('data','result'):
            if key in value:
                try:return extract_ocr_text(value[key])
                except ValueError:pass
    raise ValueError('Unrecognized OCR response; supply a reviewed text sidecar. No text was inferred.')

def ocr_url(url):
    if urlparse(url).scheme not in ('https','http'):raise ValueError('OCR requires an accessible HTTP(S) URL')
    last=None
    for attempt in range(3):
        try:
            response=requests.post(OCR_URL,json={'file':url,'task':'orderChange','callBack':'','taskType':''},timeout=(10,60))
            response.raise_for_status()
            return extract_ocr_text(response.json())
        except (requests.RequestException,ValueError) as exc:last=exc
    raise ValueError('OCR failed after 3 bounded attempts; verify endpoint/response or supply a sidecar') from last

@dataclass
class ParseResult:
    chunks: list[Chunk]
    errors: list[dict]

    @property
    def incomplete(self):
        return bool(self.errors)

def parse_document(path,ocr_map=None):
    path=Path(path)
    mapping=ocr_map or {}
    chunks=[]; errors=[]; budget={'bytes':0,'count':0,'text':0}
    def report(name,exc):
        message=str(exc) if isinstance(exc,ValueError) else 'Unable to read document/attachment; check its format and configuration'
        errors.append({'document':path.name,'attachment':name,'error_type':type(exc).__name__,'message':message[:1000]})
    def safely_parse(data,name,depth):
        try:parse(data,name,depth)
        except Exception as exc:report(name,exc)
    def add(text,name,locator,method):
        if not text.strip():return
        budget['text']+=len(text)
        if budget['text']>MAX_TEXT:raise ValueError('Document exceeds total text limit')
        chunks.append(Chunk(id=f'{hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]}-c{len(chunks)+1}',name=name,text=text,locator=locator,source_method=method))
    def parse(data,name,depth=0):
        budget['bytes']+=len(data);budget['count']+=1
        if depth>5 or budget['count']>MAX_ATTACHMENTS or budget['bytes']>MAX_BYTES*2:raise ValueError('Attachment recursion/count/size limit exceeded')
        ext=Path(name).suffix.lower()
        if ext=='.eml':
            msg=BytesParser(policy=policy.default).parsebytes(data)
            add('\n'.join(f'{k}: {msg.get(k, "")}' for k in ('From','To','Date','Subject','Message-ID')),name,'email headers','email')
            def walk(part,level,selected_body=None):
                attachment_name=part.get_filename()
                try:
                    if level>5:raise ValueError('Attachment recursion limit exceeded')
                    if part.get_content_type()=='message/rfc822':
                        for nested in part.get_payload():safely_parse(nested.as_bytes(),attachment_name or 'nested.eml',level+1)
                    elif part.is_multipart():
                        preferred=selected_body
                        if preferred is None and part.get_content_subtype()=='alternative':
                            preferred=part.get_body(preferencelist=('plain','html'))
                        for child in part.iter_parts():
                            # Walk all branches so inline/related attachments are never hidden.
                            walk(child,level+1,preferred)
                    elif attachment_name:
                        safely_parse(part.get_payload(decode=True) or b'',attachment_name,level+1)
                    elif part.get_content_maintype()=='text' and (selected_body is None or part is selected_body):
                        add(part.get_content(),name,'email body','email')
                    elif part.get_content_maintype()!='text':
                        raise ValueError('Unnamed non-text MIME part requires manual inspection')
                except Exception as exc:report(attachment_name or name,exc)
            walk(msg,depth)
        elif ext in ('.txt','.json','.csv'):
            add(data.decode('utf-8-sig'),name,'body','text')
        elif ext=='.xlsx':
            from openpyxl import load_workbook
            book=load_workbook(io.BytesIO(data),read_only=True,data_only=True)
            try:
                for sheet in book:
                    for i,row in enumerate(sheet.iter_rows(values_only=True),1):
                        add(' | '.join('' if v is None else str(v) for v in row),name,f'{sheet.title}!row {i}','xlsx')
            finally:book.close()
        elif ext=='.xls':
            import xlrd
            book=xlrd.open_workbook(file_contents=data)
            for sheet in book.sheets():
                for i in range(sheet.nrows):add(' | '.join(map(str,sheet.row_values(i))),name,f'{sheet.name}!row {i+1}','xls')
        elif ext=='.docx':
            from docx import Document
            doc=Document(io.BytesIO(data))
            for i,p in enumerate(doc.paragraphs,1):add(p.text,name,f'paragraph {i}','docx')
            for i,t in enumerate(doc.tables,1):
                for j,r in enumerate(t.rows,1):add(' | '.join(c.text for c in r.cells),name,f'table {i} row {j}','docx')
        elif ext=='.doc':
            binary=os.environ.get('LIBREOFFICE_PATH')
            if not binary:raise ValueError('Legacy DOC blocked: set LIBREOFFICE_PATH or convert to DOCX manually')
            with tempfile.TemporaryDirectory() as folder:
                source=Path(folder)/'source.doc';source.write_bytes(data)
                subprocess.run([binary,'--headless','--convert-to','docx','--outdir',folder,str(source)],check=True,timeout=60,capture_output=True)
                parse((Path(folder)/'source.docx').read_bytes(),name+'.docx',depth+1)
        elif ext in ('.pdf','.jpg','.jpeg','.png','.tif','.tiff'):
            url=mapping.get(str(path)) or mapping.get(path.name) if depth==0 else mapping.get(name)
            sidecar=Path(str(path)+'.txt')
            if url:add(ocr_url(url),name,'OCR result','remote_ocr')
            elif depth==0 and sidecar.is_file():
                if sidecar.stat().st_size>MAX_TEXT*4:raise ValueError('Sidecar exceeds size limit')
                add(sidecar.read_text(encoding='utf-8-sig'),name,'user supplied sidecar','manual_text')
            elif settings().get('BILLING_OCR_PROVIDER')=='mineru':
                from .mineru import MinerU
                raw=MinerU().parse(data,name)
                add(plain_ocr_tables(raw),name,'MinerU full.md; HTML table text view','mineru')
            else:raise ValueError(f'{name}: OCR requires an explicit accessible URL mapping or a .txt sidecar; local files are never uploaded')
        else:raise ValueError(f'Unsupported attachment/document format: {ext or "none"}')
    try:
        if path.stat().st_size>MAX_BYTES:raise ValueError('Document exceeds 25 MB size limit')
        safely_parse(path.read_bytes(),path.name,0)
    except Exception as exc:report(path.name,exc)
    if not chunks and not errors:report(path.name,ValueError('Document contains no readable text'))
    return ParseResult(chunks=chunks,errors=errors)

def parse_file(path,ocr_map=None):
    """Compatibility API: callers requiring complete input still fail closed."""
    result=parse_document(path,ocr_map)
    if result.errors:raise ValueError('; '.join(error['message'] for error in result.errors))
    return result.chunks
