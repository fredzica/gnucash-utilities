import sys
import os
import csv
import re
import pprint
from decimal import *
from datetime import date
from piecash import open_book, ledger, factories, Account, Transaction, Commodity, Split, GnucashException


gnucash_db_path = sys.argv[1]
year_filter = sys.argv[2]

is_debug = False
if len(sys.argv) > 3:
    is_debug = bool(sys.argv[3])


def collect_acoes(date_filter):
    with open_book(gnucash_db_path, readonly=True, do_backup=False, open_if_lock=True) as book:
        acoes_account = book.accounts(name='Ações')

        acoes = []
        for acao_account in acoes_account.children:

            quantity = Decimal(0)
            value = Decimal(0)

            price_avg = Decimal(0)
            value_purchases = Decimal(0)
            quantity_purchases = Decimal(0)
            for split in acao_account.splits:
                if split.transaction.post_date <= date_filter:
                    quantity += Decimal(split.quantity)
                    value += Decimal(split.value)

                if split.value > 0 and split.transaction.post_date <= date_filter:
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
    maximum_date_filter = date(int(year_filter), 12, 31)
    pp = pprint.PrettyPrinter(indent=2)

    print('retrieving data before or equal than {}'.format(maximum_date_filter))

    print("************* ações *************")
    acoes = collect_acoes(maximum_date_filter)
    for acao in acoes:
        print('acao: {}, valor: {}, quantidade: {}'.format(acao['name'], round(acao['value'], 2), round(acao['quantity'], 2)))
        
        if is_debug:
            pp.pprint(acao)

    print("**************************")

main()
