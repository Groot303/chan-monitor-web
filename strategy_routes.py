"""公开的固定模拟策略观察端点；不接受账户ID、交易参数或执行请求。"""
from fastapi import APIRouter, HTTPException, Response
from starlette.concurrency import run_in_threadpool


def strategy_router(strategy, enabled=lambda: True, *, variants=None):
    router = APIRouter(prefix='/api/strategy')
    choices=variants or {'v1':strategy}

    @router.get('/us')
    async def report(response: Response, version: str = 'v1'):
        response.headers['Cache-Control'] = 'no-store'
        if not enabled():
            raise HTTPException(503, '自动模拟调度未运行')
        if version not in choices:
            raise HTTPException(400,'策略版本不存在')
        result=await run_in_threadpool(choices[version].report)
        result['variants']=[dict(key=key,version=value.strategy_id,label='V2 风险管理' if key=='v2' else 'V1 原规则') for key,value in choices.items()]
        return result

    return router
