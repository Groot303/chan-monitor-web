"""Isolated routes; paper account credentials never authorize existing APIs."""
from fastapi import APIRouter, HTTPException, Request, Response, Depends
from starlette.concurrency import run_in_threadpool
from paper_trading import PaperError


def router_for(store, enabled=lambda: True):
    def no_cache(response: Response):
        response.headers['Cache-Control']='no-store'
        if not enabled(): raise HTTPException(503,'模拟练习盘尚未开放')
    router=APIRouter(prefix='/api/paper',dependencies=[Depends(no_cache)])

    def token(request):
        value=request.headers.get('authorization','')
        if not value.startswith('Bearer '): raise HTTPException(401,'请先创建练习账户')
        return value[7:]

    def run(action):
        try: return action()
        except PaperError as exc:
            raise HTTPException(401 if '凭据' in str(exc) else 400,str(exc))

    async def body(request):
        raw=bytearray()
        async for chunk in request.stream():
            if len(raw)+len(chunk)>5000: raise HTTPException(413,'请求过大')
            raw.extend(chunk)
        try:
            import json
            data=json.loads(raw)
            if not isinstance(data,dict): raise ValueError()
            return data
        except ValueError: raise HTTPException(400,'请求格式不正确')

    @router.post('/accounts')
    async def create(request: Request):
        data=await body(request)
        return await run_in_threadpool(run,lambda:store.create(data.get('market'),data.get('initial',100000)))

    @router.get('/account')
    def state(request: Request):
        return run(lambda:store.state(token(request)))

    @router.post('/preview')
    async def preview(request: Request):
        data=await body(request)
        return await run_in_threadpool(run,lambda:store.preview_order(token(request),data))

    @router.post('/orders')
    async def order(request: Request):
        data=await body(request)
        return await run_in_threadpool(run,lambda:store.order(token(request),data))

    @router.post('/stops/{lot_id}')
    async def stop(lot_id: int,request: Request):
        data=await body(request)
        if 'price' not in data: raise HTTPException(400,'请提供止损价，停用时传null')
        return await run_in_threadpool(run,lambda:store.update_stop(token(request),lot_id,data['price']))

    @router.post('/orders/{oid}/cancel')
    def cancel(oid: str,request: Request):
        run(lambda:store.cancel(token(request),oid))
        return {'status':'canceled'}

    return router
