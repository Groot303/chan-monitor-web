"""A股连板研究数据：只读公开快照；保留来源、日期和字段口径。"""
import hashlib
import json
import math
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SH=ZoneInfo('Asia/Shanghai')
EM='https://push2ex.eastmoney.com/'
KPL='https://apphq.longhuvip.com/w1/api/index.php'
POOL_PATHS=dict(up='getTopicZTPool',broken='getTopicZBPool',previous='getYesterdayZTPool',down='getTopicDTPool')
UNKNOWN_THEMES={'无','暂无','无题材','未知','--','-','none','null'}


def valid_attribution(note,day,observed):
    """同日真实归因可沿用；不将昨日或未来才采到的归因带入当前快照。"""
    try:
        theme=note['theme'];event=datetime.fromisoformat(note['source_event_time'])
        seen=datetime.fromisoformat(note['attribution_observed_at'])
        return (isinstance(note['name'],str) and theme['trade_date']==day and theme['source']=='kaipanla'
            and isinstance(theme['name'],str) and theme['name'].strip().lower() not in UNKNOWN_THEMES
            and bool(theme['name'].strip()) and event.astimezone(SH).date().isoformat()==day
            and seen.astimezone(SH).date().isoformat()==day and seen<=observed and not note.get('conflict'))
    except (KeyError,TypeError,ValueError):return False


def number(value, *, minimum=0):
    if type(value) not in (int,float) or not math.isfinite(value) or value<minimum:return None
    return float(value)


def integer(value):
    n=number(value)
    return int(n) if n is not None and n.is_integer() else None


def seal_time(value):
    if value is None:return None
    text=str(value).zfill(6)
    try:return datetime.strptime(text,'%H%M%S').strftime('%H:%M:%S')
    except ValueError:return None


class ResearchClock:
    def __init__(self,sessions=None):
        if sessions is None:
            from paper_market import ExchangeSessions
            sessions=ExchangeSessions()
        self.sessions=sessions

    def session(self,day):
        return self.sessions.session('cn',day)

    def context(self,now):
        local=now.astimezone(SH)
        for offset in range(24):
            day=(local.date()-timedelta(days=offset)).isoformat()
            session=self.sessions.session('cn',day)
            if not session:continue
            start,end,pause=session
            if offset==0 and now<start-timedelta(minutes=15):continue
            active=(offset==0 and start-timedelta(minutes=15)<=now<=end+timedelta(minutes=10)
                    and not (pause and pause[0]<=now<pause[1]))
            expected=min(now,end+timedelta(minutes=5))
            if pause and pause[0]<=now<pause[1]:expected=pause[0]
            return dict(trade_date=day,active=active,expected_at=expected.isoformat(),
                        phase='trading' if active else 'closed',session_close=end.isoformat())
        return dict(trade_date=None,active=False,phase='unknown',error='交易日历暂不可用')


def normalize_pool(payload,kind,day):
    if not isinstance(payload,dict) or payload.get('rc')!=0:raise ValueError('来源未返回有效响应')
    data=payload.get('data')
    if not isinstance(data,dict) or str(data.get('qdate'))!=day.replace('-',''):
        raise ValueError('行情日期不匹配，未作为当前交易日数据使用')
    pool=data.get('pool')
    total=integer(data.get('tc'))
    if not isinstance(pool,list) or total is None:raise ValueError('观察池结构不完整')
    rows=[];seen=set()
    for raw in pool:
        if not isinstance(raw,dict):raise ValueError('股票字段格式异常')
        code=raw.get('c');name=raw.get('n')
        if not isinstance(code,str) or not re.fullmatch(r'\d{6}',code) or code in seen or not isinstance(name,str):
            raise ValueError('股票代码缺失或重复')
        seen.add(code)
        price=number(raw.get('p'));change=number(raw.get('zdp'),minimum=-100)
        if price is None or price<=0 or change is None:raise ValueError('价格或涨幅缺失')
        count=integer(raw.get('lbc')) if kind=='up' else None
        if kind=='up' and (count is None or not 1<=count<=100):raise ValueError('连板高度不明')
        rows.append(dict(code=code,name=name[:50],price=price/1000,change_pct=change,
            state={'up':'sealed','broken':'broken','previous':'previous','down':'down'}[kind],
            boards=count,yesterday_boards=integer(raw.get('ylbc')) if kind=='previous' else None,
            seal_amount=number(raw.get('fund')) if kind in ('up','down') else None,
            open_count=integer(raw.get('zbc')) if kind in ('up','broken') else None,
            first_seal=seal_time(raw.get('fbt')),last_seal=seal_time(raw.get('lbt')),
            turnover_pct=number(raw.get('hs')),amount=number(raw.get('amount')),
            industry=raw.get('hybk') if isinstance(raw.get('hybk'),str) else None,
            limit_up_price=(number(raw.get('ztp'))/1000) if number(raw.get('ztp')) is not None else None,
            recent_stat=raw.get('zttj') if isinstance(raw.get('zttj'),dict) else None,
            theme=None,concepts=[],attribution_status='unknown',price_source='eastmoney'))
    if total<len(rows):raise ValueError('来源总数与股票列表矛盾')
    return rows,dict(complete=total==len(rows),reported_total=total,returned_count=len(rows))


