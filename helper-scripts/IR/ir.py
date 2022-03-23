import sys
import os
import re
import pprint

import csv
import json

from decimal import *
from datetime import date
from piecash import open_book

pp = pprint.PrettyPrinter(indent=2)


def extract_metadata(account):
    try:
        metadata = json.loads(account.description)
    except:
        raise Exception("Metadata JSON could not be read for {}".format(account.name))

    if metadata is None or not 'type' in metadata:
        raise Exception("The type field not found for {}".format(account.name))

    if metadata['type'] not in ['etf', 'acao', 'bdr', 'fii', 'us stock', 'us etf', 'reit', 'btc', 'crypto']:
        raise Exception("The type for {} is not valid".format(account.name))

    ir_group_dict = {'etf': 7, 'us etf': 7, 'fii': 7, 'acao': 3, 'bdr': 4, 'us stock': 3, 'reit': 3, 'btc': 8, 'crypto': 8}
    metadata['grupo_bem_direito'] = ir_group_dict[metadata['type']]

    ir_code_dict = {'etf': 9, 'us etf': 9, 'fii': 3, 'acao': 1, 'bdr': 4, 'us stock': 1, 'reit': 1, 'btc': 1, 'crypto': 2}
    metadata['codigo_bem_direito'] = ir_code_dict[metadata['type']]

    return metadata


def extract_sales_info(sales):
    acoes_aggregated_profits = Decimal(0)
    acoes_sales_value = Decimal(0)
    sales_info = {
            'aggregated': {
                'us': {
                    'aggregated_profits': Decimal(0)
                    },
                'acoes': {
                    'aggregated_profits': Decimal(0),
                    'dedo_duro': Decimal(0)
                    }
                },
            'monthly': {
                'fiis': {},
                'acoes+etfs': {}
                },
            'debug': {}
            }

    for i in range(1, 13):
        sales_info['monthly']['acoes+etfs'][i] = {'aggregated_results': Decimal(0), 'total_sales': Decimal(0), 'dedo_duro': Decimal(0)}
        sales_info['monthly']['fiis'][i] = {'aggregated_results': Decimal(0), 'total_sales': Decimal(0), 'dedo_duro': Decimal(0)}

    for sale in sales:
        if sale['type'] == 'acao' and sale['is_profit']:
            acoes_sales_value += -sale['value']
            acoes_aggregated_profits += sale['profit']

        # TODO: unificar blocos abaixo?
        elif sale['type'] == 'etf' or sale['type'] == 'acao' and not sale['is_profit']:
            month = sale['date'].month
            current = sales_info['monthly']['acoes+etfs'][month]

            current['aggregated_results'] += sale['profit']
            current['total_sales'] += -sale['value']
            current['dedo_duro'] += -sale['value'] * Decimal(0.00005)

            sales_info['monthly']['acoes+etfs'][month] = current
        elif sale['type'] == 'fii':
            month = sale['date'].month
            current = sales_info['monthly']['fiis'][month]

            current['aggregated_results'] += sale['profit']
            current['total_sales'] += -sale['value']
            current['dedo_duro'] += -sale['value'] * Decimal(0.00005)

            sales_info['monthly']['fiis'][month] = current


    acoes_dedo_duro = acoes_sales_value * Decimal(0.00005)
    acoes_aggregated_profits -= acoes_dedo_duro

    sales_info['aggregated']['acoes']['aggregated_profits'] = acoes_aggregated_profits
    sales_info['aggregated']['acoes']['dedo_duro'] = acoes_dedo_duro
    sales_info['debug']['acoes_sales_value'] = acoes_sales_value
    return sales_info


