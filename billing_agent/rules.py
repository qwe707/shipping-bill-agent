"""Deterministic, conservative reconciliation; never mutate the ledger input."""
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re
import math
import pycountry
from .models import FIELDS,NUMBERS

GROUPS={
 'document_info':['document_type','reference_no','date','bl_no','booking_no','container_no'],
 'transaction_party':['issuer','recipient','payer','payee'],
 'charge_details':['charge_item','amount','currency','payment_term','quantity','unit_price','subtotal','tax','total'],
 'financial_attributes':[]}
ALIASES={'handling fee':'Handling Charge','h/d fee':'Handling Charge','handling charge':'Handling Charge',
 'doc fee':'Documentation Fee','thc':'Terminal Handling Charge','trucking fee':'Trucking Charge',
 'customs fee':'Customs Clearance Fee','storage fee':'Storage Charge'}
def fee_name(value):return ALIASES.get(norm(value),value)
def output_key(key):return 'document_date' if key=='date' else key
def output_value(key,value):
    if key=='charge_item':return fee_name(value)
    if key in NUMBERS and value is not None:
        try:
            number=decimal(value)
            if number==number.to_integral_value():return int(number)
            result=float(number)
            return result if math.isfinite(result) and Decimal(str(result))==number else None
        except ValueError:return None
    return value

def flatten(row):
    result={k:row.get(k) for k in FIELDS}
    for group in GROUPS:
        if isinstance(row.get(group),dict):result.update({k:v for k,v in row[group].items() if k in FIELDS})
    if row.get('document_info',{}).get('document_date') is not None:result['date']=row['document_info']['document_date']
    return result

def decimal(value):
    try:
        text=str(value).strip()
        if ',' in text:
            if not re.fullmatch(r'[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?',text):
                raise ValueError('Ambiguous decimal grouping')
            text=text.replace(',','')
        result=Decimal(text)
        if not result.is_finite():raise ValueError('Nonfinite number')
        return result
    except (InvalidOperation,ValueError,TypeError):raise ValueError('Invalid finite decimal')

def norm(value):return str(value or '').strip().casefold()

def equal(a,b,key):
    if key=='charge_item':return norm(fee_name(a))==norm(fee_name(b))
    if key in NUMBERS and a is not None and b is not None:
        try:return decimal(a)==decimal(b)
        except ValueError:return False
    return norm(a)==norm(b)

UPDATE_FIELDS={
 'amount':r'(?<!total )\bamount\b|(?<!总)金额', 'total':r'\btotal\b|总额|总金额|合计',
 'subtotal':r'\bsubtotal\b|小计', 'tax':r'\btax\b|税额',
 'quantity':r'\bquantity\b|\bqty\b|数量', 'unit_price':r'\bunit price\b|单价',
 'currency':r'\bcurrency\b|币种', 'date':r'\bdate\b|日期',
 'reference_no':r'\b(invoice|reference|document) (number|no)\b|发票号|单据号',
 'booking_no':r'\bbooking (number|no)\b|订舱号', 'bl_no':r'\b(b/l|bl|bill of lading) (number|no)\b|提单号',
 'container_no':r'\bcontainer (number|no)\b|箱号', 'charge_item':r'\b(charge item|fee name)\b|费用名称',
 'payer':r'\bpayer\b|付款方', 'payee':r'\bpayee\b|收款方',
 'issuer':r'\bissuer\b|开票方', 'recipient':r'\brecipient\b|收票方',
 'payment_term':r'\bpayment term\b|付款条款', 'document_type':r'\bdocument type\b|单据类型',
}

def numeric_quote(value,quote):
    # Signs and thousands separators belong to the number, not token boundaries.
    return bool(re.search(r'(?<![\w.,+\-])'+re.escape(str(value))+r'(?![\w.,])',quote))

