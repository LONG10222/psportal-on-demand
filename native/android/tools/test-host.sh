#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT="$ROOT/build/host-tests"
mkdir -p "$OUT"
SRC="$ROOT/app/src/main/java/org/psportal/host"
# A normal JDK is preferred. ECJ_JAR optionally supports a JRE-only build host;
# the script never downloads a compiler or accepts any license automatically.
if command -v javac >/dev/null 2>&1; then
  javac -encoding UTF-8 --release 17 -d "$OUT" "$SRC/TrafficPresentation.java" "$ROOT/tests/TrafficPresentationTests.java" "$SRC/HostConfig.java" "$SRC/SessionController.java" "$SRC/LanSetup.java" "$SRC/SubscriptionAccounting.java" "$SRC/RuntimePresentation.java" "$SRC/RuntimeNodePresentation.java" "$SRC/ProductMode.java" "$ROOT/tests/RuntimeNodePresentationTests.java" "$SRC/BackgroundPolicy.java" "$ROOT/tests/HostTests.java" "$ROOT/tests/BackgroundPolicyTests.java" "$SRC/PhoneVpnState.java" "$ROOT/tests/PhoneVpnStateTests.java" "$SRC/UpdatePolicy.java" "$ROOT/tests/UpdatePolicyTests.java"
elif java --list-modules 2>/dev/null | grep -q '^jdk.compiler@'; then
  # Some task runtimes include the compiler module without a javac launcher or
  # ct.sym release archive. Android API compatibility is checked separately.
  java -m jdk.compiler/com.sun.tools.javac.Main -encoding UTF-8 -source 17 -target 17 -d "$OUT" "$SRC/TrafficPresentation.java" "$ROOT/tests/TrafficPresentationTests.java" "$SRC/HostConfig.java" "$SRC/SessionController.java" "$SRC/LanSetup.java" "$SRC/SubscriptionAccounting.java" "$SRC/RuntimePresentation.java" "$SRC/RuntimeNodePresentation.java" "$SRC/ProductMode.java" "$ROOT/tests/RuntimeNodePresentationTests.java" "$SRC/BackgroundPolicy.java" "$ROOT/tests/HostTests.java" "$ROOT/tests/BackgroundPolicyTests.java" "$SRC/PhoneVpnState.java" "$ROOT/tests/PhoneVpnStateTests.java" "$SRC/UpdatePolicy.java" "$ROOT/tests/UpdatePolicyTests.java"
elif [ -n "${ECJ_JAR:-}" ] && [ -f "$ECJ_JAR" ]; then
  java -jar "$ECJ_JAR" -encoding UTF-8 -17 -warn:none -d "$OUT" "$SRC/TrafficPresentation.java" "$ROOT/tests/TrafficPresentationTests.java" "$SRC/HostConfig.java" "$SRC/SessionController.java" "$SRC/LanSetup.java" "$SRC/SubscriptionAccounting.java" "$SRC/RuntimePresentation.java" "$SRC/RuntimeNodePresentation.java" "$SRC/ProductMode.java" "$ROOT/tests/RuntimeNodePresentationTests.java" "$SRC/BackgroundPolicy.java" "$ROOT/tests/HostTests.java" "$ROOT/tests/BackgroundPolicyTests.java" "$SRC/PhoneVpnState.java" "$ROOT/tests/PhoneVpnStateTests.java" "$SRC/UpdatePolicy.java" "$ROOT/tests/UpdatePolicyTests.java"
else
  echo 'A JDK17+ compiler is required (or set ECJ_JAR to an approved Eclipse Java compiler).' >&2
  exit 1
fi
java -cp "$OUT" org.psportal.host.TrafficPresentationTests
java -cp "$OUT" org.psportal.host.HostTests
java -cp "$OUT" org.psportal.host.RuntimeNodePresentationTests
java -cp "$OUT" org.psportal.host.BackgroundPolicyTests
java -cp "$OUT" org.psportal.host.PhoneVpnStateTests
java -cp "$OUT" org.psportal.host.UpdatePolicyTests
"${PYTHON:-python3}" "$ROOT/tests/check_project.py"
