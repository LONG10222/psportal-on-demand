#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Audit compiled aapt2 xmltree output, never source-manifest assumptions."""
import json
import re

PACKAGE = 'org.psportal.host'
VERSION_CODE = 6
VERSION_NAME = '0.6.0-dev'
VPN_PERMISSION = 'android.permission.BIND_VPN_SERVICE'
EXPECTED_PERMISSIONS = {
    'android.permission.INTERNET',
    'android.permission.ACCESS_NETWORK_STATE',
    'android.permission.FOREGROUND_SERVICE',
    'android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE',
    'android.permission.FOREGROUND_SERVICE_SYSTEM_EXEMPTED',
    'android.permission.CHANGE_NETWORK_STATE',
    'android.permission.POST_NOTIFICATIONS',
    'android.permission.REQUEST_INSTALL_PACKAGES',
}
# Android ServiceInfo constants: connectedDevice=16, systemExempted=1024.
CONNECTED_DEVICE = 0x10
SYSTEM_EXEMPTED = 0x400
NAMESPACES = {
    'android': 'http://schemas.android.com/apk/res/android',
    'tools': 'http://schemas.android.com/tools',
}


def _value(raw):
    if raw.startswith('"'):
        value, _ = json.JSONDecoder().raw_decode(raw)
        return value
    typed = re.fullmatch(r'\(type (0x[0-9a-fA-F]+)\)(0x[0-9a-fA-F]+)(?: \(Raw: .*\))?', raw)
    if typed:
        kind, value = (int(item, 16) for item in typed.groups())
        if kind == 0x12:
            assert value in (0, 0xffffffff), 'Malformed compiled boolean'
            return bool(value)
        if kind in (0x10, 0x11):
            return value
    # aapt2 BinaryPrimitive::PrettyPrint emits literal booleans and decimal or
    # hexadecimal integers, rather than legacy aapt's explicit type notation.
    literal = re.fullmatch(r'(true|false|-?\d+|0x[0-9a-fA-F]+)(?: \(Raw: .*\))?', raw)
    if literal:
        value = literal[1]
        if value in ('true', 'false'):
            return value == 'true'
        return int(value, 16 if value.startswith('0x') else 10)
    # Keep resource references opaque: critical values must be explicit below.
    return raw


def _attribute_name(name, namespaces):
    # aapt2 prints the full namespace URI; legacy aapt prints its alias.
    for alias, uri in NAMESPACES.items():
        for prefix in (uri + ':', alias + ':'):
            if name.startswith(prefix):
                local = name[len(prefix):]
                assert alias in namespaces, 'Undeclared compiled attribute namespace'
                assert re.fullmatch(r'[\w.-]+', local), 'Malformed compiled attribute name'
                return alias + ':' + local
    assert re.fullmatch(r'[\w.-]+', name), 'Unexpected compiled attribute namespace'
    return name


def parse_xmltree(text):
    """Read aapt2's element/attribute indentation, rejecting malformed trees."""
    roots, stack, pending, declared = [], [], [], set()
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.lstrip().startswith('N: '):
            namespace = re.fullmatch(r'( *)N: ([\w.-]+)=(\S+?)(?: \(line=\d+\))?', line)
            assert namespace, 'Malformed compiled namespace declaration'
            indent, alias, uri = len(namespace[1]), namespace[2], namespace[3]
            assert NAMESPACES.get(alias) == uri, 'Unexpected compiled namespace'
            assert alias not in declared, 'Duplicate compiled namespace'
            if pending:
                assert indent > pending[-1][0], 'Malformed compiled namespace nesting'
            else:
                while stack and stack[-1][0] >= indent:
                    stack.pop()
            declared.add(alias)
            pending.append((indent, alias))
            continue
        element = re.fullmatch(r'( *)E: ([\w.-]+)(?: \(line=\d+\))?', line)
        if element:
            indent, tag = len(element[1]), element[2]
            if pending:
                assert indent > pending[-1][0], 'Element outside its namespace'
            else:
                while stack and stack[-1][0] >= indent:
                    stack.pop()
            namespaces = (stack[-1][2] if stack else set()) | {alias for _, alias in pending}
            node = {'tag': tag, 'attrs': {}, 'children': []}
            (stack[-1][1]['children'] if stack else roots).append(node)
            stack.append((indent, node, namespaces))
            pending.clear()
            continue
        attribute = re.fullmatch(r'( *)A: ([^\s(=]+)(?:\(0x[0-9a-fA-F]+\))?=(.*)', line)
        assert attribute and stack and not pending, 'Unrecognized compiled manifest structure'
        assert len(attribute[1]) > stack[-1][0], 'Attribute outside its element'
        attrs = stack[-1][1]['attrs']
        name = _attribute_name(attribute[2], stack[-1][2])
        assert name not in attrs, 'Duplicate compiled attribute'
        attrs[name] = _value(attribute[3])
    assert not pending, 'Namespace without a compiled element'
    assert 'android' in declared, 'Missing compiled Android namespace'
    assert len(roots) == 1 and roots[0]['tag'] == 'manifest', 'Expected one compiled manifest'
    return roots[0]


def _children(node, tag):
    return [child for child in node['children'] if child['tag'] == tag]


