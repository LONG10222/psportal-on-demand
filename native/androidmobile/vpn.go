// SPDX-License-Identifier: GPL-3.0-only
package androidmobile

import "github.com/psportal/psportal/native/androidcore"

// SocketProtector receives only an already-created socket descriptor. Android
// must call VpnService.protect and return its real result, never unconditional true.
type SocketProtector interface{ Protect(fd int) bool }

func StartPhoneVPN(fd int, protector SocketProtector) error {
	app, err := activeEngine()
	if err != nil {
		return err
	}
	return app.StartPhoneVPN(fd, protector)
}

func StopPhoneVPN() {
	lifecycleMu.Lock()
	defer lifecycleMu.Unlock()
	app, err := activeEngine()
	if err == nil {
		app.StopPhoneVPN()
	}
}

func ReleasePhoneVPNProtection() {
	lifecycleMu.Lock()
	defer lifecycleMu.Unlock()
	androidcore.ReleasePhoneVPNProtection()
}
