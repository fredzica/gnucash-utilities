import sys
import csv
import re
from decimal import Decimal
from datetime import datetime
from piecash import open_book, ledger, Account, Commodity, Transaction, Split

csv_file_path = sys.argv[1]
gnucash_db_path = sys.argv[2]

def normalize_ticker(ticker):
    return re.sub(r'F$', '', ticker.upper())

def get_or_create_stock_account(book, ticker):
    ticker = normalize_ticker(ticker)
    ticker_with_suffix = f"{ticker}.SA"

    try:
        stock_commodity = book.commodities(mnemonic=ticker_with_suffix)
    except KeyError:
        stock_commodity = Commodity(
            namespace="BVMF",
            mnemonic=ticker_with_suffix,
            fullname=ticker_with_suffix,
            fraction=1,
            quote_flag=1,
            quote_source="yahoo_json"
        )

    try:
        # filter with hidden because there are old accounts I want to avoid
        stock_account = book.accounts(commodity=stock_commodity, hidden=0)
    except KeyError:
        print(f"O ativo {ticker} é Ação (1), FII (2)? ")
        tipo = int(input())
        if tipo == 1:
            parent_account = book.accounts(name="Ações")
        elif tipo == 2:
            parent_account = book.accounts(name="FIIs")
        else:
            raise Exception("Invalid input. Should be 1 or 2")

        stock_account = Account(
            name=ticker,
            type="STOCK",
            parent=parent_account,
            commodity=stock_commodity,
            placeholder=False,
        )
        book.flush()

    return stock_account

def parse_csv(path):
    with open(path, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=';')
        operations = []
        for row in reader:
            if row['Tipo de Movimentação'] not in ['Compra', 'Venda']:
                raise Exception("Coluna Tipo de Movimentação deve ser Compra ou Venda")

            date = datetime.strptime(row['Data do Negócio'], '%d/%m/%Y').date()
            operation = {
                'date': date,
                'type': row['Tipo de Movimentação'],
                'ticker': row['Código de Negociação'],
                'quantity': Decimal(row['Quantidade'].replace('.', '')),
                'price': Decimal(row['Preço'].replace('.', '').replace(',', '.').replace('RR$	', '')),
            }
            operations.append(operation)
        return operations

def write_operations_to_gnucash(operations):
    with open_book(gnucash_db_path, readonly=False, do_backup=True) as book:
        bank_account = book.accounts(name='Conta no Inter')

        grouped_by_date = {}
        for op in operations:
            grouped_by_date.setdefault(op['date'], []).append(op)

        for date, ops in grouped_by_date.items():
            splits_data = []
            total_bank_value = Decimal(0)

            for op in ops:
                stock_account = get_or_create_stock_account(book, op['ticker'])
                signed_quantity = op['quantity'] if op['type'] == 'Compra' else -op['quantity']
                signed_value = op['price'] * signed_quantity

                splits_data.append({
                    'account': stock_account,
                    'value': signed_value,
                    'quantity': signed_quantity
                })

                total_bank_value -= signed_value

                if op['type'] == 'Venda' and 'FIIs' in stock_account.fullname:
                    print(f'*************** Você vendeu o FII {stock_account.fullname}! Verifique se precisa pagar IR.')

            splits_data.append({
                'account': bank_account,
                'value': total_bank_value
            })

            splits = list(map(lambda split_data: Split(**split_data), splits_data))
            transaction = Transaction(
                currency=bank_account.commodity,
                description=f"Operações B3 - {date.strftime('%d/%m/%Y')}",
                post_date=date,
                splits=splits
            )
            print(ledger(transaction))
            book.flush()

        book.save()

if __name__ == "__main__":
    operations = parse_csv(csv_file_path)
    write_operations_to_gnucash(operations)
