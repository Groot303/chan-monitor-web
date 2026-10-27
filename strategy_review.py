"""依据不可变成交分摊与实际估值点复盘；旧数据不足时明确留空。"""
import json
from paper_trading import money, timestamp


def common_comparison(db):
    accounts={r['strategy_id']:dict(r) for r in db.execute(
        'SELECT m.strategy_id,a.id,a.created FROM managed_accounts m JOIN accounts a ON a.id=m.account '
        'WHERE m.strategy_id IN (?,?)',('us-daily-30m-v1','us-daily-30m-v2-risk'))}
    if len(accounts)!=2: return dict(status='waiting',reason='等待两个版本建立独立账户')
    start=max(timestamp(a['created']) for a in accounts.values())
    curves={key:{r['time']:r['value'] for r in db.execute('SELECT time,value FROM equity WHERE account=? ORDER BY time',(a['id'],))
                  if timestamp(r['time'])>=start} for key,a in accounts.items()}
    keys=list(curves);common=sorted(set(curves[keys[0]]) & set(curves[keys[1]]),key=timestamp)
    if len(common)<2: return dict(status='waiting',reason='等待双方至少两个同一时间的估值点，不比较不同起点的累计收益')
    first,last=common[0],common[-1]
    return dict(status='known',since=first,as_of=last,matched_points=len(common),
                returns={key:(values[last]/values[first]-1)*100 for key,values in curves.items()})


def summarize(trades):
    closed=[t for t in trades if t['closed']]
    known_r=[t['r_multiple'] for t in closed if t['r_multiple'] is not None]
    return dict(closed_trades=len(closed),open_trades=sum(not t['closed'] for t in trades),
        realized_pnl=money(sum(t['realized_pnl'] for t in trades)),
        win_rate_pct=sum(t['realized_pnl']>0 for t in closed)/len(closed)*100 if closed else None,
        average_r=sum(known_r)/len(known_r) if known_r else None,r_samples=len(known_r),
        average_holding_hours=sum(t['holding_hours'] for t in closed)/len(closed) if closed else None)


def review(db, account, state):
    trades={};unattributed=0
    orders={o['id']:o for o in state['orders']}
    for fill in state['fills']:
        if fill['side']=='buy':
            lot_id=fill.get('lot_id')
            if lot_id is None:
                unattributed+=1;continue
            trades[lot_id]=dict(lot_id=lot_id,symbol=fill['symbol'],entry_type=fill.get('entry_signal_type') or 'unknown',
                entry_time=fill['market_bar']['open_time'],entry_price=fill['price'],qty=fill['qty'],sold=0,
                initial_risk_usd=fill.get('initial_risk_usd'),realized_pnl=0.,exits=[],exit_time=None)
            continue
        allocations=fill.get('lot_allocations') or []
        if not allocations:
            unattributed+=1;continue
        net=money(fill['qty']*fill['price']-fill['fee']); assigned=0.
        try: evidence=json.loads(orders.get(fill['order_id'],{}).get('signal_json','{}'))
        except (ValueError,TypeError): evidence={}
        kind='automatic_stop' if fill['execution_reason']=='automatic_stop' else (evidence.get('signal') or {}).get('type','unknown')
        for index,part in enumerate(allocations):
            net_part=money(net-assigned) if index==len(allocations)-1 else money(net*part['qty']/fill['qty'])
            assigned=money(assigned+net_part)
            trade=trades.get(part['lot_id'])
            if trade is None:
                unattributed+=1;continue
            trade['sold']+=part['qty'];trade['realized_pnl']=money(trade['realized_pnl']+net_part-part['basis'])
            trade['exit_time']=fill['market_bar']['open_time']
            trade['exits'].append(dict(type=kind,qty=part['qty'],price=fill['price'],time=trade['exit_time']))
    has_marks=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='strategy_position_marks'").fetchone()
    for trade in trades.values():
        trade['closed']=trade['sold']==trade['qty']
        end=trade['exit_time'] if trade['closed'] else state['server_time']
        trade['holding_hours']=(timestamp(end)-timestamp(trade['entry_time'])).total_seconds()/3600
        risk=trade['initial_risk_usd']
        trade['r_multiple']=trade['realized_pnl']/risk if trade['closed'] and risk and risk>0 else None
        reasons={e['type'] for e in trade['exits']}
        trade['exit_reason']=next(iter(reasons)) if len(reasons)==1 else 'mixed' if reasons else 'open'
        marks=list(db.execute('SELECT price,bar_time FROM strategy_position_marks WHERE account=? AND lot_id=? ORDER BY bar_time',
                              (account['id'],trade['lot_id']))) if has_marks else []
        # 已平仓后不再采样；入口/出口均为已执行开盘，退出根的high/low不参与。
        values=[r['price'] for r in marks if timestamp(trade['entry_time'])<=timestamp(r['bar_time'])<=timestamp(end)]
        values.extend(e['price'] for e in trade['exits'])
        trade['observed_mark_count']=len(marks)
        trade['observed_mae_pct']=min(0,(min(values)/trade['entry_price']-1)*100) if values else None
        trade['observed_mfe_pct']=max(0,(max(values)/trade['entry_price']-1)*100) if values else None
        trade['excursion_basis']='observed_marks_and_exit_prices_only_not_intrabar_extremes'
    result=list(trades.values())
    entries={kind:summarize([t for t in result if t['entry_type']==kind]) for kind in ('2B','3B','unknown')}
    exits={kind:summarize([t for t in result if t['closed'] and t['exit_reason']==kind])
           for kind in ('1S','2S','3S','automatic_stop','mixed','unknown')}
    return dict(summary=summarize(result),by_entry=entries,by_exit=exits,trades=result[-100:],
                unattributed_legacy_fills=unattributed,statistics_basis='one_buy_lot_to_full_exit',
                excursion_basis='observed_marks_only',performance_verified=False)
