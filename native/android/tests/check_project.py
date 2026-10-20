"""Structural guardrails, not an Android build or device test."""
import pathlib
import xml.etree.ElementTree as ET
root = pathlib.Path(__file__).resolve().parents[1]
a = '{http://schemas.android.com/apk/res/android}'
t = '{http://schemas.android.com/tools}'
manifest = ET.parse(root/'app/src/main/AndroidManifest.xml').getroot()
permissions = {p.attrib[a+'name'] for p in manifest.findall('uses-permission')}
assert 'android.permission.INTERNET' in permissions
assert 'android.permission.FOREGROUND_SERVICE' in permissions
assert 'android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE' in permissions
assert 'android.permission.FOREGROUND_SERVICE_SYSTEM_EXEMPTED' in permissions
assert 'android.permission.CHANGE_NETWORK_STATE' in permissions
assert not permissions.intersection({'android.permission.SCHEDULE_EXACT_ALARM', 'android.permission.USE_EXACT_ALARM'}), 'VPN eligibility must not add unrelated alarm permissions'
assert 'android.permission.ACCESS_LOCAL_NETWORK' not in permissions, 'target36 must not request target37 permission'
assert 'android.permission.RECEIVE_BOOT_COMPLETED' not in permissions
app = manifest.find('application')
assert app.attrib[a+'allowBackup'] == 'false'
assert len(app.findall('service')) == 2
services = {entry.attrib[a+'name']: entry for entry in app.findall('service')}
service = services['.ProxyService']
assert service.attrib[a+'exported'] == 'false'
assert service.attrib[a+'foregroundServiceType'] == 'connectedDevice|systemExempted'
vpn_service = services['.PhoneVpnService']
assert vpn_service.attrib[a+'permission'] == 'android.permission.BIND_VPN_SERVICE'
assert vpn_service.attrib[a+'exported'] == 'false'
assert vpn_service.attrib[a+'foregroundServiceType'] == 'systemExempted'
assert vpn_service.find('meta-data').attrib[a+'value'] == 'false'
assert vpn_service.find('intent-filter/action').attrib[a+'name'] == 'android.net.VpnService'
# Lint 8.13.2 omits the runtime OP_ACTIVATE_VPN alternative. Keep its exception
# scoped to exactly these two service elements and preserve all real permissions.
suppressed = [element for element in manifest.iter() if t+'ignore' in element.attrib]
assert suppressed == [service, vpn_service], 'No manifest/application-wide lint suppression'
assert all(element.attrib[t+'ignore'] == 'ForegroundServicePermission' for element in suppressed)
assert service.attrib[a+'stopWithTask'] == 'false', 'Background-on runs survive Recents removal'
assert not app.findall('receiver')
src = root/'app/src/main/java/org/psportal/host'
service_source = (src/'ProxyService.java').read_text()
assert 'START_NOT_STICKY' in service_source and 'START_STICKY' not in service_source
assert 'onTaskRemoved' in service_source and 'onDestroy' in service_source
# API26 emulator regression: task removal has an internal framework start ID,
# so a guarded unconditional stop is needed after native teardown completes.
assert 'BackgroundPolicy.stopWhenTaskRemoved(allowBackground)' in service_source
assert 'BackgroundPolicy.PREFERENCE_KEY, BackgroundPolicy.DEFAULT_ALLOW_BACKGROUND' in service_source
assert 'taskRemovedSinceCommand = true;' in service_source
assert 'taskRemovedSinceCommand = false;' in service_source
assert 'if (startId != latestStartId) return;' in service_source
assert 'if (taskRemoved || taskRemovedSinceCommand) stopSelf();' in service_source
assert 'REQUEST_IGNORE_BATTERY_OPTIMIZATIONS' not in permissions
assert 'android.permission.WAKE_LOCK' not in permissions, 'No unmeasured battery locks'
native_source = (src/'NativeEngine.java').read_text()
assert 'org.psportal.engine.androidmobile.Androidmobile' in native_source
assert 'Androidmobile.start(configJson)' in native_source
for source in src.glob('*.java'):
    content = source.read_text()
    assert 'ProcessBuilder' not in content and 'Runtime.getRuntime().exec' not in content
    if 'extends VpnService' in content: assert source.name == 'PhoneVpnService.java'
