package org.prontofix.app.data;
import android.content.Context;
import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
/** Single WorkManager lane. An order is acknowledged only after server returns its durable ID. */
public final class QueueDrainWorker extends Worker {
 public QueueDrainWorker(@NonNull Context c,@NonNull WorkerParameters p){super(c,p);}
 @NonNull @Override public Result doWork(){
  SyncDatabase db=SyncDatabase.get(getApplicationContext());
  try {
   for(SyncTask task:db.tasks().pending()){
    if(isStopped())return Result.retry();
    if(!"ORDER".equals(task.kind))continue;
    if(task.status.equals(SyncRepository.SENDING))db.tasks().setState(task.id,SyncRepository.RETRY,System.currentTimeMillis(),"Recovered interrupted attempt",0);
    task=db.tasks().get(task.id); if(task==null||"CANCELED".equals(task.status))continue;
    db.tasks().setState(task.id,SyncRepository.SENDING,System.currentTimeMillis(),null,1);
    try{
     JSONObject env=new JSONObject(task.payload); String base=env.getString("baseUrl").replaceAll("/+$","");
     String req=env.getString("requestId"); JSONObject body=env.getJSONObject("body");
     HttpURLConnection con=(HttpURLConnection)new URL(base+"/orders").openConnection();
     con.setRequestMethod("POST");con.setConnectTimeout(20000);con.setReadTimeout(30000);con.setDoOutput(true);
     con.setRequestProperty("Authorization","Bearer "+task.authToken);con.setRequestProperty("Content-Type","application/json; charset=utf-8");con.setRequestProperty("X-Client-Request-ID",req);
     byte[] bytes=body.toString().getBytes(StandardCharsets.UTF_8);con.setFixedLengthStreamingMode(bytes.length);
     try(OutputStream out=con.getOutputStream()){out.write(bytes);}
     int status=con.getResponseCode(); java.io.InputStream stream=status>=200&&status<300?con.getInputStream():con.getErrorStream();
     StringBuilder text=new StringBuilder(); if(stream!=null)try(BufferedReader rd=new BufferedReader(new InputStreamReader(stream,StandardCharsets.UTF_8))){String line;while((line=rd.readLine())!=null)text.append(line);}
     if(status>=200&&status<300){
      JSONObject reply=new JSONObject(text.toString()); long remote=reply.getLong("id");
      db.tasks().setConfirmed(task.id,remote,System.currentTimeMillis());
     } else if(status==401){
      db.tasks().setState(task.id,SyncRepository.ERROR,System.currentTimeMillis(),"HTTP 401: требуется повторная авторизация",0);
     } else if(status==400||status==403||status==404||status==409||status==422){
      db.tasks().setState(task.id,SyncRepository.ERROR,System.currentTimeMillis(),"HTTP "+status+": "+text,0);
     } else {db.tasks().setState(task.id,SyncRepository.RETRY,System.currentTimeMillis(),"HTTP "+status,0);return Result.retry();}
     con.disconnect();
    }catch(Exception e){db.tasks().setState(task.id,SyncRepository.RETRY,System.currentTimeMillis(),e.getClass().getSimpleName()+": "+e.getMessage(),0);return Result.retry();}
   }
   boolean pending=!db.tasks().pending().isEmpty()||!db.attachments().pending().isEmpty();
   return pending?Result.retry():Result.success();
  }catch(Exception e){return Result.retry();}
 }
}