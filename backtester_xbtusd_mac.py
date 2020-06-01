"""
Report:
The backtest with the bare-bones MAC(20,50) strategy is profitable.
Also, the threshold for the MAC signal seems to reduce maximum drawdown but
also reduces the overall performance.
"""

import datetime as dt
import pandas as pd
from pandas_datareader import data as web
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter


class TickData:
    """
    Stores a single unit of data received from a market data source.

    """

    def __init__(self, symbol, timestamp, last_price=0, total_volume=0):
        self.symbol = symbol
        self.timestamp = timestamp
        self.open_price = 0
        self.last_price = last_price
        self.total_volume = total_volume


class MarketData:
    """
    An instance of this class is used throughout the system to store and
    retrieve prices by the various components. Essentially, a container is used
    to store the last tick data.

    """

    def __init__(self):
        self.__recent_ticks__ = dict()

    def add_last_price(self, time, symbol, price, volume):
        tick_data = TickData(symbol, time, price, volume)
        self.__recent_ticks__[symbol] = tick_data

    def add_open_price(self, time, symbol, price):
        tick_data = self.get_existing_tick_data(symbol, time)
        tick_data.open_price = price

    def get_existing_tick_data(self, symbol, time):
        if symbol not in self.__recent_ticks__:
            tick_data = TickData(symbol, time)
            self.__recent_ticks__[symbol] = tick_data

        return self.__recent_ticks__[symbol]

    def get_last_price(self, symbol):
        return self.__recent_ticks__[symbol].last_price

    def get_open_price(self, symbol):
        return self.__recent_ticks__[symbol].open_price

    def get_timestamp(self, symbol):
        return self.__recent_ticks__[symbol].timestamp


class MarketDataSource:
    """
    Download prices from an external data source.

    """

    def __init__(self):
        self.event_tick = None
        self.ticker, self.source = None, None
        self.start, self.end = None, None
        self.md = MarketData()

    def start_market_simulation(self):
        data = pd.read_csv('XBTUSD_past1000_days.csv',
                           parse_dates=['timestamp'])
        data['Date'] = data['timestamp'].dt.date
        data = data.set_index('Date')
        data = data.drop(['timestamp'], axis=1)
        data = data.rename(columns={"open": "Open", "close": "Close", "volume":
                           "Volume"})
        data = data.iloc[::-1]

        for time, row in data.iterrows():
            self.md.add_last_price(time, self.ticker, row["Close"],
                                   row["Volume"])
            self.md.add_open_price(time, self.ticker, row["Open"])

            if self.event_tick is not None:
                self.event_tick(self.md)


class Order:
    """
    The Order class represents a single order sent by the strategy to the
    server.

    """

    def __init__(self, timestamp, symbol, qty, is_buy, is_market_order,
                 price=0):
        self.timestamp = timestamp
        self.symbol = symbol
        self.qty = qty
        self.price = price
        self.is_buy = is_buy
        self.is_market_order = is_market_order
        self.is_filled = False
        self.filled_price = 0
        self.filled_time = None
        self.filled_qty = 0


class Position:
    """
    The Position class helps us keep track of our current market position and
    account balance.

    """

    def __init__(self):
        self.symbol = None
        self.buys, self.sells, self.net = 0, 0, 0
        self.realized_pnl = 0
        self.unrealized_pnl = 0
        self.position_value = 0

    def event_fill(self, timestamp, is_buy, qty, price):
        if is_buy:
            self.buys += qty
        else:
            self.sells += qty

        self.net = self.buys - self.sells
        changed_value = qty * price * (-1 if is_buy else 1)
        self.position_value += changed_value

        if self.net == 0:
            self.realized_pnl = self.position_value

    def update_unrealized_pnl(self, price):
        if self.net == 0:
            self.unrealized_pnl = 0
        else:
            self.unrealized_pnl = price * self.net + self.position_value

        return self.unrealized_pnl


class Strategy:
    """
    Base strategy for implementation.

    """

    def __init__(self):
        self.event_sendorder = None

    def on_tick_event(self, market_data):
        pass

    def event_order(self, order):
        pass

    def update_position_status(self, positions):
        pass

    def send_market_order(self, symbol, qty, is_buy, timestamp):
        if self.event_sendorder is not None:
            order = Order(timestamp, symbol, qty, is_buy, True)
            self.event_sendorder(order)