def collect_crypto(book, date_filter):
    cryptos_account = book.accounts(name='Crypto')
    children = cryptos_account.children

    crypto = []
    for crypto_account in children:
        quantity = Decimal(0)
        value = Decimal(0)

        price_avg = Decimal(0)
        value_purchases = Decimal(0)
        quantity_purchases = Decimal(0)
        for split in sorted(crypto_account.splits, key=lambda x: x.transaction.post_date):
            if split.transaction.post_date <= date_filter:

                quantity += Decimal(split.quantity)
                transaction_date = split.transaction.post_date

                if split.value > 0:
                    value_purchases += Decimal(split.value)
                    quantity_purchases += Decimal(split.quantity)
                    price_avg = value_purchases/quantity_purchases

                # avg should go back to zero if everything was sold at some point
                sold_all = quantity == 0
                if sold_all:
                    price_avg = Decimal(0)
                    value_purchases = Decimal(0)
                    quantity_purchases = Decimal(0)

        if quantity > 0:
            metadata = extract_metadata(crypto_account)

            crypto.append({
                    'name': crypto_account.name,
                    'quantity': quantity,
                    'value': price_avg * quantity,
                    'price_avg': price_avg,
                    'value_purchases': value_purchases,
                    'quantity_purchases': quantity_purchases,
                    'last_transaction_date': transaction_date,
                    'metadata': metadata
            })

        elif quantity < 0:
            raise Exception("The stock {} has a negative quantity {}!".format(crypto_account.name, quantity))

    return crypto


def collect_bens_direitos_brasil(book, date_filter, minimum_date):
    acoes_account = book.accounts(name='Ações')
    fiis_account = book.accounts(name='FIIs')
    children = acoes_account.children + fiis_account.children

    sales = []
    acoes = []
    held_during_filtered_period = set()
    for acao_account in children:

        quantity = Decimal(0)
        value = Decimal(0)

        price_avg = Decimal(0)
        value_purchases = Decimal(0)
        quantity_purchases = Decimal(0)
        for split in sorted(acao_account.splits, key=lambda x: x.transaction.post_date):
            if split.transaction.post_date <= date_filter:
                held_during_filtered_period.add(acao_account.name)

                quantity += Decimal(split.quantity)
                transaction_date = split.transaction.post_date

                if split.value > 0:
                    value_purchases += Decimal(split.value)
                    quantity_purchases += Decimal(split.quantity)
                    price_avg = value_purchases/quantity_purchases
                elif split.value < 0 and split.transaction.post_date >= minimum_date:
                    is_transfer_split = split.quantity == 0
                    if is_transfer_split:
                        value_purchases += Decimal(split.value)
                        price_avg = value_purchases/quantity_purchases
                    else:
                        sold_price = split.value/split.quantity
                        is_profit = sold_price > price_avg
                        positive_quantity = -split.quantity
                        profit = sold_price * positive_quantity - price_avg * positive_quantity

                        sales.append({
                            'name': acao_account.name,
                            'type': extract_metadata(acao_account)['type'],
                            'date': split.transaction.post_date,
                            'sold_price': sold_price,
                            'quantity': split.quantity,
                            'value': split.value,
                            'price_avg': price_avg,
                            'is_profit': is_profit,
                            'profit': profit
                        })

                # avg should go back to zero if everything was sold at some point
                sold_all = quantity == 0
                if sold_all:
                    price_avg = Decimal(0)
                    value_purchases = Decimal(0)
                    quantity_purchases = Decimal(0)

                    sold_before_period_start = split.transaction.post_date <= minimum_date
                    if sold_before_period_start:
                        held_during_filtered_period.remove(acao_account.name)


        if quantity > 0:
            metadata = extract_metadata(acao_account)

            acoes.append({
                    'name': acao_account.name,
                    'quantity': quantity,
                    'value': price_avg * quantity,
                    'price_avg': price_avg,
                    'value_purchases': value_purchases,
                    'quantity_purchases': quantity_purchases,
                    'last_transaction_date': transaction_date,
                    'metadata': metadata
            })

        elif quantity < 0:
            raise Exception("The stock {} has a negative quantity {}!".format(acao_account.name, quantity))

    return acoes, sales, held_during_filtered_period


