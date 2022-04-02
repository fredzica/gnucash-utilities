import sys
import pprint

import csv
import json

from decimal import Decimal
from datetime import date
from piecash import open_book, ledger

pp = pprint.PrettyPrinter(indent=2)

DEDO_DURO_MULTIPLIER = Decimal(0.00005)
ACOES_ETF_TAX_MULTIPLIER = Decimal(0.15)
FII_TAX_MULTIPLIER = Decimal(0.20)
US_DIVIDEND_TAX_MULTIPLIER = Decimal(0.30)
TAX_EXEMPT_SALE_FOREIGN_LIMIT = 35000
TAX_EXEMPT_SALE_DOMESTIC_LIMIT = 20000


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


def is_us_sale(sale):
    return sale['type'] in ['us stock', 'us etf', 'reit']


def is_br_acao_sale(sale):
    return sale['type'] in ['acao', 'etf']


def extract_sales_info(sales):
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
                'acoes+etfs': {},
                'us': {}
                }
    }

    for i in range(1, 13):
        sales_info['monthly']['acoes+etfs'][i] = {'aggregated_profits': Decimal(0), 'total_sales': Decimal(0), 'dedo_duro': Decimal(0)}
        sales_info['monthly']['us'][i] = {'aggregated_profits': Decimal(0), 'total_sales': Decimal(0)}
        sales_info['monthly']['fiis'][i] = {'aggregated_profits': Decimal(0), 'total_sales': Decimal(0), 'dedo_duro': Decimal(0)}

    # calculating the total monthly sales
    for sale in sales:
        if is_br_acao_sale(sale):
            month = sale['date'].month
            sales_info['monthly']['acoes+etfs'][month]['total_sales'] += -sale['value']
        elif is_us_sale(sale):
            month = sale['date'].month
            sales_info['monthly']['us'][month]['total_sales'] += -sale['value']

    # calculating the rest
    acoes_aggregated_profits = Decimal(0)
    acoes_sales_value = Decimal(0)
    us_sales_value = Decimal(0)
    us_aggregated_profits = Decimal(0)
    for sale in sales:
        month = sale['date'].month

        if is_us_sale(sale):
            current_us = sales_info['monthly']['us'][month]
            has_surpassed_limit = current_us['total_sales'] >= TAX_EXEMPT_SALE_FOREIGN_LIMIT
            if has_surpassed_limit:
                print("Limite de 35000 de vendas foi ultrapassado no mês {}. Valores para este mês não entram no cálculo e um eventual imposto deve ser pago através do GCAP".format(month))
            else:
                current_us['aggregated_profits'] += sale['profit']
                us_sales_value += -sale['value']
                us_aggregated_profits += sale['profit']
        else:
            current_acoes_etf = sales_info['monthly']['acoes+etfs'][month]
            has_surpassed_limit = current_acoes_etf['total_sales'] >= TAX_EXEMPT_SALE_DOMESTIC_LIMIT

            if sale['type'] == 'etf' or sale['type'] == 'acao' and (has_surpassed_limit or not sale['is_profit']):
                current_acoes_etf['aggregated_profits'] += sale['profit']
                current_acoes_etf['dedo_duro'] += -sale['value'] * DEDO_DURO_MULTIPLIER
            elif sale['type'] == 'acao' and sale['is_profit']:
                acoes_sales_value += -sale['value']
                acoes_aggregated_profits += sale['profit']
            elif sale['type'] == 'fii':
                current = sales_info['monthly']['fiis'][month]

                current['aggregated_profits'] += sale['profit']
                current['dedo_duro'] += -sale['value'] * DEDO_DURO_MULTIPLIER
                current['total_sales'] += -sale['value']
            else:
                raise Exception("Unexpected flow", sale)

    acoes_dedo_duro = acoes_sales_value * DEDO_DURO_MULTIPLIER
    acoes_aggregated_profits -= acoes_dedo_duro

    sales_info['aggregated']['us']['aggregated_profits'] = us_aggregated_profits
    sales_info['aggregated']['us']['sales_value'] = us_sales_value

    sales_info['aggregated']['acoes']['aggregated_profits'] = acoes_aggregated_profits
    sales_info['aggregated']['acoes']['acoes_sales_value'] = acoes_sales_value
    sales_info['aggregated']['acoes']['dedo_duro'] = acoes_dedo_duro

    return sales_info