def _component(name):
    assert isinstance(name, str) and name, 'Missing component name'
    return PACKAGE + name if name.startswith('.') else PACKAGE + '.' + name if '.' not in name else name


def audit_manifest(text):
    root = parse_xmltree(text)
    assert root['attrs'].get('package') == PACKAGE, 'Unexpected compiled package'
    assert type(root['attrs'].get('android:versionCode')) is int and root['attrs']['android:versionCode'] == VERSION_CODE, 'Unexpected compiled version code'
    assert root['attrs'].get('android:versionName') == VERSION_NAME, 'Unexpected compiled version name'
    major = root['attrs'].get('android:versionCodeMajor', 0)
    assert type(major) is int and major == 0, 'Unexpected compiled major version code'
    declarations = [child for child in root['children'] if child['tag'].startswith('uses-permission')]
    permissions = [child['attrs'].get('android:name') for child in declarations]
    assert len(permissions) == len(set(permissions)), 'Duplicate permission declarations'
    assert set(permissions) == EXPECTED_PERMISSIONS, 'Unexpected or missing compiled permissions'
    assert all(child['tag'] == 'uses-permission' and 'android:maxSdkVersion' not in child['attrs']
               for child in declarations), 'Conditional required permission declaration'
    apps = _children(root, 'application')
    assert len(apps) == 1, 'Expected one application'
    app = apps[0]
    assert app['attrs'].get('android:allowBackup') is False, 'Backups must remain disabled'
    assert 'android:process' not in app['attrs'], 'Unexpected separate application process'
    assert 'android:permission' not in app['attrs'], 'Binding permission must be service-specific'
    assert not _children(app, 'receiver'), 'No boot or other receivers are permitted'
    activities = {_component(child['attrs'].get('android:name')): child for child in _children(app, 'activity')}
    assert set(activities) == {PACKAGE + '.MainActivity', PACKAGE + '.UpdateActivity'}, 'Unexpected activity'
    updater = activities[PACKAGE + '.UpdateActivity']
    assert updater['attrs'].get('android:exported') is False and not updater['children'], 'Updater must be private'
    providers = _children(app, 'provider')
    assert len(providers) == 1, 'Expected one restricted APK provider'
    provider = providers[0]
    assert _component(provider['attrs'].get('android:name')) == PACKAGE + '.UpdateApkProvider'
    assert provider['attrs'].get('android:authorities') == PACKAGE + '.updates'
    assert provider['attrs'].get('android:exported') is False
    assert provider['attrs'].get('android:grantUriPermissions') is True
    assert 'android:process' not in provider['attrs'], 'Provider must use the app process'
    assert provider['children'] == [{'tag': 'grant-uri-permission', 'attrs': {'android:pathPrefix': '/update-'}, 'children': []}], 'Only update URI grants allowed'
    services = {}
    for service in _children(app, 'service'):
        name = _component(service['attrs'].get('android:name'))
        assert name not in services, 'Duplicate service'
        services[name] = service
    assert set(services) == {PACKAGE + '.ProxyService', PACKAGE + '.PhoneVpnService'}, 'Unexpected or missing service'
    report = {}
    for name, service in services.items():
        attrs = service['attrs']
        assert attrs.get('android:exported') is False, name + ' must not be exported'
        assert attrs.get('android:stopWithTask') is False, name + ' must retain explicit background policy'
        assert 'android:process' not in attrs and attrs.get('android:isolatedProcess', False) is False, 'Service must use the owned application process'
        fgs = attrs.get('android:foregroundServiceType')
        assert type(fgs) is int, 'FGS type must be a compiled constant'
        if name.endswith('.PhoneVpnService'):
            assert attrs.get('android:permission') == VPN_PERMISSION, 'Only system may bind phone VPN'
            assert fgs == SYSTEM_EXEMPTED, 'Unexpected phone VPN FGS type'
            filters = _children(service, 'intent-filter')
            assert len(filters) == 1, 'Expected one VPN intent filter'
            actions = filters[0]['children']
            assert len(actions) == 1 and actions[0]['tag'] == 'action' and actions[0]['attrs'].get('android:name') == 'android.net.VpnService', 'Invalid VPN service action'
            metadata = _children(service, 'meta-data')
            assert len(metadata) == 1 and metadata[0]['attrs'].get('android:name') == 'android.net.VpnService.SUPPORTS_ALWAYS_ON' and metadata[0]['attrs'].get('android:value') is False, 'Always-on VPN must be explicitly disabled'
        else:
            assert 'android:permission' not in attrs, 'Unexpected LAN service binding permission'
            assert fgs == CONNECTED_DEVICE | SYSTEM_EXEMPTED, 'Unexpected session service FGS type'
            assert not _children(service, 'intent-filter'), 'LAN session service must not expose an intent filter'
        report[name] = {'exported': False, 'foreground_service_types': fgs,
                        'binding_permission': attrs.get('android:permission'),
                        'stop_with_task': False}
    return {'services': report, 'receivers': [], 'always_on_vpn': False,
            'permissions': sorted(permissions), 'version_code': VERSION_CODE,
            'version_name': VERSION_NAME}
