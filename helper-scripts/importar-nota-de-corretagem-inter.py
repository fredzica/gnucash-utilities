import sys

import csv
from datetime import datetime

f_path = sys.argv[1]

# este script necessita das notas de corretagem salvas em csv com o delimitador ';'

# TODO: processsar vários arquivos
# TODO: adicionar data de liquidacao e data do pregao
# TODO: adicionar mais prints, tambem adicionar warn quando houver venda de possíveis FIIs, pq o IR deles deve ser declarado separadamente
# TODO: escrever saída em outro csv
with open(f_path,  newline='') as csv_file:
    # skip first two lines
    next(csv_file)
    next(csv_file)

    # read stocks, amounts and prices
    stocks = []
    taxes = []
    reader = csv.DictReader(csv_file, delimiter = ';', quotechar='"')
    current_stock = None
    has_sold = None
    for row in reader:
        if row['PRAÇA'].startswith('1-Bovespa'):
            current_stock = row['ESPECIFICAÇÃO DO TÍTULO'].split(' ')[0]
            has_sold = row['C/V'] == 'V'

        if row['ESPECIFICAÇÃO DO TÍTULO'].startswith('SUBTOTAL'):
            amount = row['QUANTIDADE']
            if has_sold:
                amount = '-' + amount

            price = row['PREÇO DE LIQUIDAÇÃO(R$)'].replace(',', '.')
            stocks.append({'stock': current_stock, 'amount': amount, 'price': price})
            current_stock = None

        if row['PRAÇA'].startswith('RESUMO'):
            break;
    row = next(reader)
    taxa_liquidacao = row['D/C'].replace('D','')
    taxa_liquidacao = float(taxa_liquidacao)
    next(reader)
    next(reader)
    row = next(reader)
    taxa_b = row['D/C'].replace('D','').replace('-', '')
    taxa_b = float(taxa_b)
    next(reader)
    row = next(reader)
    ir = row['PREÇO DE LIQUIDAÇÃO(R$)'].replace('D','')
    ir = float(ir)
    row = next(reader)
    liquido = row['D/C'].replace('D','').replace('C', '').replace('-', '')
    liquido = float(liquido)

    taxes.append({'tax': 'B3', 'value': float(taxa_liquidacao) + float(taxa_b)})
    taxes.append({'tax': 'IR B3', 'value': float(ir)})

    # TODO: check values

    print(stocks)
    print(taxes)




'''
    with open(f_path + '.formatted', 'w', newline='') as csv_write:

        field_names = ['date', 'description', 'amount']
        writer = csv.DictWriter(csv_write, fieldnames=field_names)
        writer.writeheader()

        for row in reader:
            formatted =  datetime.strptime(row[0], '%d %b, %Y')
            formatted_time = formatted.strftime('%d-%m-%Y')

            writer.writerow({'date': formatted_time, 'description': row[1], 'amount': row[2]})
'''
