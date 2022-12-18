import sys

import pprint
pp = pprint.PrettyPrinter(indent=2)

import csv
from decimal import *
from datetime import datetime
from piecash import open_book, ledger, Account, Transaction, Commodity, Split


def import_expense(brokerage_account, book, expense, expense_account_name=None):
    value = Decimal(expense['value'])

    date_split = expense['date'].split(' ')
    date = datetime.strptime(date_split[0], "%m/%d/%Y")
    description = expense['description']

    if expense_account_name is None:
        print("Enter the expense account for the purchase {} made on {} of ${}".format(description, date, value))
        expense_account_name = input()

    expense_account = book.accounts(name=expense_account_name, type='EXPENSE')
    expense_transaction = Transaction(currency=brokerage_account.commodity,
        description=description,
        post_date=date.date(),
        splits=[
            Split(value=-value, account=expense_account),
            Split(value=value, account=brokerage_account)
        ]
    )
    print(ledger(expense_transaction))


def import_income(brokerage_account, book, income, income_account_name):
    value = Decimal(income['value'])

    date_split = income['date'].split(' ')
    date = datetime.strptime(date_split[0], "%m/%d/%Y")
    description = income['description']

    income_account = book.accounts(name=income_account_name, type='INCOME')
    income_transaction = Transaction(currency=brokerage_account.commodity,
        description=description,
        post_date=date.date(),
        splits=[
            Split(value=-value, account=income_account),
            Split(value=value, account=brokerage_account)
        ]
    )
    print(ledger(income_transaction))


def write_to_gnucash(gnucash_db_path, contents):
    with open_book(gnucash_db_path, readonly=False, do_backup=True) as book:
        brokerage_account = book.accounts(name='Conta no Charles Schwab')

        [stocks, dividends, transfers, purchases, adr_fees, foreign_taxes, account_interest, salary_payments] = contents.values()

        print("Importing {} stock, {} dividend, {} transfer, {} purchase, {} adr fees transactions, {} foreign_tax, {} account_interest and {} salary_payments"
              .format(len(stocks), len(dividends), len(transfers), len(purchases), len(adr_fees), len(foreign_taxes), len(account_interest), len(salary_payments)))

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
            date_split = dividend['date'].split(' ')
            date = datetime.strptime(date_split[0], "%m/%d/%Y")
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
            import_expense(brokerage_account, book, purchase)

        for adr_fee in adr_fees:
            import_expense(brokerage_account, book, adr_fee, expense_account_name='ADR Mgmt Fee')

        for foreign_tax in foreign_taxes:
            import_expense(brokerage_account, book, foreign_tax, expense_account_name='Foreign Tax Paid')

        for interest in account_interest:
            import_income(brokerage_account, book, interest, 'Schwab Account Interest')

        for salary in salary_payments:
            import_income(brokerage_account, book, salary, 'Salary')

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
    adr_fees = []
    foreign_taxes = []
    account_interest = []
    salary_payments = []

    reader = csv.DictReader(csv_file, delimiter = ',', quotechar='"')
    for row in reader:
        date = row['Date']
        if 'end' in date.lower():
            break

        action = row['Action']
        action_lower_case = action.lower()
        symbol = row['Symbol']
        description = "{}-{}".format(action, row['Description'])
        symbol_description = "{}-{}".format(description, symbol)
        str_amount = row['Amount'].replace('$', '')
        amount = Decimal(str_amount) if str_amount else None

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
            })
        elif action.lower() == 'nra tax adj' and symbol == '':
            account_interest.append({
                'date': date,
                'description': description,
                'value': amount
            })
        elif action.lower() in ['cash dividend', 'qualified dividend', 'nra tax adj', 'non-qualified div', 'pr yr nra tax', 'pr yr non-qual div']:
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
        elif 'adr mgmt fee' == action.lower():
            adr_fees.append({
                'date': date,
                'description': description,
                'symbol': symbol,
                'value': amount
            })
        elif 'foreign tax paid' == action.lower():
            foreign_taxes.append({
                'date': date,
                'description': description,
                'symbol': symbol,
                'value': amount
            })
        elif 'credit interest' == action.lower():
            account_interest.append({
                'date': date,
                'description': description,
                'value': amount
            })
        elif 'moneylink deposit' == action.lower():
            salary_payments.append({
                'date': date,
                'description': description,
                'value': amount
            })
        elif action.lower() in ['unissued rights redemption', 'security transfer']:
            print('Warning: {} found. You should manually import it'.format(action))
            pp.pprint(row)
        elif date.lower() == 'transactions total':
            # usually the last line of the report is this
            continue
        else:
            raise Exception("Unrecognizable row {}".format(row))

    return dict(stocks=stocks, dividends=dividends, transfers=transfers, purchases=purchases, adr_fees=adr_fees, foreign_taxes=foreign_taxes, account_interest=account_interest, salary_payments=salary_payments)


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

        csv_content = process_csv(csv_file)
        if only_check_csv:
            pprint.pprint(csv_content)
        else:
            write_to_gnucash(gnucash_db_path, csv_content)


main()