build = (root/'app/build.gradle').read_text()
assert build.count('signingConfig = null') == 2
assert 'targetSdk 36' in build and 'minSdk 26' in build
assert 'verifyEmbeddedEngine' in build
assert 'abortOnError true' in build and 'checkReleaseBuilds true' in build
assert 'ForegroundServicePermission' not in build, 'Keep this lint check enabled project-wide'
assert "gradleProperty('psportalAbiSplits')" in build and '.getOrElse(false)' in build
assert "include 'arm64-v8a', 'x86_64'" in build and 'universalApk false' in build
strings = {entry.attrib.get('name') for entry in ET.parse(root/'app/src/main/res/values/strings.xml').getroot()}
import re
for source in src.glob('*.java'):
    for name in re.findall(r'R\.string\.([a-zA-Z_0-9]+)', source.read_text()):
        if name != 'cancel': assert name in strings, f'Missing string {name}'
for resource in root.glob('app/src/main/res/**/*.xml'): ET.parse(resource)
activity = (src/'MainActivity.java').read_text()
assert 'getBoolean("english", false)' in activity and 'getBoolean("dark", true)' in activity
assert 'recreate()' not in activity, 'Language/theme changes must preserve active service and inputs'
assert 'FLAG_SECURE' in activity and 'IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS' in activity
assert 'subscription.setSaveEnabled(false)' in activity
assert 'subscription.setTransformationMethod(android.text.method.PasswordTransformationMethod.getInstance())' in activity, 'setSingleLine can clear password masking; restore the transformation explicitly'
assert activity.index('subscription = input(') < activity.index('subscription.setTransformationMethod(')
assert 'Androidmobile.subscriptionInfo(requested.subscriptionUrl)' in activity
assert 'preparationGeneration++' in activity and 'generation != preparationGeneration' in activity
assert 'pendingPreparation.cancel(true)' in activity, 'Cancel obsolete preparation work'
assert '.putString("subscription"' not in activity and '.putString("subscriptionUrl"' not in activity
assert 'nativeState, "connected_clients"' in activity and 'nativeState, "active_connections"' in activity
assert 'return number >= 0' in activity, 'Missing metrics must stay unknown'
assert 'getMessage()' not in activity, 'Never expose untrusted subscription/native exceptions'
assert 'Androidmobile.prepare()' in native_source and 'Androidmobile.testNodes()' in native_source
assert 'Androidmobile.selectNodeWithThreshold' in native_source
session = (src/'SessionController.java').read_text()
assert 'teardownFinished || commandPending' in session, 'Restart must wait for old probe lane'
assert 'portal-node-probes' in (src/'PortalApplication.java').read_text()
assert 'LanSetup.safeInterface(network.getName())' in (src/'NetworkAddresses.java').read_text()
assert (root/'app/src/main/res/values-en/strings.xml').exists()
print('PASS: Android manifest, lifecycle, JNI, simple-home privacy/localization and XML structural guards')

vpn = (src/'PhoneVpnService.java').read_text()
assert 'START_NOT_STICKY' in vpn and 'START_STICKY' not in vpn
assert 'VpnService.prepare(this)' in vpn and 'hasVpnConflict(this)' in vpn
# Both foreground entries must reject missing/revoked VPN consent before using
# systemExempted. LAN operation continues to request only connectedDevice.
proxy_start = service_source.split('@Override public int onStartCommand(', 1)[1].split('private boolean notificationsAllowed()', 1)[0]
vpn_start = vpn.split('@Override public int onStartCommand(', 1)[1].split('private void startTunnel(', 1)[0]
assert '(!requestedLan && !requestedPhone)' in proxy_start
assert '(requestedPhone && (android.net.VpnService.prepare(this) != null || PhoneVpnService.hasVpnConflict(this)))' in proxy_start
# Framework start IDs change on ignored duplicate commands. Startup identity is
# fenced by SessionController, while service cleanup must use the newest ID.
start_completion = proxy_start.split('session.start(config, () -> {', 1)[1].split('\n        });', 1)[0]
assert 'latestStartId != startId' not in start_completion, 'Duplicate Start must not suppress the current session completion'
assert 'if (destroyed) return;' in start_completion
assert 'finishStop(latestStartId)' in start_completion, 'Failed startup must clean up the newest service command'
assert 'requestStop(latestStartId)' in start_completion, 'VPN startup failure must stop the newest service command'
assert 'finishStop(startId)' not in start_completion and 'requestStop(startId)' not in start_completion
start_dispatch = session.split('public synchronized boolean start(', 1)[1].split('public synchronized void stop(', 1)[0]
assert 'callbacks.execute(() -> {' in start_dispatch and 'if (token == generation) completion.run();' in start_dispatch, 'Fence startup completion at callback dispatch, not only before enqueue'
assert proxy_start.index('android.net.VpnService.prepare(this)') < proxy_start.index('startForeground(')
assert 'if (Build.VERSION.SDK_INT >= 34 && !lanEnabled)' in proxy_start
assert 'else if (Build.VERSION.SDK_INT >= 29 && lanEnabled)' in proxy_start
assert 'ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE' in proxy_start
assert 'else if (VpnService.prepare(this) != null) rejection = "consent_required";' in vpn_start
assert vpn_start.index('VpnService.prepare(this)') < vpn_start.index('if (rejection != null)') < vpn_start.index('startForeground(')
assert 'catch (RuntimeException denied)' in proxy_start and 'catch (RuntimeException denied)' in vpn_start
assert '.addRoute("0.0.0.0", 0).addRoute("::", 0)' in vpn
assert '.addDnsServer("198.18.0.2").addDnsServer("fdfe:dcba:9876::2")' in vpn
assert '.addDisallowedApplication(getPackageName())' in vpn
assert 'allowBypass(' not in vpn and 'allowFamily(' not in vpn
assert 'PhoneVpnService.this.protect((int)fd)' in vpn
assert 'Androidmobile.stopPhoneVPN()' in vpn and 'descriptor.close()' in vpn
assert 'Androidmobile.releasePhoneVPNProtection()' in vpn
assert 'onRevoke()' in vpn and 'onLost(Network n)' in vpn
assert 'new Intent(this, ProxyService.class).setAction(ProxyService.ACTION_STOP)' in vpn
assert 'lanEnabled && !NetworkAddresses.isAssigned(listenAddress)' in service_source
print('PASS: optional Android-only dual-stack VPN, consent, conflict, socket protection and cleanup guards')

