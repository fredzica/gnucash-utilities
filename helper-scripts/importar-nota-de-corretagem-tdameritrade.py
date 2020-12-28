import sys
import os

import csv
import re
from decimal import *
from datetime import datetime
from piecash import open_book, ledger, factories, Account, Transaction, Commodity, Split, GnucashException

file_path = sys.argv[1]
gnucash_db_path = sys.argv[2]

# este script necessita das notas de corretagem salvas em csv com o delimitador ';'

def write_to_gnucash(stocks, dividends, transfers):
    with open_book(gnucash_db_path, readonly=False) as book:
        brokerage_account = book.accounts(name='Conta no TD Ameritrade')

        print("Importing {} stock, {} dividend and {} transfer transactions".format(len(stocks), len(dividends), len(transfers)))

        for stock in stocks:
            symbol = stock['symbol'].upper()
            if ' ' in symbol:
                symbol = symbol.replace(' ', '-')

            try:
                stock_commodity = book.commodities(mnemonic=symbol)
            except KeyError:
                stock_commodity = Commodity(mnemonic=symbol,
                    fullname=symbol,
                    fraction=1,
                    namespace='US',
                    quote_flag=1,
                    quote_source="yahoo_json",
                )
                book.flush()

            try:
                stock_account = book.accounts(commodity=stock_commodity)
            except KeyError:
                parent_account = book.accounts(name='Ações no exterior')

                stock_account = Account(name=symbol,
                    type="STOCK",
                    parent=parent_account,
                    commodity=stock_commodity,
                    placeholder=False,
                )
                book.flush()

            value = Decimal(stock['value'])
            quantity = Decimal(stock['quantity'])
            if value < 0:
                quantity = -quantity
                print("******* You have sold the stock {}. Check if you should pay taxes this month!".format(symbol))

            date = datetime.strptime(stock['date'], "%m/%d/%Y")
            description = stock['description']

            stock_transaction = Transaction(currency=brokerage_account.commodity,
                description=description,
                post_date=date.date(),
                splits=[
                    Split(value=value, quantity=quantity, account=stock_account),
                    Split(value=-value, account=brokerage_account)
                ]
            )
            print(ledger(stock_transaction))

        bank_account = book.accounts(name='Conta no Inter')
        for transfer in transfers:
            value = transfer['value']
            date = datetime.strptime(transfer['date'], "%m/%d/%Y")
            description = transfer['description']

            print("Enter the USDBRL conversion rate for the transfer made on {} of ${}".format(date, value))
            usdbrl = Decimal(input())
            brl = value * usdbrl

            transfer_transaction = Transaction(currency=bank_account.commodity,
                description=description,
                post_date=date.date(),
                splits=[
                    Split(value=brl, quantity=value, account=brokerage_account),
                    Split(value=-brl, account=bank_account)
                ]
            )
            print(ledger(transfer_transaction))

        book.save()
        
        # TODO: import dividends and transfers
        sold_bought_balance = sum(stock['value'] for stock in stocks)
        print("Bought - sold stocks: {}".format(sold_bought_balance))

        dividends_after_tax = sum(dividend['value'] for dividend in dividends)
        print("Dividends after taxes: {}".format(dividends_after_tax))

        transferred = sum(transfer['value'] for transfer in transfers)
        print("Transferred amount: {}".format(transferred))

def process_csv(csv_file):

    # read stocks, amounts and prices
    stocks = []
    dividends = []
    transfers = []

    reader = csv.DictReader(csv_file, delimiter = ',', quotechar='"')
    for row in reader:
        date = row['DATE']
        if 'end' in date.lower():
            break

        description = row['DESCRIPTION']
        symbol = row['SYMBOL']
        amount = Decimal(row['AMOUNT'])
        if 'wire' in description.lower():
            transfers.append({
                'date': date,
                'direction': 'incoming' if amount > 0 else 'outgoing',
                'description': description,
                'value': amount
            })
        elif any(x in description.lower() for x in ['bought', 'sold']):
            stocks.append({
                'date': date,
                'description': description,
                'symbol': symbol,
                'quantity': row['QUANTITY'],
                'value': -amount,
            })
        elif any(x in description.lower() for x in ['dividend', 'w-8']):
            dividends.append({
                'date': date,
                'description': description,
                'symbol': symbol,
                'value': amount
            })
        else:
            raise Exception("Unrecognizable row")

    return (stocks, dividends, transfers)


with open(file_path,  newline='') as csv_file:
    stocks, dividends, transfers = process_csv(csv_file)
    write_to_gnucash(stocks, dividends, transfers)

