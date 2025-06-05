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

# 25/05/2024 - bug: quando há um reverse split (agrupamento), o script diminui o valor total de aquisição. O valor total de aquisição deveria se manter constante, pois nenhuma ação foi vendida nesse caso.
# Exemplo: IRS - o valor total de aquisição em dólares parece correto, mas o calculado em reais diminui

# 04/06/2025 - 
# coisas para resolver:
# - reportar dividendos de ações no exterior separadamente para cada uma delas
#   - qual valor de dólar usar? ainda tem aquela loucura de dólar do dia 15?
# - bens e direitos de acoes no exterior estão ok?
# - pedir para o chatgpt refatorar o código para ter mais funções. Criar saídas de IR de 2023, 2024, 2025, salvá-las e fazer o diff com a versão nova que ele sugerir
# - saldo de conta da corretora no exterior está ligeiramente diferente do saldo no relatório deles. O que está errado?
# - rendimentos de FIIs são reportados com uma linha para cada FII, com o CNPJ de cada um deles (baixa prioridade, pois o mais importante são os informes de rendimentos)
# FIXME: conferir se em agosto vendi mais de 20k e paguei impostos

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


def add_taxes(sales_info):
    for i in range(1, 13):
        acoes_etfs = sales_info['monthly']['acoes+etfs'][i]
        us = sales_info['monthly']['us'][i]
        fiis = sales_info['monthly']['fiis'][i]

        if acoes_etfs['aggregated_profits'] > 0:
            acoes_etfs['imposto'] = acoes_etfs['aggregated_profits'] * ACOES_ETF_TAX_MULTIPLIER

        if us['aggregated_profits'] > 0:
            us['imposto'] = us['aggregated_profits'] * ACOES_ETF_TAX_MULTIPLIER

        if fiis['aggregated_profits'] > 0:
            fiis['imposto'] = fiis['aggregated_profits'] * FII_TAX_MULTIPLIER


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
        sales_info['monthly']['acoes+etfs'][i] = {'aggregated_profits': Decimal(0), 'total_sales': Decimal(0), 'dedo_duro': Decimal(0), 'imposto': Decimal(0)}
        sales_info['monthly']['us'][i] = {'aggregated_profits': Decimal(0), 'total_sales': Decimal(0), 'imposto': Decimal(0)}
        sales_info['monthly']['fiis'][i] = {'aggregated_profits': Decimal(0), 'total_sales': Decimal(0), 'dedo_duro': Decimal(0), 'imposto': Decimal(0)}

    # calculating the total monthly sales
    for sale in sales:
        month = sale['date'].month
        if is_br_acao_sale(sale):
            sales_info['monthly']['acoes+etfs'][month]['total_sales'] += -sale['value']
        elif is_us_sale(sale):
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
                current_us['aggregated_profits'] += sale['profit']
            else:
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

    add_taxes(sales_info)

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