# These are source guardrails only; actual widget and OS-consent behavior remains
# covered by Android instrumentation/device checks, never inferred from strings.
config_source = (src/'HostConfig.java').read_text()
assert 'ROUTING_MODES = {"rule", "global", "direct"}' in activity
assert 'getString("routing_mode", "rule")' in activity
assert 'getBoolean("lan_enabled", true)' in activity
assert 'phoneApps.setChecked(PhoneVpnService.isRequested())' in activity
assert '.putBoolean("phone_vpn"' not in activity, 'Never save consent intent as a standing opt-in'
assert 'boolean hasSelectedTraffic = lanSharing.isChecked() || phoneApps.isChecked();' in activity
assert 'start.setEnabled(editable && hasSelectedTraffic)' in activity
assert 'if (!lanSharing.isChecked()) { configureStart(null); return; }' in activity
assert 'pendingConfig.lanEnabled && Permissions.requiresLocalNetwork' in activity
assert 'requested.lanEnabled && !NetworkAddresses.isAssigned' in activity
assert 'if (!lanEnabled && !phoneVpn)' in config_source
assert 'routingMode, boolean lanEnabled, boolean phoneVpn' in config_source
assert 'if (requestCode != REQUEST_PHONE_VPN) return;' in activity
assert 'resultCode == RESULT_OK && pendingConfig != null && phoneApps.isChecked()' in activity
assert 'startActivityForResult(consent, REQUEST_PHONE_VPN)' in activity
assert 'if (!vpnConsentPending)' in activity, 'Retain setup only for the explicit OS consent activity'
assert 'resumeAfterVpnConsent = false; continueStart();' in activity
assert 'BackgroundPolicy.stopWhenUiHidden(backgroundSharing.isChecked(), isChangingConfigurations())' in activity
assert '!PhoneVpnService.isActive() && pendingConfig == null' in activity, 'Wait for old VPN cleanup before a new session'
assert 'if (!checked && PhoneVpnService.isRequested()) PhoneVpnService.stop(this)' in activity
assert 'snapshot.phase == SessionController.Phase.RUNNING && phoneApps.isChecked()' in activity, 'Permit only live OFF; live ON requires a new Start'
assert 'nativeState.optString("routing_mode", "")' in activity
assert 'coreName + " · "' in activity and 'phoneVpnDescription()' in activity
assert 'two improving rounds' not in activity and '连续两轮' not in activity
print('PASS: independent routing/LAN/phone/background UI, explicit consent, cancellation and safe mode-status guards')
assert 'phoneRequested && PhoneVpnService.requestPending()' in service_source, 'Canceled phone selection must not start from a queued core callback'
assert 'if (!requested)' in vpn, 'A queued VPN Start must honor a newer off intent'
assert 'STATE.stop("stopped")' in vpn, 'Live OFF invalidates native-start generations synchronously'

