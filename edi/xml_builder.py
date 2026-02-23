"""
edi/xml_builder.py — Генерация XML для 1С

Логика:
  1. Проверяем наличие активного XmlTemplate в БД для данного типа
  2. Если есть — рендерим через шаблон (гибкая настройка)
  3. Если нет — генерируем GS1/EANCOM по умолчанию через lxml

Это позволяет настроить формат XML под любой 1С
прямо из интерфейса без изменения кода.
"""
from lxml import etree
from datetime import date


# ───────────────────────────────────────────────────────
# Генераторы GS1 по умолчанию (используются если нет шаблона)
# ───────────────────────────────────────────────────────

def _root(msg_type, doc_id, supplier_gln, buyer_gln, doc_date):
    root = etree.Element('Document')
    etree.SubElement(root, 'DocumentType').text  = msg_type
    etree.SubElement(root, 'DocumentId').text    = doc_id
    etree.SubElement(root, 'DocumentDate').text  = doc_date or str(date.today())
    parties = etree.SubElement(root, 'Parties')
    sup = etree.SubElement(parties, 'Supplier')
    etree.SubElement(sup, 'GLN').text = supplier_gln
    buy = etree.SubElement(parties, 'Buyer')
    etree.SubElement(buy, 'GLN').text = buyer_gln
    return root

def _positions(root, positions):
    lines = etree.SubElement(root, 'Lines')
    for i, p in enumerate(positions, 1):
        line = etree.SubElement(lines, 'Line')
        etree.SubElement(line, 'LineNumber').text    = str(i)
        etree.SubElement(line, 'EAN').text           = str(p.get('ean', ''))
        etree.SubElement(line, 'ItemCode').text      = str(p.get('itemCode', ''))
        etree.SubElement(line, 'ItemName').text      = str(p.get('itemName', ''))
        etree.SubElement(line, 'Quantity').text      = str(p.get('quantity', 0))
        etree.SubElement(line, 'UnitPrice').text     = str(p.get('unitPrice', 0))
        etree.SubElement(line, 'VAT').text           = str(p.get('vat', 0))
        etree.SubElement(line, 'Amount').text        = str(p.get('amount', 0))
        etree.SubElement(line, 'AmountWithVAT').text = str(p.get('amountWithVat', 0))

def _default_order(d):
    root = _root('ORDER', d.get('number',''), d.get('supplierGln',''), d.get('buyerGln',''), d.get('date',''))
    etree.SubElement(root, 'DeliveryDate').text  = d.get('deliveryDate','')
    etree.SubElement(root, 'DeliveryPlace').text = d.get('deliveryPlace','')
    etree.SubElement(root, 'Currency').text      = d.get('currency','KZT')
    _positions(root, d.get('positions', []))
    return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='UTF-8')

def _default_ordrsp(d):
    root = _root('ORDRSP', d.get('number',''), d.get('supplierGln',''), d.get('buyerGln',''), d.get('date',''))
    etree.SubElement(root, 'OrderNumber').text        = d.get('orderNumber','')
    etree.SubElement(root, 'ConfirmationStatus').text = str(d.get('confirmationStatus', 29))
    _positions(root, d.get('positions', []))
    return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='UTF-8')

def _default_desadv(d):
    root = _root('DESADV', d.get('number',''), d.get('supplierGln',''), d.get('buyerGln',''), d.get('date',''))
    etree.SubElement(root, 'OrderNumber').text        = d.get('orderNumber','')
    etree.SubElement(root, 'ShipmentDate').text       = d.get('shipmentDate','')
    etree.SubElement(root, 'TransportDocNumber').text = d.get('transportDoc','')
    _positions(root, d.get('positions', []))
    return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='UTF-8')

