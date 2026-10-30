"""基于实际快照的题材接力观察。无网络、交易、资金净流入或因果推断。"""
from collections import defaultdict, deque
from datetime import datetime, timedelta
import hashlib

from cn_limitup_source import SH, valid_attribution

WINDOWS = (5, 15, 30)
MAX_GAP = 90
TRIGGER_SECONDS = 180
TRIGGER_STOCKS = 2
COOLDOWN_SECONDS = 1800


def stamp(value):
    try:
        result = datetime.fromisoformat(value)
        return result if result.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def theme_of(stock, day, observed):
    note = {key: stock.get(key) for key in ('name', 'theme', 'concepts', 'source_event_time')}
    note['attribution_observed_at'] = stock.get('attribution_observed_at') or observed.isoformat()
    event = stamp(note.get('source_event_time'))
    return note['theme'] if valid_attribution(note, day, observed) and event and event <= observed else None


def phase(observed, session):
    start, end, pause = session
    if not start <= observed <= end:
        return None
    if not pause:
        return start, end
    if observed < pause[0]:
        return start, pause[0]
    if observed >= pause[1]:
        return pause[1], end
    return None


def frame(snapshot, day, session):
    observed = stamp(snapshot.get('observed_at'))
    if not observed or snapshot.get('trade_date') != day or observed.astimezone(SH).date().isoformat() != day:
        return None
    block = phase(observed, session)
    if not block:
        return None
    quality = snapshot.get('coherent') is True
    sources = snapshot.get('sources', {})
    for key in ('up', 'broken'):
        source = sources.get(key, {})
        received = stamp(source.get('observed_at'))
        quality = quality and source.get('status') == 'ok' and source.get('trade_date') == day
        quality = quality and received is not None and 0 <= (observed-received).total_seconds() <= MAX_GAP
    stocks = {}
    for key, state in (('up', 'sealed'), ('broken', 'broken')):
        rows = snapshot.get('pools', {}).get(key)
        if not isinstance(rows, list):
            quality = False
            continue
        for stock in rows:
            code = stock.get('code')
            if code in stocks or not isinstance(code, str) or stock.get('state') != state:
                quality = False
            stocks[code] = stock
    return dict(time=observed, block=block, valid=bool(quality), stocks=stocks)


def continuous(frames):
    return bool(frames) and all(f['valid'] for f in frames) and all(
        a['block'] == b['block'] and 0 < (b['time']-a['time']).total_seconds() <= MAX_GAP
        for a, b in zip(frames, frames[1:]))


def triggers(frames, day):
    """只认相邻有效快照的sealed→broken，基线炸板与断网后的状态不算触发。"""
    queues = defaultdict(deque)
    last = {}
    previous = None
    events = []
    for index, current in enumerate(frames):
        if not current['valid']:
            previous = None
            queues.clear()
            continue
        if previous is None or not continuous([previous, current]):
            previous = current
            queues.clear()
            continue
        for code, stock in current['stocks'].items():
            prior = previous['stocks'].get(code)
            if stock['state'] != 'broken' or not prior or prior['state'] != 'sealed':
                continue
            theme = theme_of(prior, day, previous['time'])
            if not theme or stock['name'] != prior['name']:
                continue
            queues[theme['id']].append(dict(code=code, name=stock['name'], observed_at=current['time'].isoformat(), theme=theme))
        for key, queue in queues.items():
            while queue and (current['time']-stamp(queue[0]['observed_at'])).total_seconds() > TRIGGER_SECONDS:
                queue.popleft()
            unique = {item['code']: item for item in queue}
            if len(unique) < TRIGGER_STOCKS or (key in last and (current['time']-last[key]).total_seconds() < COOLDOWN_SECONDS):
                continue
            last[key] = current['time']
            identity = hashlib.sha256((day+key+current['time'].isoformat()).encode()).hexdigest()[:20]
            events.append(dict(id=identity, index=index, observed_at=current['time'].isoformat(),
                theme=next(iter(unique.values()))['theme'], opened=list(unique.values())))
        previous = current
    return events