def sorted_splits_by_date(account):
    return sorted(account.splits, key=lambda x: x.transaction.post_date)


def collect_bens_direitos(children, date_filter, minimum_date = None):
    sales = []
    bens = []
    held_during_filtered_period = set()
    for account in children:

        quantity = Decimal(0)
        price_avg = Decimal(0)
        value_purchases = Decimal(0)
        quantity_purchases = Decimal(0)
        transaction_date = None
        for split in sorted_splits_by_date(account):
            if split.transaction.post_date <= date_filter:
                held_during_filtered_period.add(account.name)

                quantity += Decimal(split.quantity)
                transaction_date = split.transaction.post_date

                is_stock_split = split.value == 0 and split.action == 'Split'
                if split.value > 0 or is_stock_split:
                    value_purchases += Decimal(split.value)
                    quantity_purchases += Decimal(split.quantity)
                    price_avg = value_purchases/quantity_purchases
                elif minimum_date is not None:
                    if split.value < 0 and split.transaction.post_date >= minimum_date:
                        is_transfer = split.quantity == 0
                        if is_transfer:
                            value_purchases += Decimal(split.value)
                            price_avg = value_purchases/quantity_purchases
                        else:
                            sold_price = split.value/split.quantity
                            is_profit = sold_price > price_avg
                            positive_quantity = -split.quantity
                            profit = sold_price * positive_quantity - price_avg * positive_quantity

                            sales.append({
                                'name': account.name,
                                'type': extract_metadata(account)['type'],
                                'date': split.transaction.post_date,
                                'sold_price': sold_price,
                                'quantity': split.quantity,
                                'value': split.value,
                                'price_avg': price_avg,
                                'is_profit': is_profit,
                                'profit': profit
                            })
                    elif split.transaction.post_date >= minimum_date:
                        raise Exception("Split wasn't recognized", account.name, split.transaction.post_date)

                # avg should go back to zero if everything was sold at some point
                sold_all = quantity == 0
                if sold_all:
                    price_avg = Decimal(0)
                    value_purchases = Decimal(0)
                    quantity_purchases = Decimal(0)

                    sold_before_period_start = split.transaction.post_date <= minimum_date
                    if sold_before_period_start:
                        held_during_filtered_period.remove(account.name)


        if quantity > 0:
            metadata = extract_metadata(account)

            bens.append({
                    'name': account.name,
                    'quantity': quantity,
                    'value': price_avg * quantity,
                    'price_avg': price_avg,
                    'value_purchases': value_purchases,
                    'quantity_purchases': quantity_purchases,
                    'last_transaction_date': transaction_date,
                    'metadata': metadata
            })

        elif quantity < 0:
            raise Exception("The stock {} has a negative quantity {}!".format(account.name, quantity))

    return bens, sales, held_during_filtered_period


def collect_crypto(book, date_filter):
    cryptos_account = book.accounts(name='Crypto')
    children = cryptos_account.children

    crypto, _, _ = collect_bens_direitos(children, date_filter)
    return crypto


def collect_bens_direitos_brasil(book, date_filter, minimum_date):
    acoes_account = book.accounts(name='Ações')
    fiis_account = book.accounts(name='FIIs')
    children = acoes_account.children + fiis_account.children

    return collect_bens_direitos(children, date_filter, minimum_date)