def update_names_field(field,quote,value):
    if value is None or re.search(r"\b(?:not|never|no|cannot)\b|\b(?:don't|don’t|doesn't|doesn’t|can't|can’t)\b|不要|不得|禁止|不应|无需|未要求",quote,re.I):return False
    named={k for k,pattern in UPDATE_FIELDS.items() if re.search(pattern,quote,re.I)}
    if named!={field}:return False
    # Recognize a small affirmative grammar; arbitrary prose is review-only.
    # A value in a "from" clause is never permission to use it as the destination.
    field_pattern='(?:'+UPDATE_FIELDS[field]+')'
    destination='(?P<destination>'+re.escape(str(value))+')'
    suffix=r'\s*[.!。]?\s*'
    english=(r'\s*(?:(?:please|kindly)\s+)?(?:update|change|correct|revise|replace|amend)\s+'
             r'(?:the\s+)?'+field_pattern+r'\s*(?:from\s+[^;\n]+?\s+)?(?:to\b|=|:)\s*'+destination+suffix)
    chinese=(r'\s*(?:请)?(?:将|把)?'+field_pattern+r'\s*(?:从[^;；\n]+?)?'
             r'(?:修改|更正|更新|调整)(?:为|至)\s*'+destination+suffix)
    chinese_prefix=(r'\s*(?:请)?(?:修改|更正|更新|调整)'+field_pattern+r'\s*(?:为|至|=|:|：)\s*'+destination+suffix)
    for pattern in (english,chinese,chinese_prefix):
        match=re.fullmatch(pattern,quote,re.I)
        if match:
            return numeric_quote(value,match['destination']) if field in NUMBERS else True
    return False

