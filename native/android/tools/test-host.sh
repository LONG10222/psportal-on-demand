#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT="$ROOT/build/host-tests"
mkdir -p "$OUT"
SRC="$ROOT/app/src/main/java/org/psportal/host"
# A normal JDK is preferred. ECJ_JAR optionally supports a JRE-only build host;
# the script never downloads a compiler or accepts any license automatically.
if command -v javac >/dev/null 2>&1; then
  javac --release 17 -d "$OUT" "$SRC/HostConfig.java" "$SRC/SessionController.java" "$SRC/LanSetup.java" "$SRC/SubscriptionAccounting.java" "$SRC/RuntimePresentation.java" "$SRC/RuntimeNodePresentation.java" "$SRC/ProductMode.java" "$ROOT/tests/RuntimeNodePresentationTests.java" "$SRC/BackgroundPolicy.java" "$ROOT/tests/HostTests.java" "$ROOT/tests/BackgroundPolicyTests.java" "$SRC/PhoneVpnState.java" "$ROOT/tests/PhoneVpnStateTests.java"
elif java --list-modules 2>/dev/null | grep -q '^jdk.compiler@'; then
  # Some task runtimes include the compiler module without a javac launcher or
  # ct.sym release archive. Android API compatibility is checked separately.
  java -m jdk.compiler/com.sun.tools.javac.Main -source 17 -target 17 -d "$OUT" "$SRC/HostConfig.java" "$SRC/SessionController.java" "$SRC/LanSetup.java" "$SRC/SubscriptionAccounting.java" "$SRC/RuntimePresentation.java" "$SRC/RuntimeNodePresentation.java" "$SRC/ProductMode.java" "$ROOT/tests/RuntimeNodePresentationTests.java" "$SRC/BackgroundPolicy.java" "$ROOT/tests/HostTests.java" "$ROOT/tests/BackgroundPolicyTests.java" "$SRC/PhoneVpnState.java" "$ROOT/tests/PhoneVpnStateTests.java"
elif [ -n "${ECJ_JAR:-}" ] && [ -f "$ECJ_JAR" ]; then
  java -jar "$ECJ_JAR" -17 -warn:none -d "$OUT" "$SRC/HostConfig.java" "$SRC/SessionController.java" "$SRC/LanSetup.java" "$SRC/SubscriptionAccounting.java" "$SRC/RuntimePresentation.java" "$SRC/RuntimeNodePresentation.java" "$SRC/ProductMode.java" "$ROOT/tests/RuntimeNodePresentationTests.java" "$SRC/BackgroundPolicy.java" "$ROOT/tests/HostTests.java" "$ROOT/tests/BackgroundPolicyTests.java" "$SRC/PhoneVpnState.java" "$ROOT/tests/PhoneVpnStateTests.java"
else
  echo 'A JDK17+ compiler is required (or set ECJ_JAR to an approved Eclipse Java compiler).' >&2
  exit 1
fi
java -cp "$OUT" org.psportal.host.HostTests
java -cp "$OUT" org.psportal.host.RuntimeNodePresentationTests
java -cp "$OUT" org.psportal.host.BackgroundPolicyTests
java -cp "$OUT" org.psportal.host.PhoneVpnStateTests
python3 "$ROOT/tests/check_project.py"