def collect_bens_direitos_stocks(book, quotes_by_date, date_filter, minimum_date):
    stocks_account = book.accounts(name='Ações no exterior')
    children = stocks_account.children

    stocks = []
    sales = []
    for stock_account in children:
        quantity = Decimal(0)

        dollar_price_avg = Decimal(0)
        real_price_avg = Decimal(0)
        dollar_value_purchases = Decimal(0)
        real_value_purchases = Decimal(0)
        quantity_purchases = Decimal(0)
        transaction_date = None
        for split in sorted_splits_by_date(stock_account):
            if split.transaction.post_date <= date_filter:
                quantity += Decimal(split.quantity)
                transaction_date = split.transaction.post_date

                is_stock_split = split.value == 0 and split.action == 'Split'
                format = "%d%m%Y"
                date = split.transaction.post_date.strftime(format)
                if split.value > 0 or is_stock_split:
                    day_ask_usdbrl = quotes_by_date[date]['ask']

                    dollar_value_purchases += Decimal(split.value)
                    real_value_purchases += (day_ask_usdbrl * Decimal(split.value))
                    quantity_purchases += Decimal(split.quantity)
                    dollar_price_avg = dollar_value_purchases/quantity_purchases
                    real_price_avg = real_value_purchases/quantity_purchases
                elif split.value < 0 and split.transaction.post_date >= minimum_date:
                    day_bid_usdbrl = quotes_by_date[date]['bid']

                    sold_price_usd = split.value/split.quantity
                    sold_price_brl = day_bid_usdbrl * sold_price_usd
                    is_profit = sold_price_brl > real_price_avg

                    positive_quantity = -split.quantity
                    profit = sold_price_brl * positive_quantity - real_price_avg * positive_quantity

                    value_brl = sold_price_brl * split.quantity

                    sales.append({
                        'name': stock_account.name,
                        'type': extract_metadata(stock_account)['type'],
                        'date': split.transaction.post_date,
                        'sold_price': sold_price_brl,
                        'dollar_sold_price': sold_price_usd,
                        'quantity': split.quantity,
                        'dollar_value': split.value,
                        'value': value_brl,
                        'price_avg': real_price_avg,
                        'dollar_price_avg': dollar_price_avg,
                        'is_profit': is_profit,
                        'profit': profit
                    })
                elif split.transaction.post_date >= minimum_date:
                    raise Exception("Split wasn't recognized", stock_account.name, split.transaction.post_date)

                # avg should go back to zero if everything was sold at some point
                if quantity == 0:
                    dollar_price_avg = Decimal(0)
                    real_price_avg = Decimal(0)
                    dollar_value_purchases = Decimal(0)
                    real_value_purchases = Decimal(0)
                    quantity_purchases = Decimal(0)

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
                    'last_transaction_date': transaction_date,
                    'metadata': metadata
            })
        elif quantity < 0:
            raise Exception("The stock {} has a negative quantity {}!".format(stock_account.name, quantity))

    return sales, stocks


def get_closest_available_quote(upper_limit_day, month, year, quotes_by_date):
    day = upper_limit_day
    while day > 0:
        try:
            date = "{:>02}{:>02}{}".format(day, month, year)
            return quotes_by_date[date]['bid']
        except KeyError:
            day -= 1

    raise Exception("Unexpected state: quote not found", day, month, year)


def get_us_dividend_usdbrl_quotes(quotes_by_date, year):
    quotes_by_month = {}
    for month in range(1, 13):
        # retrieves the last available usdbrl quote from the first half of the previous month
        found_year = year
        previous_month = month - 1
        if month == 1:
            found_year = year - 1
            previous_month =  12

        quotes_by_month[month] = get_closest_available_quote(15, previous_month, found_year, quotes_by_date)

    return quotes_by_month


def get_year_last_usdbrl_bid_quote(quotes_by_date, year):
    return get_closest_available_quote(31, 12, year, quotes_by_date)