def collect_bens_direitos(children, date_filter, quotes_by_date=None, is_us=False, minimum_date=None):
    sales = []
    bens = []
    held_during_filtered_period = set()
    for account in children:
        brl_price_avg = Decimal(0)
        brl_value_purchases = Decimal(0)

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
                format = "%d%m%Y"
                date = split.transaction.post_date.strftime(format)
                if split.value > 0 or is_stock_split:
                    # it's a purchase or a stock split
                    value_purchases += Decimal(split.value)
                    quantity_purchases += Decimal(split.quantity)
                    price_avg = value_purchases/quantity_purchases

                    if is_us and quotes_by_date is not None:
                        day_bid_usdbrl = quotes_by_date[date]['bid']
                        brl_value_purchases += day_bid_usdbrl * Decimal(split.value)
                        brl_price_avg = brl_value_purchases/quantity_purchases
                elif minimum_date is not None:
                    if split.value < 0 and split.transaction.post_date >= minimum_date:
                    # it's a sale or a transfer (?) in the current date filter range
                        is_transfer = split.quantity == 0
                        if is_transfer:
                            # I'm supposing a transfer is an asset becoming another one
                            # FIXME: two ifs doing the same thing?
                            has_no_quantity = split.quantity == 0
                            if has_no_quantity:
                                print(f'transaction of {account.name} on date {transaction_date} is already at quantity 0, skipping')

                                continue

                            value_purchases += Decimal(split.value)
                            price_avg = value_purchases/quantity_purchases

                            if is_us and quotes_by_date is not None:
                                day_ask_usdbrl = quotes_by_date[date]['ask']
                                brl_value_purchases += Decimal(split.value) * day_ask_usdbrl
                                brl_price_avg = brl_value_purchases/quantity_purchases
                        else:
                            # it's a sale
                            sold_price = split.value/split.quantity
                            positive_quantity = -split.quantity
                            is_profit = sold_price > price_avg
                            profit = sold_price * positive_quantity - price_avg * positive_quantity
                            sale = {
                                'name': account.name,
                                'type': extract_metadata(account)['type'],
                                'date': split.transaction.post_date,
                                'sold_price': sold_price,
                                'quantity_sold': split.quantity,
                                'quantity_after_sale': quantity,
                                'value': split.value,
                                'price_avg': price_avg,
                                'is_profit': is_profit,
                                'profit': profit
                            }

                            if is_us and quotes_by_date is not None:
                                day_bid_usdbrl = quotes_by_date[date]['bid']
                                sold_price_brl = day_bid_usdbrl * sold_price
                                sale['sold_price_brl'] = sold_price_brl
                                sale['is_profit'] = sold_price_brl > brl_price_avg
                                sale['profit'] = sold_price_brl * positive_quantity - brl_price_avg * positive_quantity

                                sale['brl_value'] = brl_price_avg * quantity
                                sale['brl_price_avg'] =  brl_price_avg
                                sale['brl_value_purchases'] = brl_value_purchases

                            sales.append(sale)
                    elif split.transaction.post_date >= minimum_date:
                        raise Exception("Split wasn't recognized", account.name, split.transaction.post_date)

                # avg should go back to zero if everything was sold at some point
                sold_all = quantity == 0
                if sold_all:
                    price_avg = Decimal(0)
                    brl_price_avg = Decimal(0)
                    value_purchases = Decimal(0)
                    brl_value_purchases = Decimal(0)
                    quantity_purchases = Decimal(0)

                    sold_before_period_start = split.transaction.post_date <= minimum_date
                    if sold_before_period_start:
                        held_during_filtered_period.remove(account.name)


        if quantity > 0:
            metadata = extract_metadata(account)

            bem = {
                    'name': account.name,
                    'quantity': quantity,
                    'value': price_avg * quantity,
                    'price_avg': price_avg,
                    'value_purchases': value_purchases,
                    'quantity_purchases': quantity_purchases,
                    'last_transaction_date': transaction_date,
                    'metadata': metadata
            }

            if is_us:
                bem['brl_value'] = brl_price_avg * quantity
                bem['brl_price_avg'] = brl_price_avg
                bem['brl_value_purchases'] = brl_value_purchases

            bens.append(bem)

        elif quantity < 0:
            raise Exception("The stock {} has a negative quantity {}!".format(account.name, quantity))

    return bens, sales, held_during_filtered_period


def collect_crypto(book, date_filter, minimum_date):
    cryptos_account = book.accounts(name='Crypto')
    children = cryptos_account.children

    crypto, _, _ = collect_bens_direitos(children, date_filter, minimum_date=minimum_date)
    return crypto


def collect_bens_direitos_brasil(book, date_filter, minimum_date):
    acoes_account = book.accounts(name='Ações')
    fiis_account = book.accounts(name='FIIs')
    children = acoes_account.children + fiis_account.children

    return collect_bens_direitos(children, date_filter, minimum_date=minimum_date)


def collect_bens_direitos_stocks(book, quotes_by_date, date_filter, minimum_date):
    stocks_account = book.accounts(name='Ações no exterior')
    children = stocks_account.children

    return collect_bens_direitos(children, date_filter, is_us=True, quotes_by_date=quotes_by_date, minimum_date=minimum_date)


def get_closest_available_quote(upper_limit_day, month, year, quotes_by_date, bid_or_ask):
    day = upper_limit_day
    while day > 0:
        try:
            date = "{:>02}{:>02}{}".format(day, month, year)
            return quotes_by_date[date][bid_or_ask]
        except KeyError:
            day -= 1

    raise Exception("Unexpected state: quote not found", day, month, year)


