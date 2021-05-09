import sys
import os
import csv
import re
import pprint

import yaml

from decimal import *
from datetime import date
from piecash import open_book, ledger, factories, Account, Transaction, Commodity, Split, GnucashException


def collect_bens_direitos_brasil(book, date_filter):
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
        for split in sorted(acao_account.splits, key=lambda x: x.transaction.post_date):
            if split.transaction.post_date <= date_filter:
                quantity += Decimal(split.quantity)

                if split.value > 0:
                    value_purchases += Decimal(split.value)
                    quantity_purchases += Decimal(split.quantity)
                    price_avg = value_purchases/quantity_purchases

                    # avg should go back to zero if everything was sold at some point
                    if quantity == 0:
                        price_avg = Decimal(0)
                        value_purchases = Decimal(0)
                        quantity_purchases = Decimal(0)

        if quantity > 0:
            acoes.append({
                    'name': acao_account.name,
                    'quantity': quantity,
                    'value': price_avg * quantity,
                    'price_avg': price_avg,
                    'value_purchases': value_purchases,
                    'quantity_purchases': quantity_purchases
            })

        elif quantity < 0:
            raise Exception("The stock {} has a negative quantity {}!".format(acao_account.name, quantity))

    return acoes


def retrieve_usdbrl_quote(aux_yaml_path, day):
    with open(aux_yaml_path, 'r') as yaml_file:

        # yaml with Decimal objects can only be loaded with unsafe_load
        yaml_content = yaml.unsafe_load(yaml_file)

        if yaml_content is None or not 'usdbrl' in yaml_content or yaml_content['usdbrl'] is None:
            print('yaml is currently empty')
            yaml_content = {'usdbrl': {}}

        usdbrl_quotes = yaml_content['usdbrl']
        
        try:
            day_quote = usdbrl_quotes[day]
            return Decimal(day_quote)
        except KeyError:
            print("What is the USDBRL quote for {}?".format(day))
            quote = Decimal(input())

            usdbrl_quotes[day] = quote
            yaml_content['usdbrl'].update(usdbrl_quotes)
 
            with open(aux_yaml_path, 'w') as yaml_file_write:
                yaml.dump(yaml_content, yaml_file_write)

            return quote


def collect_bens_direitos_stocks(book, aux_yaml_path, date_filter):
    stocks_account = book.accounts(name='Ações no exterior')
    children = stocks_account.children

    stocks = []
    for stock_account in children:
        quantity = Decimal(0)
        value = Decimal(0)

        dollar_price_avg = Decimal(0)
        real_price_avg = Decimal(0)
        dollar_value_purchases = Decimal(0)
        real_value_purchases = Decimal(0)
        quantity_purchases = Decimal(0)
        for split in sorted(stock_account.splits, key=lambda x: x.transaction.post_date):
            if split.transaction.post_date <= date_filter:
                quantity += Decimal(split.quantity)

                if split.value > 0:
                    format = "%d-%m-%Y"
                    day = split.transaction.post_date.strftime(format)

                    day_usdbrl = retrieve_usdbrl_quote(aux_yaml_path, day)

                    dollar_value_purchases += Decimal(split.value)
                    real_value_purchases += (day_usdbrl * Decimal(split.value))
                    quantity_purchases += Decimal(split.quantity)
                    dollar_price_avg = dollar_value_purchases/quantity_purchases
                    real_price_avg = real_value_purchases/quantity_purchases

                    # avg should go back to zero if everything was sold at some point
                    if quantity == 0:
                        dollar_price_avg = Decimal(0)
                        real_price_avg = Decimal(0)
                        dollar_value_purchases = Decimal(0)
                        real_value_purchases = Decimal(0)
                        quantity_purchases = Decimal(0)

        if quantity > 0:
            stocks.append({
                    'name': stock_account.name,
                    'quantity': quantity,
                    'dollar_value': dollar_price_avg * quantity,
                    'real_value': real_price_avg * quantity,
                    'dollar_price_avg': dollar_price_avg,
                    'real_price_avg': real_price_avg,
                    'dollar_value_purchases': dollar_value_purchases,
                    'real_value_purchases': real_value_purchases,
                    'quantity_purchases': quantity_purchases,
                    'usdbrl_quote': day_usdbrl
            })
        elif quantity < 0:
            raise Exception("The stock {} has a negative quantity {}!".format(acao_account.name, quantity))

    return stocks



def main():
    pp = pprint.PrettyPrinter(indent=2)

    if len(sys.argv) < 4:
        print('Wrong number of arguments!')
        print('Usage: ir.py gnucash_db_path aux_yaml_path year_filter is_debug (optional, default false)')
        return

    gnucash_db_path = sys.argv[1]
    aux_yaml_path = sys.argv[2]
    year_filter = sys.argv[3]

    is_debug = False
    if len(sys.argv) > 4:
        is_debug = bool(sys.argv[4])

    maximum_date_filter = date(int(year_filter), 12, 31)

    with open_book(gnucash_db_path, readonly=True, do_backup=False, open_if_lock=True) as book:
        print('retrieving data before or equal than {}'.format(maximum_date_filter))

        print("************* Bens e direitos *************")
        bens_direitos = collect_bens_direitos_brasil(book, maximum_date_filter)
        for bem_direito in sorted(bens_direitos, key=lambda x: x['name']):
            print('ticker: {}, valor: {}, quantidade: {}'.format(bem_direito['name'], round(bem_direito['value'], 2), round(bem_direito['quantity'], 2)))
            
            if is_debug:
                pp.pprint(bem_direito)

        stocks = collect_bens_direitos_stocks(book, aux_yaml_path, maximum_date_filter)
        for stock in sorted(stocks, key=lambda x: x['name']):
            print('ticker: {}, valor_dollar: {}, valor_real: {}, quantidade: {}'.format(stock['name'], round(stock['dollar_value'], 2), round(stock['real_value'], 2), round(stock['quantity'], 2)))
            
            if is_debug:
                pp.pprint(stock)
        print("**************************")


main()