def collect_bens_direitos_stocks(book, quotes_by_date, date_filter):
    stocks_account = book.accounts(name='Ações no exterior')
    children = stocks_account.children

    stocks = []
    for stock_account in children:
        quantity = Decimal(0)

        dollar_price_avg = Decimal(0)
        real_price_avg = Decimal(0)
        dollar_value_purchases = Decimal(0)
        real_value_purchases = Decimal(0)
        quantity_purchases = Decimal(0)
        for split in sorted(stock_account.splits, key=lambda x: x.transaction.post_date):
            if split.transaction.post_date <= date_filter:
                quantity += Decimal(split.quantity)
                transaction_date = split.transaction.post_date

                # avg should go back to zero if everything was sold at some point
                if quantity == 0:
                    dollar_price_avg = Decimal(0)
                    real_price_avg = Decimal(0)
                    dollar_value_purchases = Decimal(0)
                    real_value_purchases = Decimal(0)
                    quantity_purchases = Decimal(0)

                if split.value > 0:
                    format = "%d%m%Y"
                    date = split.transaction.post_date.strftime(format)

                    day_usdbrl = quotes_by_date[date]['ask']

                    dollar_value_purchases += Decimal(split.value)
                    real_value_purchases += (day_usdbrl * Decimal(split.value))
                    quantity_purchases += Decimal(split.quantity)
                    dollar_price_avg = dollar_value_purchases/quantity_purchases
                    real_price_avg = real_value_purchases/quantity_purchases

        if quantity > 0:
            metadata = extract_metadata(stock_account)

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
                    'last_usdbrl_quote': day_usdbrl,
                    'last_transaction_date': transaction_date,
                    'metadata': metadata
            })
        elif quantity < 0:
            raise Exception("The stock {} has a negative quantity {}!".format(acao_account.name, quantity))

    return stocks

def collect_proventos(book, minimum_date, maximum_date):
    dividendos = book.accounts(name='Dividendos').children
    jcp = book.accounts(name='JCP').children

    proventos = {}
    for provento_account in dividendos + jcp:
        name = provento_account.name
        if name not in proventos:
            acao_account = book.accounts(name='Ações').children(name=name)
            metadata = extract_metadata(acao_account)
            proventos[name] = {'fonte_pagadora': metadata['cnpj'], 'long_name': metadata['long_name'],'Dividendos': Decimal(0), 'JCP': Decimal(0)}

        for split in provento_account.splits:
            if split.transaction.post_date >= minimum_date and split.transaction.post_date <= maximum_date:
                provento_type = provento_account.parent.name
                proventos[name][provento_type] += -split.value

    return proventos


def collect_proventos_fiis(book, minimum_date, maximum_date):
    rendimentos = book.accounts(name='Receita de FIIs').children

    proventos = {}
    for provento_account in rendimentos:
        name = provento_account.name
        metadata = json.loads(provento_account.description)
        fonte_pagadora = metadata['fonte_pagadora']
        if fonte_pagadora not in proventos:
            proventos[fonte_pagadora] = {'fiis': [], 'long_name': metadata['long_name'], 'proventos': Decimal(0)}

        value_sum = Decimal(0)
        for split in provento_account.splits:
            if split.transaction.post_date >= minimum_date and split.transaction.post_date <= maximum_date:
                value_sum += -split.value

        if value_sum != 0:
            proventos[fonte_pagadora]['proventos'] += value_sum
            proventos[fonte_pagadora]['fiis'].append(name)

    return proventos


def collect_us_dividends(book, minimum_date, maximum_date):
    monthly_dividends = {}
    for dividend_account in book.accounts(name='US Dividends').children:
        for split in dividend_account.splits:
            if split.transaction.post_date >= minimum_date and split.transaction.post_date <= maximum_date:
                month = split.transaction.post_date.month

                if month not in monthly_dividends:
                    monthly_dividends[month] = Decimal(0)

                monthly_dividends[month] += -split.value

    return monthly_dividends