def get_year_last_usdbrl_bid_quote(quotes_by_date, year):
    return get_closest_available_quote(31, 12, year, quotes_by_date, 'bid')


def collect_brokerage_account_balance(book, maximum_date, quotes_by_date, year_filter):
    account = book.accounts(name='Conta no Charles Schwab')

    usd_value = Decimal(0)
    for split in sorted_splits_by_date(account):
        if split.transaction.post_date > maximum_date:
            break

        currency = split.transaction.currency.mnemonic
        if currency == 'USD':
            usd_value += split.value
        elif currency == 'BRL':
            usd_value += split.quantity
        else:
            raise Exception("Unsupported currency in the brokerage account history", currency)

    usdbrl_quote = get_year_last_usdbrl_bid_quote(quotes_by_date, year_filter)
    brl_value = usdbrl_quote * usd_value

    return usd_value, brl_value


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


def collect_us_dividends(book, minimum_date, maximum_date, quotes_by_date):
    # Fonte: https://youtu.be/lNTl9nkOUSQ?t=741
    # Fonte: PDF da XP e mycapital
    # Juros e dividendos recebidos → Ptax de venda na data do recebimento.
    # Imposto de Renda pago no exterior → Ptax de compra na data do pagamento do imposto.

    stock_dividends = {}
    for dividend_account in book.accounts(name='US Dividends').children:
        for split in dividend_account.splits:
            # if it's within the range we want
            if split.transaction.post_date >= minimum_date and split.transaction.post_date <= maximum_date:
                stock_name = dividend_account.name

                if stock_name not in stock_dividends:
                    stock_dividends[stock_name] = {}
                    stock_dividends[stock_name]['usd_value'] = Decimal(0)
                    stock_dividends[stock_name]['brl_value'] = Decimal(0)
                    stock_dividends[stock_name]['usd_tax_value'] = Decimal(0)
                    stock_dividends[stock_name]['brl_tax_value'] = Decimal(0)

                # sum all dividends and taxes per year for each stock
                date = split.transaction.post_date
                if split.value > 0:
                    # it's a tax payment
                    stock_dividends[stock_name]['usd_tax_value'] += split.value

                    ask_quote = get_closest_available_quote(date.day, date.month, date.year, quotes_by_date, 'ask')
                    stock_dividends[stock_name]['brl_tax_value'] += split.value * ask_quote
                elif split.value < 0:
                    # it's a dividend payment
                    stock_dividends[stock_name]['usd_value'] += -split.value

                    bid_quote = get_closest_available_quote(date.day, date.month, date.year, quotes_by_date, 'bid')
                    stock_dividends[stock_name]['brl_value'] += -split.value * bid_quote
                else:
                    raise Exception("Unexpected state: US dividend split value is 0", split.value)


    us_dividend_per_stock = {}
    for stock_name in sorted(stock_dividends.keys()):
        usd_value = stock_dividends[stock_name]['usd_value']
        brl_value = stock_dividends[stock_name]['brl_value']
        usd_tax_value = stock_dividends[stock_name]['usd_tax_value']
        brl_tax_value = stock_dividends[stock_name]['brl_tax_value']

        # Tax value tends to be embedded in the dividend payment for ADRs. There is no separate transaction for it.
        # That means it's 0 for those cases, so I need to calculate it from the received value.
        # I'm not sure it's always 30%, but I have no other choice for now than just guessing because i don't want to pay more taxes :(.
        # the correct thing would be to know how much was paid in taxes and apply the correct tax rate and correct exchange rate at the time of the payment
        if usd_tax_value == 0:
            usd_tax_value = usd_value * US_DIVIDEND_TAX_MULTIPLIER
        if brl_tax_value == 0:
            brl_tax_value = brl_value * US_DIVIDEND_TAX_MULTIPLIER

        # let's keep everything available for debugging purposes
        us_dividend_per_stock[stock_name] = {
            'usd_net_value': usd_value,
            'brl_net_value': brl_value,
            'usd_tax_value': usd_tax_value,
            'brl_tax_value': brl_tax_value
        }

    return us_dividend_per_stock


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

        stocks, stock_sales, _ = collect_bens_direitos_stocks(book, quotes_by_date, maximum_date_filter, minimum_date_filter)
        us_dividend_per_stock = collect_us_dividends(book, minimum_date_filter, maximum_date_filter, quotes_by_date)

        types = {'us etf': 'ETF', 'us stock': 'Ação', 'reit': 'REIT'}
        for stock in sorted(stocks, key=lambda x: (x['metadata']['grupo_bem_direito'], x['metadata']['codigo_bem_direito'], x['name'])):
            metadata = stock['metadata']

            type_description = types[metadata['type']]

            print(stock['name'])
            print("Grupo:", metadata['grupo_bem_direito'])
            print("Código:", metadata['codigo_bem_direito'])
            print("Localização: EUA")
            print("Discriminação: {} {} {}. Código de negociação {}. Valor total de aquisição US$ {}. Corretora Charles Schwab.".format(round(stock['quantity'], 0), type_description, metadata['long_name'], stock['name'], round(stock['value'], 2)))
            print("Situação R$:", round(stock['brl_value'], 2))
            if stock['name'] in us_dividend_per_stock:
                print("Aplicação Financeira - Lucro ou prejuízo R$:", round(us_dividend_per_stock[stock['name']]['brl_net_value'], 2))
                print("Aplicação Financeira - Imposto pago no exterior R$:", round(us_dividend_per_stock[stock['name']]['brl_tax_value'], 2))
            print("***")

            if is_debug:
                pp.pprint(stock)
                pp.pprint(stock_sales)
                pp.pprint(us_dividend_per_stock)

        brokerage_usd_value, brokerage_brl_value = collect_brokerage_account_balance(book, maximum_date_filter, quotes_by_date, year_filter)
        print("Conta na corretora no exterior")
        print("Grupo: 06")
        print("Código: 01", )
        print("Localização: EUA")
        print("Discriminação: US$ {} em conta na corretora Charles Schwab. Número da conta: [preencher aqui]".format(brokerage_usd_value))
        print("Situação R$:", round(brokerage_brl_value, 2))
        print("***")

        cryptos = collect_crypto(book, maximum_date_filter, minimum_date_filter)
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
        acoes_dedo_duro = sales_info['aggregated']['acoes']['dedo_duro']
        print("20 - Ganhos líquidos em operações no mercado à vista de ações: ", round(acoes_aggregated_profit, 2))
        # FIXME: remove parts of the code that calculate this. it's not needed anymore
        #  print("5 - Ganho de capital na alienação de bem, direito ou conjunto de bens ou direitos da mesma natureza, alienados em um mesmo mês, de valor total de alienação até R$ 20.000,00, para ações alienadas no mercado de balcão, e R$ 35.000,00, nos demais casos (Lucro com venda no exterior) (Declarar apenas se for valor positivo): ", round(us_aggregated_profits, 2))
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
            imposto = current['imposto']

            if resultado != 0:
                print("Mês:", key)
                print("    Resultado", round(resultado, 2))
                print("    IR Fonte", round(ir_fonte, 2))
                print("    Valor do imposto", round(imposto, 2))

        print("***")
        print("Operações FIIs")
        print("** ATENÇÃO: Antes de pagar qualquer imposto, não se esqueça de conferir se há prejuízo acumulado!")
        if is_debug:
            pp.pprint(sales_info['monthly']['fiis'])

        for key in sales_info['monthly']['fiis'].keys():
            current = sales_info['monthly']['fiis'][key]
            resultado = current['aggregated_profits']
            ir_fonte = current['dedo_duro']
            imposto = current['imposto']

            if resultado != 0:
                print("Mês:", key)
                print("    Resultado", round(resultado, 2))
                print("    IR Fonte", round(ir_fonte, 2))
                print("    Valor do imposto", round(imposto, 2))

        print("***")
        # FIXME: remove parts of the code that calculate this. it's not needed anymore
        # print("Vendas no exterior que geraram impostos")
        # for key in sales_info['monthly']['us'].keys():
        #     current = sales_info['monthly']['us'][key]
        #     resultado = current['aggregated_profits']
        #     imposto = current['imposto']

        #     if resultado != 0:
        #         print("Mês:", key)
        #         print("    Resultado", round(resultado, 2))
        #         print("    Valor do imposto", round(imposto, 2))

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
