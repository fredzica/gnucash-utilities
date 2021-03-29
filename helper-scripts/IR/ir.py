import sys
import os
import csv
import re
import pprint
from decimal import *
from datetime import date
from piecash import open_book, ledger, factories, Account, Transaction, Commodity, Split, GnucashException


def collect_bens_direitos(book, date_filter):
    acoes_account = book.accounts(name='Ações')
    fiis_account = book.accounts(name='FIIs')
    children = acoes_account.children + fiis_account.children

    acoes = []
    for acao_account in children:
        quantity = Decimal(0)
        value = Decimal(0)

        price_avg = Decimal(0)
        value_purchases = Decimal(0)
        quantity_purchases = Decimal(0)
        for split in acao_account.splits:
            if split.transaction.post_date <= date_filter:
                quantity += Decimal(split.quantity)
                value += Decimal(split.value)

                if split.value > 0:
                    value_purchases += Decimal(split.value)
                    quantity_purchases += Decimal(split.quantity)
                    price_avg = value_purchases/quantity_purchases

        if quantity > 0:
            acoes.append({
                    'name': acao_account.name,
                    'quantity': quantity,
                    'value': price_avg * quantity,
                    'price_avg': price_avg,
                    'value_purchases': value_purchases,
                    'quantity_purchases': quantity_purchases
            })

    return acoes


def main():
    pp = pprint.PrettyPrinter(indent=2)

    gnucash_db_path = sys.argv[1]
    year_filter = sys.argv[2]

    is_debug = False
    if len(sys.argv) > 3:
        is_debug = bool(sys.argv[3])

    maximum_date_filter = date(int(year_filter), 12, 31)

    with open_book(gnucash_db_path, readonly=True, do_backup=False, open_if_lock=True) as book:
        print('retrieving data before or equal than {}'.format(maximum_date_filter))

        print("************* Bens e direitos *************")
        bens_direitos = collect_bens_direitos(book, maximum_date_filter)
        for bem_direito in bens_direitos:
            print('ticker: {}, valor: {}, quantidade: {}'.format(bem_direito['name'], round(bem_direito['value'], 2), round(bem_direito['quantity'], 2)))
            
            if is_debug:
                pp.pprint(bem_direito)

        print("**************************")


main()