assert 'state.optJSONArray("ignored_profile_settings")' in activity
assert 'Math.min(settings.length(), 64)' in activity
assert 'RuntimePresentation.settingLabel(settings.optString(i, ""), english)' in activity
assert 'RuntimePresentation.profileError(nativeState.optString("error_code", ""), english)' in activity
assert 'state.optJSONArray("policy_groups")' in activity and 'Math.min(groups.length(), 20)' in activity
assert 'safeNodeName(state.optString("selected_group", ""))' in activity

assert 'UDP unsupported by the selected node is blocked, without direct fallback' in activity
assert 'ICMP (ping) is unsupported' in activity
assert 'including in Direct mode. Turn it off to restore normal networking.' in activity
assert 'Phone routing currently supports TCP and DNS only' not in activity

# Full profiles keep their native group algorithms. Choices are fetched only
# for a selected manual group, rather than copying every membership into status.
assert 'session.groupChoices(sessionId, groupName' in activity
assert 'session.selectGroup(sessionId, groupName, names.get(index))' in activity
assert 'session.control(sessionId, action, mode, name, improvement)' in activity
assert 'sessionId != session.sessionId()' in activity
assert 'uiGeneration != nodeUiGeneration' in activity
assert 'visible = false;\n        nodeUiGeneration++;\n        dismissNodeDialog();' in activity, 'A pending group result must not reopen after leaving and returning'
assert 'nodeDialog != null && !canSelectInSession(nodeDialogSession)' in activity
assert 'RuntimeNodePresentation.selectableGroup(selectable, count(group, "choice_count"))' in activity
assert 'Math.min(groups.length(), 257)' in activity and 'choices.length() > 1256' in activity
assert 'boolean nodeEditable = snapshot.phase == SessionController.Phase.RUNNING && !session.commandPending()' in activity, 'Loading/testing must remain available for full profiles'
assert 'chooseGroup.setEnabled(canSelectRoute && nativeState.optBoolean("group_management", false))' in activity
assert 'Load live nodes' in activity and 'Load & test nodes' not in activity, 'Loading is not a completed latency test'
assert 'RuntimeNodePresentation.latency(delay, healthy, english)' in activity
assert 'Selected route / group: ' in activity, 'Automatic group name must not be mislabeled as a leaf node'
assert 'subscriptionInfo.updatedAt' in activity and 'System.currentTimeMillis() / 1000' in activity
assert 'main.postDelayed(this, 2000)' in activity and 'main.removeCallbacks(networkTick)' in activity
assert 'session and reset after Stop' in activity
assert 'Androidmobile.groupChoices(group)' in native_source and 'Androidmobile.selectGroup(group, choice)' in native_source
print('PASS: bounded session-fenced manual groups, honest latency/accounting and visible network refresh guards')

product_mode = (src/'ProductMode.java').read_text()
assert 'GAME(true, false), MIXED(true, true), CLASH(false, true)' in product_mode
assert 'return null;' in product_mode, 'Both inputs off must not silently enable another mode'
assert 'TCP only' in product_mode and 'not guaranteed' in product_mode
assert 'Start requires Android VPN consent' in product_mode
assert '星渡 StarPass' in activity
assert 'ProductMode.fromInputs(lanSharing.isChecked(), phoneApps.isChecked())' in activity
assert 'if (!canChangeProductMode()) { syncProductMode(); return; }' in activity
assert 'if (mode == null) productModes.clearCheck();' in activity
assert 'configurationViews.add(choice)' in activity, 'Disable each radio button during pending or active sessions'
assert 'pendingConfig != null || preparing || launchRequested || addressChoiceOpen || vpnConsentPending' in activity
preset_handler = activity.split('productModes.setOnCheckedChangeListener(', 1)[1].split('text(subscriptionCard,', 1)[0]
assert 'lanSharing.setChecked(mode.lanEnabled); phoneApps.setChecked(mode.phoneVpn);' in preset_handler
assert 'vpnConsentGranted = false' in preset_handler
assert 'subscription.setText' not in preset_handler and 'routing.setSelection' not in preset_handler
assert 'startService(' not in preset_handler and 'startForegroundService(' not in preset_handler and 'VpnService.prepare(' not in preset_handler
assert '.putBoolean("phone_vpn"' not in activity and '.putString("product_mode"' not in activity
print('PASS: StarPass game/mixed/Clash input presets, separate routing, consent and startup boundaries')

assert 'A connection does not prove Internet access; verify on the device.' in activity
assert 'Open a webpage on the device, then test the intended game feature' in activity
assert 'Turn its HTTP proxy off when finished.' in activity
print('PASS: novice game setup separates connection evidence from verified access and explains cleanup')