def normalize_attributions(payload,day):
    if not isinstance(payload,dict) or str(payload.get('errcode'))!='0':raise ValueError('题材来源暂不可用')
    info=payload.get('info')
    if not isinstance(info,list) or not info or not isinstance(info[0],list):raise ValueError('题材来源结构变更')
    result={}
    for row in info[0]:
        if not isinstance(row,list) or len(row)<23:raise ValueError('题材字段结构不完整')
        code,name,event,reason,concepts,theme=row[0],row[1],row[4],row[5],row[12],row[19]
        if not isinstance(code,str) or not re.fullmatch(r'\d{6}',code):raise ValueError('题材股票代码异常')
        if type(event) not in (int,float):continue
        try:event_time=datetime.fromtimestamp(event,SH)
        except (ValueError,OverflowError,OSError):continue
        # 日期只证明该条来源事件属于本交易日，不能冒充抓取时间或网站首次发现时间。
        if event_time.date().isoformat()!=day:continue
        if not isinstance(name,str) or not isinstance(reason,str) or not reason.strip():continue
        label=reason.strip()[:120]
        if label.lower() in UNKNOWN_THEMES:continue
        theme_id=str(theme) if isinstance(theme,(str,int)) and str(theme) else hashlib.sha256(label.encode()).hexdigest()[:12]
        result[code]=dict(name=name,theme=dict(id='kpl:'+theme_id,name=label,source='kaipanla',trade_date=day),
            concepts=[s.strip()[:80] for s in re.split('[、,，;；]',concepts) if s.strip()][:20] if isinstance(concepts,str) else [],
            source_event_time=event_time.isoformat())
    return result


class PublicLimitupSource:
    def __init__(self,clock=None):self.clock=clock or (lambda:datetime.now(timezone.utc))

    def request(self,key,day):
        started=self.clock().isoformat()
        if key in POOL_PATHS:
            params=dict(ut='7eea3edcaed734bea9cbfc24409ed989',dpt='wz.ztzt',Pageindex=0,pagesize=10000,
                        sort='zs:desc' if key=='previous' else 'fund:asc' if key=='down' else 'fbt:asc',date=day.replace('-',''))
            url=EM+POOL_PATHS[key]+'?'+urllib.parse.urlencode(params);body=None
        else:
            params=dict(a='DailyLimitPerformance',c='HomeDingPan',Order='0',st='2000',Index='0',
                        PidType=key[-1],PhoneOSNew='1',VerSion='5.21.0.2',Type='4',apiv='w42')
            url=KPL;body=urllib.parse.urlencode(params).encode()
        req=urllib.request.Request(url,data=body,headers={'User-Agent':'ChanResearch/1.0','Referer':'https://quote.eastmoney.com/'})
        with urllib.request.urlopen(req,timeout=8) as response:
            raw=response.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:raise ValueError('来源数据超过安全读取大小')
        return dict(key=key,started_at=started,received_at=self.clock().isoformat(),payload=json.loads(raw))

    def fetch(self,day):
        keys=list(POOL_PATHS)+['attribution'+str(i) for i in range(1,6)]
        def fetch_one(key):
            try:return self.request(key,day)
            except Exception as exc:return dict(key=key,received_at=self.clock().isoformat(),error='来源请求失败：'+type(exc).__name__)
        with ThreadPoolExecutor(max_workers=4) as executor:return list(executor.map(fetch_one,keys))


