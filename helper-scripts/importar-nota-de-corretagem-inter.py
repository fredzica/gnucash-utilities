import sys
import os

import csv
from decimal import *
from datetime import datetime
from piecash import open_book, ledger, Transaction, Split, GnucashException

folder_path = sys.argv[1]
gnucash_db_path = sys.argv[2]

# este script necessita das notas de corretagem salvas em csv com o delimitador ';'

# TODO: adicionar warn quando houver venda de FIIs, pq o IR deles deve ser declarado separadamente


def write_to_gnucash(brokerage_statements):
    with open_book(gnucash_db_path, readonly=False) as book:
        bank_account = book.accounts(name='Conta no Inter')
        sold_value = Decimal(0)
        bought_value = Decimal(0)

        for statement in brokerage_statements:
            bank_account_value = 0
            splits = []

            for stock in statement['stocks']:
                stock_commodity = book.commodities(mnemonic=stock['stock'].upper() + '.SA')

                stock_account = book.accounts(commodity=stock_commodity)

                price = Decimal(stock['price'])
                amount = Decimal(stock['amount'])
                value =  price * amount

                if value > 0:
                    bought_value += value
                else:
                    sold_value += -value


                splits.append(Split(value=value, quantity=stock['amount'], account=stock_account))
                bank_account_value -= value

            for tax in statement['taxes']:
                tax_account = book.accounts(name=tax['tax'])


                value = Decimal(tax['value'])
                splits.append(Split(value=value, account=tax_account))

                bank_account_value -= value

            splits.append(Split(value=bank_account_value, account=bank_account))

            date = datetime.strptime(statement['date'], "%d/%m/%Y")
            t1 = Transaction(currency=bank_account.commodity,
                description=statement['description'],
                post_date=date.date(),
                splits=splits
            )
            print(ledger(t1))
            book.save()


        print('sold value: {:.2f}'.format(sold_value))
        print('bought value: {:.2f}'.format(bought_value))

        if sold_value >= 20000:
            print('*************** You sold more than 20000! Check if you need to pay taxes this month')

def extract_date_from_liq(liq_string):
    splitted = liq_string.split()

    return splitted[2].replace(':', '')


def extract_negotiation_date(file_path):
    splitted_path = file_path.split('/')
    file_name = splitted_path[len(splitted_path) - 1]

    return file_name.split('_')[2]


def process_csv(csv_file):
    # skip first two lines
    next(csv_file)
    next(csv_file)

    # read stocks, amounts and prices
    brokerage_statement = {}
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
            stocks.append({
                'stock': current_stock,
                'amount': amount,
                'price': price,
            })
            current_stock = None

        if row['PRAÇA'].startswith('RESUMO'):
            break;
    row = next(reader)
    taxa_liquidacao = row['D/C'].replace('D','')
    taxa_liquidacao = Decimal(taxa_liquidacao)
    next(reader)
    next(reader)
    row = next(reader)
    taxa_b = row['D/C'].replace('D','').replace('-', '')
    taxa_b = Decimal(taxa_b)
    next(reader)
    row = next(reader)
    ir = row['PREÇO DE LIQUIDAÇÃO(R$)'].replace('D','')
    ir = Decimal(ir)
    row = next(reader)
    liquido = row['D/C'].replace('D','').replace('C', '').replace('-', '')
    liquido = Decimal(liquido)


    tax_value = "{:.2f}".format(Decimal(taxa_liquidacao) + Decimal(taxa_b))
    taxes.append({
        'tax': 'B3',
        'value': tax_value,
    })

    ''' o valor do IR nao esta sendo debitado da conta...
    if ir:
        taxes.append({
            'tax': 'IR B3',
            'value': "{:.2f}".format(ir)
        })
    '''

    negotiation_date = extract_negotiation_date(csv_file.name)
    data_liquido = extract_date_from_liq(row['COMPRA/VENDA (R$)'])
    brokerage_statement['stocks'] = stocks
    brokerage_statement['taxes'] = taxes
    brokerage_statement['date'] = data_liquido
    brokerage_statement['description'] = 'Pregão do dia {}'.format(negotiation_date)
    return brokerage_statement


for root, directories, files in os.walk(folder_path):
    brokerage_statements = []
    for f in files:
        if '_NotaCor_'in f and '.csv' in f:
            print("Iterating through file {}".format(f))
            file_path = '{}/{}'.format(root, f)

            with open(file_path,  newline='') as csv_file:
                statement = process_csv(csv_file)
                brokerage_statements.append(statement)
    write_to_gnucash(brokerage_statements)

