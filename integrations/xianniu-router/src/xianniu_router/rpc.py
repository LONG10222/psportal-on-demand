"""rpcd exec-plugin protocol; never emit raw server responses or exceptions."""
import json
import os
import sys
from .control import APIError
from .manager import Manager

METHODS={'status':{},'devices':{},'catalog':{'query':'','platform':'','offset':32,'limit':32},'lines':{'game_id':32,'area_id':32},
         'select':{'game_id':32,'area_id':32,'line_id':32},'start':{},'stop':{},
         'launch':{'device':'','game_id':32,'area_id':32,'line_id':32},
         'member':{},'member_pause':{},'member_resume':{},
         'wechat_create':{},'wechat_image':{'id':'','part':32},'wechat_poll':{'id':''},
         'login_password':{'mobile':'String','password':'String'}}


def main():
    os.umask(0o077)
    if sys.argv[1:] == ['list']:
        print(json.dumps(METHODS));return
    output={'ok':False,'error':'请求未完成'}
    try:
        if len(sys.argv)!=3 or sys.argv[1]!='call' or sys.argv[2] not in METHODS:raise ValueError('未知的插件操作')
        raw=sys.stdin.buffer.read(65537)
        if len(raw)>65536:raise ValueError('请求过大')
        args=json.loads(raw or b'{}');method=sys.argv[2]
        if isinstance(args,dict):args.pop('ubus_rpc_session',None)
        if not isinstance(args,dict) or set(args)-set(METHODS[method]):raise ValueError('请求参数无效')
        if os.name=='posix':os.setegid(65534)
        manager=Manager()
        if method in ('wechat_poll','wechat_image'):args['identity']=args.pop('id','')
        output={'ok':True,'data':getattr(manager,method)(**args)}
    except APIError as exc:
        output={'ok':False,'code':exc.code,'error':'官方登录或加速请求未通过，请按官方要求完成验证（代码 '+str(exc.code)+'）'}
    except BlockingIOError:
        output={'ok':False,'error':'另一项操作正在进行，请稍后重试'}
    except ValueError as exc:
        # Only our bounded validation messages; backend payloads are never included.
        output={'ok':False,'error':str(exc)[:180]}
    except Exception as exc:
        output={'ok':False,'error':'操作未完成，请检查网络或重新登录','error_type':type(exc).__name__}
    print(json.dumps(output,ensure_ascii=False))


if __name__=='__main__':main()