def collect_brokerage_account_balance(book, maximum_date, quotes_by_date, year_filter):
    account = book.accounts(name='Conta no Charles Schwab')

    dollar_value = Decimal(0)
    for split in sorted_splits_by_date(account):
        if split.transaction.post_date > maximum_date:
            break

        currency = split.transaction.currency.mnemonic
        if currency == 'USD':
            dollar_value += split.value
        elif currency == 'BRL':
            dollar_value += split.quantity
        else:
            raise Exception("Unsupported currency in the brokerage account history", currency)

    usdbrl_quote = get_year_last_usdbrl_bid_quote(quotes_by_date, year_filter)
    real_value = usdbrl_quote * dollar_value

    return dollar_value, real_value


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


def collect_us_dividends(book, minimum_date, maximum_date, bid_quotes_by_month):
    monthly_dividends = {}
    for dividend_account in book.accounts(name='US Dividends').children:
        for split in dividend_account.splits:
            if split.transaction.post_date >= minimum_date and split.transaction.post_date <= maximum_date:
                month = split.transaction.post_date.month

                if month not in monthly_dividends:
                    monthly_dividends[month] = Decimal(0)

                monthly_dividends[month] += -split.value

    all_values = {}
    paid_tax_brl = Decimal(0)
    for month in sorted(monthly_dividends.keys()):
        dollar_net_value = monthly_dividends[month]
        dollar_gross_value = dollar_net_value/Decimal(1 - US_DIVIDEND_TAX_MULTIPLIER)
        real_gross_value = bid_quotes_by_month[month] * dollar_gross_value

        all_values[month] = {
            'dollar_net_value': dollar_net_value,
            'dollar_gross_value': dollar_gross_value,
            'real_gross_value': real_gross_value
        }

        paid_tax_brl += real_gross_value * US_DIVIDEND_TAX_MULTIPLIER

    return paid_tax_brl, all_values


def collect_bonificacoes(book, minimum_date, maximum_date):
    account = book.accounts(name='Bonificações')

    bonificacoes = []
    for split in sorted_splits_by_date(account):
        if split.transaction.post_date >= minimum_date and split.transaction.post_date <= maximum_date:
            bonificacoes.append(ledger(split.transaction))

    return bonificacoes


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


