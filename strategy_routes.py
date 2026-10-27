"""公开的固定模拟策略观察端点；不接受账户ID、交易参数或执行请求。"""
from fastapi import APIRouter, HTTPException, Response
from starlette.concurrency import run_in_threadpool


def strategy_router(strategy, enabled=lambda: True):
    router = APIRouter(prefix='/api/strategy')

    @router.get('/us')
    async def report(response: Response):
        response.headers['Cache-Control'] = 'no-store'
        if not enabled():
            raise HTTPException(503, '自动模拟调度未运行')
        return await run_in_threadpool(strategy.report)

    return router