def cohort_metrics(frames, anchor, baseline, day, trigger_theme):
    """在比较区间首次出现时锁定归因。未知者不因后续补归因变成封板净增。"""
    mapping = {}
    names = {}
    renamed = set()
    changed = set()
    for f in frames:
        for code, stock in f['stocks'].items():
            note = theme_of(stock, day, f['time'])
            if code not in mapping:
                mapping[code] = note
                names[code] = stock['name']
            elif stock['name'] != names[code]:
                renamed.add(code)
            elif note and mapping[code] and note['id'] != mapping[code]['id']:
                changed.add(code)
    for code in renamed:
        mapping[code] = None
    groups = {}
    for code, theme in mapping.items():
        if theme:
            groups.setdefault(theme['id'], dict(id=theme['id'], name=theme['name'], trigger=theme['id']==trigger_theme,
                start_count=0, end_count=0, baseline_count=0 if baseline else None,
                members=[], new_seen={}, resealed={}, opened={}, pool_exits={}))
            groups[theme['id']]['members'].append(dict(code=code,name=names[code]))
    def sealed(f, code):
        return f['stocks'].get(code, {}).get('state') == 'sealed'
    def add_count(f, field):
        for code, theme in mapping.items():
            if theme and sealed(f, code):
                groups[theme['id']][field] += 1
    add_count(anchor, 'start_count')
    add_count(frames[-1], 'end_count')
    if baseline:
        add_count(baseline, 'baseline_count')
    post = [f for f in frames if f['time'] >= anchor['time']]
    ever = {code for f in frames if f['time'] <= anchor['time'] for code in f['stocks']}
    for a, b in zip(post, post[1:]):
        for code in set(a['stocks']) | set(b['stocks']):
            theme = mapping.get(code)
            if not theme:
                continue
            old, new = a['stocks'].get(code), b['stocks'].get(code)
            prior_state = old['state'] if old else None
            state = new['state'] if new else None
            kind = ('new_seen' if code not in ever and state=='sealed' else
                    'resealed' if prior_state=='broken' and state=='sealed' else
                    'opened' if prior_state=='sealed' and state=='broken' else
                    'pool_exits' if old and not new else None)
            if kind:
                groups[theme['id']][kind][code] = dict(code=code, name=names[code], observed_at=b['time'].isoformat())
        ever.update(b['stocks'])
    for group in groups.values():
        group['net_delta'] = group['end_count'] - group['start_count']
        group['before_delta'] = group['start_count'] - group['baseline_count'] if baseline else None
        group['acceleration'] = group['net_delta'] - group['before_delta'] if baseline else None
        for key in ('new_seen', 'resealed', 'opened', 'pool_exits'):
            group[key] = sorted(group[key].values(), key=lambda s: s['code'])
        group['gained']=[dict(code=s['code'],name=s['name']) for s in group['members']
            if not sealed(anchor,s['code']) and sealed(frames[-1],s['code'])]
        group['lost']=[dict(code=s['code'],name=s['name']) for s in group['members']
            if sealed(anchor,s['code']) and not sealed(frames[-1],s['code'])]
    count_all = lambda f: sum(s['state']=='sealed' for s in f['stocks'].values())
    return dict(rows=sorted(groups.values(), key=lambda g: (-g['net_delta'], -(g['acceleration'] or 0), g['name'])),
        unknown_stocks=sum(theme is None for theme in mapping.values()),
        fixed_theme_changes=len(changed), renamed_stocks=len(renamed),
        pool_net_delta=count_all(frames[-1])-count_all(anchor),
        pool_before_delta=count_all(anchor)-count_all(baseline) if baseline else None,
        scope='fixed_verified_cohort', partial=any(theme is None for theme in mapping.values()))


