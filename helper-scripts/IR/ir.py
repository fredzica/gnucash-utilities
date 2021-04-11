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


def retrieve_usdbrl_quote(aux_yaml_path, day):
    with open(aux_yaml_path, 'r') as yaml_file:
        yaml_content = yaml.full_load(yaml_file)
        print(yaml_content)

        usdbrl_quotes = yaml_content['usdbrl']
        print(usdbrl_quotes)
        
        try:
            day_quote = usdbrl_quotes[day]
            return Decimal(day_quote)
        except KeyError:
            print("What is the USDBRL quote for {}?".format(day))
            quote = Decimal(input())

            usdbrl_quotes[day] = quote
            yaml_content.items()['usdbrl'] = usdbrl_quotes
            yaml.dump(yaml_content, yaml_file)



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
        for split in stock_account.splits:
            if split.transaction.post_date <= date_filter:
                quantity += Decimal(split.quantity)
                value += Decimal(split.value)

                if split.value > 0:
                    day_usdbrl = retrieve_usdbrl_quote(aux_yaml_path, '11-04-2021')
                    dollar_value_purchases += Decimal(split.value)
                    real_value_purchases += (day_usdbrl * Decimal(split.value))
                    quantity_purchases += Decimal(split.quantity)
                    dollar_price_avg = dollar_value_purchases/quantity_purchases
                    real_price_avg = real_value_purchases/quantity_purchases


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
                    'quantity_purchases': quantity_purchases
            })

    return stocks



def main():
    pp = pprint.PrettyPrinter(indent=2)

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
        for bem_direito in bens_direitos:
            print('ticker: {}, valor: {}, quantidade: {}'.format(bem_direito['name'], round(bem_direito['value'], 2), round(bem_direito['quantity'], 2)))
            
            if is_debug:
                pp.pprint(bem_direito)

        stocks = collect_bens_direitos_stocks(book, aux_yaml_path, maximum_date_filter)
        for stock in stocks:
            print('ticker: {}, valor_dollar: {}, valor_real: {}, quantidade: {}'.format(stock['name'], round(stock['dollar_value'], 2), round(stock['real_value'], 2), round(stock['quantity'], 2)))
            
            if is_debug:
                pp.pprint(stock)
        print("**************************")


main()
