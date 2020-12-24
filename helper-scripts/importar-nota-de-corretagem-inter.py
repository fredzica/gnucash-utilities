import sys
import os

import csv
from decimal import *
from datetime import datetime
from piecash import open_book, ledger, Transaction, Split, GnucashException

folder_path = sys.argv[1]
gnucash_db_path = sys.argv[2]

# este script necessita das notas de corretagem salvas em csv com o delimitador ';'

# TODO: adicionar mais prints, tambem adicionar warn quando houver venda de possíveis FIIs, pq o IR deles deve ser declarado separadamente
# TODO: para escrever a conta inteira do gnucash talvez faca mais sentido buscar no DB dele todas as possíveis contas e bater com as que estão aqui? isso permitiria fazer o controle melhor de IR quando for uma venda de FII


def write_stocks_csv(stocks):
    print(stocks)

    with open_book(gnucash_db_path, readonly=False) as book:
        for stock in stocks:
            stock_commodity = book.commodities(mnemonic=stock['stock'].upper() + '.SA')
            print(stock_commodity)

            stock_account = book.accounts(commodity=stock_commodity)
            print(stock_account)

            bank_account = book.accounts(name='Conta no Inter')
            print(bank_account)

            price = Decimal(stock['price'])
            amount = Decimal(stock['amount'])
            value =  price * amount

            date = datetime.strptime(stock['date'], "%d/%m/%Y")

            t1 = Transaction(currency=bank_account.commodity,
                description=stock['description'],
                post_date=date.date(),
                enter_date=datetime.now(),
                splits=[
                    Split(value=-value, account=bank_account),
                    Split(value=value, quantity=stock['amount'], account=stock_account),
                ]
            )

            print(ledger(t1))
            book.save()






def write_taxes_csv(taxes):
    print(taxes)



def extract_date_from_liq(liq_string):
    splitted = liq_string.split()

    return splitted[2].replace(':', '')


def add_liq_date_to_lists(liq_date, stocks, taxes):
    for stock in stocks:
        stock['date'] = liq_date

    for tax in taxes:
        tax['date'] = liq_date


def extract_negotiation_date(file_path):
    splitted_path = file_path.split('/')
    file_name = splitted_path[len(splitted_path) - 1]

    return file_name.split('_')[2]


def process_csv(csv_file):
    # skip first two lines
    next(csv_file)
    next(csv_file)

    # read stocks, amounts and prices
    stocks = []
    taxes = []
    negotiation_date = extract_negotiation_date(csv_file.name)

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
            stocks.append({
                'stock': current_stock,
                'amount': amount,
                'price': price,
                'description': 'Pregão do dia {}'.format(negotiation_date)
            })
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

    data_liquido = extract_date_from_liq(row['COMPRA/VENDA (R$)'])

    tax_value = "{:.2f}".format(float(taxa_liquidacao) + float(taxa_b))
    taxes.append({
        'tax': 'B3',
        'value': tax_value,
        'description': 'Pregão do dia {}'.format(negotiation_date)
    })

    ir_float = float(ir)
    if ir_float:
        taxes.append({
            'tax': 'IR B3',
            'value': "{:.2f}".format(ir_float),
            'description': 'Pregão do dia {}'.format(negotiation_date)
        })

    add_liq_date_to_lists(data_liquido, stocks, taxes)


    return stocks, taxes
    # TODO: check values





for root, directories, files in os.walk(folder_path):
    stocks = []
    taxes = []
    for f in files:
        if '_NotaCor_'in f and '.csv' in f:
            print("Iterating through file {}".format(f))
            file_path = '{}/{}'.format(root, f)

            with open(file_path,  newline='') as csv_file:
                (stockss, taxess) = process_csv(csv_file)
                stocks += stockss
                taxes += taxess

    write_stocks_csv(stocks)
    write_taxes_csv(taxes)

