from billing_agent.parsers import plain_ocr_tables


def test_table_cells_are_traceable_contiguous_text():
    raw='Notice\n<table><tr><td>B/L #</td><td>AMOUNT</td></tr><tr><td>BL1</td><td>245.0000</td></tr></table>\nEnd'
    assert plain_ocr_tables(raw)=='Notice\nB/L # AMOUNT\nBL1 245.0000\nEnd'


def test_table_conversion_preserves_outside_text_and_entities():
    raw='# Fee & conditions\n<table><tr><td>Handling &amp; port</td><td>USD<br>245</td></tr></table>\n- cancel fee $25 if requested'
    assert plain_ocr_tables(raw)=='# Fee & conditions\nHandling & port USD 245\n- cancel fee $25 if requested'


def test_non_table_document_unchanged():
    raw='ordinary <reference> $25\nline 2'
    assert plain_ocr_tables(raw)==raw