def reconcile(records,chunks,existing,accounting_entity,*,source_issues=None):
    if not accounting_entity or not accounting_entity.strip():raise ValueError('Current accounting entity is required')
    sources={c.id:c for c in chunks}; old=[flatten(r) for r in existing]
    def matches(r):
        for keys in [('reference_no','charge_item'),('bl_no','charge_item','currency'),('booking_no','charge_item','currency'),('container_no','payer','payee','date','amount')]:
            if all(r.get(k) is not None for k in keys):
                found=[j for j,o in enumerate(old) if all(equal(o.get(k),r.get(k),k) for k in keys)]
                if found:return found
        return []
    all_matches=[matches(r) for r in records]
    effective=[{**(old[m[0]] if len(m)==1 else {}),**{k:v for k,v in r.items() if v is not None}} for r,m in zip(records,all_matches)]
    def valid(ev):return isinstance(ev,dict) and ev.get('chunk_id') in sources and bool(ev.get('quote')) and ev['quote'] in sources[ev['chunk_id']].text
    if source_issues is not None and len(source_issues)!=len(records):raise ValueError('Source issue count must match extracted records')
    problems=[list(issues) for issues in source_issues] if source_issues is not None else [[] for _ in records]
    duplicates=Counter((norm(r.get('reference_no')),norm(fee_name(r.get('charge_item')))) for r in records)
    totals=defaultdict(list)
    for i,r in enumerate(records):
        for k in FIELDS:
            value=r.get(k)
            if value is None:continue
            ev=r.get('evidence',{}).get(k)
            supported=valid(ev) and str(value) in ev['quote']
            if supported and k in NUMBERS:
                supported=numeric_quote(value,ev['quote'])
            if not supported:problems[i].append(f'Unverified field evidence: {k}')
            if k in NUMBERS:
                try:
                    decimal(value)
                    if output_value(k,value) is None:problems[i].append(f'Numeric value cannot be represented safely in JSON: {k}')
                except ValueError:problems[i].append(f'Invalid amount/number: {k}')
        r=effective[i]
        if not r.get('charge_item') or r.get('amount') is None:problems[i].append('Fee name and amount required')
        if not r.get('currency') or not pycountry.currencies.get(alpha_3=str(r.get('currency'))):problems[i].append('Invalid or missing ISO 4217 currency')
        if not any(r.get(k) for k in ('reference_no','bl_no','booking_no','container_no')):problems[i].append('No stable document/shipment reference')
        if duplicates[(norm(r.get('reference_no')),norm(fee_name(r.get('charge_item'))))]>1:problems[i].append('Duplicate same-name fee lines require review')
        if any(re.search(r'O0|0O',str(r.get(k) or '')) for k in ('reference_no','bl_no','booking_no','container_no')):problems[i].append('Ambiguous O/0 identifier requires source review')
        try:
            if r.get('quantity') is not None and r.get('unit_price') is not None and decimal(r['quantity'])*decimal(r['unit_price'])!=decimal(r['amount']):problems[i].append('Quantity × unit price differs from amount')
        except ValueError:pass
        totals[(r.get('reference_no'),r.get('currency'))].append(i)
    for indices in totals.values():
        try:
            rs=[effective[i] for i in indices]
            # Evaluate the proposed final ledger, retaining untouched lines and totals.
            matched_indices={all_matches[i][0] for i in indices if len(all_matches[i])==1}
            ref,currency=rs[0].get('reference_no'),rs[0].get('currency')
            if ref:
                rs.extend(o for j,o in enumerate(old) if j not in matched_indices and equal(o.get('reference_no'),ref,'reference_no') and equal(o.get('currency'),currency,'currency') and norm(existing[j].get('financial_attributes',{}).get('accounting_entity') or accounting_entity)==norm(accounting_entity))
            values={decimal(r['total']) for r in rs if r.get('total') is not None}
            taxes={decimal(r['tax']) for r in rs if r.get('tax') is not None}
            subtotals={decimal(r['subtotal']) for r in rs if r.get('subtotal') is not None}
            amount=sum((decimal(r['amount']) for r in rs),Decimal(0))
            # Totals/tax/subtotal describe the document-currency group, never each fee.
            bad=len(values)>1 or len(taxes)>1 or len(subtotals)>1
            if subtotals and amount!=next(iter(subtotals)):bad=True
            if values and amount+(next(iter(taxes)) if taxes else Decimal(0))!=next(iter(values)):bad=True
            if bad:
                for i in indices:problems[i].append('Document/currency totals do not reconcile')
        except ValueError:pass
    output=[]
    for i,r in enumerate(records):
        issues=problems[i]; direction=None
        payer,payee=norm(effective[i].get('payer')),norm(effective[i].get('payee'));entity=norm(accounting_entity)
        if payer and payee and payer!=payee:
            if payer==entity:direction='AP'
            elif payee==entity:direction='AR'
        if direction is None:issues.append('AR/AP requires evidenced payer/payee and the current entity')
        candidates=all_matches[i]
        conflicts=[old[j] for j in candidates if any(old[j].get(k) and r.get(k) and not equal(old[j][k],r[k],k) for k in ('issuer','recipient','payer','payee','currency'))]
        if conflicts:issues.append('Same reference has conflicting parties/currency')
        if len(candidates)>1:issues.append('Multiple ledger matches')
        matched=candidates[0] if len(candidates)==1 else None
        if matched is not None:
            ledger_entity=existing[matched].get('financial_attributes',{}).get('accounting_entity')
            if ledger_entity and norm(ledger_entity)!=entity:issues.append('Matched ledger belongs to a different accounting entity')
        base=deepcopy(existing[matched]) if matched is not None else {g:{output_key(k):output_value(k,r.get(k)) for k in fields} for g,fields in GROUPS.items()}
        changes=[]
        if matched is not None:
            differences=[k for k in FIELDS if r.get(k) is not None and not equal(old[matched].get(k),r[k],k)]
            permissions={u.get('field') for u in r.get('explicit_updates',[]) if valid(u) and update_names_field(u.get('field'),u['quote'],r.get(u.get('field')))}
            if any(k not in permissions for k in differences):issues.append('Changed fields lack explicit update instructions/evidence')
            if not issues:
                for k in differences:
                    group=next(g for g,fields in GROUPS.items() if k in fields)
                    base.setdefault(group,{})[output_key(k)]=output_value(k,r[k])
                    changes.append({'field':output_key(k),'before':old[matched].get(k),'after':output_value(k,r[k])})
            operation='UPDATE' if changes else 'NO_CHANGE'
        else:operation='CREATE'
        if issues:operation='PENDING_REVIEW'
        base['operation']=operation
        if matched is None or not issues:
            base.setdefault('financial_attributes',{})['posting_type']=direction
            base['financial_attributes']['accounting_entity']=accounting_entity
        base['audit_trail']={**base.get('audit_trail',{}),'original_charge_name':r.get('charge_item'),'issues':list(dict.fromkeys(issues)),'changes':changes,'evidence':deepcopy(r.get('evidence',{})),'explicit_updates':deepcopy(r.get('explicit_updates',[])),'provenance':[{'id':c.id,'name':c.name,'locator':c.locator,'source_method':c.source_method} for c in chunks if c.id in {e.get('chunk_id') for e in r.get('evidence',{}).values()}]}
        output.append(base)
    return output
