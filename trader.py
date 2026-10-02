import logging, os, time, uuid
from datetime import datetime, timezone
from dotenv import load_dotenv
from binance_client import BinanceAPIError, BinanceSpotClient
from data import fetch_klines
from db import Database
from strategy import calculate_indicators, config_from_env
from telegram_bot import Telegram
load_dotenv(); logging.basicConfig(level=logging.INFO,format='%(asctime)s | %(levelname)s | %(message)s'); log=logging.getLogger('williams-v4')
def utc_now():return datetime.now(timezone.utc).isoformat()
class Trader:
    def __init__(self,api_key=None,api_secret=None,testnet=None):
        self.symbol=os.getenv('SYMBOL','BTCUSDT').upper(); self.interval=os.getenv('INTERVAL','1h'); self.position_fraction=float(os.getenv('POSITION_FRACTION','0.25')); self.stop_pct=float(os.getenv('STOP_LOSS_PCT','0.02')); self.target_pct=float(os.getenv('TAKE_PROFIT_PCT','0.04')); self.poll_seconds=int(os.getenv('POLL_SECONDS','20'))
        self.db=Database(os.getenv('DB_PATH','data/trader.sqlite3')); self.tg=Telegram(os.getenv('TELEGRAM_BOT_TOKEN',''),os.getenv('TELEGRAM_CHAT_ID',''))
        self.client=BinanceSpotClient(api_key if api_key is not None else os.getenv('BINANCE_API_KEY',''),api_secret if api_secret is not None else os.getenv('BINANCE_API_SECRET',''),testnet=(os.getenv('TESTNET','true').lower()=='true') if testnet is None else testnet)
        self.filters={}; self.base_asset=self.quote_asset=None; self.recovered=False
    def notify(self,text):
        log.info(text.replace('\n',' | '))
        try:self.tg.send(text)
        except Exception as e:log.error('Telegram error: %s',e)
    def setup(self):
        if not self.client.testnet and os.getenv('ALLOW_LIVE','false').lower()!='true':raise RuntimeError('Live trading disabled; TESTNET=true is required unless ALLOW_LIVE=true.')
        if not self.client.api_key or not self.client.api_secret:raise RuntimeError('BINANCE_API_KEY and BINANCE_API_SECRET are required.')
        self.client.sync_time(); info=self.client.exchange_info(self.symbol); s=info['symbols'][0]; self.filters={f['filterType']:f for f in s['filters']}; self.base_asset=s['baseAsset']; self.quote_asset=s['quoteAsset']
        self.db.log_event('INFO','startup','Trader initialized',{'symbol':self.symbol,'interval':self.interval,'testnet':self.client.testnet}); self.recover_state(); self.notify(f'Williams v4 STARTED\n{self.symbol} {self.interval}\nTESTNET={self.client.testnet}\nRECOVERY={"OK" if self.recovered else "FAILED"}')
    def normalize_qty(self,qty):
        f=self.filters.get('LOT_SIZE') or self.filters.get('MARKET_LOT_SIZE'); step=f['stepSize'] if f else '0.000001'; min_qty=float(f['minQty']) if f else 0; q=self.client.decimal_floor(qty,step); return float(q) if float(q)>=min_qty else 0.0
    def normalize_price(self,price):
        f=self.filters.get('PRICE_FILTER'); tick=f['tickSize'] if f else '0.01'; return float(self.client.decimal_floor(price,tick))
    def available_quote(self):
        a=self.client.account(); return next((float(b['free']) for b in a.get('balances',[]) if b['asset']==self.quote_asset),0.0)
    def base_balance_total(self):
        a=self.client.account(); return next((float(b['free'])+float(b['locked']) for b in a.get('balances',[]) if b['asset']==self.base_asset),0.0)
    def _min_qty(self):
        f=self.filters.get('LOT_SIZE') or self.filters.get('MARKET_LOT_SIZE'); return float(f['minQty']) if f else 0.0
    def _is_meaningful_position(self): return self.base_balance_total()>=self._min_qty()
    def _is_bot_order(self,o): return str(o.get('clientOrderId','')).startswith(('WILLV4_ENTRY_','WILLV4_OCO_'))
    def _is_bot_oco_list(self,lst):
        lid=str(lst.get('listClientOrderId',''))
        if lid.startswith('WILLV4_OCO_'): return True
        return any(str(o.get('clientOrderId','')).startswith(('WILLV4_OCO_','tp-','sl-')) for o in lst.get('orders',[]))
    def _filled_sell_qty_after(self,buy,all_orders):
        bid=int(buy.get('time',buy.get('transactTime',0)) or 0)
        return sum(float(o.get('executedQty',0) or 0) for o in all_orders if o.get('side')=='SELL' and o.get('status')=='FILLED' and int(o.get('time',0) or 0)>=bid and self._sell_belongs_to_bot(o, all_orders))
    def _trade_remaining_qty(self,trade,all_orders):
        entry_id=str(trade.get('entry_order_id') or '')
        buy=next((o for o in all_orders if str(o.get('orderId'))==entry_id and o.get('side')=='BUY'),None)
        if not buy: return float(trade.get('quantity') or 0)
        bought=float(buy.get('executedQty',0) or 0)
        sold=sum(float(o.get('executedQty',0) or 0) for o in all_orders if o.get('side')=='SELL' and o.get('status')=='FILLED' and int(o.get('time',0) or 0)>=int(buy.get('time',buy.get('transactTime',0)) or 0) and self._sell_belongs_to_bot(o,all_orders))
        return max(0.0,min(float(trade.get('quantity') or bought),bought)-sold)
    def _sell_belongs_to_bot(self,o,all_orders):
        cid=str(o.get('clientOrderId',''))
        if cid.startswith('WILLV4_OCO_') or cid.startswith('tp-') or cid.startswith('sl-'): return True
        lid=str(o.get('orderListId',''))
        if not lid: return False
        if any(str(x.get('orderListId',''))==lid and (str(x.get('clientOrderId','')).startswith(('WILLV4_OCO_','tp-','sl-')) or str(x.get('raw_json','')).find('WILLV4_OCO_')>=0) for x in all_orders): return True
        row=self.db.conn.execute("SELECT 1 FROM orders WHERE order_list_id=? AND client_order_id LIKE 'WILLV4_OCO_%' LIMIT 1",(lid,)).fetchone()
        return row is not None
    def recover_state(self):
        self.db.log_event('INFO','recovery_start','Starting exchange/SQLite reconciliation')
        open_trade=self.db.open_trade()
        all_orders=self.client.all_orders(self.symbol,limit=1000)
        for o in all_orders:self.db.save_order(o)
        open_lists=self.client.open_order_lists(self.symbol)
        for lst in open_lists:
            for o in lst.get('orders',[]):self.db.save_order(o)
        bot_open_lists=[x for x in open_lists if self._is_bot_oco_list(x)]
        open_oco_ids={str(x.get('orderListId')) for x in bot_open_lists if x.get('orderListId') is not None}
        position_qty=self.base_balance_total()
        # Reconstruct only an actually-unresolved bot BUY. A historical BUY followed by a bot OCO sell must never be revived just because the account still owns unrelated BTC.
        if open_trade is None:
            candidates=[]
            for buy in all_orders:
                if buy.get('side')!='BUY' or buy.get('status')!='FILLED' or not self._is_bot_order(buy): continue
                bought=float(buy.get('executedQty',0) or 0); sold=self._filled_sell_qty_after(buy,all_orders); remaining=max(0.0,bought-sold)
                if remaining>=self._min_qty() and position_qty>=self._min_qty():
                    candidates.append((int(buy.get('time',buy.get('transactTime',0)) or 0),buy,remaining))
            if candidates:
                _,buy,remaining=max(candidates,key=lambda x:x[0]); quote=float(buy.get('cummulativeQuoteQty',0) or 0); bought=float(buy.get('executedQty',0) or 0); entry=quote/bought if quote and bought else float(buy.get('price',0) or 0); qty=min(remaining,position_qty)
                self.db.save_trade(entry_time=datetime.fromtimestamp(int(buy.get('transactTime',buy.get('time',0)))/1000,tz=timezone.utc).isoformat(),symbol=self.symbol,side='LONG',entry_price=entry,quantity=qty,entry_order_id=str(buy.get('orderId')),fees=0); open_trade=self.db.open_trade()
                self.db.log_event('WARNING','trade_reconstructed','Reconstructed unresolved bot-owned LONG from tagged entry order',buy)
        if open_trade:
            expected_qty=self._trade_remaining_qty(open_trade,all_orders)
            if expected_qty < self._min_qty():
                self._recover_closed_trade(open_trade,all_orders); self.db.state_set('position_state','FLAT')
            elif position_qty < self._min_qty() or position_qty + self._min_qty()*0.01 < expected_qty:
                self.db.state_set('position_state','RECONCILE_REQUIRED')
                self.notify(f'RECOVERY\nPosition mismatch detected; trading paused for safety.\nexpected≈{expected_qty:.8f} {self.base_asset}, actual≈{position_qty:.8f}')
                self.recovered=True
                return
            else:
                if not open_oco_ids:
                    qty=min(expected_qty,position_qty); self.place_oco(qty,float(open_trade['entry_price'])); self.notify('RECOVERY\nMissing TP/SL detected; recreated OCO')
                self.db.state_set('position_state','OPEN')
        else:
            self.db.state_set('position_state','FLAT')
        self.recovered=True; self.db.log_event('INFO','recovery_complete','Exchange/SQLite reconciliation complete',{'position_qty':position_qty,'bot_trade':bool(open_trade),'open_oco_ids':sorted(open_oco_ids)})
    def _recover_closed_trade(self,trade,all_orders):
        entry_id=str(trade.get('entry_order_id')) if trade.get('entry_order_id') else None
        entry_time=int(next((b.get('time',0) for b in all_orders if str(b.get('orderId'))==entry_id),0) or 0)
        sells=[o for o in all_orders if o.get('side')=='SELL' and o.get('status')=='FILLED' and int(o.get('time',0) or 0)>=entry_time and self._sell_belongs_to_bot(o,all_orders)]
        if not sells:return
        sell=max(sells,key=lambda x:int(x.get('time',0) or 0)); qty=float(sell.get('executedQty',0) or 0); proceeds=float(sell.get('cummulativeQuoteQty',0) or 0); exit_price=proceeds/qty if qty else float(sell.get('price',0) or 0); entry=float(trade['entry_price']); pnl=(exit_price-entry)*min(qty,float(trade['quantity'])); pct=(exit_price/entry-1) if entry else 0
        self.db.close_trade(trade['id'],datetime.fromtimestamp(int(sell.get('transactTime',sell.get('time',0)))/1000,tz=timezone.utc).isoformat(),exit_price,pnl,pct,'TAKE_PROFIT/STOP_LOSS (recovered)',sell.get('orderListId')); self.notify(f'RECOVERY\nPosition closed while bot was offline\nexit≈{exit_price:.8f}\nPnL≈{pnl:.8f} ({pct:.2%})')
    def market_buy(self):
        quote=self.available_quote()*self.position_fraction; min_notional=float((self.filters.get('NOTIONAL') or self.filters.get('MIN_NOTIONAL') or {}).get('minNotional',0))
        if quote<=0 or quote<min_notional:raise RuntimeError(f'Insufficient quote balance: quote={quote}, minNotional={min_notional}')
        cid=f'WILLV4_ENTRY_{uuid.uuid4().hex[:20]}'; order=self.client.order(self.symbol,'BUY','MARKET',quote_order_qty=self.client.decimal_format(quote),new_client_order_id=cid); self.db.save_order(order); qty=float(order.get('executedQty',0)); spent=float(order.get('cummulativeQuoteQty',0)); avg=spent/qty if qty else 0; return order,qty,avg
    def place_oco(self,qty,entry_price):
        qty=self.normalize_qty(qty)
        if qty<=0:raise RuntimeError('Position quantity became zero after LOT_SIZE rounding')
        tp=self.normalize_price(entry_price*(1+self.target_pct)); sl=self.normalize_price(entry_price*(1-self.stop_pct)); tick=float((self.filters.get('PRICE_FILTER') or {}).get('tickSize','0.01')); sl_limit=self.normalize_price(max(sl-tick*2,tick));
        if not (tp > entry_price and sl < entry_price and sl_limit < sl): raise RuntimeError(f'Invalid TP/SL after exchange tick rounding: entry={entry_price}, tp={tp}, sl={sl}, sl_limit={sl_limit}')
        cid=f'WILLV4_OCO_{uuid.uuid4().hex[:20]}'; result=self.client.create_oco_sell(self.symbol,self.client.decimal_format(qty),self.client.decimal_format(tp),self.client.decimal_format(sl),self.client.decimal_format(sl_limit),cid)
        self.db.log_event('INFO','oco_created','Native TP/SL OCO created',result)
        for leg in result.get('orderReports',[]):self.db.save_order(leg)
        return result,tp,sl
    def has_open_position(self):return self.db.open_trade() is not None and self._is_meaningful_position()
    def process(self):
        self.recover_state(); df=fetch_klines(self.client,self.symbol,self.interval,limit=250)
        if len(df)<100:return
        closed=df.iloc[:-1].copy(); ind=calculate_indicators(closed,config_from_env()); last=ind.iloc[-1]; last_time=str(ind.index[-1]); already=self.db.state_get('last_signal_candle')==last_time; open_position=self.has_open_position()
        signal=bool(last.get('long_signal',False))
        if already:return
        if not signal or open_position:
            self.db.state_set('last_signal_candle',last_time); return
        # Do not mark the candle before an entry succeeds; transient API errors can then retry.
        order,qty,entry=self.market_buy(); self.db.log_event('INFO','entry','LONG market entry filled',order); self.db.save_trade(entry_time=utc_now(),symbol=self.symbol,side='LONG',entry_price=entry,quantity=qty,entry_order_id=str(order.get('orderId')),fees=0)
        try:self.place_oco(qty,entry)
        except Exception as e:
            self.db.log_event('ERROR','oco_failed_after_entry',str(e)); self.notify(f'WARNING\nBUY filled but OCO placement failed; recovery will retry.\n{e}'); raise
        self.db.state_set('last_signal_candle',last_time); self.db.state_set('position_state','OPEN'); self.notify(f'LONG ENTRY\n{self.symbol}\nqty={qty}\nentry≈{entry:.8f}\nOrder={order.get("orderId")}')
    def run(self):
        self.setup()
        while True:
            try:self.process()
            except Exception as e:self.db.log_event('ERROR','loop_error',str(e)); self.notify(f'Williams v4 ERROR\n{self.symbol}\n{type(e).__name__}: {e}')
            time.sleep(self.poll_seconds)
if __name__=='__main__':Trader().run()
