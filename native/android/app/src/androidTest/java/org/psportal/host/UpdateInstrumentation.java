// SPDX-License-Identifier: GPL-3.0-only
package org.psportal.host;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.database.Cursor;
import android.provider.OpenableColumns;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import org.json.JSONObject;
import org.json.JSONArray;
import java.io.File;
import java.io.FileOutputStream;
import java.io.FileInputStream;
import java.lang.reflect.Method;
import java.lang.reflect.InvocationTargetException;
import java.security.MessageDigest;
import java.util.Locale;

/** Exercises real APK verification/provider/UI; never grants install permission or installs. */
public final class UpdateInstrumentation extends Instrumentation {
    private int assertions;
    private Bundle arguments;
    @Override public void onCreate(Bundle args) { arguments = args; super.onCreate(args); start(); }
    private void check(boolean value, String label) { assertions++; if (!value) throw new AssertionError(label); }
    private static View tagged(View root, String tag) {
        if (tag.equals(root.getTag())) return root;
        if (root instanceof ViewGroup) for (int i=0;i<((ViewGroup)root).getChildCount();i++) { View found=tagged(((ViewGroup)root).getChildAt(i),tag); if(found!=null)return found; }
        return null;
    }
    private static JSONObject asset(int version, String abi) throws Exception {
        String name="StarPass-Android-"+version+"-"+abi+".apk";
        return new JSONObject().put("name",name).put("browser_download_url","https://github.com/LONG10222/psportal-on-demand/releases/download/test/"+name)
            .put("size",4096).put("digest","sha256:"+"0".repeat(64)).put("state","uploaded");
    }
    private static JSONObject release(JSONArray assets) throws Exception {
        return new JSONObject().put("draft",false).put("prerelease",false).put("tag_name","test").put("name","Test").put("body","Changes").put("assets",assets);
    }
    private static Object invoke(Method method, Object target, Object... args) throws Exception {
        try { return method.invoke(target,args); }
        catch (InvocationTargetException e) { if(e.getCause() instanceof Exception)throw (Exception)e.getCause(); throw e; }
    }
    private static String hash(File file) throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256"); byte[] bytes=new byte[65536]; int n;
        try(FileInputStream in=new FileInputStream(file)){while((n=in.read(bytes))!=-1)digest.update(bytes,0,n);}
        StringBuilder value=new StringBuilder();for(byte b:digest.digest())value.append(String.format(Locale.ROOT,"%02x",b&255));return value.toString();
    }
    @Override public void onStart() {
        Bundle result=new Bundle();Activity screen=null;File probe=null;
        try {
            Class<?> updater=Class.forName("org.psportal.host.UpdateActivity"), entry=Class.forName("org.psportal.host.UpdateActivity$Asset");
            Method select=updater.getDeclaredMethod("select",JSONObject.class,long.class,String[].class);select.setAccessible(true);
            java.lang.reflect.Field name=entry.getDeclaredField("name");name.setAccessible(true);
            String[] arm={"arm64-v8a"};
            JSONObject data=release(new JSONArray().put(asset(6,"universal")).put(asset(6,"arm64-v8a")).put(asset(6,"x86_64")));
            Object selected=invoke(select,null,data,5L,arm);check(name.get(selected).equals("StarPass-Android-6-arm64-v8a.apk"),"preferred ABI");
            check(name.get(invoke(select,null,data,5L,new String[]{"x86_64"})).equals("StarPass-Android-6-x86_64.apk"),"x86 selection");
            check(invoke(select,null,data,6L,arm)==null,"no downgrade/reinstall");
            data.put("prerelease",true);check(invoke(select,null,data,5L,arm)==null,"pre-release excluded");data.put("prerelease",false).put("draft",true);
            check(invoke(select,null,data,5L,arm)==null,"draft excluded");data.put("draft",false);
            check(name.get(invoke(select,null,release(new JSONArray().put(asset(6,"universal"))),5L,arm)).toString().endsWith("universal.apk"),"universal fallback");
            check(invoke(select,null,release(new JSONArray().put(asset(6,"x86_64"))),5L,arm)==null,"unsupported ABI excluded");
            check(name.get(invoke(select,null,release(new JSONArray().put(asset(6,"arm64-v8a")).put(asset(7,"universal"))),5L,arm)).toString().contains("-7-"),"highest code before ABI");
            for(String key:new String[]{"digest","browser_download_url","size"}) {
                JSONObject invalid=asset(6,"universal");invalid.put(key,key.equals("size")?-1:"invalid");
                boolean rejected=false;try{invoke(select,null,release(new JSONArray().put(invalid)),5L,arm);}catch(Exception expected){rejected=true;}check(rejected,"reject malformed "+key);
            }
            screen=startActivitySync(new Intent().setClassName(getTargetContext(),"org.psportal.host.UpdateActivity").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            Activity shown=screen;runOnMainSync(()->{
                Button action=(Button)tagged(shown.getWindow().getDecorView(),"update_action");
                check(action!=null&&action.getVisibility()==View.GONE,"no install before check");
                check(tagged(shown.getWindow().getDecorView(),"update_status")!=null,"status accessible");
            });
            Method verify=updater.getDeclaredMethod("verifyApk",File.class,entry);verify.setAccessible(true);
            java.lang.reflect.Constructor<?> constructor=entry.getDeclaredConstructor(JSONObject.class,String.class,String.class,String.class);constructor.setAccessible(true);
            File installed=new File(getTargetContext().getApplicationInfo().sourceDir);
            JSONObject same=asset(6,"universal").put("size",installed.length()).put("digest","sha256:"+hash(installed));
            boolean rejected=false;try{invoke(verify,screen,installed,constructor.newInstance(same,"test","Test",""));}catch(java.io.IOException expected){rejected=true;}check(rejected,"same/old APK rejected despite matching hash");
            // Optional explicitly generated APK fixtures test the real platform signature parser.
            for(String key:new String[]{"fixture_good","fixture_bad","fixture_package"}) {
                String path=arguments==null?null:arguments.getString(key);if(path==null)continue;
                File fixture=new File(path);JSONObject meta=asset(6,"universal").put("size",fixture.length()).put("digest","sha256:"+hash(fixture));
                boolean accepted=true;try{invoke(verify,screen,fixture,constructor.newInstance(meta,"test","Test",""));}catch(java.io.IOException expected){accepted=false;}
                check(accepted==key.equals("fixture_good"),"real certificate/package validation: "+key);
            }
            File directory=new File(getTargetContext().getFilesDir(),"updates");directory.mkdirs();probe=new File(directory,"update-"+"0".repeat(64)+".apk");
            try(FileOutputStream out=new FileOutputStream(probe)){out.write(new byte[]{1,2,3});}
            Uri uri=Uri.parse("content://org.psportal.host.updates/"+probe.getName());
            check("application/vnd.android.package-archive".equals(getTargetContext().getContentResolver().getType(uri)),"APK MIME");
            try(Cursor cursor=getTargetContext().getContentResolver().query(uri,null,null,null,null)){check(cursor!=null&&cursor.moveToFirst()&&cursor.getLong(cursor.getColumnIndexOrThrow(OpenableColumns.SIZE))==3,"single-file metadata");}
            try(ParcelFileDescriptor fd=getTargetContext().getContentResolver().openFileDescriptor(uri,"r")){check(fd!=null&&fd.getStatSize()==3,"read-only APK grant");}
            rejected=false;try{getTargetContext().getContentResolver().openFileDescriptor(uri,"w");}catch(Exception expected){rejected=true;}check(rejected,"write denied");
            for(String path:new String[]{"/../ui.xml","/update-../files","/download.part","/"}) {rejected=false;try{getTargetContext().getContentResolver().getType(Uri.parse("content://org.psportal.host.updates"+path));}catch(Exception expected){rejected=true;}check(rejected,"path denied");}
            result.putString("result","PASS: "+assertions+" Android update selection, real APK identity, private provider and UI assertions (no installation permission granted)");finish(Activity.RESULT_OK,result);
        } catch(Throwable error) {result.putString("failure",android.util.Log.getStackTraceString(error));finish(Activity.RESULT_CANCELED,result);}
        finally {if(probe!=null)probe.delete();if(screen!=null){Activity shown=screen;runOnMainSync(shown::finish);}}
    }
}
