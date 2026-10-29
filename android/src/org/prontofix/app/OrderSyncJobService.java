package org.prontofix.app;
import android.app.job.JobParameters;
import android.app.job.JobService;
import android.content.SharedPreferences;
import android.os.AsyncTask;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Map;
public class OrderSyncJobService extends JobService {
 @Override public boolean onStartJob(final JobParameters params) {
  AsyncTask.execute(new Runnable(){ public void run(){
   SharedPreferences p=getSharedPreferences(MainActivity.OUTBOX_PREFS,MODE_PRIVATE);
   Map<String,?> all=p.getAll();
   java.util.HashSet<String> ids=new java.util.HashSet<String>();
   for(String k:all.keySet()) if(k.startsWith("pending:") && Boolean.TRUE.equals(all.get(k))) ids.add(k.substring(8));
   for(String id:ids) {
    String base=p.getString("base:"+id,null), token=p.getString("token:"+id,null), body=p.getString("body:"+id,null);
    if(base==null||token==null||body==null) continue;
    HttpURLConnection c=null;
    try {
     c=(HttpURLConnection)new URL(base+"/orders").openConnection(); c.setRequestMethod("POST"); c.setConnectTimeout(15000); c.setReadTimeout(20000); c.setDoOutput(true);
     c.setRequestProperty("Authorization","Bearer "+token); c.setRequestProperty("Content-Type","application/json"); c.setRequestProperty("X-Client-Request-ID",id);
     byte[] bytes=body.getBytes("UTF-8"); c.setFixedLengthStreamingMode(bytes.length);
     OutputStream out=c.getOutputStream(); out.write(bytes); out.close();
     int code=c.getResponseCode();
     if(code>=200&&code<300) p.edit().remove("pending:"+id).remove("base:"+id).remove("token:"+id).remove("body:"+id).commit();
     else if(code>=400&&code<500&&code!=408&&code!=429) p.edit().putBoolean("pending:"+id,false).commit();
    } catch(Exception ignored) { } finally { if(c!=null)c.disconnect(); }
   }
   jobFinished(params,false);
  }});
  return true;
 }
 @Override public boolean onStopJob(JobParameters params){ return true; }
}