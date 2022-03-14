import sys
import os
import shutil
import time

import pprint
pp = pprint.PrettyPrinter(indent=2)

import csv
import re
from decimal import *
from datetime import datetime
from piecash import open_book, ledger, factories, Account, Transaction, Commodity, Split, GnucashException


def write_to_gnucash(gnucash_db_path, stocks, dividends, transfers, purchases):
    # backing up the db file first
    ms = time.time() * 1000.0
    shutil.copy(gnucash_db_path, '{}.{}.schwab-importing'.format(gnucash_db_path, ms))

    with open_book(gnucash_db_path, readonly=False) as book:
        brokerage_account = book.accounts(name='Conta no Charles Schwab')

        print("Importing {} stock, {} dividend, {} transfer and {} purchase transactions".format(len(stocks), len(dividends), len(transfers), len(purchases)))

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
            fee = Decimal(stock['fee'])
            if value < 0:
                quantity = -quantity
                print("******* You have sold the stock {}. Check if you should pay taxes this month!".format(symbol))

            date = datetime.strptime(stock['date'], "%m/%d/%Y")
            description = stock['description']

            stock_transaction = Transaction(currency=brokerage_account.commodity,
                description=description,
                post_date=date.date(),
                splits=[
                    Split(value=value-fee, quantity=quantity, account=stock_account),
                    Split(value=-value, account=brokerage_account)
                ]
            )

            if fee != 0:
                fee_account = book.accounts(name='Schwab Fees')
                stock_transaction.splits.append(Split(value=fee, account=fee_account))

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

        for purchase in purchases:
            value = Decimal(purchase['value'])

            date_split = purchase['date'].split(' ')
            date = datetime.strptime(date_split[0], "%m/%d/%Y")
            description = purchase['description']

            print("Enter the expense account for the purchase {} made on {} of ${}".format(description, date, value))
            expense_account_name = input()
            expense_account = book.accounts(name=expense_account_name, type='EXPENSE')
            purchase_transaction = Transaction(currency=brokerage_account.commodity,
                description=description,
                post_date=date.date(),
                splits=[
                    Split(value=-value, account=expense_account),
                    Split(value=value, account=brokerage_account)
                ]
            )
            print(ledger(purchase_transaction))

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
    purchases = []

    reader = csv.DictReader(csv_file, delimiter = ',', quotechar='"')
    for row in reader:
        date = row['Date']
        if 'end' in date.lower():
            break

        action = row['Action']
        symbol = row['Symbol']
        description = "{}-{}".format(action, row['Description'])
        symbol_description = "{}-{}".format(description, symbol)
        str_amount = row['Amount'].replace('$', '')
        amount = Decimal(str_amount) if str_amount else None

        str_fee = row['Fees & Comm'].replace('$', '')
        fee = Decimal(str_fee) if str_fee != '' else Decimal(0)
        if 'wire funds received' == action.lower():
            transfers.append({
                'date': date,
                'direction': 'incoming' if amount > 0 else 'outgoing',
                'description': description,
                'value': amount
            })
        elif 'buy' == action.lower() or 'sell' == action.lower():
            stocks.append({
                'date': date,
                'description': symbol_description,
                'symbol': symbol,
                'quantity': row['Quantity'],
                'value': -amount,
                'fee': fee
            })
        elif any(x in action.lower() for x in ['dividend', 'nra tax adj', 'non-qualified div', 'pr yr nra tax', 'pr yr non-qual div']):
            dividends.append({
                'date': date,
                'description': symbol_description,
                'symbol': symbol,
                'value': amount
            })
        elif 'visa purchase' == action.lower():
            purchases.append({
                'date': date,
                'description': description,
                'value': amount
            })
        elif 'security transfer' == action.lower():
            print('Warning: Security transfer found. You should manually import it')
            pp.pprint(row)
        elif date.lower() == 'transactions total':
            # usually the last line of the report is this
            continue
        else:
            raise Exception("Unrecognizable row {}".format(row))

    return (stocks, dividends, transfers, purchases)


def main():
    if len(sys.argv) < 3:
        print("Incorrect arguments. Arguments are file_path, gnucash_db_path and only_check_csv (optional)")
        exit()

    file_path = sys.argv[1]
    gnucash_db_path = sys.argv[2]
    only_check_csv = len(sys.argv) > 3
    with open(file_path,  newline='') as csv_file:
        # skip first line
        next(csv_file)

        stocks, dividends, transfers, purchases = process_csv(csv_file)
        if only_check_csv:
            print("stocks")
            pp.pprint(stocks)
            print("dividends")
            pp.pprint(dividends)
            print("transfers")
            pp.pprint(transfers)
            print("purchases")
            pp.pprint(purchases)
        else:
            write_to_gnucash(gnucash_db_path, stocks, dividends, transfers, purchases)


main()
