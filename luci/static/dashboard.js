'use strict';
'require baseclass';
var root,api,token,timer,busy=false,lastUpdate='',active=false,previousTraffic=null,previousNative=null,lastNativeReply=null;
function text(id,value) { var node=root.querySelector('[data-sp="'+id+'"]');if(node)node.textContent=value; }
function bytes(n) {
 if(!Number.isFinite(n)||n<0)return '未提供';
 var units=['B','KiB','MiB','GiB','TiB'],i=0;while(n>=1024&&i<4){n/=1024;i++;}return n.toFixed(i?2:0)+' '+units[i];
}
function date(n) {return n===0?'长期有效':Number.isFinite(n)&&n>0?new Date(n*1000).toLocaleString():'未提供';}
async function call(operation) {
 var options={credentials:'same-origin',cache:'no-store'};
 if(operation){options.method='POST';options.headers={'Content-Type':'application/x-www-form-urlencoded'};options.body=new URLSearchParams({token:token,operation:operation}).toString();}
 var response=await fetch(api,options);
 if(!response.ok)throw Error('请求失败（'+response.status+'），请刷新登录状态后重试');
 if(!(response.headers.get('Content-Type')||'').includes('application/json'))throw Error('管理接口暂不可用，请刷新页面重试');
 return response.json();
}
function renderSubscriptions(rows) {
 var panel=root.querySelector('[data-sp="subscriptions"]');if(!panel)return;
 var mode=root.dataset.mode;
 var selected=rows.filter(function(r){return mode==='game'?r.game:r.starpass;});
 if(!selected.length&&mode==='starpass')selected=rows.filter(function(r){return r.title!=='独立订阅';});
 panel.replaceChildren();
 if(!selected.length){panel.textContent='没有可读取的订阅。请在高级设置或 OpenClash 中配置。';return;}
 selected.forEach(function(row){
  var box=document.createElement('div');box.className='sp-subscription';
  var title=document.createElement('strong');title.textContent=row.title;box.append(title);
  var info=row.info||{},used=Number.isFinite(info.upload)&&Number.isFinite(info.download)?info.upload+info.download:NaN;
  var values=[['已用 / 总量',bytes(used)+' / '+(info.total===0?'不限量':bytes(info.total))],
   ['剩余',info.total===0?'不限量':Number.isFinite(used)&&Number.isFinite(info.total)?bytes(Math.max(0,info.total-used)):'未提供'],
   ['到期时间',date(info.expire)+(info.expire>0?'（剩余 '+Math.max(0,Math.ceil((info.expire-Date.now()/1000)/86400))+' 天）':'')],['订阅上传 / 下载',bytes(info.upload)+' / '+bytes(info.download)]];
  var list=document.createElement('div');list.className='sp-sub-grid';
  values.forEach(function(pair){var cell=document.createElement('p');var label=document.createElement('span');label.textContent=pair[0]+'：';cell.append(label,document.createTextNode(pair[1]));list.append(cell);});box.append(list);
  var status=document.createElement('small');status.textContent=(row.state==='error'?'刷新失败，保留上次数据。':row.state==='unavailable'?'服务商未返回用量或日期。':!row.state?'点击刷新读取服务商信息。':'')+(row.updated_at?' 更新于 '+date(row.updated_at):'');box.append(status);panel.append(box);
 });
}
function nativeEvidence(data,entry,now) {
 var native=data.accelerator||{},c=native.counters||{},p=previousNative;
 var valid=native.fresh&&native.running&&native.session&&Number.isFinite(native.sample_at)&&Number.isFinite(c.sent)&&Number.isFinite(c.received);
 var same=valid&&p&&p.session===native.session&&native.sample_at>=p.sampleAt&&c.sent>=p.sent&&c.received>=p.received;
 if(!same)lastNativeReply=null;
 var newer=same&&native.sample_at>p.sampleAt,elapsed=newer?native.sample_at-p.sampleAt:0;
 var upload=newer?(c.sent-p.sent)/elapsed:same?p.upload:NaN;
 var download=newer?(c.received-p.received)/elapsed:same?p.download:NaN;
 if(newer&&c.received>p.received)lastNativeReply=now;
 previousNative=valid?{session:native.session,sampleAt:native.sample_at,sent:c.sent,received:c.received,upload:upload,download:download}:null;
 var state='unknown',title='正在确认加速状态',detail='正在读取本机通道数据…';
 if(entry.fresh&&native.fresh) {
  if(entry.route==='direct'&&!native.running) {state='off';title='加速已关闭 · 当前直连';detail='原代理地址仍可使用，流量经默认网关直接联网。';}
  else if(entry.route==='socks'&&native.running) {
   if(!native.healthy) {state='waiting';title='线路状态待确认';detail='服务已启动，正在确认鲜牛线路状态。';}
   else if(lastNativeReply!==null&&now-lastNativeReply<=8000) {state='active';title='正在加速 · 已确认数据传输';detail='已检测到鲜牛线路返回的数据，当前连接确实经过加速通道。';}
   else if(upload>0) {state='waiting';title='正在发送 · 等待线路响应';detail='已发送数据，收到线路返回后会自动亮绿。';}
   else {state='waiting';title='加速已开启 · 等待设备流量';detail='暂时没有新的数据传输；打开商店、下载或联网后会自动确认。';}
  } else {state='waiting';title='正在切换通道';detail='等待服务与代理入口状态同步。';}
 } else if(entry.fresh) {title='加速状态暂不可用';detail='本机状态读取暂时中断，正在重试。';}
 var card=root.querySelector('[data-sp="live-card"]');if(card)card.dataset.state=state;
 text('live-title',title);text('live-detail',detail);
 text('live-device',native.device_name||native.device||'未选择设备');
 text('live-device-ip',native.device_name?native.device:'');
 text('live-game',[native.game,native.area].filter(Boolean).join(' · ')||'未选择游戏');
 text('live-exit',state==='off'?'默认网关直连':'鲜牛加速线路');
 text('live-upload',valid?(Number.isFinite(upload)?bytes(upload)+'/s':'采样中…'):'—');
 text('live-download',valid?(Number.isFinite(download)?bytes(download)+'/s':'采样中…'):'—');
 text('live-proof',valid?'本次鲜牛通道已上传 '+bytes(c.sent)+' · 已下载 '+bytes(c.received):state==='off'?'当前直连流量见下方实时流量':'等待鲜牛通道数据');
 text('live-scope','此状态确认代理通道的数据传输，不表示游戏延迟一定降低。');
}
function render(data) {
 var kind=root.dataset.mode==='accelerator'?'accelerator':'shared';
 var entry=data.entries&&data.entries[kind]||{},traffic=entry.traffic||{},counts=traffic.bytes||{};
 var now=performance.now(),previous=previousTraffic;
 nativeEvidence(data,data.entries&&data.entries.accelerator||{},now);
 var shared=data.entries&&data.entries.shared||{},accel=data.entries&&data.entries.accelerator||{};
 text('feature-status','游戏共享：'+(shared.fresh?(shared.route==='game'?'已开启':'未运行'):'读取中')+' · 鲜牛：'+(accel.fresh?(accel.route==='socks'?'运行中':'未运行'):'读取中')+' · 星渡：'+(shared.fresh?(shared.route==='starpass'?'已开启':'已关闭'):'读取中')+'。');
 var comparable=entry.fresh&&previous&&previous.kind===kind&&previous.session===traffic.session&&now>previous.at;
 var elapsed=comparable?(now-previous.at)/1000:0;
 // Average over the visible polling interval so short bursts are not missed.
 ['local','external'].forEach(function(bucket){
  ['upload','download'].forEach(function(direction){
   var total=(counts[bucket]||{})[direction],before=previous&&((previous.bytes[bucket]||{})[direction]);
   var valid=entry.fresh&&Number.isFinite(total)&&total>=0;
   var rate=valid&&comparable&&Number.isFinite(before)&&total>=before?(total-before)/elapsed:NaN;
   text(bucket+'-'+direction,valid?(Number.isFinite(rate)?bytes(rate)+'/s':'采样中…'):'—');
   text(bucket+'-'+direction+'-total',valid?bytes(total):'—');
   var node=root.querySelector('[data-sp="'+bucket+'-'+direction+'"]');
   if(node)node.dataset.flow=Number.isFinite(rate)&&rate>0?'active':'idle';
  });
 });
 previousTraffic=entry.fresh&&traffic.bytes?{kind:kind,session:traffic.session,at:now,bytes:counts}:null;
 text('traffic-source',kind==='accelerator'?'加速器入口':root.dataset.mode==='starpass'?'星渡入口':'游戏共享入口');
 var routes={direct:'直连',socks:'鲜牛加速',game:'游戏共享',starpass:'OpenClash'};
 text('traffic-route',entry.fresh?'当前出口：'+(routes[entry.route]||'未知'):'入口状态暂不可用');
 text('traffic-time',entry.fresh?'每 2 秒刷新 · 更新于 '+new Date().toLocaleTimeString():'');
 text('traffic-status',!entry.fresh?'入口状态暂不可用，正在重试':traffic.bytes?'↑ 设备上传 · ↓ 设备下载；按目的地址区分内外网，仅统计经过此代理入口的数据，不包含绕过代理的游戏 UDP 或设备间直连串流。累计值从入口启动时计算。':'等待入口统计');
 renderSubscriptions(data.subscriptions||[]);
 var u=data.update||{};text('version',u.current||'未知');
 var message=u.message||'点击检查 GitHub 正式路由器版本';
 if(u.target)message+=' · '+u.target;
 if(u.backup&&u.phase==='error')message+=' · 备份：'+u.backup;
 text('update-status',message);
 var install=root.querySelector('[data-sp="install-update"]');
 var running=['checking','downloading','installing'].indexOf(u.phase)>=0;
 if(install){install.hidden=!u.available||running;install.disabled=busy;}
 var check=root.querySelector('[data-sp="check-update"]');if(check)check.disabled=running||busy;
 if(u.phase==='done'&&lastUpdate!==u.updated_at){lastUpdate=u.updated_at; text('update-status',message+'。刷新页面以载入新界面。');}
}
async function refresh() {
 if(active)return;active=true;
 try{render(await call());}
 catch(e){previousNative=null;lastNativeReply=null;var card=root.querySelector('[data-sp="live-card"]');if(card)card.dataset.state='unknown';text('live-title','状态读取中断');text('live-detail','正在重试，暂时无法确认加速状态。');text('live-upload','—');text('live-download','—');text('feature-status','服务状态暂不可用，正在重试。');previousTraffic=null;['local','external'].forEach(function(k){['upload','download'].forEach(function(d){text(k+'-'+d,'—');var n=root.querySelector('[data-sp="'+k+'-'+d+'"]');if(n)n.dataset.flow='idle';});});text('traffic-time','');text('traffic-status','状态读取失败，正在重试');text('update-status',e.message);}
 finally{active=false;}
}
return baseclass.extend({
 mount:function(node,url,csrf){
  root=node;api=url;token=csrf;
  ['check-update','install-update','subscriptions-refresh'].forEach(function(operation){
   var button=root.querySelector('[data-sp="'+operation+'"]');if(!button)return;
   button.addEventListener('click',async function(){
    if(busy)return;busy=true;button.disabled=true;
    text(operation==='subscriptions-refresh'?'subscription-status':'update-status',operation==='install-update'?'正在准备安装…':operation==='check-update'?'正在检查…':'正在刷新订阅…');
    try{var value=await call(operation);if(value.ok===false)throw Error(value.error||'操作未完成');if(operation==='subscriptions-refresh')text('subscription-status','刷新已提交，结果将自动显示。');await refresh();}
    catch(e){text(operation==='subscriptions-refresh'?'subscription-status':'update-status',e.message);}
    finally{busy=false;button.disabled=false;}
   });
  });
  refresh();timer=setInterval(function(){if(!document.hidden)refresh();},2000);
  window.addEventListener('pagehide',function(){clearInterval(timer);});
 }
});
