package org.prontofix.app.data;
import android.content.Context;
import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;
import org.json.JSONObject;
import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
/** Serial queue drain: confirm orders before uploading their attachments. */
public final class QueueDrainWorker extends Worker {
 public QueueDrainWorker(@NonNull Context c,@NonNull WorkerParameters p){super(c,p);}
 @NonNull @Override public Result doWork(){
  SyncDatabase db=SyncDatabase.get(getApplicationContext());
  String leaseOwner=UUID.randomUUID().toString();
  try {
   // A network attempt may outlive the normal interval; reclaim only after a conservative lease timeout.
   long leaseCutoff=System.currentTimeMillis()-15L*60L*1000L;
   db.tasks().reclaimExpired(leaseCutoff);
   db.attachments().reclaimExpired(leaseCutoff);
   for(SyncTask task:db.tasks().pending()){
    if(isStopped())return Result.retry();
    if(!"ORDER".equals(task.kind))continue;
    task=db.tasks().get(task.id); if(task==null||"CANCELED".equals(task.status))continue;
    if("UPLOADED".equals(task.status))continue;
    if(db.tasks().claim(task.id,System.currentTimeMillis(),leaseOwner)!=1)continue;
    try{
     JSONObject env=new JSONObject(task.payload); String base=env.getString("baseUrl").replaceAll("/+$","");
     HttpURLConnection con=(HttpURLConnection)new URL(base+"/orders").openConnection();
     con.setRequestMethod("POST");con.setConnectTimeout(20000);con.setReadTimeout(30000);con.setDoOutput(true);
     con.setRequestProperty("Authorization","Bearer "+task.authToken);con.setRequestProperty("Content-Type","application/json; charset=utf-8");con.setRequestProperty("X-Client-Request-ID",env.getString("requestId"));
     byte[] bytes=env.getJSONObject("body").toString().getBytes(StandardCharsets.UTF_8);con.setFixedLengthStreamingMode(bytes.length);
     try(OutputStream out=con.getOutputStream()){out.write(bytes);}
     int status=con.getResponseCode(); String response=readResponse(con,status);con.disconnect();
     if(status>=200&&status<300){long remote=new JSONObject(response).getLong("id");db.tasks().confirmOwned(task.id,remote,System.currentTimeMillis(),leaseOwner);}
     else if(status==401){db.tasks().finishOwned(task.id,leaseOwner,SyncRepository.ERROR,System.currentTimeMillis(),"HTTP 401: требуется повторная авторизация");}
     else if(status==400||status==403||status==404||status==409||status==422){db.tasks().finishOwned(task.id,leaseOwner,SyncRepository.ERROR,System.currentTimeMillis(),"HTTP "+status+": "+response);}
     else {db.tasks().finishOwned(task.id,leaseOwner,SyncRepository.RETRY,System.currentTimeMillis(),"HTTP "+status);return Result.retry();}
    }catch(Exception e){db.tasks().finishOwned(task.id,leaseOwner,SyncRepository.RETRY,System.currentTimeMillis(),e.getClass().getSimpleName()+": "+e.getMessage());return Result.retry();}
   }
   boolean retry=false;
   for(Attachment item:db.attachments().pending()){
    if(isStopped())return Result.retry();
    SyncTask parent=db.tasks().get(item.taskId);
    if(parent==null||"ERROR".equals(parent.status)||"CANCELED".equals(parent.status)){
     db.attachments().setStateIfReady(item.id,SyncRepository.ERROR,parent==null?"Parent order task is missing":"Parent order cannot be synchronized: "+parent.status);continue;
    }
    if(!"UPLOADED".equals(parent.status)||parent.remoteOrderId==null){
     db.attachments().setStateIfReady(item.id,SyncRepository.RETRY,"Waiting for confirmed server order");retry=true;continue;
    }
    if(parent.authToken==null||parent.authToken.isEmpty()){
     db.attachments().setStateIfReady(item.id,SyncRepository.ERROR,"Missing authorization token");continue;
    }
    File file=new File(item.localPath);
    if(!file.isFile()){db.attachments().setStateIfReady(item.id,SyncRepository.ERROR,"Local attachment file is missing");continue;}
    if(db.attachments().claimAt(item.id,System.currentTimeMillis(),leaseOwner)!=1)continue;
    HttpURLConnection con=null;
    try{
     JSONObject env=new JSONObject(parent.payload);String base=env.getString("baseUrl").replaceAll("/+$","");
     String boundary="ProntoFix-"+item.id.replace("-","");
     con=(HttpURLConnection)new URL(base+"/orders/"+parent.remoteOrderId+"/media").openConnection();
     con.setRequestMethod("POST");con.setConnectTimeout(20000);con.setReadTimeout(120000);con.setDoOutput(true);
     con.setRequestProperty("Authorization","Bearer "+parent.authToken);
     con.setRequestProperty("Content-Type","multipart/form-data; boundary="+boundary);
     con.setRequestProperty("X-Client-Upload-ID",item.id);
     con.setRequestProperty("X-Content-SHA256",item.sha256);
     con.setRequestProperty("X-Content-Size",Long.toString(item.sizeBytes));
     String filename=item.displayName.replace("\\","_").replace("\"","_").replace("\r","_").replace("\n","_");
     String head="--"+boundary+"\r\nContent-Disposition: form-data; name=\"file\"; filename=\""+filename+"\"\r\nContent-Type: "+item.mimeType+"\r\n\r\n";
     byte[] prefix=head.getBytes(StandardCharsets.UTF_8),suffix=("\r\n--"+boundary+"--\r\n").getBytes(StandardCharsets.UTF_8);
     con.setChunkedStreamingMode(65536);
     try(OutputStream out=con.getOutputStream();InputStream in=new FileInputStream(file)){
      out.write(prefix);byte[] buf=new byte[65536];int n;while((n=in.read(buf))!=-1){if(isStopped())throw new InterruptedIOException("Worker stopped");out.write(buf,0,n);}out.write(suffix);
     }
     int status=con.getResponseCode();String response=readResponse(con,status);
     if(status>=200&&status<300){
      String remote=new JSONObject(response).getString("id");
      int persisted=db.attachments().setUploadedOwned(item.id,remote,leaseOwner);
      // Keep the local copy unless Room confirms the receipt update.
      if(persisted>0)file.delete();
      else {db.attachments().finishOwned(item.id,leaseOwner,SyncRepository.RETRY,"Server accepted upload but local receipt was not persisted; retry is idempotent");retry=true;}
     }else if(status==401){db.attachments().finishOwned(item.id,leaseOwner,SyncRepository.ERROR,"HTTP 401: требуется повторная авторизация");}
     else if(status==400||status==403||status==404||status==409||status==413||status==422){db.attachments().finishOwned(item.id,leaseOwner,SyncRepository.ERROR,"HTTP "+status+": "+response);}
     else{db.attachments().finishOwned(item.id,leaseOwner,SyncRepository.RETRY,"HTTP "+status);retry=true;}
    }catch(InterruptedIOException e){db.attachments().finishOwned(item.id,leaseOwner,SyncRepository.RETRY,"Upload interrupted; safe to retry");return Result.retry();}
    catch(Exception e){db.attachments().finishOwned(item.id,leaseOwner,SyncRepository.RETRY,e.getClass().getSimpleName()+": "+e.getMessage());retry=true;}
    finally{if(con!=null)con.disconnect();}
   }
   if(retry)return Result.retry();
   // Retry only transient/pending records; terminal ERROR items must not spin forever.
   for(SyncTask t:db.tasks().pending())if("ORDER".equals(t.kind))return Result.retry();
   for(Attachment x:db.attachments().pending())return Result.retry();
   return Result.success();
  }catch(Exception e){return Result.retry();}
 }
 private static String readResponse(HttpURLConnection con,int status)throws IOException{
  InputStream stream=status>=200&&status<300?con.getInputStream():con.getErrorStream();
  StringBuilder b=new StringBuilder();if(stream!=null)try(BufferedReader rd=new BufferedReader(new InputStreamReader(stream,StandardCharsets.UTF_8))){String line;while((line=rd.readLine())!=null)b.append(line);}return b.toString();
 }
}