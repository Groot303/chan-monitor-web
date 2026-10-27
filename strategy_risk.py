"""V2风险预算。所有上限为模拟参数，只有已知行情及保护证据才能开仓。"""
import json
import math
from decimal import Decimal, ROUND_FLOOR
from paper_trading import PaperError, costs, money, timestamp

RISK_GROUPS = {
    **{s: ('semiconductor','technology') for s in 'NVDA AMD AVGO INTC MU TSM MRVL SNDK SKHY'.split()},
    **{s: ('ai_hardware','technology') for s in 'LITE AAOI'.split()},
    **{s: ('platform_software','technology') for s in 'META GOOG ORCL PLTR'.split()},
    'AAPL': ('consumer_devices','technology'),
    'NOK': ('communications','technology'), 'TSLA': ('mobility','technology'), 'MRNA': ('biotech',),
}
GROUP_LABELS = dict(semiconductor='半导体',technology='科技成长',ai_hardware='AI硬件',
                    platform_software='平台与软件',consumer_devices='消费电子',communications='通信',mobility='出行',biotech='生物科技')
GROUP_LIMITS = {k: (3 if k=='technology' else 2) for k in GROUP_LABELS}


def budget_money(equity, fraction):
    return float((Decimal(str(equity))*Decimal(str(fraction))).quantize(Decimal('.01'),rounding=ROUND_FLOOR))


def planned_loss(qty, entry, stop):
    """有序退出假设下的预算损失，含双边费用及卖出5bp滑点，非跳空亏损保证。"""
    exit_price=money(Decimal(str(stop))*Decimal('.9995'))
    return money(max(entry-exit_price,0)*qty + costs('us','buy',qty,entry) + costs('us','sell',qty,exit_price))


def portfolio_risk(store, db, account, rules):
    equity, used, marks = account['cash'], 0., []
    lots=[dict(r) for r in db.execute('SELECT * FROM lots WHERE account=? AND remaining>0',(account['id'],))]
    pending=[dict(r) for r in db.execute("SELECT * FROM orders WHERE account=? AND status='pending' AND side='buy'",(account['id'],))]
    symbols={r['symbol'] for r in lots+pending}
    quotes={}
    for symbol in {lot['symbol'] for lot in lots}:
        quote=store.market_data.quote('us',symbol,store.clock())
        if not quote or not quote.get('fresh'): raise PaperError('持仓估值未知，暂停新增风险')
        quotes[symbol]=quote; marks.append(timestamp(quote['time']))
    if marks and (max(marks)-min(marks)).total_seconds()>300:
        raise PaperError('持仓估值不同步，暂停新增风险')
    latest_fill=db.execute("SELECT time FROM events WHERE account=? AND kind='fill' ORDER BY id DESC LIMIT 1",(account['id'],)).fetchone()
    if latest_fill and marks and min(marks)<timestamp(latest_fill['time']):
        raise PaperError('持仓估值早于最近成交，暂停新增风险')
    for lot in lots:
        quote=quotes[lot['symbol']]; equity+=lot['remaining']*quote['price']
        stop=db.execute('SELECT * FROM protective_stops WHERE account=? AND lot_id=?',(account['id'],lot['id'])).fetchone()
        if not stop or stop['status']!='active': raise PaperError('存在缺失或已触发的止损保护，等待退出核验')
        entry=db.execute("SELECT payload FROM events WHERE account=? AND kind='fill' AND json_extract(payload,'$.lot_id')=?",
                         (account['id'],lot['id'])).fetchone()
        if not entry: raise PaperError('持仓缺少实际入场风险证据')
        used+=planned_loss(lot['remaining'],max(quote['price'],json.loads(entry['payload'])['price']),stop['price'])
    for order in pending:
        evidence=json.loads(order['signal_json'])
        plan=evidence.get('risk_plan') if isinstance(evidence,dict) else None
        if not plan or plan.get('max_loss_usd',0)<=0: raise PaperError('待成交买单风险证据缺失')
        used+=plan['max_loss_usd']
    counts={key:sum(key in RISK_GROUPS.get(symbol,()) for symbol in symbols) for key in GROUP_LIMITS}
    if any(symbol not in RISK_GROUPS for symbol in symbols): raise PaperError('持仓风险分组未知，暂停新增风险')
    equity=money(equity)
    return dict(known=True,equity=equity,used_risk_usd=money(used),limit_usd=budget_money(equity,rules['portfolio_risk_fraction']),
                single_trade_limit_usd=budget_money(equity,rules['trade_risk_fraction']),
                symbols=sorted(symbols),groups=[dict(id=k,label=GROUP_LABELS[k],count=v,limit=GROUP_LIMITS[k]) for k,v in counts.items()])


def size_entry(store, db, account, symbol, quote, stop, cash_budget, rules):
    groups=RISK_GROUPS.get(symbol)
    if not groups: raise PaperError('标的风险分组尚未核验，不默认归入其他行业')
    risk=portfolio_risk(store,db,account,rules)
    for group in risk['groups']:
        if group['id'] in groups and group['count']>=group['limit']:
            raise PaperError(group['label']+'集中度已达上限（含待成交买单）')
    single=budget_money(risk['equity'],rules['trade_risk_fraction'])
    remaining=money(risk['limit_usd']-risk['used_risk_usd'])
    # 风险上限按分向下取整，防止四舍五入带来一分钱超限。
    maximum=float(Decimal(str(min(single,remaining))).quantize(Decimal('.01'),rounding=ROUND_FLOOR))
    if maximum<=0: raise PaperError('组合总止损风险预算已用尽')
    entry=money(Decimal(str(quote['price']))*Decimal('1.0005'))
    low,high=0,min(1000000,math.floor(cash_budget/entry))
    while low<high:
        mid=(low+high+1)//2
        if planned_loss(mid,entry,stop)<=maximum and money(mid*entry+costs('us','buy',mid,entry))<=cash_budget:
            low=mid
        else: high=mid-1
    if low<1: raise PaperError('风险或资金预算不足以买入1股')
    return low,dict(schema='us-risk-plan-v2',decision_equity=risk['equity'],max_loss_usd=maximum,
        single_trade_limit_usd=single,portfolio_limit_usd=risk['limit_usd'],portfolio_used_usd=risk['used_risk_usd'],
        expected_entry=entry,expected_loss_usd=planned_loss(low,entry,stop),notional_budget_usd=money(cash_budget),
        groups=list(groups),group_contract='manual-risk-groups-v1',gap_policy='reject_not_resize',
        limit_scope='decision_snapshot_and_frozen_fill_budget',known_gap_risk=True)
