// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileNotFoundException;

/** Only an immutable update APK can be shared, using a temporary read grant. */
public final class UpdateApkProvider extends ContentProvider {
    static final String AUTHORITY = "org.psportal.host.updates";
    static final String MIME = "application/vnd.android.package-archive";
    static Uri uri(File file) { return new Uri.Builder().scheme("content").authority(AUTHORITY).appendPath(file.getName()).build(); }
    private File file(Uri uri) {
        if (!"content".equals(uri.getScheme()) || !AUTHORITY.equals(uri.getAuthority()) ||
                uri.getQuery() != null || uri.getFragment() != null ||
                !uri.getPath().matches("/update-[0-9a-f]{64}\\.apk")) throw new IllegalArgumentException("Unknown update");
        return new File(new File(getContext().getFilesDir(), "updates"), uri.getLastPathSegment());
    }
    @Override public boolean onCreate() { return true; }
    @Override public String getType(Uri uri) { file(uri); return MIME; }
    @Override public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!"r".equals(mode)) throw new FileNotFoundException("Read only");
        return ParcelFileDescriptor.open(file(uri), ParcelFileDescriptor.MODE_READ_ONLY);
    }
    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] args, String order) {
        File apk = file(uri);
        String[] columns = projection == null ? new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE} : projection;
        MatrixCursor cursor = new MatrixCursor(columns); Object[] row = new Object[columns.length];
        for (int i = 0; i < columns.length; i++) {
            if (OpenableColumns.DISPLAY_NAME.equals(columns[i])) row[i] = "StarPass-update.apk";
            else if (OpenableColumns.SIZE.equals(columns[i])) row[i] = apk.length();
        }
        cursor.addRow(row); return cursor;
    }
    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri uri, ContentValues values, String where, String[] args) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri uri, String where, String[] args) { throw new UnsupportedOperationException(); }
}