def calculate_tax_value(amount, multiplier):
    return round(amount * multiplier, 2) if amount > 0 else 0


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

        bens_direitos, br_sales, need_additional_data = collect_bens_direitos_brasil(book, maximum_date_filter, minimum_date_filter)
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

        stock_sales, stocks = collect_bens_direitos_stocks(book, quotes_by_date, maximum_date_filter, minimum_date_filter)
        types = {'us etf': 'ETF', 'us stock': 'Ação', 'reit': 'REIT'}
        for stock in sorted(stocks, key=lambda x: (x['metadata']['grupo_bem_direito'], x['metadata']['codigo_bem_direito'], x['name'])):
            metadata = stock['metadata']

            type_description = types[metadata['type']]

            print(stock['name'])
            print("Grupo:", metadata['grupo_bem_direito'])
            print("Código:", metadata['codigo_bem_direito'])
            print("Localização: EUA")
            print("Discriminação: {} {} {}. Código de negociação {}. Valor total de aquisição US$ {}. Corretora Charles Schwab.".format(round(stock['quantity'], 0), type_description, metadata['long_name'], stock['name'], round(stock['dollar_value'], 2)))
            print("Situação R$:", round(stock['real_value'], 2))
            print("***")

            if is_debug:
                pp.pprint(stock)

        brokerage_dollar_value, brokerage_real_value = collect_brokerage_account_balance(book, maximum_date_filter, quotes_by_date, year_filter)
        print("Conta na corretora no exterior")
        print("Grupo: 06")
        print("Código: 01", )
        print("Localização: EUA")
        print("Discriminação: US$ {} em conta na corretora Charles Schwab. Número da conta: [preencher aqui]".format(brokerage_dollar_value))
        print("Situação R$:", round(brokerage_real_value, 2))
        print("***")

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

        all_sales = br_sales + stock_sales
        sales_info = extract_sales_info(all_sales)
        if is_debug:
            pp.pprint("sales_info")
            pp.pprint(sales_info)
            pp.pprint("all_sales")
            pp.pprint(all_sales)

        print("************* RV Agregado (exclui ETFs BR e FIIs) *************")
        print("A ser declarado em Rendimentos Isentos e Não tributáveis")

        acoes_aggregated_profit = sales_info['aggregated']['acoes']['aggregated_profits']
        us_aggregated_profits = sales_info['aggregated']['us']['aggregated_profits']
        acoes_dedo_duro = sales_info['aggregated']['acoes']['dedo_duro']
        print("20 - Ganhos líquidos em operações no mercado à vista de ações: ", round(acoes_aggregated_profit, 2))
        print("5 - Ganho de capital na alienação de bem, direito ou conjunto de bens ou direitos da mesma natureza, alienados em um mesmo mês, de valor total de alienação até R$ 20.000,00, para ações alienadas no mercado de balcão, e R$ 35.000,00, nos demais casos (Lucro com venda no exterior): ", round(us_aggregated_profits, 2))
        print("Imposto Pago/Retido (Imposto Pago/Retido na linha 03) (dedo-duro): ", round(acoes_dedo_duro, 2))

        print("**************************")

        print("************* RV mês a mês *************")
        print("Operações comuns/Day-trade - Mercado à vista")
        print("Venda de ações com prejuízo, vendas em mês com mais de 20k ou vendas de ETFs")
        if is_debug:
            pp.pprint(sales_info['monthly']['acoes+etfs'])

        print("** ATENÇÃO: Antes de pagar qualquer imposto, não se esqueça de conferir se há prejuízo acumulado!")
        for key in sales_info['monthly']['acoes+etfs'].keys():
            current = sales_info['monthly']['acoes+etfs'][key]
            resultado = current['aggregated_profits']
            ir_fonte = current['dedo_duro']

            if resultado != 0:
                imposto = calculate_tax_value(resultado, ACOES_ETF_TAX_MULTIPLIER)
                print("Mês:", key)
                print("    Resultado", round(resultado, 2))
                print("    IR Fonte", round(ir_fonte, 2))
                print("    Valor do imposto", imposto)

        print("***")
        print("Operações FIIs")
        print("** ATENÇÃO: Antes de pagar qualquer imposto, não se esqueça de conferir se há prejuízo acumulado!")
        if is_debug:
            pp.pprint(sales_info['monthly']['fiis'])

        for key in sales_info['monthly']['fiis'].keys():
            resultado = sales_info['monthly']['fiis'][key]['aggregated_profits']
            ir_fonte = sales_info['monthly']['fiis'][key]['dedo_duro']

            if resultado != 0:
                imposto = calculate_tax_value(resultado, FII_TAX_MULTIPLIER)
                print("Mês:", key)
                print("    Resultado", round(resultado, 2))
                print("    IR Fonte", round(ir_fonte, 2))
                print("    Valor do imposto", imposto)

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
        bid_quotes_by_month = get_us_dividend_usdbrl_quotes(quotes_by_date, int(year_filter))
        paid_tax, us_dividends = collect_us_dividends(book, minimum_date_filter, maximum_date_filter, bid_quotes_by_month)

        print("Imposto Pago/Retido - Declarar na linha 02 (Rendimentos Tributáveis Recebidos de PF/Exterior)")
        print("Valor em R$:", round(paid_tax, 2))
        print("***")

        for key in us_dividends:
            dividend = us_dividends[key]
            print("Mês", key)
            print("Valor em R$:", round(dividend['real_gross_value'], 2))
            print("***")

        if is_debug:
            pp.pprint(bid_quotes_by_month)
            pp.pprint(paid_tax)
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

        print("******")
        print("Bonificações")
        bonificacoes = collect_bonificacoes(book, minimum_date_filter, maximum_date_filter)
        for bonificacao in bonificacoes:
            print(bonificacao)
        print("**************************")

        print("******* Papéis que estiveram na carteira ou que receberam proventos durante {} ******".format(year_filter))
        print("(Para saber quais informes devem ser coletados)")
        for papel in need_additional_data:
            print(papel)
        print("**************************")


main()
