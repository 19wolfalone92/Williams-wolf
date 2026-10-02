import os,tempfile
from decimal import Decimal,ROUND_DOWN
from datetime import datetime,timezone
from trader import Trader
from db import Database
class FakeClient:
    def __init__(self,price=100,quote=1000,base_free=0,base_locked=0):self.api_key='TEST';self.api_secret='TEST';self.testnet=True;self.price=price;self.quote=quote;self.base_free=base_free;self.base_locked=base_locked;self.orders=[];self.open_ocos=[];self.next_order_id=1000;self.next_list_id=5000;self.created_oco_count=0
    def account(self):return {'balances':[{'asset':'USDT','free':str(self.quote),'locked':'0'},{'asset':'BTC','free':str(self.base_free),'locked':str(self.base_locked)}]}
    def all_orders(self,symbol,limit=1000):return list(self.orders)
    def open_order_lists(self,symbol=None):return list(self.open_ocos)
    def create_oco_sell(self,symbol,quantity,take_profit_price,stop_price,stop_limit_price,list_client_order_id=None):
        lid=self.next_list_id;self.next_list_id+=1;qty=float(quantity);tp=float(take_profit_price);sl=float(stop_price);slp=float(stop_limit_price);a=self.next_order_id;self.next_order_id+=2;legs=[{'symbol':symbol,'side':'SELL','type':'TAKE_PROFIT_LIMIT','orderId':a,'orderListId':lid,'clientOrderId':f'tp-{a}','status':'NEW','price':str(tp),'stopPrice':str(tp),'origQty':str(qty),'time':2000+self.created_oco_count},{'symbol':symbol,'side':'SELL','type':'STOP_LOSS_LIMIT','orderId':a+1,'orderListId':lid,'clientOrderId':f'sl-{a+1}','status':'NEW','price':str(slp),'stopPrice':str(sl),'origQty':str(qty),'time':2000+self.created_oco_count}];self.created_oco_count+=1;self.orders.extend(legs);self.open_ocos.append({'symbol':symbol,'orderListId':lid,'listOrderStatus':'EXEC_STARTED','orders':legs});return {'orderListId':lid,'orderReports':legs}
    @staticmethod
    def decimal_floor(value,step):return (Decimal(str(value))/Decimal(str(step))).to_integral_value(rounding=ROUND_DOWN)*Decimal(str(step))
    def decimal_format(self,value):return f'{float(value):.8f}'
def new_trader(path,c):
    t=Trader.__new__(Trader);t.symbol='BTCUSDT';t.interval='1h';t.position_fraction=.25;t.stop_pct=.02;t.target_pct=.04;t.poll_seconds=1;t.db=Database(path);t.client=c;t.filters={'LOT_SIZE':{'minQty':'0.001','stepSize':'0.001'},'PRICE_FILTER':{'tickSize':'0.01'},'MIN_NOTIONAL':{'minNotional':'10'}};t.base_asset='BTC';t.quote_asset='USDT';t.recovered=False;t.notify=lambda m:None;return t
def seed(t,c):
    buy={'symbol':'BTCUSDT','side':'BUY','type':'MARKET','orderId':1,'clientOrderId':'buy-1','status':'FILLED','price':'100','origQty':'1','executedQty':'1','cummulativeQuoteQty':'100','transactTime':1000,'time':1000};c.orders.append(buy);c.base_free=1;c.quote-=100;t.db.save_order(buy);t.db.save_trade(entry_time=datetime.fromtimestamp(1,tz=timezone.utc).isoformat(),symbol='BTCUSDT',side='LONG',entry_price=100,quantity=1,entry_order_id='1',fees=0)
def mark_exit(c,price):
    q=c.base_free+c.base_locked;c.orders.append({'symbol':'BTCUSDT','side':'SELL','type':'LIMIT','orderId':9000,'orderListId':5000,'clientOrderId':'exit','status':'FILLED','price':str(price),'origQty':str(q),'executedQty':str(q),'cummulativeQuoteQty':str(q*price),'transactTime':3000,'time':3000});c.base_free=0;c.base_locked=0;c.open_ocos.clear()
def check(name,fn):
    try:fn();print('[PASS]',name)
    except Exception as e:print('[FAIL]',name,type(e).__name__,e);raise
def scenario_exit(price):
    with tempfile.TemporaryDirectory() as d:
        c=FakeClient();t=new_trader(os.path.join(d,'x.sqlite3'),c);seed(t,c);t.place_oco(1,100);mark_exit(c,price);r=new_trader(os.path.join(d,'x.sqlite3'),c);r.recover_state();assert r.db.open_trade() is None;assert abs(float(r.db.conn.execute('select exit_price from trades').fetchone()[0])-price)<1e-9;r.recover_state();assert r.db.conn.execute('select count(*) from trades').fetchone()[0]==1
def scenario_missing():
    with tempfile.TemporaryDirectory() as d:
        c=FakeClient();t=new_trader(os.path.join(d,'x.sqlite3'),c);seed(t,c);r=new_trader(os.path.join(d,'x.sqlite3'),c);r.recover_state();assert c.created_oco_count==1;r.recover_state();assert c.created_oco_count==1
def scenario_restart():
    with tempfile.TemporaryDirectory() as d:
        c=FakeClient();t=new_trader(os.path.join(d,'x.sqlite3'),c);seed(t,c);t.place_oco(1,100);r=new_trader(os.path.join(d,'x.sqlite3'),c);r.recover_state();assert r.db.open_trade() is not None;assert c.created_oco_count==1
def scenario_foreign_balance():
    with tempfile.TemporaryDirectory() as d:
        c=FakeClient(base_free=2);t=new_trader(os.path.join(d,'x.sqlite3'),c);t.recover_state();assert t.db.open_trade() is None;assert t.db.state_get('position_state')=='FLAT';assert c.created_oco_count==0
def run():
    check('BUY -> OCO -> crash -> TP',lambda:scenario_exit(104));check('BUY -> OCO -> crash -> SL',lambda:scenario_exit(98));check('BUY -> crash -> missing OCO',scenario_missing);check('BUY -> OCO -> crash -> restart',scenario_restart);check('pre-existing BTC is not treated as bot position',scenario_foreign_balance);print('\nRecovery tests: 5/5 passed')
if __name__=='__main__':run()
