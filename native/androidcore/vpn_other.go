// SPDX-License-Identifier: GPL-3.0-only
//go:build !android

package androidcore

import "errors"

// The phone VPN path is deliberately unavailable on developer/test host OSes.
func (e *Engine) StartPhoneVPN(fd int, protector SocketProtector) error {
	return errors.New("phone VPN requires Android VpnService consent")
}
