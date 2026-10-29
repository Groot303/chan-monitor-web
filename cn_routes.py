"""固定只读研究接口，不触发网络采集、通知或交易。"""
import re
from fastapi import APIRouter, HTTPException, Response
from starlette.concurrency import run_in_threadpool


def research_router(research):
    router=APIRouter()

    @router.get('/api/cn/research')
    async def snapshot(response:Response,date:str|None=None):
        if date is not None:
            from datetime import date as Date
            try:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date):raise ValueError()
                Date.fromisoformat(date)
            except ValueError:raise HTTPException(400,'交易日格式应为YYYY-MM-DD')
        response.headers['Cache-Control']='no-store'
        return await run_in_threadpool(research.report,date)

    return router
