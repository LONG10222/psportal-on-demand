// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import org.psportal.engine.androidmobile.Androidmobile;

/** Direct gomobile/JNI binding to bundled native/androidmobile full Mihomo core. No subprocess or downloaded executable. */
final class NativeEngine implements SessionController.Engine {
    @Override public void start(String configJson) throws Exception { Androidmobile.start(configJson); }
    @Override public void stop() { Androidmobile.stop(); }
    @Override public String status() { return Androidmobile.runtimeStatus(); }
    @Override public void prepare() throws Exception { Androidmobile.prepare(); }
    @Override public void testNodes() throws Exception { Androidmobile.testNodes(); }
    @Override public void selectNode(String mode, String name, int threshold) throws Exception { Androidmobile.selectNodeWithThreshold(mode, name, threshold); }
    @Override public String groupChoices(String group) throws Exception { return Androidmobile.groupChoices(group); }
    @Override public void selectGroup(String group, String choice) throws Exception { Androidmobile.selectGroup(group, choice); }
}
