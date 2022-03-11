import sys
import os

import csv
import re
from decimal import *
from datetime import datetime
from piecash import open_book, ledger, factories, Account, Transaction, Commodity, Split, GnucashException

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
            value = Decimal(transfer['value'])
            date = datetime.strptime(transfer['date'], "%m/%d/%Y")
            description = transfer['description']

            print("Enter the USDBRL conversion rate for the transfer made on {} of ${}".format(date, value))
            usdbrl = Decimal(input())
            brl = value * usdbrl
            brl = brl.quantize(Decimal('.01'), rounding=ROUND_DOWN) # round correctly to monetary value after multiplication

            print("Enter the IOF value for the transfer made on {} of ${}".format(date, value))
            iof = Decimal(input())

            iof_account = book.accounts(name='IOF de remessas internacionais')
            transfer_transaction = Transaction(currency=bank_account.commodity,
                description=description,
                post_date=date.date(),
                splits=[
                    Split(value=brl, quantity=value, account=brokerage_account),
                    Split(value=iof, account=iof_account),
                    Split(value=-(brl + iof), account=bank_account)
                ]
            )
            print(ledger(transfer_transaction))


        for dividend in dividends:
            symbol = dividend['symbol'].upper()
            if ' ' in symbol:
                symbol = symbol.replace(' ', '-')

            try:
                dividend_account = book.accounts(name=symbol, type='INCOME')
            except KeyError:
                parent_account = book.accounts(name='US Dividends')

                dividend_account = Account(name=symbol,
                    type="INCOME",
                    parent=parent_account,
                    commodity=parent_account.commodity,
                    placeholder=False,
                )
                book.flush()

            value = Decimal(dividend['value'])
            date = datetime.strptime(dividend['date'], "%m/%d/%Y")
            description = dividend['description']

            dividend_transaction = Transaction(currency=brokerage_account.commodity,
                description=description,
                post_date=date.date(),
                splits=[
                    Split(value=-value, account=dividend_account),
                    Split(value=value, account=brokerage_account)
                ]
            )
            print(ledger(dividend_transaction))


        book.save()
        
        sold_bought_balance = sum(stock['value'] for stock in stocks)
        print("Bought - sold stocks: ${}".format(sold_bought_balance))

        dividends_after_tax = sum(dividend['value'] for dividend in dividends)
        print("Dividends after taxes: ${}".format(dividends_after_tax))

        transferred = sum(transfer['value'] for transfer in transfers)
        print("Transferred amount: ${}".format(transferred))

def process_csv(csv_file):
    stocks = []
    dividends = []
    transfers = []

    reader = csv.DictReader(csv_file, delimiter = ',', quotechar='"')
    for row in reader:
        date = row['Date']
        if 'end' in date.lower():
            break

        description = row['Description']
        action = row['Action']
        symbol = row['Symbol']
        str_amount = row['Amount'].replace('$', '')
        amount = Decimal(str_amount) if str_amount else None
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
                'quantity': row['Quantity'],
                'value': -amount,
            })
        elif any(x in description.lower() for x in ['dividend', 'w-8', 'short term capital gains']):
            dividends.append({
                'date': date,
                'description': description,
                'symbol': symbol,
                'value': amount
            })
        elif any(x in action.lower() for x in ['security transfer']):
            print('Warning: Security transfer found. You should manually import it {} \n'.format(row))
        elif date.lower() == 'transactions total':
            # usually the last line of the report is this
            continue
        else:
            raise Exception("Unrecognizable row {}".format(row))

    return (stocks, dividends, transfers)


if len(sys.argv) < 3:
    print("Incorrect arguments. Arguments are file_path, gnucash_db_path and only_check_csv (optional)")
    exit()

file_path = sys.argv[1]
gnucash_db_path = sys.argv[2]
only_check_csv = len(sys.argv) > 3
with open(file_path,  newline='') as csv_file:
    # skip first line
    next(csv_file)

    stocks, dividends, transfers = process_csv(csv_file)
    if only_check_csv:
        print(stocks)
        print(dividends)
        print(transfers)
    else:
        write_to_gnucash(stocks, dividends, transfers)

