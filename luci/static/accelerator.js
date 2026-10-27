'use strict';
'require baseclass';
'require form';
'require poll';
'require rpc';
'require ui';
'require xianniu_router.member_clock as memberClock';

var api = {}, schemas = { status: [], devices: [], catalog: ['query', 'platform', 'offset', 'limit'],
    lines: ['game_id', 'area_id'], launch: ['device', 'game_id', 'area_id', 'line_id'],
    set_device_note: ['mac', 'note'], start: [], stop: [], finish: [], member: [], member_pause: [], member_resume: [], wechat_create: [],
    wechat_image: ['id', 'part'], wechat_poll: ['id'], login_password: ['mobile', 'password'] };
Object.keys(schemas).forEach(function(name) {
    var call = rpc.declare({ object: 'xianniu', method: name, params: schemas[name], expect: { '': {} } });
    api[name] = function() {
        return call.apply(null, arguments).then(function(value) {
            if (!value.ok) throw new Error(value.error || '请求未完成');
            return value.data;
        });
    };
});

function accelerator() {
    var state = {}, inventory = {}, device = '', deviceMac = '', selected = null, platform = '', offset = 0;
    var qrId = null, qrBusy = false, qrTimer = null, actionBusy = false, searchSequence = 0, lineSequence = 0, timer;
    var memberTimer = null, memberBusy = false, clock = memberClock.create(), clockLabel = null;
    var account = E('div'), membership = E('div'), runtime = E('div'), message = E('p', { role: 'status', 'aria-live': 'polite' });
    var devices = E('div', { 'class': 'xn-cards' }), library = E('div', { 'class': 'xn-library' });
    var search = E('input', { type: 'search', placeholder: '搜索游戏名、简称，例如 PS5港服、暗黑4', 'aria-label': '搜索游戏' });
    var result = E('span'), tabs = E('div', { 'class': 'xn-tabs' }), pager = E('div', { 'class': 'xn-actions' });
    var gameTitle = E('strong', {}, '请选择游戏'), areas = E('select', { 'aria-label': '区服' });
    var lines = E('select', { 'aria-label': '加速线路' }), nodeList = E('div'), qrBox = E('div');
    var proxyHelp = E('p'), loginDetails = E('details'), allLines = [];

    function fail(error) { message.textContent = error.message || '操作未完成'; }
    function button(label, action, kind) {
        return E('button', { type: 'button', 'class': 'cbi-button ' + (kind || 'cbi-button-action'), click: function(ev) {
            var node = ev.currentTarget;
            if (actionBusy) return;
            node.disabled = true; actionBusy = true; message.textContent = '正在处理…';
            return Promise.resolve().then(action).catch(fail).finally(function() {
                actionBusy = false; node.disabled = false; updateLaunch();
            });
        } }, label);
    }
    var launch = button('开始加速', function() {
        if (!device || !selected || !areas.value || !lines.value) throw new Error('请先选择设备、游戏和区服');
        return api.launch(device, selected.id, Number(areas.value), Number(lines.value)).then(function(value) {
            message.textContent = value.already_running ? '当前设备已使用这套加速方案' :
                (value.time_resumed ? '已恢复官方会员计时，正在连接节点' : '正在连接官方节点，请等待运行状态更新');
            return Promise.all([refresh(), refreshDevices(false)]);
        });
    }, 'cbi-button-positive');
    function updateLaunch() {
        launch.textContent = (state.runtime || {}).running ? '切换并加速' : selected && selected.is_free === true ? '免费加速' :
            ((state.member || {}).pause_state === 0 ? '恢复计时并加速' : '开始加速');
        launch.disabled = actionBusy || !device || !selected || !areas.value || !lines.value;
    }
    function tickMembership() {
        var value = clock.read();
        if (!clockLabel || !value) return;
        var seconds = value.seconds;
        clockLabel.textContent = '剩余可用时长' + (value.estimated ? '（倒计时估算）：' : '（官方）：') +
            Math.floor(seconds / 3600).toLocaleString('zh-CN') + ' 小时 ' +
            Math.floor(seconds % 3600 / 60) + ' 分 ' + seconds % 60 + ' 秒';
    }
    function showMembership(value) {
        clock.accept(value);
        var pieces = [];
        if (value.package_title) pieces.push(String(value.package_title));
        if (value.pause_state !== undefined) pieces.push(Number(value.pause_state) === 0 ? '官方计时：已暂停' : '官方计时：未暂停');
        if (value.expired_datetime) pieces.push('官方到期时间：' + String(value.expired_datetime));
        function duration(seconds) {
            if (typeof seconds !== 'number' || !Number.isSafeInteger(seconds) || seconds < 0) return '暂未获取';
            return Math.floor(seconds / 3600).toLocaleString('zh-CN') + ' 小时 ' +
                Math.floor(seconds % 3600 / 60) + ' 分 ' + seconds % 60 + ' 秒';
        }
        clockLabel = E('strong', {}, '剩余可用时长（官方）：' + duration(value.remaining_seconds));
        var rows = [E('p', {}, [clockLabel])];
        if (value.trial_seconds !== null && value.trial_seconds !== undefined)
            rows.push(E('p', {}, '试用时长（单列）：' + duration(value.trial_seconds)));
        rows.push(E('p', {}, pieces.join(' · ') || '可刷新官方会员状态，暂停计时以官方返回结果为准'));
        if (value.updated_at) rows.push(E('small', {}, '官方数据更新于 ' + new Date(value.updated_at * 1000).toLocaleString('zh-CN',
            { timeZone: 'Asia/Shanghai', hour12: false }) + ' · 每 60 秒官方校准，计时中每秒更新估算'));
        membership.replaceChildren.apply(membership, rows);
        tickMembership();
    }
    function refreshMember(automatic) {
        if (memberBusy) return Promise.resolve();
        memberBusy = true;
        return api.member().then(function(value) {
            showMembership(value);
            if (!automatic) message.textContent = '剩余时长已从官方刷新';
        }).catch(function(error) { if (!automatic) fail(error); }).finally(function() { memberBusy = false; });
    }
    function scheduleMember() {
        if (memberTimer !== null || state.login_state !== 'authenticated') return;
        memberTimer = setTimeout(function() {
            memberTimer = null;
            if (state.login_state !== 'authenticated') return;
            if (actionBusy) { scheduleMember(); return; }
            return refreshMember(true).finally(scheduleMember);
        }, 60000);
    }
    function refresh() {
        return api.status().then(function(value) {
            state = value;
            var authenticated = value.login_state === 'authenticated';
            var label = value.login_required ? '鲜牛账号：需要重新登录' : authenticated ? '鲜牛账号：已登录' :
                (value.saved_login ? '鲜牛账号：旧会话待验证' : '鲜牛账号：未登录');
            var detail = authenticated ? (value.nickname ? value.nickname + ' · ' : '') +
                (value.login_method === 'wechat' ? '微信官方登录' : '官方密码登录') : '';
            if (authenticated && value.login_at) detail += ' · 登录时间 ' + new Date(value.login_at * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
            account.replaceChildren(E('strong', { style: authenticated ? 'color:#198754' : '' }, label), E('p', {}, detail));
            if (!authenticated) clock.reset();
            showMembership(value.member || {});
            scheduleMember();
            var current = value.runtime || {}, text;
            if (current.running) text = '加速服务运行中 · ' + (current.refresh_ok ? '会话续期正常' : '正在确认续期') +
                ' · 目标设备 ' + (value.active_device || (current.devices || []).join('、') || '未选择');
            else text = current.login_required ? '未运行：官方登录失效，请展开账号登录' :
                (current.start_error_code ? '未运行：' + (current.message || '官方返回 ' + current.start_error_code) : '尚未启动加速');
            runtime.textContent = text;
            if (!value.saved_login || value.login_required) loginDetails.open = true;
            updateLaunch();
        });
    }
    function drawDevices() {
        devices.replaceChildren();
        (inventory.devices || []).forEach(function(row) {
            var card = E('button', { type: 'button', 'class': 'xn-device' + (device === row.ip ? ' xn-selected' : ''),
                'aria-pressed': device === row.ip ? 'true' : 'false', click: function() {
                    if (actionBusy) return;
                    device = row.ip; deviceMac = row.mac || ''; drawDevices();
                    var preset = row.preset;
                    if (preset) api.catalog(String(preset.game_id), '', 0, 1).then(function(value) {
                        if (device === row.ip && value.games.length) return selectGame(value.games[0], preset);
                    }).catch(fail);
                    updateLaunch();
                } }, [E('strong', {}, row.name), E('small', {}, row.ip + ' · ' + (row.seen ? '近期有通信' : '已发现/已保存')),
                    E('small', {}, row.preset ? '已记住游戏与线路，点击恢复' : '点击为此设备选择游戏')]);
            var note = E('input', { type: 'text', maxlength: 64, value: row.note || '',
                style: 'width:100%;box-sizing:border-box', placeholder: '设备备注，例如 PS5 / PS Portal', 'aria-label': '设备备注 ' + (row.mac || row.ip) });
            var save = button('保存备注', function() {
                return api.set_device_note(row.mac, note.value).then(function() {
                    message.textContent = '备注已按 MAC 保存，IP 改变后仍保留';
                    return refreshDevices(false);
                });
            }, '');
            save.disabled = !row.mac;
            devices.appendChild(E('div', { style: 'min-width:0' }, [card, E('details', {}, [E('summary', {}, '备注'), E('small', {}, row.mac ? 'MAC ' + row.mac : '暂未发现 MAC，无法保存备注'), note, save])]));
        });
        if (!(inventory.devices || []).length) devices.appendChild(E('p', {}, '暂未发现设备，请让设备联网后刷新；高级设置可添加离线设备。'));
        proxyHelp.textContent = '设备的手动 HTTP 代理填写：' + inventory.host + '，端口 ' + inventory.port + '。仅首次接入需要设置。';
    }
    function refreshDevices(choose) {
        return api.devices().then(function(value) {
            inventory = value;
            if (choose || !value.devices.some(function(row) { return row.ip === device; })) {
                var preferred = value.devices.find(function(row) { return row.mac && row.mac === (deviceMac || state.active_device_mac); }) ||
                    value.devices.find(function(row) { return row.ip === state.active_device; }) ||
                    value.devices.find(function(row) { return row.name.indexOf('PS5') >= 0; }) || value.devices[0];
                device = preferred ? preferred.ip : ''; deviceMac = preferred ? preferred.mac || '' : '';
            }
            drawDevices(); updateLaunch();
        });
    }
    function drawNodes() {
        var table = E('table', { 'class': 'table' }, [E('tr', {}, ['官方线路', '入口 / 出口', '运营商', '公开入口', '选择'].map(function(t) { return E('th', {}, t); }))]);
        allLines.forEach(function(row) {
            table.appendChild(E('tr', {}, [E('td', {}, row.title), E('td', {}, (row.entry || '—') + ' / ' + (row.exit || '—')),
                E('td', {}, row.isp || row.provider || '—'), E('td', {}, (row.entry_ips || []).join('、') || '官方动态分配'),
                E('td', {}, [E('button', { type: 'button', 'class': 'cbi-button', disabled: !row.compatible,
                    click: function() { lines.value = String(row.id); updateLaunch(); } }, row.compatible ? '选用' : '不适用此区服')])]));
        });
        nodeList.replaceChildren(E('p', {}, '本游戏官方返回 ' + allLines.length + ' 条线路；可用范围和实际节点由官方接口确定。'), table);
    }
    function loadLines(preferred) {
        var sequence = ++lineSequence;
        lines.replaceChildren(); allLines = []; drawNodes(); updateLaunch();
        if (!selected || !areas.value) return Promise.resolve();
        return api.lines(selected.id, Number(areas.value)).then(function(value) {
            if (sequence !== lineSequence) return;
            allLines = value.all_lines || [];
            value.lines.forEach(function(row) { lines.appendChild(E('option', { value: row.id }, row.title + (row.exclusive ? '（专属）' : ''))); });
            if (value.lines.some(function(row) { return row.id === preferred; })) lines.value = String(preferred);
            drawNodes(); updateLaunch();
        }).catch(function(error) { if (sequence === lineSequence) fail(error); });
    }
    function selectGame(game, preset) {
        selected = game; gameTitle.textContent = game.title;
        areas.replaceChildren();
        game.areas.forEach(function(row) { areas.appendChild(E('option', { value: row.id }, row.title)); });
        if (preset && preset.game_id === game.id && game.areas.some(function(row) { return row.id === preset.area_id; })) areas.value = String(preset.area_id);
        return loadLines(preset && preset.game_id === game.id ? preset.line_id : null);
    }
    areas.addEventListener('change', function() { loadLines().catch(fail); });
    lines.addEventListener('change', updateLaunch);
    function findGames(reset) {
        if (reset) offset = 0;
        var sequence = ++searchSequence;
        return api.catalog(search.value, platform, offset, 24).then(function(value) {
            if (sequence !== searchSequence) return;
            library.replaceChildren();
            value.games.forEach(function(game) {
                var image = game.icon ? E('img', { src: game.icon, alt: '', loading: 'lazy', referrerpolicy: 'no-referrer' }) : E('span', { 'class': 'xn-placeholder' }, '游戏');
                library.appendChild(E('button', { type: 'button', 'class': 'xn-game', title: game.title, click: function() {
                    var row = (inventory.devices || []).find(function(r) { return r.ip === device; });
                    selectGame(game, row && row.preset).catch(fail);
                } }, [image, E('span', {}, game.title)]));
            });
            if (!value.games.length) library.appendChild(E('p', {}, platform === 'recent' ? '启动过的游戏会显示在这里' : '没有匹配游戏，试试简称或部分名称'));
            result.textContent = value.total + ' 个游戏';
            pager.replaceChildren();
            if (offset > 0) pager.appendChild(button('上一页', function() { offset = Math.max(0, offset - 24); return findGames(false); }, ''));
            if (offset + value.games.length < value.total) pager.appendChild(button('下一页', function() { offset += 24; return findGames(false); }, ''));
        }).catch(fail);
    }
    [['', '全部游戏'], ['pc', 'PC游戏'], ['console', 'PS / Xbox'], ['switch', 'Switch'], ['recent', '最近加速']].forEach(function(item) {
        var tab = E('button', { type: 'button', 'class': 'cbi-button', 'aria-pressed': item[0] === '' ? 'true' : 'false', click: function() {
            platform = item[0]; Array.prototype.forEach.call(tabs.children, function(child) { child.setAttribute('aria-pressed', child === tab ? 'true' : 'false'); });
            findGames(true);
        } }, item[1]); tabs.appendChild(tab);
    });
    search.addEventListener('input', function() { clearTimeout(timer); timer = setTimeout(function() { findGames(true); }, 250); });

    var qrButton = button('微信扫码登录', function() {
        qrId = null; clearTimeout(qrTimer); qrBox.replaceChildren(E('p', { role: 'status' }, '正在获取鲜牛官方二维码…'));
        return api.wechat_create().then(function(value) {
            var calls = [];
            for (var part = 0; part < value.parts; part++) calls.push(api.wechat_image(value.id, part));
            return Promise.all(calls).then(function(chunks) {
                qrId = value.id;
                qrBox.replaceChildren(E('img', { src: 'data:' + value.mime + ';base64,' + chunks.map(function(v) { return v.chunk; }).join(''),
                    alt: '鲜牛官方微信登录二维码', style: 'width:260px;max-width:100%;height:auto' }), E('p', {}, '用微信扫码并确认，请等待本页显示登录成功。'));
                message.textContent = '等待微信确认';
                qrTimer = setTimeout(checkLogin, 1000);
            });
        }).catch(function(error) {
            qrBox.replaceChildren(E('p', { role: 'alert' }, '二维码获取失败：' + (error.message || '请稍后重试')),
                E('p', {}, '请重新点击“微信扫码登录”。'));
            throw error;
        });
    });
    function checkLogin() {
        if (!qrId) return Promise.resolve();
        if (qrBusy) { qrTimer = setTimeout(checkLogin, 1000); return Promise.resolve(); }
        var identity = qrId;
        qrBusy = true;
        return api.wechat_poll(identity).then(function(value) {
            if (qrId !== identity) return;
            var texts = { waiting: '等待扫码', scanned: '已扫码，请在微信确认', expired: '二维码已过期，请重新获取', cancelled: '已取消登录', complete: '官方登录成功，可以开始加速' };
            message.textContent = texts[value.status] || '等待官方授权';
            if (['complete', 'expired', 'cancelled'].indexOf(value.status) >= 0) qrId = null;
            if (value.status === 'complete') {
                qrBox.replaceChildren(E('p', {}, '鲜牛账号已登录，登录信息已保存到 N1。'));
                loginDetails.open = false;
                return refresh().then(function() { return api.member().then(showMembership).catch(fail); });
            }
        }).catch(function(error) {
            if (qrId !== identity) return;
            qrId = null;
            qrBox.replaceChildren(E('p', { role: 'alert' }, '授权结果未完成：' + (error.message || '请重新获取二维码')));
            fail(error);
        }).finally(function() {
            qrBusy = false;
            if (qrId) qrTimer = setTimeout(checkLogin, 2000);
        });
    }
    var mobile = E('input', { type: 'tel', placeholder: '手机号', autocomplete: 'username', maxlength: 11 });
    var password = E('input', { type: 'password', placeholder: '鲜牛账号密码', autocomplete: 'current-password', maxlength: 128 });
    loginDetails.appendChild(E('summary', {}, '账号登录 / 更换账号'));
    loginDetails.appendChild(E('div', { 'class': 'xn-section' }, [qrButton, qrBox,
        E('details', {}, [E('summary', {}, '手机号密码登录'), E('p', {}, [mobile]), E('p', {}, [password]),
            button('登录', function() { return api.login_password(mobile.value, password.value).then(function() {
                password.value = ''; message.textContent = '官方登录成功'; return refresh();
            }).finally(function() { password.value = ''; }); }), E('p', {}, '短信验证登录尚未接入；如官方要求额外验证，请使用微信登录。')]),
        E('p', {}, '登录信息仅保存到 N1 私有配置。有效期和重新验证要求由官方决定。更换账号会停止当前加速。')]));

    var panel = E('div', { 'class': 'xn' }, [
        E('style', {}, '.xn{max-width:1200px}.xn-section{padding:18px;margin:14px 0;border:1px solid var(--border-color-medium,#d9dde4);border-radius:12px}.xn-cards,.xn-library{display:grid;gap:12px}.xn-cards{grid-template-columns:repeat(auto-fill,minmax(210px,1fr))}.xn-library{grid-template-columns:repeat(auto-fill,minmax(135px,1fr));margin:16px 0}.xn-device,.xn-game{background:var(--background-color-high,#fff);color:inherit;border:1px solid var(--border-color-medium,#d9dde4);border-radius:10px;padding:14px;text-align:left;cursor:pointer}.xn-device small{display:block;margin-top:6px;opacity:.75}.xn-selected{border:2px solid #287be6}.xn-game{display:flex;align-items:center;gap:10px}.xn-game img,.xn-placeholder{width:42px;height:42px;border-radius:8px;object-fit:cover;flex-shrink:0}.xn-game span{overflow-wrap:anywhere}.xn-tabs,.xn-actions{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0}.xn-tabs [aria-pressed=true]{background:#287be6;color:white}.xn input[type=search]{width:min(100%,460px)}.xn select{max-width:100%;margin:8px}.xn summary{cursor:pointer;padding:8px 0}.xn-note{opacity:.8;line-height:1.7}.xn table{overflow-wrap:anywhere}'),
        E('h2', {}, '鲜牛游戏加速 · 0.4.4'),
        E('div', { 'class': 'xn-section' }, [account, membership, E('div', { 'class': 'xn-actions' }, [
            button('刷新账号状态', function() { return refresh().then(function() { message.textContent = '鲜牛登录状态已刷新'; }); }, ''),
            button('刷新剩余时长', function() { return refreshMember(false); }, ''),
            button('暂停计时', function() { return api.member_pause().then(function(value) { showMembership(value); message.textContent = '官方已处理暂停请求；当前加速已停止'; return refresh(); }); }, ''),
            button('恢复计时', function() { return api.member_resume().then(function(value) { showMembership(value); message.textContent = '官方已处理恢复请求；选择游戏后开始加速'; return refresh(); }); }, '')]), loginDetails]),
        E('div', { 'class': 'xn-section' }, [E('h3', {}, '1. 选择设备'), devices,
            button('刷新设备', function() { return refreshDevices(false).then(function() { message.textContent = '已刷新设备列表'; }); }, ''),
            proxyHelp, E('p', { 'class': 'xn-note' }, '当前接入：Wi-Fi HTTP 代理（TCP）。只处理设备主动交给此代理的连接；游戏 UDP、语音和 NAT 不会因此自动接管。')]),
        E('div', { 'class': 'xn-section' }, [E('h3', {}, '2. 选择游戏'), tabs, search, ' ', result, library, pager]),
        E('div', { 'class': 'xn-section' }, [E('h3', {}, '3. 一键加速'), gameTitle,
            E('div', {}, ['区服 ', areas, ' 线路 ', lines]),
            E('div', { 'class': 'xn-actions' }, [launch, button('停止加速', function() { return api.finish().then(function(value) {
                message.textContent = value.time_paused ? '加速已停止，官方计时已暂停' : '加速已停止；免费项目不会操作会员计时'; return refresh();
            }); }, 'cbi-button-negative')]), runtime, message,
            E('p', { 'class': 'xn-note' }, '每台设备记住独立选择；当前一次运行一个设备/游戏会话。免费标记按官方目录处理；Steam 商店加速时不使用直连例外。'),
            E('details', {}, [E('summary', {}, '查看官方全部线路和节点'), nodeList])])
    ]);
    return refresh().then(function() { return refreshMember(true); }).then(function() { return refreshDevices(true); }).then(function() {
        var row = (inventory.devices || []).find(function(r) { return r.ip === device; });
        var preset = row && row.preset ? row.preset : { game_id: state.game_id, area_id: (state.profile || {}).area_id, line_id: (state.profile || {}).line_id };
        return Promise.all([findGames(true), api.catalog(String(preset.game_id || 797), '', 0, 1).then(function(value) {
            if (value.games.length) return selectGame(value.games[0], preset);
        })]);
    }).catch(fail).then(function() {
        poll.add(function() { tickMembership(); return Promise.resolve(); }, 1);
        poll.add(function() { return refresh().catch(fail); }, 5);
        return panel;
    });
}

return baseclass.extend({
    handleSaveApply: null, handleSave: null, handleReset: null,
    render: function() {
        var map = new form.Map('xianniu-router', '高级设置', '仅修改本插件的代理入口和设备名单。保存后需停止并重新开始加速。');
        var section = map.section(form.NamedSection, 'main', 'service'); section.anonymous = true;
        var devices = section.option(form.DynamicList, 'devices', '允许的设备 IPv4'); devices.datatype = 'ip4addr'; devices.rmempty = false;
        var iface = section.option(form.Value, 'interface', '局域网接口'); iface.default = 'br-lan'; iface.rmempty = false;
        var host = section.option(form.Value, 'http_host', 'N1 代理监听地址'); host.datatype = 'ip4addr'; host.rmempty = false;
        var port = section.option(form.Value, 'http_port', 'HTTP 代理端口'); port.datatype = 'range(1024,65535)'; port.default = '10082'; port.rmempty = false;
        var steam = section.option(form.Flag, 'steam_store_direct', 'Steam 商店域名直连'); steam.default = '1'; steam.rmempty = false;
        return Promise.all([accelerator(), map.render()]).then(function(values) {
            var save = E('button', { type: 'button', 'class': 'cbi-button cbi-button-save', click: function(ev) {
                var node = ev.currentTarget; node.disabled = true;
                return map.save().then(function() { ui.addNotification(null, E('p', {}, '高级设置已保存。停止并重新开始加速后生效。')); })
                    .catch(function(error) { ui.addNotification(null, E('p', {}, error.message)); }).finally(function() { node.disabled = false; });
            } }, '保存高级设置');
            return E('div', {}, [values[0], E('details', { 'class': 'xn-section' }, [E('summary', {}, '高级设置（通常无需修改）'), values[1], save])]);
        });
    }
});