def build_snapshot(envelopes,context,now,prior_attributions=None):
    day=context['trade_date'];sources={};pools={};notes={}
    for envelope in envelopes:
        key=envelope['key'];meta=dict(source='eastmoney' if key in POOL_PATHS else 'kaipanla',
            observed_at=envelope['received_at'],request_started_at=envelope.get('started_at'),requested_date=day,status='error',
            exchange_time_verified=False)
        try:
            if envelope.get('error'):raise ValueError(envelope['error'])
            if key in POOL_PATHS:
                rows,quality=normalize_pool(envelope['payload'],key,day);pools[key]=rows
                meta.update(status='ok' if quality['complete'] else 'partial',trade_date=day,**quality)
            else:
                normalized=normalize_attributions(envelope['payload'],day)
                for code,note in normalized.items():
                    note.update(attribution_observed_at=envelope['received_at'],attribution_basis='current_snapshot')
                    if code in notes and notes[code]['theme']!=note['theme']:
                        notes[code]['conflict']=True
                    elif code not in notes or not notes[code].get('conflict'):notes[code]=note
                meta.update(status='ok' if normalized else 'empty',returned_count=len(normalized),event_date=day if normalized else None)
        except (ValueError,TypeError,KeyError) as exc:meta['error']=str(exc)[:140]
        sources[key]=meta
    up=pools.get('up');broken=pools.get('broken');previous=pools.get('previous');down=pools.get('down')
    for code,note in (prior_attributions or {}).items():
        if code not in notes and valid_attribution(note,day,now):
            notes[code]={**note,'attribution_basis':'earlier_today'}
    for rows in pools.values():
        for stock in rows:
            note=notes.get(stock['code'])
            if note and note['name']==stock['name'] and valid_attribution(note,day,now):
                stock.update(theme=note['theme'],concepts=note['concepts'],source_event_time=note['source_event_time'],
                    attribution_observed_at=note['attribution_observed_at'],attribution_basis=note['attribution_basis'],attribution_status='supplier_attribution')
    up_codes={s['code'] for s in up or []};broken_codes={s['code'] for s in broken or []}
    overlap=up_codes & broken_codes
    coherent=(sources.get('up',{}).get('status')=='ok' and sources.get('broken',{}).get('status')=='ok' and not overlap)
    if coherent:
        coherent=abs((datetime.fromisoformat(sources['up']['observed_at'])-datetime.fromisoformat(sources['broken']['observed_at'])).total_seconds())<=30
    for rows in (up,broken):
        for stock in rows or []:
            if stock['code'] in overlap:stock['state']='ambiguous'
    complete=lambda key:sources.get(key,{}).get('status')=='ok'
    progression=[]
    if previous is not None:
        for height in sorted({s['yesterday_boards'] for s in previous if s['yesterday_boards']}):
            yesterday=[s for s in previous if s['yesterday_boards']==height]
            advanced=[s for s in up or [] if s['code'] in {r['code'] for r in yesterday} and s['boards']==height+1]
            known=coherent and complete('previous')
            progression.append(dict(from_boards=height,candidates=len(yesterday),currently_advanced=len(advanced) if known else None,
                rate_pct=len(advanced)/len(yesterday)*100 if known else None))
        for stock in previous:
            current=next((s for s in up or [] if s['code']==stock['code']),None)
            stock['current_boards']=current['boards'] if current else None
            stock['currently_sealed']=(stock['code'] in up_codes) if complete('up') else None
    themes,coverage=attribution_summary(pools,sources,coherent)
    total=(len(up or [])+len(broken or []))
    return dict(schema='cn-limitup-research-v1',attribution_contract=2,market='cn',mode='research_only',trade_date=day,
        observed_at=now.isoformat(),market_context=context,sources=sources,pools=pools,coherent=coherent,
        summary=dict(sealed_count=len(up) if up is not None and complete('up') else None,
            broken_count=len(broken) if broken is not None and complete('broken') else None,
            down_count=len(down) if down is not None and complete('down') else None,
            observed_height=max((s['boards'] for s in up or []),default=None),
            snapshot_open_ratio_pct=len(broken)/total*100 if coherent and total else None,**coverage),
        themes=themes,
        progression=progression,coverage_note='涨跌停池使用东财来源统计范围，不等同于开盘啦全站统计；题材为开盘啦供应商当日归因，行业和其他概念另列。',
        limitations=['快照可能遗漏采样间的开合，不代表逐笔成交或排队证据。','网站首次观察时间与供应商首封、回封时间分别保存。'])


def attribution_summary(pools,sources,coherent):
    """覆盖率不足时只给已匹配下限，不能把未分类误报为某题材零炸板。旧快照亦适用。"""
    up=pools.get('up',[]);broken=pools.get('broken',[]);themes={}
    complete=lambda key:sources.get(key,{}).get('status')=='ok'
    for stock in up+broken:
        theme=stock['theme'];key=theme['id'] if theme else 'unclassified'
        group=themes.setdefault(key,dict(id=key,name=theme['name'] if theme else '题材待核验',
            source='kaipanla' if theme else None,stocks=[],sealed_count=0,broken_count=0,highest_boards=None))
        if stock['code'] not in group['stocks']:group['stocks'].append(stock['code'])
        if stock['state']=='sealed':group['sealed_count']+=1
        if stock['state']=='broken':group['broken_count']+=1
        if stock['boards'] is not None:group['highest_boards']=max(group['highest_boards'] or 0,stock['boards'])
    covered=sum(s['theme'] is not None for s in up)
    broken_covered=sum(s['theme'] is not None for s in broken)
    broken_complete=coherent and complete('broken') and broken_covered==len(broken)
    for group in themes.values():
        group['known_broken_count']=group['broken_count']
        group['broken_count_complete']=broken_complete
        if not complete('up'):group['sealed_count']=None
        if not broken_complete:group['broken_count']=None
    coverage=dict(attributed_sealed=covered,attribution_total=len(up),attributed_broken=broken_covered,
        broken_attribution_total=len(broken),unattributed_broken=len(broken)-broken_covered,broken_attribution_complete=broken_complete)
    return sorted(themes.values(),key=lambda t:(-(t['sealed_count'] or 0),-(t['highest_boards'] or 0),t['name'])),coverage