def _default_invoice(d):
    root = _root('INVOICE', d.get('number',''), d.get('supplierGln',''), d.get('buyerGln',''), d.get('date',''))
    etree.SubElement(root, 'OrderNumber').text   = d.get('orderNumber','')
    etree.SubElement(root, 'TotalAmount').text   = str(d.get('totalAmount', 0))
    etree.SubElement(root, 'TotalVAT').text      = str(d.get('totalVat', 0))
    etree.SubElement(root, 'TotalWithVAT').text  = str(d.get('totalWithVat', 0))
    etree.SubElement(root, 'Currency').text      = d.get('currency','KZT')
    _positions(root, d.get('positions', []))
    return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='UTF-8')

def _default_pricat(d):
    root = _root('PRICAT', d.get('number',''), d.get('supplierGln',''), d.get('buyerGln',''), d.get('date',''))
    etree.SubElement(root, 'ValidFrom').text = d.get('validFrom','')
    etree.SubElement(root, 'ValidTo').text   = d.get('validTo','')
    etree.SubElement(root, 'Currency').text  = d.get('currency','KZT')
    _positions(root, d.get('positions', []))
    return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='UTF-8')

_DEFAULT_BUILDERS = {
    'ORDER':   _default_order,
    'ORDRSP':  _default_ordrsp,
    'DESADV':  _default_desadv,
    'INVOICE': _default_invoice,
    'PRICAT':  _default_pricat,
}


# ───────────────────────────────────────────────────────
# Основная функция — с поддержкой шаблонов из БД
# ───────────────────────────────────────────────────────

def build_xml(doc_type: str, data: dict) -> bytes:
    """
    Генерирует XML для документа.
    Сначала ищет активный XmlTemplate в БД.
    Если не найден — использует GS1 по умолчанию.
    """
    # Пробуем получить шаблон из БД
    try:
        from .models import XmlTemplate
        tpl = XmlTemplate.objects.filter(doc_type=doc_type, is_active=True).first()
        if tpl:
            rendered = tpl.render(data)
            return rendered.encode('utf-8')
    except Exception:
        pass  # БД недоступна или миграции не применены — идём к дефолту

    # Дефолтный GS1-генератор
    builder = _DEFAULT_BUILDERS.get(doc_type)
    if not builder:
        raise ValueError(f'Неизвестный тип документа: {doc_type}')
    return builder(data)


