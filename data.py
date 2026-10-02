import time, pandas as pd, requests
BASE_URL='https://testnet.binance.vision'
def _frame(rows):
    cols=['open_time','open','high','low','close','volume','close_time','quote_volume','trades','taker_buy_base','taker_buy_quote','ignore']
    df=pd.DataFrame(rows,columns=cols)
    if df.empty:return df
    for c in ['open','high','low','close','volume']:df[c]=pd.to_numeric(df[c],errors='coerce')
    df['open_time']=pd.to_datetime(df['open_time'],unit='ms',utc=True); df['close_time']=pd.to_datetime(df['close_time'],unit='ms',utc=True)
    return df.set_index('open_time')[['open','high','low','close','volume','close_time']].dropna()
def fetch_klines(client_or_symbol,symbol_or_interval,interval=None,limit=200,start=None,end=None):
    # Live mode: fetch_klines(client, symbol, interval, limit=...). Backtest mode: fetch_klines(symbol, interval, start, end).
    if hasattr(client_or_symbol,'klines'):
        client=client_or_symbol; symbol=symbol_or_interval; iv=interval; return _frame(client.klines(symbol,iv,limit=limit))
    symbol=client_or_symbol; iv=symbol_or_interval; start=interval if start is None else start
    params={'symbol':symbol,'interval':iv,'limit':1000}
    if start: params['startTime']=int(pd.Timestamp(start,tz='UTC').timestamp()*1000)
    if end: params['endTime']=int(pd.Timestamp(end,tz='UTC').timestamp()*1000)
    rows=[]; cursor=params.get('startTime')
    while True:
        p=dict(params); p['startTime']=cursor if cursor is not None else p.get('startTime')
        r=requests.get(BASE_URL+'/api/v3/klines',params={k:v for k,v in p.items() if v is not None},timeout=20); r.raise_for_status(); batch=r.json()
        if not batch:break
        rows.extend(batch)
        if len(batch)<1000:break
        cursor=int(batch[-1][0])+1; time.sleep(0.05)
        if end and cursor>=int(pd.Timestamp(end,tz='UTC').timestamp()*1000):break
    return _frame(rows)
def save_csv(df,path):df.reset_index().to_csv(path,index=False)
