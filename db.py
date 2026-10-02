import json, sqlite3
from pathlib import Path
class Database:
    def __init__(self,path='data/trader.sqlite3'):
        Path(path).parent.mkdir(parents=True,exist_ok=True); self.conn=sqlite3.connect(path,check_same_thread=False,timeout=10); self.conn.row_factory=sqlite3.Row; self.conn.execute('PRAGMA busy_timeout=10000'); self.conn.execute('PRAGMA journal_mode=WAL'); self.conn.execute('PRAGMA synchronous=NORMAL'); self.init()
    def init(self):
        self.conn.executescript('''CREATE TABLE IF NOT EXISTS bot_state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS candles(symbol TEXT NOT NULL,interval TEXT NOT NULL,open_time TEXT NOT NULL,open REAL,high REAL,low REAL,close REAL,volume REAL,PRIMARY KEY(symbol,interval,open_time));
        CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,symbol TEXT,side TEXT,type TEXT,order_id TEXT,order_list_id TEXT,client_order_id TEXT,status TEXT,price REAL,stop_price REAL,quantity REAL,raw_json TEXT);
        CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY AUTOINCREMENT,entry_time TEXT,exit_time TEXT,symbol TEXT,side TEXT,entry_price REAL,exit_price REAL,quantity REAL,pnl REAL,pnl_pct REAL,reason TEXT,entry_order_id TEXT,exit_order_list_id TEXT,fees REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,level TEXT,event TEXT,message TEXT,raw_json TEXT);'''); self.conn.commit()
    def state_get(self,key,default=None):
        r=self.conn.execute('SELECT value FROM bot_state WHERE key=?',(key,)).fetchone(); return default if r is None else r['value']
    def state_set(self,key,value):
        self.conn.execute('INSERT INTO bot_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value))); self.conn.commit()
    def log_event(self,level,event,message,raw=None):
        self.conn.execute('INSERT INTO events(level,event,message,raw_json) VALUES(?,?,?,?)',(level,event,message,json.dumps(raw) if raw is not None else None)); self.conn.commit()
    def save_order(self,data):
        oid=str(data.get('orderId')) if data.get('orderId') is not None else None
        if oid:
            r=self.conn.execute('SELECT id FROM orders WHERE symbol=? AND order_id=?',(data.get('symbol'),oid)).fetchone()
            vals=(data.get('side'),data.get('type'),str(data.get('orderListId')) if data.get('orderListId') is not None else None,data.get('clientOrderId'),data.get('status'),float(data['price']) if data.get('price') not in (None,'') else None,float(data['stopPrice']) if data.get('stopPrice') not in (None,'') else None,float(data['origQty']) if data.get('origQty') not in (None,'') else None,json.dumps(data))
            if r:
                self.conn.execute('UPDATE orders SET side=?,type=?,order_list_id=?,client_order_id=?,status=?,price=?,stop_price=?,quantity=?,raw_json=? WHERE id=?',vals+(r['id'],)); self.conn.commit(); return
        self.conn.execute('INSERT INTO orders(symbol,side,type,order_id,order_list_id,client_order_id,status,price,stop_price,quantity,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(data.get('symbol'),data.get('side'),data.get('type'),oid,str(data.get('orderListId')) if data.get('orderListId') is not None else None,data.get('clientOrderId'),data.get('status'),float(data['price']) if data.get('price') not in (None,'') else None,float(data['stopPrice']) if data.get('stopPrice') not in (None,'') else None,float(data['origQty']) if data.get('origQty') not in (None,'') else None,json.dumps(data))); self.conn.commit()
    def open_trade(self):
        r=self.conn.execute('SELECT * FROM trades WHERE exit_time IS NULL ORDER BY id DESC LIMIT 1').fetchone(); return dict(r) if r else None
    def save_trade(self,**kwargs):
        cols=','.join(kwargs); self.conn.execute(f'INSERT INTO trades({cols}) VALUES({",".join("?" for _ in kwargs)})',tuple(kwargs.values())); self.conn.commit()
    def close_trade(self,trade_id,exit_time,exit_price,pnl,pnl_pct,reason,exit_order_list_id=None,fees=0):
        self.conn.execute('UPDATE trades SET exit_time=?,exit_price=?,pnl=?,pnl_pct=?,reason=?,exit_order_list_id=?,fees=? WHERE id=? AND exit_time IS NULL',(exit_time,exit_price,pnl,pnl_pct,reason,exit_order_list_id,fees,trade_id)); self.conn.commit()
    def recent_orders(self,symbol,limit=100): return [dict(r) for r in self.conn.execute('SELECT * FROM orders WHERE symbol=? ORDER BY id DESC LIMIT ?',(symbol,limit)).fetchall()]
