// SPDX-License-Identifier: GPL-3.0-only
package engine

import "testing"

func TestSubscriptionAccountingUsesOnlyBoundedServerValues(t *testing.T) {
	info := parseSubscriptionInfo("upload=100; download=200; total=1000; expire=2000000000; token=opaque")
	if len(info) != 4 || info["download"] != 200 || info["total"] != 1000 {
		t.Fatal(info)
	}
	for _, header := range []string{"total=-1; expire=99999999999999999", "total=NaN", "upload=18446744073709551615"} {
		if len(parseSubscriptionInfo(header)) != 0 {
			t.Fatal("Invalid accounting accepted")
		}
	}
	for _, url := range []string{"https://127.0.0.1/token", "http://provider.example/token", "https://user:secret@provider.example/token"} {
		if SubscriptionInfo(url) != `{"available":false}` {
			t.Fatal("Unsafe URL accepted")
		}
	}
}