class MACStrategy(Strategy):
    """
    Implementation of an MAC strategy based on the Strategy class.

    """

    def __init__(self, symbol, lookback_intervals=20, buy_threshold=-1.5,
                 sell_threshold=1.5):
        Strategy.__init__(self)
        self.symbol = symbol
        self.lookback_intervals = lookback_intervals
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.prices = pd.DataFrame()
        self.is_long, self.is_short = False, False

    def update_position_status(self, positions):
        if self.symbol in positions:
            position = positions[self.symbol]
            self.is_long = True if position.net > 0 else False
            self.is_short = True if position.net < 0 else False

    def on_tick_event(self, market_data):
        self.store_prices(market_data)
        # if len(self.prices) < self.lookback_intervals:
        #     return

        volatility_fraction = 0
        signal_value = self.calculate_mac(20, 50)
        timestamp = market_data.get_timestamp(self.symbol)
        signal_threshold = volatility_fraction * self.calculate_volatility()

        if signal_value > signal_threshold:
            self.on_buy_signal(timestamp)
        elif signal_value < -signal_threshold:
            self.on_sell_signal(timestamp)

    def store_prices(self, market_data):
        timestamp = market_data.get_timestamp(self.symbol)
        self.prices.loc[timestamp, "close"] = \
            market_data.get_last_price(self.symbol)
        self.prices.loc[timestamp, "open"] = \
            market_data.get_open_price(self.symbol)

    def calculate_mac(self, fast_window, slow_window):
        ma_fast = self.prices["close"].ewm(span=fast_window).mean()
        ma_slow = self.prices["close"].ewm(span=slow_window).mean()
        mac = ma_fast[-1] - ma_slow[-1]
        return mac

    def calculate_volatility(self):
        prices = self.prices[-self.lookback_intervals:]
        returns = prices["close"].diff().dropna()
        volatility = returns.std()
        return volatility

    def on_buy_signal(self, timestamp):
        if not self.is_long:
            self.send_market_order(self.symbol, 100, True, timestamp)

    def on_sell_signal(self, timestamp):
        if not self.is_short:
            self.send_market_order(self.symbol, 100, False, timestamp)


class Backtester:
    """
    Implementation of the backtesting engine, combining all core components.

    """

    def __init__(self, symbol, start_date, end_date, data_source="google"):
        self.target_symbol = symbol
        self.data_source = data_source
        self.start_dt = start_date
        self.end_dt = end_date
        self.strategy = None
        self.unfilled_orders = []
        self.positions = dict()
        self.current_prices = None
        self.rpnl, self.upnl = pd.DataFrame(), pd.DataFrame()

    def get_timestamp(self):
        return self.current_prices.get_timestamp(self.target_symbol)

    def get_trade_date(self):
        timestamp = self.get_timestamp()
        return timestamp.strftime("%Y-%m-%d")

    def update_filled_position(self, symbol, qty, is_buy, price, timestamp):
        position = self.get_position(symbol)
        position.event_fill(timestamp, is_buy, qty, price)
        self.strategy.update_position_status(self.positions)
        self.rpnl.loc[timestamp, "rpnl"] = position.realized_pnl
        print(self.get_trade_date(), "Filled:", "BUY" if is_buy else "SELL",
              qty, symbol, "at", '{:,.0f}'.format(price))

    def get_position(self, symbol):
        if symbol not in self.positions:
            position = Position()
            position.symbol = symbol
            self.positions[symbol] = position

        return self.positions[symbol]

    def evthandler_order(self, order):
        self.unfilled_orders.append(order)

        print(self.get_trade_date(), "Received order:", "BUY" if order.is_buy
              else "SELL", order.qty, order.symbol)

    def match_order_book(self, prices):
        if len(self.unfilled_orders) > 0:
            self.unfilled_orders = \
                [order for order in self.unfilled_orders
                 if self.is_order_unmatched(order, prices)]

    def is_order_unmatched(self, order, prices):
        symbol = order.symbol
        timestamp = prices.get_timestamp(symbol)

        if order.is_market_order and timestamp > order.timestamp:
            # Order is matched and filled.
            order.is_filled = True
            open_price = prices.get_open_price(symbol)
            order.filled_timestamp = timestamp
            order.filled_price = open_price
            self.update_filled_position(symbol, order.qty, order.is_buy,
                                        open_price, timestamp)
            self.strategy.event_order(order)
            return False

        return True

    def print_position_status(self, symbol, prices):
        if symbol in self.positions:
            position = self.positions[symbol]
            close_price = prices.get_last_price(symbol)
            position.update_unrealized_pnl(close_price)
            self.upnl.loc[self.get_timestamp(), "upnl"] = \
                position.unrealized_pnl

            print(self.get_trade_date(), "Net:", position.net, "Value:",
                  '{:,.0f}'.format(position.position_value), "UPnL:",
                  '{:,.0f}'.format(position.unrealized_pnl), "RPnL:",
                  '{:,.0f}'.format(position.realized_pnl))

    def handle_incoming_tick(self, prices):
        self.current_prices = prices
        self.strategy.on_tick_event(prices)
        self.match_order_book(prices)
        self.print_position_status(self.target_symbol, prices)

    def start_backtest(self):
        self.strategy = MACStrategy(self.target_symbol)
        self.strategy.event_sendorder = self.evthandler_order

        mds = MarketDataSource()
        mds.event_tick = self.handle_incoming_tick
        mds.ticker = self.target_symbol
        mds.source = self.data_source
        mds.start, mds.end = self.start_dt, self.end_dt

        print("Backtesting started...")
        mds.start_market_simulation()
        print("Completed.")


backtester = Backtester("XBTUSD", dt.datetime(2017, 7, 20),
                        dt.datetime(2018, 1, 1), data_source="csv_file")
backtester.start_backtest()


def _num_format(x, pos):
    """
    Define formatter for the chart.
    The two arguments are the number and tick position.

    """

    string = '{:,.0f}'.format(x)
    return string

formatter = FuncFormatter(_num_format)

# Plotting the chart.
fig, ax = plt.subplots()
plt.xticks(rotation=70)
ax.plot(backtester.rpnl, label='RPNL')
ax.grid(axis='both', linestyle='--', linewidth=.1)
ax.yaxis.set_major_formatter(formatter)
ax.legend()
plt.show()