def retrieve_usdbrl_quotes(quotes_csv_path):
    quotes_by_date = {}

    with open(quotes_csv_path,  newline='') as csv_file:
        reader = csv.DictReader(csv_file, delimiter = ';')
        for row in reader:
            date = row['data']
            bid = row['compra']
            ask = row['venda']

            quotes_by_date[date] = {'bid': Decimal(bid.replace(',', '.')), 'ask': Decimal(ask.replace(',', '.'))}

    return quotes_by_date


def main():
    if len(sys.argv) < 4:
        print('Wrong number of arguments!')
        print('Usage: ir.py gnucash_db_path quotes_csv_path year_filter is_debug (optional, default false)')
        return

    gnucash_db_path = sys.argv[1]
    quotes_csv_path = sys.argv[2]
    year_filter = sys.argv[3]

    quotes_by_date = retrieve_usdbrl_quotes(quotes_csv_path)

    is_debug = False
    if len(sys.argv) > 4:
        is_debug = bool(sys.argv[4])

    maximum_date_filter = date(int(year_filter), 12, 31)
    minimum_date_filter = date(int(year_filter), 1, 1)

    with open_book(gnucash_db_path, readonly=True, do_backup=False, open_if_lock=True) as book:
        print('retrieving data before or equal than {}'.format(maximum_date_filter))

        bens_direitos, all_sales, need_additional_data = collect_bens_direitos_brasil(book, maximum_date_filter, minimum_date_filter)
        print("************* Bens e direitos *************")
        for bem_direito in sorted(bens_direitos, key=lambda x: (x['metadata']['grupo_bem_direito'], x['metadata']['codigo_bem_direito'], x['name'])):
            metadata = bem_direito['metadata']

            print(bem_direito['name'])
            print("Grupo:", metadata['grupo_bem_direito'])
            print("Código:", metadata['codigo_bem_direito'])
            print("CNPJ:", metadata['cnpj'])
            print("Discriminação: {} {} - CORRETORA INTER DTVM".format(round(bem_direito['quantity'], 0), bem_direito['name']))
            print("Situação R$:", round(bem_direito['value'], 2))
            print("***")
            
            if is_debug:
                pp.pprint(bem_direito)

        stocks = collect_bens_direitos_stocks(book, quotes_by_date, maximum_date_filter)
        types = {'us etf': 'ETF', 'us stock': 'Ação', 'reit': 'REIT'}
        for stock in sorted(stocks, key=lambda x: (x['metadata']['grupo_bem_direito'], x['metadata']['codigo_bem_direito'], x['name'])):
            metadata = stock['metadata']

            type_description = types[metadata['type']]

            print(stock['name'])
            print("Grupo:", metadata['grupo_bem_direito'])
            print("Código:", metadata['codigo_bem_direito'])
            print("Localização: EUA")
            print("Discriminação: {} {} {}. Código de negociação {}. Valor total de aquisição US$ {}. Moeda originariamente nacional. Corretora Charles Schwab.".format(round(stock['quantity'], 0), type_description, metadata['long_name'], stock['name'], round(stock['dollar_value'], 2)))
            print("Situação R$:", round(stock['real_value'], 2))
            print("***")

            if is_debug:
                pp.pprint(stock)

        cryptos = collect_crypto(book, maximum_date_filter)
        for crypto in cryptos:
            metadata = crypto['metadata']

            print(crypto['name'])
            print("Grupo:", metadata['grupo_bem_direito'])
            print("Código:", metadata['codigo_bem_direito'])
            print("Discriminação: {} {} - {}".format(crypto['quantity'], crypto['name'], metadata['long_name']))
            print("Situação R$:", round(crypto['value'], 2))
            print("***")

            if is_debug:
                pp.pprint(crypto)

        print("**************************")
        print()
        print()

        sales_info = extract_sales_info(all_sales)
        if is_debug:
            pp.pprint(sales_info)
            pp.pprint(all_sales)

        print("************* RV Agregado (exclui ETFs e FIIs) *************")
        print("A ser declarado em Rendimentos Isentos e Não tributáveis")
        acoes_aggregated_profit = sales_info['aggregated']['acoes']['aggregated_profits']
        acoes_dedo_duro = sales_info['aggregated']['acoes']['dedo_duro']
        print("20 - Ganhos líquidos em operações no mercado à vista de ações: ", round(acoes_aggregated_profit, 2))
        print("Imposto Pago/Retido (Imposto Pago/Retido na linha 03) (dedo-duro): ", round(acoes_dedo_duro, 2))
       
        print("**************************")

        print("************* RV mês a mês *************")
        print("Operações comuns/Day-trade - Mercado à vista")
        print("Venda de ações com prejuízo, vendas em mês com mais de 20k ou vendas de ETFs")
        for key in sales_info['monthly']['acoes+etfs'].keys():
            resultado = sales_info['monthly']['acoes+etfs'][key]['aggregated_results']
            ir_fonte = sales_info['monthly']['acoes+etfs'][key]['dedo_duro']

            if resultado != 0:
                print("Mês:", key)
                print("    Resultado", round(resultado, 2))
                print("    IR Fonte", round(ir_fonte, 2))

        if is_debug:
            pp.pprint(sales_info['monthly']['acoes+etfs'])

        print("***")
        print("Operações FIIs")
        for key in sales_info['monthly']['fiis'].keys():
            resultado = sales_info['monthly']['fiis'][key]['aggregated_results']
            ir_fonte = sales_info['monthly']['fiis'][key]['dedo_duro']

            if resultado != 0:
                print("Mês:", key)
                print("    Resultado", round(resultado, 2))
                print("    IR Fonte", round(ir_fonte, 2))

        if is_debug:
            pp.pprint(sales_info['monthly']['fiis'])

        print("**************************")


        print("************* Rendimentos *************")
        proventos = collect_proventos(book, minimum_date_filter, maximum_date_filter)
        print("JCP: Rendimentos Sujeitos à Tributação Exclusiva/Definitiva, código 10")
        for key in proventos:
            provento = proventos[key]
            if provento['JCP'] != 0: 
                need_additional_data.add(key)

                print(key)
                print("Fonte pagadora:", provento['fonte_pagadora'])
                print("Nome da fonte pagadora:", provento['long_name'])
                print("JCP:", provento['JCP'])
                print("***")

        print("******")
        print("Dividendos: Rendimentos Isentos e Não tributáveis, código 9")
        for key in proventos:

            provento = proventos[key]
            if provento['Dividendos'] != 0: 
                need_additional_data.add(key)

                print(key)
                print("Fonte pagadora:", provento['fonte_pagadora'])
                print("Nome da fonte pagadora:", provento['long_name'])
                print("Dividendos:", provento['Dividendos'])
                print("***")

        if is_debug:
            pp.pprint(proventos)
        print("******")
        print("Dividendos no exterior")
        us_dividends = collect_us_dividends(book, minimum_date_filter, maximum_date_filter)
        
        pp.pprint(us_dividends)
        if is_debug:
            pp.pprint(us_dividends)
        print("******")
        print("Rendimentos de FIIs")
        proventos_fiis = collect_proventos_fiis(book, minimum_date_filter, maximum_date_filter)
        for key in proventos_fiis:

            provento = proventos_fiis[key]
            if provento['proventos'] != 0: 
                need_additional_data.update(provento['fiis'])

                print(key)
                print(provento['fiis'])
                print("Nome da fonte pagadora:", provento['long_name'])
                print("Rendimento:", provento['proventos'])
                print("***")

        print("**************************")

        print("******* Papéis que estiveram na carteira ou que receberam proventos durante {} ******".format(year_filter))
        print("(Para saber quais informes devem ser coletados)")
        for papel in need_additional_data:
            print(papel)
        print("**************************")


main()
