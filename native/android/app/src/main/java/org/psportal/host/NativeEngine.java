// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import org.psportal.engine.mobile.Mobile;

/** Direct gomobile/JNI binding to bundled native/mobile. No subprocess or downloaded executable. */
final class NativeEngine implements SessionController.Engine {
    @Override public void start(String configJson) throws Exception { Mobile.start(configJson); }
    @Override public void stop() { Mobile.stop(); }
    @Override public String status() { return Mobile.runtimeStatus(); }
    @Override public void prepare() throws Exception { Mobile.prepare(); }
    @Override public void testNodes() throws Exception { Mobile.testNodes(); }
    @Override public void selectNode(String mode, String name, int threshold) throws Exception { Mobile.selectNodeWithThreshold(mode, name, threshold); }
}