def window_result(frames, event, minutes, now, day):
    index = event['index']
    anchor = frames[index]
    duration = timedelta(minutes=minutes)
    target = anchor['time'] + duration
    result = dict(minutes=minutes, target_at=target.isoformat(), start_at=anchor['time'].isoformat(),
        end_at=None, rows=[], before_status='unavailable', unknown_stocks=None)
    if target > anchor['block'][1]:
        return dict(result, status='session_break', reason='观察窗口跨越午休或收盘，不跨休市拼接。')
    if now < target:
        return dict(result, status='pending', reason='观察时间尚未到达，不提前计算后续结果。')
    end = next((i for i in range(index+1, len(frames)) if frames[i]['time'] >= target), None)
    if end is None:
        return dict(result, status='pending' if now <= target+timedelta(seconds=MAX_GAP) else 'incomplete',
            reason='等待窗口结束后的实际采样。' if now <= target+timedelta(seconds=MAX_GAP) else '窗口结束处缺少实际快照，未用旧数据替代。')
    post = frames[index:end+1]
    if (frames[end]['time']-target).total_seconds() > MAX_GAP or not continuous(post):
        return dict(result, status='incomplete', reason='后续快照存在缺失、不完整或采样间隔超过90秒。')
    before_target = anchor['time'] - duration
    start = next((i for i in range(index, -1, -1) if frames[i]['time'] <= before_target), None)
    before = frames[start:index+1] if start is not None else []
    baseline_ok = bool(before) and (before_target-before[0]['time']).total_seconds() <= MAX_GAP and continuous(before)
    combined = frames[start:end+1] if baseline_ok else post
    metrics = cohort_metrics(combined, anchor, before[0] if baseline_ok else None, day, event['theme']['id'])
    return dict(result, **metrics, status='complete', reason=None, end_at=frames[end]['time'].isoformat(),
        observed_duration_seconds=(frames[end]['time']-anchor['time']).total_seconds(),
        before_status='complete' if baseline_ok else 'insufficient',
        baseline_at=before[0]['time'].isoformat() if baseline_ok else None,
        before_duration_seconds=(anchor['time']-before[0]['time']).total_seconds() if baseline_ok else None)


def analyze(snapshots, day, now, session):
    result = dict(schema='cn-theme-relay-v1', mode='research_only', trade_date=day,
        server_time=now.isoformat(), latest_observed_at=None, events=[],
        rules=dict(trigger_seconds=TRIGGER_SECONDS, trigger_stocks=TRIGGER_STOCKS, cooldown_seconds=COOLDOWN_SECONDS,
                   windows_minutes=list(WINDOWS), max_gap_seconds=MAX_GAP),
        scope='涨跌停观察池中的已核验题材样本，不代表全市场资金流向或因果关系。')
    if not session:
        return dict(result, status='unavailable', message='交易日历暂不可用，无法核验观察窗口。')
    frames = []
    for snapshot in snapshots:
        f = frame(snapshot, day, session)
        if f and f['time'] <= now:
            frames.append(f)
    # 同一接收时刻只保留最后一份，重复采样不能制造额外事件。
    frames = sorted({f['time']: f for f in frames}.values(), key=lambda f: f['time'])
    if not frames:
        return dict(result, status='unavailable', message='该日暂无交易时段内的分钟快照；每日末次快照不足以还原接力过程。')
    result['latest_observed_at'] = frames[-1]['time'].isoformat()
    result['quality'] = dict(frames=len(frames), invalid_frames=sum(not f['valid'] for f in frames))
    found = triggers(frames, day)
    for event in reversed(found[-12:]):
        windows = [window_result(frames, event, n, now, day) for n in WINDOWS]
        result['events'].append({k: v for k, v in event.items() if k!='index'} | {'windows': windows})
    return dict(result, status='ready' if found else 'collecting',
        message='按实际接收的快照观察先后变化，不证明资金转移。' if found else '暂无达到“3分钟内2只不同股票开板”的观察事件，不表示当日没有炸板。')
