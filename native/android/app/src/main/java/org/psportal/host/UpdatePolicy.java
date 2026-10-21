// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Release contract independent of Android UI and network transport. */
public final class UpdatePolicy {
    public static final String REPOSITORY = "LONG10222/psportal-on-demand";
    public static final String ENDPOINT = "https://api.github.com/repos/" + REPOSITORY + "/releases/latest";
    public static final long MAX_APK = 256L * 1024 * 1024;
    private static final Pattern ASSET = Pattern.compile("StarPass-Android-([1-9][0-9]{0,8})-(arm64-v8a|x86_64|universal)\\.apk");
    private UpdatePolicy() {}

    public static int version(String name) {
        Matcher match = ASSET.matcher(name);
        return match.matches() ? Integer.parseInt(match.group(1)) : -1;
    }
    public static int preference(String name, String[] abis) {
        Matcher match = ASSET.matcher(name);
        if (!match.matches()) return Integer.MAX_VALUE;
        for (int i = 0; i < abis.length; i++) if (match.group(2).equals(abis[i])) return i;
        return match.group(2).equals("universal") ? abis.length : Integer.MAX_VALUE;
    }
    public static boolean assetUrl(String url, String tag, String name) {
        try {
            URI uri = URI.create(url);
            return safeHttps(uri) && "github.com".equals(uri.getHost()) && uri.getQuery() == null &&
                    uri.getPath().equals("/" + REPOSITORY + "/releases/download/" + tag + "/" + name);
        } catch (IllegalArgumentException e) { return false; }
    }
    public static boolean downloadUrl(String url) {
        try {
            URI uri = URI.create(url);
            return safeHttps(uri) && ("github.com".equals(uri.getHost()) ||
                    "release-assets.githubusercontent.com".equals(uri.getHost()) ||
                    "objects.githubusercontent.com".equals(uri.getHost()));
        } catch (IllegalArgumentException e) { return false; }
    }
    private static boolean safeHttps(URI uri) {
        return "https".equals(uri.getScheme()) && uri.getRawUserInfo() == null &&
                (uri.getPort() == -1 || uri.getPort() == 443) && uri.getFragment() == null;
    }
    public static String digest(String value) throws IOException {
        if (value == null || !value.matches("sha256:[0-9a-fA-F]{64}")) throw new IOException("digest");
        return value.substring(7).toLowerCase(Locale.ROOT);
    }
    public interface Progress { void bytes(long count) throws IOException; }
    public static void copyVerified(InputStream input, OutputStream output, long expected, String hash, Progress progress) throws IOException {
        if (expected < 1024 || expected > MAX_APK || !hash.matches("[0-9a-f]{64}")) throw new IOException("metadata");
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] buffer = new byte[65536]; long count = 0; int read;
            while ((read = input.read(buffer)) != -1) {
                if (Thread.currentThread().isInterrupted()) throw new IOException("cancelled");
                count += read;
                if (count > expected) throw new IOException("size");
                output.write(buffer, 0, read); digest.update(buffer, 0, read); progress.bytes(count);
            }
            if (count != expected || !hex(digest.digest()).equals(hash)) throw new IOException("integrity");
        } catch (java.security.NoSuchAlgorithmException e) { throw new IOException("SHA-256", e); }
    }
    // HexFormat is not available on our Android minimum API.
    private static String hex(byte[] bytes) {
        StringBuilder out = new StringBuilder();
        for (byte value : bytes) out.append(String.format(Locale.ROOT, "%02x", value & 255));
        return out.toString();
    }
}
