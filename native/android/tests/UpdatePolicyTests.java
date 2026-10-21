// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.security.MessageDigest;
import java.util.Arrays;

public final class UpdatePolicyTests {
    private static int assertions;
    private static void check(boolean value) { assertions++; if (!value) throw new AssertionError(); }
    private interface Attempt { void run() throws Exception; }
    private static void rejects(Attempt attempt) throws Exception {
        try { attempt.run(); } catch (IOException expected) { assertions++; return; }
        throw new AssertionError("Accepted invalid update");
    }
    public static void main(String[] args) throws Exception {
        String asset = "StarPass-Android-6-arm64-v8a.apk";
        check(UpdatePolicy.version(asset) == 6);
        for (String name : new String[]{"StarPass-Android-0-universal.apk", "StarPass-Android-06-universal.apk", "StarPass-Android-2147483648-universal.apk", "StarPass-Android-6-armeabi-v7a.apk", "app-debug.apk", asset + ".zip"}) check(UpdatePolicy.version(name) == -1);
        String[] abis = {"arm64-v8a", "x86_64"};
        check(UpdatePolicy.preference(asset, abis) == 0);
        check(UpdatePolicy.preference("StarPass-Android-6-x86_64.apk", abis) == 1);
        check(UpdatePolicy.preference("StarPass-Android-6-universal.apk", abis) == 2);
        check(UpdatePolicy.preference(asset, new String[]{"x86_64"}) == Integer.MAX_VALUE);
        String url = "https://github.com/" + UpdatePolicy.REPOSITORY + "/releases/download/v0.6/" + asset;
        check(UpdatePolicy.assetUrl(url,"v0.6",asset));
        for (String bad : new String[]{url.replace("https:","http:"), url.replace("github.com", "github.com.evil.test"), url.replace(UpdatePolicy.REPOSITORY,"other/repo"), url + "?url=x", url + "#fragment", url.replace("github.com", "user@github.com"), url.replace("github.com", "github.com:8443")}) check(!UpdatePolicy.assetUrl(bad,"v0.6",asset));
        check(UpdatePolicy.downloadUrl("https://release-assets.githubusercontent.com/a?token=temporary"));
        check(!UpdatePolicy.downloadUrl("https://release-assets.githubusercontent.com.evil.test/a"));
        check(!UpdatePolicy.downloadUrl("file:///etc/passwd"));
        String zeros = "0".repeat(64);
        check(UpdatePolicy.digest("sha256:" + zeros).equals(zeros));
        rejects(() -> UpdatePolicy.digest("md5:" + zeros)); rejects(() -> UpdatePolicy.digest("sha256:abc"));
        byte[] bytes = new byte[4096]; Arrays.fill(bytes,(byte)7);
        String hash = java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        UpdatePolicy.copyVerified(new ByteArrayInputStream(bytes),output,bytes.length,hash,count -> check(count == bytes.length));
        check(Arrays.equals(bytes,output.toByteArray()));
        rejects(() -> UpdatePolicy.copyVerified(new ByteArrayInputStream(bytes),new ByteArrayOutputStream(),bytes.length,zeros,count -> {}));
        rejects(() -> UpdatePolicy.copyVerified(new ByteArrayInputStream(bytes),new ByteArrayOutputStream(),bytes.length-1,hash,count -> {}));
        rejects(() -> UpdatePolicy.copyVerified(new ByteArrayInputStream(bytes),new ByteArrayOutputStream(),bytes.length+1,hash,count -> {}));
        rejects(() -> UpdatePolicy.copyVerified(new ByteArrayInputStream(bytes),new ByteArrayOutputStream(),UpdatePolicy.MAX_APK+1,hash,count -> {}));
        Thread.currentThread().interrupt();
        try { rejects(() -> UpdatePolicy.copyVerified(new ByteArrayInputStream(bytes),new ByteArrayOutputStream(),bytes.length,hash,count -> {})); }
        finally { Thread.interrupted(); }
        rejects(() -> UpdatePolicy.copyVerified(new ByteArrayInputStream(bytes),new ByteArrayOutputStream(),bytes.length,hash,count -> { throw new IOException("cancel"); }));
        System.out.println("PASS: " + assertions + " Android update URL/ABI/integrity/cancellation assertions");
    }
}
