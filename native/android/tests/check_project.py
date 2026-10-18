"""Structural guardrails, not an Android build or device test."""
import pathlib
import xml.etree.ElementTree as ET
root = pathlib.Path(__file__).resolve().parents[1]
a = '{http://schemas.android.com/apk/res/android}'
manifest = ET.parse(root/'app/src/main/AndroidManifest.xml').getroot()
permissions = {p.attrib[a+'name'] for p in manifest.findall('uses-permission')}
assert 'android.permission.INTERNET' in permissions
assert 'android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE' in permissions
assert 'android.permission.CHANGE_NETWORK_STATE' in permissions
assert 'android.permission.ACCESS_LOCAL_NETWORK' not in permissions, 'target36 must not request target37 permission'
assert 'android.permission.RECEIVE_BOOT_COMPLETED' not in permissions
app = manifest.find('application')
assert app.attrib[a+'allowBackup'] == 'false'
assert len(app.findall('service')) == 1
service = app.find('service')
assert service.attrib[a+'exported'] == 'false'
assert service.attrib[a+'foregroundServiceType'] == 'connectedDevice'
assert not app.findall('receiver')
src = root/'app/src/main/java/org/psportal/host'
service_source = (src/'ProxyService.java').read_text()
assert 'START_NOT_STICKY' in service_source and 'START_STICKY' not in service_source
assert 'onTaskRemoved' in service_source and 'onDestroy' in service_source
# API26 emulator regression: task removal has an internal framework start ID,
# so a guarded unconditional stop is needed after native teardown completes.
assert 'onTaskRemoved(Intent rootIntent) { requestStop(latestStartId, true); }' in service_source
assert 'if (startId != latestStartId) return;' in service_source
assert 'if (taskRemoved) stopSelf();' in service_source
native_source = (src/'NativeEngine.java').read_text()
assert 'org.psportal.engine.mobile.Mobile' in native_source
assert 'Mobile.start(configJson)' in native_source
for source in src.glob('*.java'):
    content = source.read_text()
    assert 'ProcessBuilder' not in content and 'Runtime.getRuntime().exec' not in content
    assert 'VpnService' not in content
build = (root/'app/build.gradle').read_text()
assert build.count('signingConfig = null') == 2
assert 'targetSdk 36' in build and 'minSdk 26' in build
assert 'verifyEmbeddedEngine' in build
assert "gradleProperty('psportalAbiSplits')" in build and '.getOrElse(false)' in build
assert "include 'arm64-v8a', 'x86_64'" in build and 'universalApk false' in build
strings = {entry.attrib.get('name') for entry in ET.parse(root/'app/src/main/res/values/strings.xml').getroot()}
import re
for source in src.glob('*.java'):
    for name in re.findall(r'R\.string\.([a-zA-Z_0-9]+)', source.read_text()):
        if name != 'cancel': assert name in strings, f'Missing string {name}'
for resource in root.glob('app/src/main/res/**/*.xml'): ET.parse(resource)
print('PASS: Android manifest, lifecycle, JNI linkage, unsigned-build and XML structural guards')
