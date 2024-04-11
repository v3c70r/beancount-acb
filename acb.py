from beancount.loader import load_file
from pricehist.sources.bankofcanada import BankOfCanada
from pricehist.outputs.json import JSON
from pricehist.series import Series

import argparse
import datetime

class Transaction:
    def __init__(self, date, amount, symbol, cost, currency = 'USD'):
        self.date = date
        self.amount= amount
        self.symbol = symbol
        self.cost = cost
        self.currency = currency
        self.price = cost / amount

class PriceFetcher:
    def __init__(self):
        # Cache for price lookups, key is tuple(currency, date), value is price
        self._price_cache = {}

    # Look up the price of the symbol on the date
    # search range is the number of days to search for the price in case the date falls on a weekend
    def convert_to_cad(self, date, amount, currency, search_range = 5):
        if (currency, date) in self._price_cache:
            priceAmount = self._price_cache[(currency, date)]
        else:
            start_date_str = date.strftime("%Y-%m-%d")
            end_date_str = (date + datetime.timedelta(days=search_range)).strftime("%Y-%m-%d")
            series = BankOfCanada().fetch(Series(currency, "CAD", "reference", start_date_str, end_date_str))

            priceAmount = 1.0
            if series.prices:
                priceAmount = series.prices[0].amount

            # add all fetched prices to cache
            self._price_cache[(currency, date)] = priceAmount
            for price in series.prices:
                self._price_cache[(currency, datetime.datetime.strptime(price.date, "%Y-%m-%d").date())] = price.amount

        return priceAmount * amount

class TransactionStack:
    def __init__(self, is_rsu = True):
        self._transactions = []
        self._is_rsu = is_rsu
        self._priceFetcher = PriceFetcher()

    def _combine_identical_properties(self):
        # Combine all transactions to a single transaction in stack when they are all indentical properties
        if self._transactions.count != 0:
            total_cost = 0
            total_amount = 0
            for transaction in self._transactions:
                total_cost += transaction.cost
                total_amount += transaction.amount
            
            self._transactions = self._transactions[-1:]
            self._transactions[0].cost = total_cost
            self._transactions[0].amount = total_amount
            self._transactions[0].price = total_cost / total_amount

    def _convert_transaction_to_cad(self, transaction):
        if transaction.currency != 'CAD':
            transaction.cost = self._priceFetcher.convert_to_cad(transaction.date, transaction.cost, transaction.currency)
            transaction.price = self._priceFetcher.convert_to_cad(transaction.date, transaction.price, transaction.currency)
            transaction.currency = 'CAD'
        return transaction

    def buy(self, buy_transaction):
        buy_transaction = self._convert_transaction_to_cad(buy_transaction)
        self._transactions.append(buy_transaction)

    def sell(self, sell_transaction):
        sell_transaction = self._convert_transaction_to_cad(sell_transaction)
        if self._is_rsu:
            # first pass. Sell non-identical properties from stack
            for buy_transaction in reversed(self._transactions):
                if ((sell_transaction.date - buy_transaction.date).days < 30):
                    # Sell with in 30 days are not identical properties
                    amount_to_sell = min(buy_transaction.amount, sell_transaction.amount)
                    if amount_to_sell == 0:
                        continue
                    buy_transaction.amount -= amount_to_sell
                    sell_transaction.amount -= amount_to_sell

                    buy_cost = amount_to_sell * buy_transaction.price
                    sell_cost = amount_to_sell * sell_transaction.price

                    print("On {0}, Sell {1}{2} cost {3} (distinct property purchased on {4}, with cost {5}, amount left after sell: {6})".format(
                        sell_transaction.date.strftime("%Y-%m-%d"),
                        amount_to_sell, 
                        sell_transaction.symbol, 
                        sell_cost,
                        buy_transaction.date.strftime("%Y-%m-%d"),
                        buy_cost,
                        buy_transaction.amount
                        ))

            if sell_transaction.amount > 0:
                # sencond pass, sell the rest as ACB
                _combine_identical_properties()
                amount_to_sell = min(self._transactions[0].amount, sell_transaction.amount)
                self._transactions[0].amount -= amount_to_sell
                sell_transaction.amount -= amount_to_sell
                assert(self._transactions[0].amount >= 0)
                print("On {0}, Sell {1}{2} cost {3} (acb price)".format(
                    sell_transaction.date.strftime("%Y-%m-%d"),
                    amount_to_sell,
                    self._transactions[0].symbol, 
                    self._transactions[0].cost))
                

class ACB:
    def __init__(self, beancount_file, symbol, exclude_tags = ['tfsa', 'rrsp']):
        self._beancount_file = beancount_file
        self._symbol = symbol
        self._transactions = []

        # get all transactions
        entries, errors, options_map = load_file(self._beancount_file)

        for entry in entries:
            # Skip transactions with exclude tags
            if hasattr(entry, 'tag') and any(tag in entry.tag for tag in exclude_tags):
                continue
            if hasattr(entry, 'postings'):
                for posting in entry.postings:
                    if posting.units.currency == self._symbol:
                        self._transactions.append(entry)

    def compute_acb_rsu(self):
        transaction_stack = TransactionStack()

        for transaction in self._transactions:
            transaction_amount = 0
            transaction_price = 0
            transaction_expense = 0


            for posting in transaction.postings:
                if posting.units.currency == self._symbol:
                    transaction_amount += posting.units.number
                    if(posting.meta.get('fmv')):
                        transaction_price = posting.meta.get('fmv').number
                    elif posting.price is not None:
                        transaction_price = posting.price.number
                # if posting has expense
                if posting.account.startswith("Expenses:"):
                    transaction_expense += posting.units.number

            if transaction_amount > 0:
                # buy, update total bought units and cost
                cost = transaction_amount * transaction_price + transaction_expense
                transaction_stack.buy(Transaction(transaction.date, transaction_amount, self._symbol, cost))

            elif transaction_amount < 0:
                cost = abs(transaction_amount) * transaction_price - transaction_expense
                transaction_stack.sell(Transaction(transaction.date, abs(transaction_amount), self._symbol, cost))

    

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Compute ACB for a symbol, pass in the beancount file and the symbol to compute ACB for.")
    # Adding arguments
    parser.add_argument("-i", "--input", help="Input beancount journal file", required = True)
    parser.add_argument("-s", "--symbol", help="Symbol", required = True)

    # Parsing arguments
    args = parser.parse_args()

    acb = ACB(args.input, args.symbol)
    acb.compute_acb_rsu()