# Дефолтные шаблоны для авто-создания при первом запуске
DEFAULT_TEMPLATES = {
    'ORDER': {
        'name': 'GS1 ORDER (по умолчанию)',
        'position_tpl': '''    <Line>
      <LineNumber>{{line}}</LineNumber>
      <EAN>{{ean}}</EAN>
      <ItemCode>{{item_code}}</ItemCode>
      <ItemName>{{item_name}}</ItemName>
      <Quantity>{{quantity}}</Quantity>
      <UnitPrice>{{unit_price}}</UnitPrice>
      <VAT>{{vat}}</VAT>
      <Amount>{{amount}}</Amount>
      <AmountWithVAT>{{amount_with_vat}}</AmountWithVAT>
    </Line>''',
        'body_tpl': '''<?xml version="1.0" encoding="UTF-8"?>
<Document>
  <DocumentType>ORDER</DocumentType>
  <DocumentId>{{number}}</DocumentId>
  <DocumentDate>{{date}}</DocumentDate>
  <DeliveryDate>{{delivery_date}}</DeliveryDate>
  <Currency>{{currency}}</Currency>
  <Parties>
    <Supplier><GLN>{{supplier_gln}}</GLN><Name>{{supplier_name}}</Name></Supplier>
    <Buyer><GLN>{{buyer_gln}}</GLN><Name>{{buyer_name}}</Name></Buyer>
  </Parties>
  <Lines>
{{positions}}
  </Lines>
</Document>''',
    },
    'ORDRSP': {
        'name': 'GS1 ORDRSP (по умолчанию)',
        'position_tpl': '''    <Line>
      <LineNumber>{{line}}</LineNumber>
      <EAN>{{ean}}</EAN>
      <ItemName>{{item_name}}</ItemName>
      <Quantity>{{quantity}}</Quantity>
      <UnitPrice>{{unit_price}}</UnitPrice>
    </Line>''',
        'body_tpl': '''<?xml version="1.0" encoding="UTF-8"?>
<Document>
  <DocumentType>ORDRSP</DocumentType>
  <DocumentId>{{number}}</DocumentId>
  <DocumentDate>{{date}}</DocumentDate>
  <OrderNumber>{{order_number}}</OrderNumber>
  <Parties>
    <Supplier><GLN>{{supplier_gln}}</GLN></Supplier>
    <Buyer><GLN>{{buyer_gln}}</GLN></Buyer>
  </Parties>
  <Lines>
{{positions}}
  </Lines>
</Document>''',
    },
    'DESADV': {
        'name': 'GS1 DESADV (по умолчанию)',
        'position_tpl': '''    <Line>
      <LineNumber>{{line}}</LineNumber>
      <EAN>{{ean}}</EAN>
      <ItemName>{{item_name}}</ItemName>
      <Quantity>{{quantity}}</Quantity>
    </Line>''',
        'body_tpl': '''<?xml version="1.0" encoding="UTF-8"?>
<Document>
  <DocumentType>DESADV</DocumentType>
  <DocumentId>{{number}}</DocumentId>
  <DocumentDate>{{date}}</DocumentDate>
  <ShipmentDate>{{shipment_date}}</ShipmentDate>
  <OrderNumber>{{order_number}}</OrderNumber>
  <Parties>
    <Supplier><GLN>{{supplier_gln}}</GLN></Supplier>
    <Buyer><GLN>{{buyer_gln}}</GLN></Buyer>
  </Parties>
  <Lines>
{{positions}}
  </Lines>
</Document>''',
    },
    'INVOICE': {
        'name': 'GS1 INVOICE (по умолчанию)',
        'position_tpl': '''    <Line>
      <LineNumber>{{line}}</LineNumber>
      <EAN>{{ean}}</EAN>
      <ItemName>{{item_name}}</ItemName>
      <Quantity>{{quantity}}</Quantity>
      <UnitPrice>{{unit_price}}</UnitPrice>
      <VAT>{{vat}}</VAT>
      <Amount>{{amount}}</Amount>
      <AmountWithVAT>{{amount_with_vat}}</AmountWithVAT>
    </Line>''',
        'body_tpl': '''<?xml version="1.0" encoding="UTF-8"?>
<Document>
  <DocumentType>INVOICE</DocumentType>
  <DocumentId>{{number}}</DocumentId>
  <DocumentDate>{{date}}</DocumentDate>
  <OrderNumber>{{order_number}}</OrderNumber>
  <TotalAmount>{{total_amount}}</TotalAmount>
  <TotalVAT>{{total_vat}}</TotalVAT>
  <TotalWithVAT>{{total_with_vat}}</TotalWithVAT>
  <Currency>{{currency}}</Currency>
  <Parties>
    <Supplier><GLN>{{supplier_gln}}</GLN></Supplier>
    <Buyer><GLN>{{buyer_gln}}</GLN></Buyer>
  </Parties>
  <Lines>
{{positions}}
  </Lines>
</Document>''',
    },
    'PRICAT': {
        'name': 'GS1 PRICAT (по умолчанию)',
        'position_tpl': '''    <Item>
      <LineNumber>{{line}}</LineNumber>
      <EAN>{{ean}}</EAN>
      <ItemCode>{{item_code}}</ItemCode>
      <ItemName>{{item_name}}</ItemName>
      <UnitPrice>{{unit_price}}</UnitPrice>
      <VAT>{{vat}}</VAT>
    </Item>''',
        'body_tpl': '''<?xml version="1.0" encoding="UTF-8"?>
<Document>
  <DocumentType>PRICAT</DocumentType>
  <DocumentId>{{number}}</DocumentId>
  <DocumentDate>{{date}}</DocumentDate>
  <Currency>{{currency}}</Currency>
  <Parties>
    <Supplier><GLN>{{supplier_gln}}</GLN></Supplier>
    <Buyer><GLN>{{buyer_gln}}</GLN></Buyer>
  </Parties>
  <Items>
{{positions}}
  </Items>
</Document>''',
    },
}
