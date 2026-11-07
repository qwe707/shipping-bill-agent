"""MinerU local-file protocol; signed URLs and credentials never enter reports."""
import io
from pathlib import PurePosixPath
import time
from urllib.parse import urlsplit, quote
import zipfile
import requests
from .api import settings

MAX_RESULT=50*1024*1024
MAX_MARKDOWN=2*1024*1024


class MinerU:
    def __init__(self,token=None,session=None,timeout=300):
        self.token=token or settings().get('MINERU_API_TOKEN')
        if not self.token:raise ValueError('Configure MINERU_API_TOKEN in local .env')
        self.session=session or requests.Session()
        self.timeout=timeout
        self.metadata={'provider':'mineru','state':'not_started','model_version':'vlm'}

    def request(self,method,url,**kwargs):
        parsed=urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username:
            raise ValueError('MinerU returned an invalid HTTPS address')
        try:
            response=self.session.request(method,url,timeout=(10,60),allow_redirects=False,**kwargs)
        except requests.RequestException:
            raise ValueError('MinerU network request failed') from None
        if not 200<=response.status_code<300:
            raise ValueError(f'MinerU HTTP {response.status_code}')
        return response

    def api(self,method,path,**kwargs):
        response=self.request(method,'https://mineru.net/api/v4/'+path,
            headers={'Authorization':'Bearer '+self.token},**kwargs)
        try:result=response.json()
        except ValueError:raise ValueError('MinerU returned invalid JSON') from None
        if result.get('code')!=0:
            code=str(result.get('code','unknown'))
            # Do not include arbitrary server messages or echoed data.
            safe=code if code.lstrip('-').isalnum() and len(code)<20 else 'unknown'
            raise ValueError('MinerU API error '+safe)
        data=result.get('data')
        if not isinstance(data,dict):raise ValueError('MinerU missing result data')
        return data

    @staticmethod
    def read_markdown(content):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                matches=[i for i in archive.infolist() if PurePosixPath(i.filename).name=='full.md']
                if len(matches)!=1 or matches[0].file_size>MAX_MARKDOWN:
                    raise ValueError('MinerU missing/ambiguous/oversized full.md')
                # Never extract archive paths to the filesystem.
                text=archive.read(matches[0]).decode('utf-8-sig')
                if not text.strip():raise ValueError('MinerU returned empty text')
                return text
        except (zipfile.BadZipFile,UnicodeError,RuntimeError):
            raise ValueError('MinerU result archive is invalid') from None

    def parse(self,data,name):
        start=time.monotonic()
        self.metadata['state']='requesting_upload'
        upload=self.api('POST','file-urls/batch',json={
            'files':[{'name':PurePosixPath(name.replace('\\','/')).name,'data_id':'document','is_ocr':True}],
            'model_version':'vlm','enable_table':True})
        urls=upload.get('file_urls',[])
        batch=upload.get('batch_id')
        if len(urls)!=1 or not isinstance(batch,str):raise ValueError('MinerU missing upload information')
        self.request('PUT',urls[0],data=data).close()
        self.metadata['batch_id']=batch
        while time.monotonic()-start<self.timeout:
            result=self.api('GET','extract-results/batch/'+quote(batch,safe=''))
            rows=result.get('extract_result',[])
            if len(rows)>1:raise ValueError('MinerU returned unexpected number of files')
            row=rows[0] if rows else {}
            state=row.get('state','pending')
            self.metadata['state']=state
            if state=='failed':raise ValueError('MinerU document parsing failed')
            if state=='done':
                response=self.request('GET',row.get('full_zip_url',''),stream=True)
                content=bytearray()
                try:
                    for part in response.iter_content(65536):
                        content.extend(part)
                        if len(content)>MAX_RESULT:raise ValueError('MinerU result exceeds size limit')
                except requests.RequestException:
                    raise ValueError('MinerU result download failed') from None
                finally:response.close()
                text=self.read_markdown(content)
                self.metadata['duration_seconds']=round(time.monotonic()-start,3)
                return text
            time.sleep(3)
        self.metadata['state']='timeout'
        raise ValueError('MinerU parsing timeout; retry later')
