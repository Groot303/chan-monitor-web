"""固定只读研究接口，不触发网络采集、通知或交易。"""
import re
from fastapi import APIRouter, HTTPException, Response
from starlette.concurrency import run_in_threadpool


def research_router(research):
    router=APIRouter()
    def check_date(date):
        if date is not None:
            from datetime import date as Date
            try:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date):raise ValueError()
                Date.fromisoformat(date)
            except ValueError:raise HTTPException(400,'交易日格式应为YYYY-MM-DD')

    @router.get('/api/cn/research')
    async def snapshot(response:Response,date:str|None=None):
        check_date(date)
        response.headers['Cache-Control']='no-store'
        return await run_in_threadpool(research.report,date)

    @router.get('/api/cn/relay')
    async def relay(response:Response,date:str|None=None):
        check_date(date)
        response.headers['Cache-Control']='no-store'
        return await run_in_threadpool(research.relay_report,date)

    return router
