from decimal import Decimal
import pytest
from billing_agent.rules import decimal, output_value, reconcile
from billing_agent.models import Chunk

@pytest.mark.parametrize('raw,value',[('1,310.40',Decimal('1310.40')),('-1,310.40',Decimal('-1310.40')),('1,000,000',Decimal('1000000'))])
def test_grouped_amounts(raw,value):
    assert decimal(raw)==value
    assert output_value('amount',raw)==float(value)

@pytest.mark.parametrize('raw',['1,31.40','1,310,40','1.310,40','12,34,567','1,0000'])
def test_ambiguous_grouping_is_rejected(raw):
    with pytest.raises(ValueError):decimal(raw)

def test_real_bill_grouped_total_and_line_sum():
    text='INV-X USD ACME Carrier A B C 65.00 1,310.40 35.00 1,410.40'
    chunk=Chunk(id='x',name='bill',text=text,locator='body',source_method='text')
    records=[]
    for name,amount in [('A','65.00'),('B','1,310.40'),('C','35.00')]:
        r=dict(reference_no='INV-X',currency='USD',payer='ACME',payee='Carrier',charge_item=name,amount=amount,total='1,410.40')
        r['evidence']={k:dict(chunk_id='x',quote=v) for k,v in r.items()}
        records.append(r)
    rows=reconcile(records,[chunk],[],'ACME')
    assert all(r['operation']=='CREATE' for r in rows)
    assert [r['charge_details']['amount'] for r in rows]==[65,1310.4,35]
    assert all(r['charge_details']['total']==1410.4 for r in rows)
